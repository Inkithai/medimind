"""Offline tests for the openFDA reference adapter.

Verifies the three discipline properties the feature exists to protect:

  1. A label mention CORROBORATES a finding — the claim hook fires only when
     one label actually names the OTHER drug involved, and never fabricates
     a citation the label cannot support.
  2. ABSENCE IS NOT EVIDENCE OF SAFETY — a miss returns None and leaves the
     finding graded exactly as it was, and a transport failure is never
     cached as a definitive "no label exists".
  3. The grading loop performs no network I/O — the claim hook reads only
     the warmed cache.

Everything here is offline: the HTTP layer is mocked, and the cache TTL is
disabled for the module-level cache so each test starts cold and deterministic.
"""

import os
import sys
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Disable the module-level cache so every test starts cold and deterministic
# (the cache-TTL tests build their own fresh _TTLCache instances instead).
# The API key is NOT set here: it is applied per test via _configured() so a
# key can never leak into other offline test modules in the same process and
# trigger real network egress in their record/upload paths.
os.environ["OPENFDA_LABEL_CACHE_TTL"] = "0"

import evidence_grading  # noqa: E402
import openfda_reference  # noqa: E402


@contextmanager
def _configured():
    with mock.patch.dict(os.environ, {"OPENFDA_API_KEY": "test-openfda-key"}):
        yield


def _fluconazole_label_payload():
    return {
        "meta": {"disclaimer": "openFDA test"},
        "results": [
            {
                "id": "uuid-1",
                "set_id": "abc-123",
                "effective_time": "20260114",
                "version": "12",
                "openfda": {"generic_name": ["FLUCONAZOLE"], "brand_name": ["DIFLUCAN"]},
                "drug_interactions": [
                    "Fluconazole is a strong CYP2C9 inhibitor. Concomitant use of "
                    "montelukast with fluconazole may increase montelukast exposure. "
                    "Monitor the patient closely."
                ],
                "contraindications": ["Hypersensitivity to fluconazole."],
            }
        ],
    }


def _shaped_fluconazole():
    return openfda_reference._shape_label(_fluconazole_label_payload()["results"][0], "fluconazole")


# ---------------------------------------------------------------------------
# Label shaping and section matching
# ---------------------------------------------------------------------------


def test_shape_label_formats_effective_time_and_sections():
    shaped = _shaped_fluconazole()
    assert shaped["effective_time"] == "2026-01-14"
    assert shaped["version"] == "12"
    assert shaped["set_id"] == "abc-123"
    assert shaped["display_name"] == "FLUCONAZOLE"
    assert "drug_interactions" in shaped["sections"]
    assert "contraindications" in shaped["sections"]
    assert "boxed_warning" not in shaped["sections"]  # absent section is omitted
    assert "setid=abc-123" in shaped["url"]


def test_label_mentions_ingredient_finds_verbatim_sentence():
    hits = openfda_reference.label_mentions_ingredient(_shaped_fluconazole(), "montelukast")
    assert len(hits) >= 1
    assert hits[0]["section"] == "drug_interactions"
    assert "montelukast" in hits[0]["quote"]
    # The quote is the sentence that actually names the other drug, verbatim
    # from the label — the neighbouring "CYP2C9 inhibitor" sentence is not
    # smuggled in as part of the claim.
    assert "increase montelukast exposure" in hits[0]["quote"]


def test_label_mentions_ingredient_salt_form_normalizes():
    # "Montelukast sodium" must match the same way "Montelukast" does.
    assert openfda_reference.label_mentions_ingredient(_shaped_fluconazole(), "Montelukast sodium")


def test_label_mentions_ingredient_miss_is_empty_not_negative():
    assert openfda_reference.label_mentions_ingredient(_shaped_fluconazole(), "warfarin") == []


# ---------------------------------------------------------------------------
# The claim hook
# ---------------------------------------------------------------------------


def test_claim_reference_cites_only_a_pair_the_label_names():
    labels = {"fluconazole": _shaped_fluconazole()}
    cite = openfda_reference.openfda_claim_reference(
        {"medications_involved": ["Fluconazole", "Montelukast"]}, labels=labels
    )
    assert cite is not None
    assert cite["mentions"] == "montelukast"
    assert cite["drug_label"] == "FLUCONAZOLE"
    assert cite["section"] == "drug_interactions"
    assert "montelukast" in cite["quote"]
    assert cite["effective_time"] == "2026-01-14"
    assert cite["note"]


def test_claim_reference_does_not_cite_a_pair_the_label_ignores():
    labels = {"fluconazole": _shaped_fluconazole()}
    assert (
        openfda_reference.openfda_claim_reference(
            {"medications_involved": ["Fluconazole", "Warfarin"]}, labels=labels
        )
        is None
    )


def test_claim_reference_single_drug_never_cited():
    labels = {"fluconazole": _shaped_fluconazole()}
    assert (
        openfda_reference.openfda_claim_reference({"medication": "Fluconazole"}, labels=labels)
        is None
    )


def test_claim_reference_never_fetches_during_grading():
    """With a cold cache, the claim hook must return None without touching the
    network — grading reads only what the record path already warmed."""
    with (
        _configured(),
        mock.patch.object(openfda_reference, "_get_json", side_effect=AssertionError("network!")),
    ):
        cite = openfda_reference.openfda_claim_reference(
            {"medications_involved": ["Fluconazole", "Montelukast"]}
        )
    assert cite is None


# ---------------------------------------------------------------------------
# Lookup / cache behaviour
# ---------------------------------------------------------------------------


def _mock_fetch_for_fluconazole(url):
    if "generic_name" in url:
        if "fluconazole" in url:
            return _fluconazole_label_payload()
        return {"error": {"code": "NOT_FOUND"}}  # any other ingredient: no label
    if "substance_name" in url:
        return {"error": {"code": "NOT_FOUND"}}  # openFDA reports no-match as error
    raise AssertionError(f"unexpected URL: {url}")


def test_lookup_label_references_keys_by_base_ingredient():
    with (
        _configured(),
        mock.patch.object(openfda_reference, "_get_json", side_effect=_mock_fetch_for_fluconazole),
    ):
        found = openfda_reference.lookup_label_references(["Warfarin sodium", "Fluconazole"])
    # "Warfarin sodium" normalizes to "warfarin" (no US label here -> absent),
    # "Fluconazole" is fetched and keyed by its base ingredient.
    assert set(found) == {"fluconazole"}
    assert found["fluconazole"]["effective_time"] == "2026-01-14"


def test_definitive_miss_is_cached_but_transport_error_is_not():
    calls = {"n": 0}

    def _empty(url):
        calls["n"] += 1
        return {"error": {"code": "NOT_FOUND"}}

    cache = openfda_reference._TTLCache(3600)
    with _configured(), mock.patch.object(openfda_reference, "_LABEL_CACHE", cache):
        with mock.patch.object(openfda_reference, "_get_json", side_effect=_empty):
            assert openfda_reference.lookup_label_references(["aspirin"]) == {}
            first_calls = calls["n"]
            assert openfda_reference.lookup_label_references(["aspirin"]) == {}
            # A clean "no label" is cached as a miss: the second lookup must
            # not re-query.
            assert calls["n"] == first_calls


def test_transport_error_is_not_cached_as_a_miss():
    calls = {"n": 0}

    def _fail(url):
        calls["n"] += 1
        raise openfda_reference.OpenFdaUnavailableError("down", retryable=True)

    cache = openfda_reference._TTLCache(3600)
    with _configured(), mock.patch.object(openfda_reference, "_LABEL_CACHE", cache):
        with mock.patch.object(openfda_reference, "_get_json", side_effect=_fail):
            assert openfda_reference.lookup_label_references(["aspirin"]) == {}
            first_calls = calls["n"]
            assert openfda_reference.lookup_label_references(["aspirin"]) == {}
            # A transport failure must NOT be remembered as "no label", so the
            # second lookup retries (same number of attempts again).
            assert calls["n"] == first_calls * 2


# ---------------------------------------------------------------------------
# Grading integration
# ---------------------------------------------------------------------------


def test_grade_finding_supports_a_chain_of_claim_references():
    def no_cite(finding):
        return None

    def cite(finding):
        return {
            "source": "test source",
            "quote": "verbatim text",
            "note": "custom note for this finding",
        }

    finding = {
        "medications_involved": ["A", "B"],
        "explanation": "x",
        "confidence": 0.9,
    }
    evidence_grading.grade_finding(finding, claim_reference=(no_cite, cite))
    assert finding["evidence_source"] == evidence_grading.REFERENCE_GRAPH
    assert finding["grounded"] is True
    assert finding["confidence"] == 0.9  # cited claim is not capped
    assert finding["evidence_note"] == "custom note for this finding"
    # The note is moved to evidence_note, not left inside the reference.
    assert "note" not in finding["reference"]
    assert finding["reference"]["quote"] == "verbatim text"


def test_grade_finding_still_accepts_a_single_callable():
    def cite(finding):
        return {"source": "s"}

    finding = {"medication": "X", "confidence": 0.9}
    evidence_grading.grade_finding(finding, claim_reference=cite)
    assert finding["evidence_source"] == evidence_grading.REFERENCE_GRAPH
    assert "source and page" in finding["evidence_note"]  # default note preserved


def test_grade_cross_check_cites_openfda_and_caps_the_rest():
    labels = {"fluconazole": _shaped_fluconazole()}

    def claim(finding):
        return openfda_reference.openfda_claim_reference(finding, labels=labels)

    report = {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Fluconazole", "Montelukast"],
                "explanation": "CYP2C9 inhibition.",
                "severity": "moderate",
                "confidence": 0.9,
            },
            {
                "medications_involved": ["Fluconazole", "Warfarin"],
                "explanation": "label does not discuss this.",
                "severity": "moderate",
                "confidence": 0.9,
            },
        ],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    }
    evidence_grading.grade_cross_check(report, claim_reference=claim)

    cited, uncited = report["potential_drug_interactions"]
    assert cited["evidence_source"] == evidence_grading.REFERENCE_GRAPH
    assert cited["confidence"] == 0.9
    assert "montelukast" in cited["reference"]["quote"]

    assert uncited["evidence_source"] == evidence_grading.MODEL_KNOWLEDGE
    assert uncited["confidence"] == 0.6  # unchanged from the cap, not "reassured"

    summary = report["evidence_summary"]
    assert summary["reference_graph"] == 1
    assert summary["model_knowledge"] == 1


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_unconfigured_adapter_stays_dormant():
    with mock.patch.dict(os.environ, {"OPENFDA_API_KEY": ""}):
        assert openfda_reference.is_configured() is False
        assert openfda_reference.lookup_label_references(["warfarin"]) == {}
        assert (
            openfda_reference.openfda_claim_reference({"medications_involved": ["A", "B"]}) is None
        )


def test_placeholder_key_is_treated_as_missing():
    with mock.patch.dict(os.environ, {"OPENFDA_API_KEY": "your-openfda-api-key"}):
        assert openfda_reference.is_configured() is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
