"""
Deterministic brand -> generic (INN) resolution via the NDC directory
=======================================================================
The extractor resolves brand names to active ingredients with MODEL knowledge
("Panadol" -> "Paracetamol"), and the extraction prompt correctly keeps the
confidence of that inference below 0.90. When the model cannot resolve a
brand at all, it leaves `ingredients` empty and the medication silently drops
out of duplicate / interaction / allergy cross-checking (which all key on
ingredients) — the gap language_guard.py calls out, and the gap that would
otherwise never be visible.

This module closes part of that gap deterministically: for a medication whose
printed name is Latin-script and whose ingredient list is EMPTY, it looks the
brand up in openFDA's NDC directory and fills `ingredients` from the
directory's own `generic_name`. That is a lookup, not a model recollection,
so it is not subject to the inference confidence ceiling — and the
medication starts taking part in cross-checking instead of being skipped.

SCOPE DISCIPLINE
----------------
* It only FILLS an empty ingredient list. It never overwrites ingredients the
  extractor already produced, and never changes a confidence the model
  assigned — the extraction pipeline's honesty about what was inferred is
  preserved. When the NDC generic matches an existing ingredient, that is
  recorded as `ndc_verified: True` for audit, without altering the finding.
* It only tries Latin-script names: NDC brand names are Latin, so a Sinhala
  or Tamil brand name would never match, and querying for one would just burn
  quota. Those remain language_guard's responsibility
  (cross_check_eligible=False), unchanged.
* Fail-open: without an OPENFDA_API_KEY, or on any lookup failure, the
  document passes through exactly as extracted — the medication keeps its
  empty ingredients and the record stays honest about the gap.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("brand_resolver")

_LATIN_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .'\-/()&,+]{1,80}$")


def _is_latin_brand(name: Any) -> bool:
    """A brand-like name worth an NDC query: Latin script, letters present,
    reasonably short, and not already an obvious INN-ish single token with a
    numeric dose embedded. (A dose suffix like '500mg' is not a brand.)"""
    if not name or not isinstance(name, str):
        return False
    text = name.strip()
    if not text or not _LATIN_NAME_RE.match(text):
        return False
    return any(ch.isalpha() for ch in text)


def _existing_ingredients(med: Dict[str, Any]) -> List[str]:
    return [str(i).strip() for i in (med.get("ingredients") or []) if str(i).strip()]


def resolve_brand_ingredients(
    doc: Dict[str, Any], fetch_missing: bool = True
) -> Dict[str, Any]:
    """Fill empty ingredient lists from the NDC directory, in place.

    Returns a summary: ``{"resolved": [...], "verified": [...], "unresolved": [...]}``
    so the upload pipeline can log what changed without re-scanning the doc.

    Mutates the medications on `doc` (the same dict the upload pipeline
    persists), so reanalysis and cross-checking see the resolved ingredients.
    """
    from openfda_reference import lookup_generic_names

    medications = doc.get("medications") or []
    summary: Dict[str, List[str]] = {"resolved": [], "verified": [], "unresolved": []}

    # Collect candidate brand names (Latin-script, empty ingredients first).
    to_resolve: Dict[str, List[str]] = {}
    for med in medications:
        if not isinstance(med, dict):
            continue
        name = str(med.get("name") or "").strip()
        if not _is_latin_brand(name):
            continue
        ingredients = _existing_ingredients(med)
        if not ingredients:
            to_resolve.setdefault(name.casefold(), []).append(name)
        elif not med.get("ndc_verified"):
            to_resolve.setdefault(name.casefold(), []).append(name)

    if not to_resolve:
        return summary

    hits = lookup_generic_names(list(to_resolve), fetch_missing=fetch_missing)

    for med in medications:
        if not isinstance(med, dict):
            continue
        name = str(med.get("name") or "").strip()
        entry = hits.get(name.casefold())
        if not isinstance(entry, dict):
            continue
        generic = str(entry.get("generic_name") or "").strip()
        if not generic:
            continue
        ingredients = _existing_ingredients(med)
        if not ingredients:
            med["ingredients"] = [generic]
            med["ingredient_source"] = "ndc_directory"
            med["ndc_match"] = {
                "brand_name": entry.get("brand_name") or name,
                "generic_name": generic,
                "product_ndc": entry.get("product_ndc"),
                "labeler_name": entry.get("labeler_name"),
            }
            summary["resolved"].append(name)
        else:
            # The extractor already had an ingredient; NDC agreeing with it is
            # recorded for audit, and the medication's confidence is left as
            # the model set it (a corroborated inference is still an inference
            # for confidence purposes).
            from document_dedup import _base_ingredient

            if _base_ingredient(generic) in {_base_ingredient(i) for i in ingredients}:
                med["ndc_verified"] = True
                med["ndc_match"] = {
                    "brand_name": entry.get("brand_name") or name,
                    "generic_name": generic,
                    "product_ndc": entry.get("product_ndc"),
                }
                summary["verified"].append(name)

    return summary


if __name__ == "__main__":
    import sys
    from unittest import mock

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    assert _is_latin_brand("Panadol")
    assert _is_latin_brand("Atorvastatin 20 mg")
    assert not _is_latin_brand("")
    assert not _is_latin_brand("500 mg")
    assert not _is_latin_brand("පැනඩෝල්")  # non-Latin: language_guard's job

    import openfda_reference

    def _fake_lookup(brands, fetch_missing=True):
        return {
            "panadol": {
                "brand_name": "Panadol",
                "generic_name": "Acetaminophen",
                "product_ndc": "12345-678-90",
            },
            "metformin": {
                "brand_name": "Metformin",
                "generic_name": "Metformin",
                "product_ndc": "00000-000-00",
            },
        }

    doc = {
        "medications": [
            {"name": "Panadol", "ingredients": []},
            {"name": "පැනඩෝල්", "ingredients": []},
            {"name": "Metformin", "ingredients": ["Metformin"]},
        ]
    }
    with mock.patch.object(openfda_reference, "lookup_generic_names", side_effect=_fake_lookup):
        summary = resolve_brand_ingredients(doc)

    assert summary["resolved"] == ["Panadol"], summary
    assert doc["medications"][0]["ingredients"] == ["Acetaminophen"]
    assert doc["medications"][0]["ingredient_source"] == "ndc_directory"
    # Non-Latin name untouched (never sent to NDC).
    assert doc["medications"][1]["ingredients"] == []
    # Existing ingredient verified, not overwritten.
    assert doc["medications"][2]["ingredients"] == ["Metformin"]
    assert doc["medications"][2]["ndc_verified"] is True

    print("brand_resolver self-checks passed.")
