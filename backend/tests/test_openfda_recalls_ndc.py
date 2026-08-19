"""Offline tests for the openFDA recall + NDC lookup functions.

The discipline properties these protect:

  * recall records and NDC entries are keyed by normalized ingredient/brand,
    cache-first, and fetched only when a key is configured;
  * a definitive no-match is cached as a miss, but a transport failure is
    NOT (so a network outage is never remembered as "no recall" / "no such
    brand" — the honest answer is "we don't know", and the next record
    retries);
  * no network I/O when ``fetch_missing=False`` (the grading / safety-check
    path) — only the record path warms the cache.

The HTTP layer is mocked and a fresh TTL cache is injected per test, so these
are fully offline and deterministic regardless of the process environment.
"""

import os
import sys
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OPENFDA_RECALL_CACHE_TTL"] = "0"
os.environ["OPENFDA_NDC_CACHE_TTL"] = "0"

import openfda_reference  # noqa: E402


@contextmanager
def _configured():
    with mock.patch.dict(os.environ, {"OPENFDA_API_KEY": "test-openfda-key"}):
        yield


def _enforcement_payload():
    return {
        "results": [
            {
                "recall_number": "D-1234-2024",
                "classification": "Class I",
                "status": "Ongoing",
                "recall_initiation_date": "20240105",
                "reason_for_recall": "Microbial contamination of non-sterile product.",
                "product_description": "Losartan potassium tablets, 50 mg",
                "openfda": {"generic_name": ["LOSARTAN POTASSIUM"]},
            },
            {
                "recall_number": "D-0001-2020",
                "classification": "Class III",
                "status": "Completed",
                "recall_initiation_date": "20200202",
                "reason_for_recall": "Labeling: incorrect lot number.",
                "openfda": {"generic_name": ["LOSARTAN POTASSIUM"]},
            },
        ]
    }


def _ndc_payload():
    return {
        "results": [
            {
                "product_ndc": "12345-678-90",
                "brand_name": "PANADOL",
                "generic_name": "ACETAMINOPHEN",
                "openfda": {
                    "brand_name": ["PANADOL"],
                    "generic_name": ["ACETAMINOPHEN"],
                    "manufacturer_name": ["Test Labeler Inc."],
                    "marketing_status": "prescription",
                },
                "active_ingredients": [{"name": "ACETAMINOPHEN", "strength": "500 mg/1"}],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Recall lookup
# ---------------------------------------------------------------------------


def test_recall_lookup_sorts_ongoing_first_and_keys_by_ingredient():
    cache = openfda_reference._TTLCache(3600)
    with _configured(), mock.patch.object(openfda_reference, "_RECALL_CACHE", cache):
        with mock.patch.object(openfda_reference, "_get_json", return_value=_enforcement_payload()):
            found = openfda_reference.lookup_recall_references(["Losartan potassium"])
    assert set(found) == {"losartan"}
    recalls = found["losartan"]
    # Ongoing Class I ranks ahead of Completed Class III despite being newer.
    assert recalls[0]["recall_number"] == "D-1234-2024"
    assert recalls[0]["ongoing"] is True
    assert recalls[0]["classification_rank"] == 0
    assert recalls[1]["classification_rank"] == 2


def test_recall_miss_cached_but_transport_error_not():
    cache = openfda_reference._TTLCache(3600)
    calls = {"n": 0}

    def _empty(url):
        calls["n"] += 1
        return {"results": []}

    with _configured(), mock.patch.object(openfda_reference, "_RECALL_CACHE", cache):
        with mock.patch.object(openfda_reference, "_get_json", side_effect=_empty):
            assert openfda_reference.lookup_recall_references(["aspirin"]) == {}
            first = calls["n"]
            assert openfda_reference.lookup_recall_references(["aspirin"]) == {}
            assert calls["n"] == first  # clean miss cached — no re-query

    calls2 = {"n": 0}

    def _fail(url):
        calls2["n"] += 1
        raise openfda_reference.OpenFdaUnavailableError("down", retryable=True)

    cache2 = openfda_reference._TTLCache(3600)
    with _configured(), mock.patch.object(openfda_reference, "_RECALL_CACHE", cache2):
        with mock.patch.object(openfda_reference, "_get_json", side_effect=_fail):
            assert openfda_reference.lookup_recall_references(["aspirin"]) == {}
            first2 = calls2["n"]
            assert openfda_reference.lookup_recall_references(["aspirin"]) == {}
            assert calls2["n"] == first2 * 2  # transport failure NOT cached as a miss


def test_recall_lookup_no_network_without_key():
    with mock.patch.object(openfda_reference, "_get_json", side_effect=AssertionError("network!")):
        assert openfda_reference.lookup_recall_references(["losartan"]) == {}


# ---------------------------------------------------------------------------
# NDC lookup
# ---------------------------------------------------------------------------


def test_ndc_lookup_resolves_brand_to_generic():
    cache = openfda_reference._TTLCache(3600)
    with _configured(), mock.patch.object(openfda_reference, "_NDC_CACHE", cache):
        with mock.patch.object(openfda_reference, "_get_json", return_value=_ndc_payload()):
            found = openfda_reference.lookup_generic_names(["Panadol"])
    assert found["panadol"]["generic_name"] == "ACETAMINOPHEN"
    assert found["panadol"]["product_ndc"] == "12345-678-90"
    assert found["panadol"]["active_ingredients"] == ["ACETAMINOPHEN"]


def test_ndc_miss_cached_but_transport_error_not():
    cache = openfda_reference._TTLCache(3600)
    calls = {"n": 0}

    def _empty(url):
        calls["n"] += 1
        return {"results": []}

    with _configured(), mock.patch.object(openfda_reference, "_NDC_CACHE", cache):
        with mock.patch.object(openfda_reference, "_get_json", side_effect=_empty):
            assert openfda_reference.lookup_generic_names(["Nobrand"]) == {}
            first = calls["n"]
            assert openfda_reference.lookup_generic_names(["Nobrand"]) == {}
            assert calls["n"] == first


def test_ndc_lookup_no_network_without_key():
    with mock.patch.object(openfda_reference, "_get_json", side_effect=AssertionError("network!")):
        assert openfda_reference.lookup_generic_names(["Panadol"]) == {}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
