"""Offline tests for deterministic brand -> generic (NDC) resolution.

The properties being protected:

  * a Latin-script brand with an EMPTY ingredient list gets its INN filled
    from the NDC directory, so it joins cross-checking instead of silently
    dropping out (the gap language_guard documents);
  * a non-Latin brand is NEVER queried (NDC names are Latin) and stays
    language_guard's responsibility (cross_check_eligible=False);
  * an existing ingredient is NEVER overwritten — an NDC agreement is
    recorded as ndc_verified for audit, without touching confidence;
  * fail-open: without a configured key (or on any failure) the document
    passes through exactly as extracted.
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import brand_resolver  # noqa: E402
import openfda_reference  # noqa: E402


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


def test_resolves_empty_ingredient_brand():
    doc = {"medications": [{"name": "Panadol", "ingredients": []}]}
    with mock.patch.object(openfda_reference, "lookup_generic_names", side_effect=_fake_lookup):
        summary = brand_resolver.resolve_brand_ingredients(doc)
    assert summary["resolved"] == ["Panadol"]
    med = doc["medications"][0]
    assert med["ingredients"] == ["Acetaminophen"]
    assert med["ingredient_source"] == "ndc_directory"
    assert med["ndc_match"]["product_ndc"] == "12345-678-90"


def test_non_latin_brand_never_queried():
    doc = {"medications": [{"name": "පැනඩෝල්", "ingredients": []}]}

    def _no_network(brands, fetch_missing=True):
        raise AssertionError("non-Latin brands must never reach the NDC lookup")

    with mock.patch.object(openfda_reference, "lookup_generic_names", side_effect=_no_network):
        summary = brand_resolver.resolve_brand_ingredients(doc)
    assert summary == {"resolved": [], "verified": [], "unresolved": []}
    assert doc["medications"][0]["ingredients"] == []


def test_existing_ingredient_verified_but_not_overwritten():
    doc = {"medications": [{"name": "Metformin", "ingredients": ["Metformin"]}]}
    with mock.patch.object(openfda_reference, "lookup_generic_names", side_effect=_fake_lookup):
        summary = brand_resolver.resolve_brand_ingredients(doc)
    assert summary["verified"] == ["Metformin"]
    med = doc["medications"][0]
    assert med["ingredients"] == ["Metformin"]  # unchanged
    assert med["ndc_verified"] is True
    assert "ingredient_source" not in med


def test_combination_product_resolves_all_ingredients():
    """A combo product's active_ingredients must be filled as a list, not
    crammed into one garbled ingredient string."""
    doc = {"medications": [{"name": "ComboX", "ingredients": []}]}

    def _lookup(brands, fetch_missing=True):
        return {
            "combox": {
                "brand_name": "ComboX",
                "generic_name": "ACETAMINOPHEN",
                "product_ndc": "11111-222-33",
                "active_ingredients": [
                    "ACETAMINOPHEN",
                    "DIPHENHYDRAMINE HYDROCHLORIDE",
                ],
            }
        }

    with mock.patch.object(openfda_reference, "lookup_generic_names", side_effect=_lookup):
        summary = brand_resolver.resolve_brand_ingredients(doc)
    assert summary["resolved"] == ["ComboX"]
    assert doc["medications"][0]["ingredients"] == [
        "ACETAMINOPHEN",
        "DIPHENHYDRAMINE HYDROCHLORIDE",
    ]


def test_disagreement_does_not_touch_ingredients():
    """NDC returning a different generic than the extracted one must not
    overwrite the extraction — the record stays honest about what the model
    produced."""
    doc = {"medications": [{"name": "BrandX", "ingredients": ["SomeIngredient"]}]}

    def _lookup(brands, fetch_missing=True):
        return {"brandx": {"brand_name": "BrandX", "generic_name": "OtherGeneric"}}

    with mock.patch.object(openfda_reference, "lookup_generic_names", side_effect=_lookup):
        summary = brand_resolver.resolve_brand_ingredients(doc)
    assert summary == {"resolved": [], "verified": [], "unresolved": []}
    assert doc["medications"][0]["ingredients"] == ["SomeIngredient"]


def test_unconfigured_resolver_is_a_noop():
    doc = {"medications": [{"name": "Panadol", "ingredients": []}]}
    # No key -> lookup_generic_names returns {} without any HTTP.
    with mock.patch.object(openfda_reference, "lookup_generic_names", return_value={}) as lookup:
        summary = brand_resolver.resolve_brand_ingredients(doc)
    assert summary == {"resolved": [], "verified": [], "unresolved": []}
    assert doc["medications"][0]["ingredients"] == []
    lookup.assert_called_once()


def test_is_latin_brand_classification():
    assert brand_resolver._is_latin_brand("Panadol")
    assert brand_resolver._is_latin_brand("Atorvastatin 20 mg")
    assert not brand_resolver._is_latin_brand("")
    assert not brand_resolver._is_latin_brand("500 mg")
    assert not brand_resolver._is_latin_brand("පැනඩෝල්")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
