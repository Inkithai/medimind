"""
Living Guidelines — version registry & staleness detection
==========================================================
The clinical guidance in this pipeline (reference_library.py, the curated
drug-interaction / condition / drug-lab rule tables, the WHO EML graph) is
version-pinned in source. Guidelines change. This module is the scaffolding
that turns "static knowledge" into "knowledge with a review date": a registry
of every curated source + rule set, its version and last-reviewed date, and a
deterministic staleness check that flags anything older than a configured
window as "review for updates".

It does NOT auto-fetch new guidelines (that requires a content pipeline and
human clinical review, which is out of scope for a code library). What it DOES
do is make the maintenance obligation explicit and machine-checkable, so an
operator can see at a glance which rule sets are due for review — the first,
indispensable half of "living" guidelines.

Usage:
    register("drug_interactions", version="2026-08", reviewed="2026-08-01")
    registry_status()  -> which sources are current vs stale
"""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional

DEFAULT_STALENESS_DAYS = 365  # conservative: review each curated source yearly

_lock = threading.RLock()
_registry: Dict[str, Dict[str, Any]] = {}

# Seed the registry with the curated sources the pipeline actually ships, so a
# fresh install already has a maintenance schedule rather than an empty table.
_SEEDED = False


def _seed() -> None:
    global _SEEDED
    if _SEEDED:
        return
    _SEEDED = True
    today = date.today().isoformat()
    for key, desc in {
        "drug_interactions": "Curated drug-drug interaction rule table",
        "drug_lab_interactions": "Curated drug-laboratory interaction rule table",
        "renal_hepatic_dosing": "Curated renal/hepatic dosing sensitivity table",
        "condition_contraindications": "Curated drug-condition contraindication table",
        "drug_allergy_rules": "Curated medication-allergy rule table",
        "dosage_rules": "Curated adult dosage limits",
        "reference_library_samhsa": "SAMHSA Overdose Prevention & Response Toolkit (PEP23-03-00-001)",
        "preventive_care": "General adult preventive-care / screening reminders",
        "who_eml_graph": "WHO Model List of Essential Medicines (EML/EMLc) graph",
    }.items():
        register(key, version="initial", reviewed=today, description=desc, _seed=True)


def register(
    key: str,
    *,
    version: str,
    reviewed: str,
    description: str = "",
    source_url: str = "",
    _seed: bool = False,
) -> Dict[str, Any]:
    entry = {
        "key": key,
        "version": version,
        "reviewed": reviewed,
        "description": description,
        "source_url": source_url,
        "registered_at": date.today().isoformat(),
    }
    with _lock:
        _registry[key] = entry
    return entry


def _days_since(reviewed: str) -> Optional[int]:
    try:
        d = datetime.fromisoformat(str(reviewed)[:10]).date()
    except Exception:
        return None
    return (date.today() - d).days


def registry_status(staleness_days: int = DEFAULT_STALENESS_DAYS) -> Dict[str, Any]:
    _seed()
    with _lock:
        items = []
        for key, entry in _registry.items():
            age = _days_since(entry.get("reviewed") or "")
            items.append({
                **entry,
                "age_days": age,
                "stale": age is not None and age > staleness_days,
            })
    items.sort(key=lambda x: (x["age_days"] is None, -(x["age_days"] or 0)))
    stale = [i for i in items if i["stale"]]
    return {
        "sources": items,
        "total": len(items),
        "stale_count": len(stale),
        "staleness_threshold_days": staleness_days,
        "note": ("Each curated clinical source has a review date. A 'stale' source is one whose "
                 "review date is older than the threshold — it should be checked against the "
                 "current published guideline. Auto-updating requires a content pipeline and "
                 "clinical sign-off, which is handled outside this library."),
    }


def mark_reviewed(key: str, *, version: str, reviewed: Optional[str] = None) -> Dict[str, Any]:
    """Record that a source was reviewed (operator action after a manual
    check against the current published guideline)."""
    reviewed = reviewed or date.today().isoformat()
    with _lock:
        entry = _registry.get(key)
    if not entry:
        raise KeyError(f"unknown source {key}")
    return register(key, version=version, reviewed=reviewed,
                    description=entry.get("description", ""), source_url=entry.get("source_url", ""))


def reset() -> None:
    global _SEEDED
    with _lock:
        _registry.clear()
        _SEEDED = False
