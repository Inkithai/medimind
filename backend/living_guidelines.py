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
from typing import Any, Dict, Optional

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
        "reference_library_samhsa": "SAMHSA Overdose Prevention & Response Toolkit (PEP23-03-00-001)",  # noqa: E501
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
            items.append(
                {
                    **entry,
                    "age_days": age,
                    "stale": age is not None and age > staleness_days,
                }
            )
    items.sort(key=lambda x: (x["age_days"] is None, -(x["age_days"] or 0)))
    stale = [i for i in items if i["stale"]]
    return {
        "sources": items,
        "total": len(items),
        "stale_count": len(stale),
        "staleness_threshold_days": staleness_days,
        "note": (
            "Each curated clinical source has a review date. A 'stale' source is one whose "
            "review date is older than the threshold — it should be checked against the "
            "current published guideline. Auto-updating requires a content pipeline and "
            "clinical sign-off, which is handled outside this library."
        ),
    }


def mark_reviewed(key: str, *, version: str, reviewed: Optional[str] = None) -> Dict[str, Any]:
    """Record that a source was reviewed (operator action after a manual
    check against the current published guideline)."""
    _seed()
    reviewed = reviewed or date.today().isoformat()
    with _lock:
        entry = _registry.get(key)
    if not entry:
        raise KeyError(f"unknown source {key}")
    return register(
        key,
        version=version,
        reviewed=reviewed,
        description=entry.get("description", ""),
        source_url=entry.get("source_url", ""),
    )


def reset() -> None:
    global _SEEDED
    with _lock:
        _registry.clear()
        _SEEDED = False


# --------------------------------------------------------------------------- #
# Auto-refresh (manifest-based)
# --------------------------------------------------------------------------- #
# True "auto-update" requires a content source and human clinical sign-off,
# which lives outside this library. What IS implementable safely and without
# fragile publisher-site scraping is a MANIFEST-driven check: the operator
# hosts a small JSON file listing each curated source's current published
# version (they curate it when a guideline changes). This module fetches that
# manifest, compares each version against the registry, and flags — and can
# apply — updates. It fails open: no manifest configured -> "manual review".

_MANIFEST_TIMEOUT = 8.0


def _manifest_url() -> Optional[str]:
    import os

    return os.environ.get("LIVING_GUIDELINES_MANIFEST_URL") or None


def _fetch_manifest(url: Optional[str]) -> Optional[Dict[str, Any]]:
    """Fetch and parse the manifest JSON. Returns None on any failure."""
    if not url:
        return None
    try:
        import json
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "MediMind-living-guidelines/1.0"})
        with urllib.request.urlopen(req, timeout=_MANIFEST_TIMEOUT) as resp:  # nosec - operator-configured URL
            data = resp.read().decode("utf-8", errors="replace")
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _normalise_manifest(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Accept either {"sources": {key: {...}}} or a flat {key: {...}|version}."""
    raw = manifest.get("sources") if isinstance(manifest.get("sources"), dict) else manifest
    out: Dict[str, Dict[str, Any]] = {}
    for key, val in (raw or {}).items():
        if isinstance(val, str):
            out[str(key)] = {"version": val}
        elif isinstance(val, dict):
            out[str(key)] = val
    return out


def check_for_updates(manifest_url: Optional[str] = None) -> Dict[str, Any]:
    """Compare the registry against the manifest. Reports, per source, whether a
    newer version is published. Does NOT change the registry."""
    _seed()
    url = manifest_url or _manifest_url()
    manifest = _fetch_manifest(url)
    if manifest is None:
        return {
            "checked": False,
            "reason": (
                "No manifest configured (set LIVING_GUIDELINES_MANIFEST_URL) or it could "
                "not be fetched. Manual review is still required."
            ),
            "updates_available": [],
        }
    norm = _normalise_manifest(manifest)
    with _lock:
        registry_snapshot = {k: dict(v) for k, v in _registry.items()}
    updates = []
    for key, entry in registry_snapshot.items():
        remote = norm.get(key)
        if not remote:
            continue
        remote_version = str(remote.get("version") or "").strip()
        local_version = str(entry.get("version") or "").strip()
        if remote_version and remote_version != local_version:
            updates.append(
                {
                    "key": key,
                    "registered_version": local_version,
                    "latest_version": remote_version,
                    "url": remote.get("url"),
                    "notes": remote.get("notes"),
                    "update_available": True,
                }
            )
    # sources in the manifest but not in the registry (new sources)
    new_sources = [k for k in norm if k not in registry_snapshot]
    return {
        "checked": True,
        "manifest_url": url,
        "updates_available": updates,
        "new_sources_in_manifest": new_sources,
        "checked_at": date.today().isoformat(),
    }


def apply_updates(manifest_url: Optional[str] = None) -> Dict[str, Any]:
    """Run check_for_updates and apply any newer versions to the registry,
    recording the review. Returns what changed. Never raises — fetch failures
    are reported, not thrown."""
    check = check_for_updates(manifest_url)
    if not check.get("checked"):
        return {"applied": [], **check}
    applied = []
    for upd in check["updates_available"]:
        try:
            mark_reviewed(upd["key"], version=upd["latest_version"])
            applied.append({"key": upd["key"], "version": upd["latest_version"]})
        except Exception:
            continue
    return {
        "applied": applied,
        "applied_count": len(applied),
        "checked_at": check.get("checked_at"),
        "manifest_url": check.get("manifest_url"),
        "new_sources_in_manifest": check.get("new_sources_in_manifest"),
    }
