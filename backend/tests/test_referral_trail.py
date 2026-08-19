"""Tests for the referral trail: finding -> specialty -> search -> providers
with a persisted referral reason and transparent per-provider ranking
breakdowns.

Synthetic ranking inputs only — no real provider, directory, or rating
fixture data (the care stack's own rule: live directory records must only
ever come from runtime sources).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api  # noqa: E402
from provider_ranking import rank_providers  # noqa: E402
from referral_trail import build_referral_search, referral_reason  # noqa: E402
from specialty_mapping import match_specialty  # noqa: E402

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")


def _flag(issue_type="high_severity_interaction"):
    evidence = "Medication: A; Medication: B. The safety cross-check marked a medication interaction as high severity."  # noqa: E501
    return {
        "id": "interaction-0",
        "issue_type": issue_type,
        "trigger": "high_risk",
        "risk_level": "high",
        "title": "Potential high-severity medication interaction",
        "evidence": evidence,
        "source": "Medication safety cross-check",
        "confidence": 0.91,
        "specialty": match_specialty(issue_type, evidence),
    }


def _provider(name, distance_km, rating=None, specialties=("pharmacy",)):
    return {
        "source_provider_id": f"synthetic-{name.replace(' ', '-')}",
        "name": name,
        "provider_type": "pharmacy",
        "source_specialties": list(specialties),
        "address": "1 Example Street",
        "latitude": 6.9,
        "longitude": 79.9,
        "distance_km": distance_km,
        "rating": rating,
        "rating_count": 5 if rating is not None else None,
        "phone": None,
        "opening_hours": [],
        "open_now": None,
        "map_url": None,
        "website_url": None,
        "source": "synthetic",
    }


# ---------------------------------------------------------------------------
# referral_reason
# ---------------------------------------------------------------------------


def test_referral_reason_assembles_finding_and_specialty_reason():
    flag = _flag()
    reason = referral_reason(flag)
    assert flag["title"] in reason
    assert "high-risk finding" in reason
    assert "routing suggestion, not a diagnosis" in reason
    # The specialty matcher's own reason is carried in
    assert "pharmacist" in reason


def test_referral_reason_for_low_confidence_finding():
    flag = _flag(issue_type="low_confidence_medication")
    flag["trigger"] = "low_confidence"
    flag["risk_level"] = "review"
    reason = referral_reason(flag)
    assert "low-confidence finding" in reason


# ---------------------------------------------------------------------------
# ranking components (numeric breakdown disclosure)
# ---------------------------------------------------------------------------


def test_ranked_providers_carry_numeric_components():
    providers = [
        _provider("Alpha Pharmacy", 1.2, rating=4.5),
        _provider("Beta Pharmacy", 18.0),
    ]
    specialty = match_specialty("high_severity_interaction", "x")
    ranked = rank_providers(providers, specialty, "any")

    assert [p["name"] for p in ranked][0] == "Alpha Pharmacy"
    for provider in ranked:
        components = provider["ranking"]["components"]
        assert components, "every provider must disclose its ranking breakdown"
        signals = {c["signal"] for c in components}
        assert "specialty_relevance" in signals
        assert "distance" in signals  # both synthetic providers carry distances
        # weights sum to the total used in the score
        total_weight = sum(c["weight"] for c in components)
        assert total_weight in (90.0, 100.0, 105.0)
        # contributions are within the 0-100 band
        for c in components:
            assert 0.0 <= c["score"] <= 1.0
            assert 0.0 <= c["contribution"] <= 100.0
            assert c["explanation"]
        # the displayed score equals the sum of rounded contributions
        assert provider["ranking"]["score"] == round(sum(c["contribution"] for c in components), 1)


def test_optional_signals_only_appear_when_source_provides_them():
    # No rating and no opening hours -> only specialty + distance components.
    providers = [_provider("Gamma Clinic", 3.0)]
    ranked = rank_providers(
        providers, match_specialty("high_severity_interaction", "x"), "evenings"
    )
    signals = {c["signal"] for c in ranked[0]["ranking"]["components"]}
    assert signals == {"specialty_relevance", "distance"}


# ---------------------------------------------------------------------------
# build_referral_search
# ---------------------------------------------------------------------------


def test_referral_search_record_shape():
    flag = _flag()
    specialty = flag["specialty"]
    providers = rank_providers(
        [_provider("Alpha Pharmacy", 1.2, rating=4.5)], specialty, "evenings"
    )
    record = build_referral_search(
        clinical_flag=flag,
        specialty=specialty,
        location={"query": "Kandy", "resolved_area": "Kandy", "latitude": 7.29, "longitude": 80.63},
        availability="evenings",
        providers=providers,
        provenance={
            "source_id": "synthetic",
            "label": "Live provider data — synthetic",
            "retrieved_at": "2026-08-17T00:00:00Z",
        },
    )

    assert record["search_id"].startswith("interaction-0::")
    assert record["intent"]["clinical_flag"]["id"] == "interaction-0"
    assert record["intent"]["specialty"]["id"] == specialty["id"]
    assert "referral_reason" in record["intent"]
    assert record["intent"]["location"]["query"] == "Kandy"
    assert record["intent"]["availability"] == "evenings"
    assert record["results"][0]["ranking"]["components"]
    assert record["provenance"]["retrieved_at"] == "2026-08-17T00:00:00Z"
    assert "not a diagnosis" in record["disclaimer"]


# ---------------------------------------------------------------------------
# Endpoint wiring (persistence best-effort; response carries the trail)
# ---------------------------------------------------------------------------

SEARCH_RESPONSE = {
    "clinical_flag": {
        "id": "interaction-0",
        "issue_type": "high_severity_interaction",
        "trigger": "high_risk",
        "risk_level": "high",
        "title": "Potential high-severity medication interaction",
        "evidence": "x",
        "source": "Medication safety cross-check",
        "confidence": 0.91,
    },
    "specialty": {
        "id": "pharmacy",
        "label": "Pharmacist",
        "provider_query": "pharmacy",
        "reason": "medication safety concerns warrant pharmacist review.",
    },
    "location": {"query": "Kandy", "resolved_area": "Kandy", "latitude": None, "longitude": None},
    "availability": "any",
    "provenance": {
        "live": True,
        "source_id": "synthetic",
        "label": "Live provider data — synthetic",
        "retrieved_at": "2026-08-17T00:00:00Z",
    },
    "ranking_method": "transparent",
    "providers": [],
    "no_results_message": None,
    "disclaimer": "not a diagnosis",
}


def _auth_override():
    async def override_user():
        return "anon_referral_user"

    api.app.dependency_overrides[api.get_current_user] = override_user


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def _snapshot_for_flag():
    return {
        "patient_timeline": {"visits": [], "medications_timeline": [], "lab_results_timeline": []},
        "cross_check_report": {
            "potential_drug_interactions": [
                {
                    "medications_involved": ["A", "B"],
                    "severity": "high",
                    "confidence": 0.91,
                    "explanation": "x",
                },
            ],
            "allergy_conflicts": [],
        },
        "lab_trends": {},
    }


def test_search_endpoint_attaches_referral_trail_and_persists(monkeypatch):
    from fastapi.testclient import TestClient

    _auth_override()
    saved = {}

    def _fake_save(user_id, search):
        saved["user_id"] = user_id
        saved["search"] = search

    monkeypatch.setattr(api.db, "save_referral_search", _fake_save)
    monkeypatch.setattr(api, "_load_snapshot_or_rebuild", lambda uid: _snapshot_for_flag())
    monkeypatch.setattr(api, "search_live_providers", lambda *a, **kw: dict(SEARCH_RESPONSE))
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/care-recommendations/search",
            json={
                "flag_id": "interaction-0",
                "location": "Kandy",
                "availability": "any",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["referral_id"].startswith("interaction-0::")
    assert "high-risk finding" in body["referral_reason"]
    assert body["referral"]["intent"]["clinical_flag"]["id"] == "interaction-0"
    assert body["referral"]["intent"]["specialty"]["id"] == "pharmacy"
    assert saved["user_id"] == "anon_referral_user"
    assert saved["search"]["search_id"] == body["referral_id"]


def test_search_endpoint_survives_persistence_failure(monkeypatch):
    """A missing referrals table (or any persistence failure) must never
    fail the live provider search itself — the trail is still returned."""
    from fastapi.testclient import TestClient

    _auth_override()
    monkeypatch.setattr(api, "_load_snapshot_or_rebuild", lambda uid: _snapshot_for_flag())
    monkeypatch.setattr(api, "search_live_providers", lambda *a, **kw: dict(SEARCH_RESPONSE))
    monkeypatch.setattr(
        api.db,
        "save_referral_search",
        lambda user_id, search: (_ for _ in ()).throw(
            api.db.SchemaNotInitializedError("missing table")
        ),
    )
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/care-recommendations/search",
            json={
                "flag_id": "interaction-0",
                "location": "Kandy",
                "availability": "any",
            },
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["referral_id"]


def test_referrals_endpoint_lists_history(monkeypatch):
    from fastapi.testclient import TestClient

    _auth_override()
    history = [
        {
            "id": 2,
            "created_at": "2026-08-17T01:00:00Z",
            "search": {"search_id": "interaction-0::abc", "intent": {}, "results": []},
        }
    ]
    monkeypatch.setattr(api.db, "load_referral_searches", lambda uid, limit=20: history)
    with TestClient(api.app) as client:
        resp = client.get("/api/v1/care-referrals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["referrals"] == history
    assert "historical records" in body["note"]
