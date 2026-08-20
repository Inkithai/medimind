"""FDA CYP/transporter derived-evidence channel.

The FDA table quotes each drug's enzyme role separately and never states
that two drugs interact. ``interactions_kg.potential_interactions()`` joins
the quoted roles into DERIVED pairs, and the evidence grader must keep that
honest: such a pair grades ``derived_reference`` (capped at 0.75, flagged
for clinical review) — never ``reference_graph`` (uncapped) and never
silently ``model_knowledge``.

Covers:
  * the HTML snapshot parser (parse_cell / parse_snapshot),
  * the pair-key adaptation (derived_references_from_interactions),
  * grading of a shared-enzyme pair at the right tier,
  * the upload-pipeline wiring: configured graph -> derived grading,
    unconfigured or unreachable graph -> fail-open model_knowledge.
"""

import contextlib
import os
import sys
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy"
os.environ["CLOUDINARY_CLOUD_NAME"] = "dummy"
os.environ["CLOUDINARY_API_KEY"] = "dummy"
os.environ["CLOUDINARY_API_SECRET"] = "dummy"
os.environ["JWT_SECRET"] = "dummy"

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import evidence_grading  # noqa: E402
import interactions_kg  # noqa: E402
import medical_extractor  # noqa: E402
import poisoning_kg  # noqa: E402

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_cell_role_and_strength():
    assert interactions_kg.parse_cell("") == []
    one = interactions_kg.parse_cell("3A sensitive substrate")
    assert one == [{
        "enzyme": "3A", "kind": "cyp", "strength": "sensitive",
        "relationship": "METABOLIZED_BY", "statement": "3A sensitive substrate",
    }]
    two = interactions_kg.parse_cell("2D6; 3A weak inhibitor")
    assert [e["enzyme"] for e in two] == ["2D6", "3A"]
    assert all(e["strength"] == "weak" and e["relationship"] == "INHIBITS" for e in two)


def test_parse_cell_transporter_and_footnotes():
    pgp = interactions_kg.parse_cell("P-gp inhibitor")
    assert pgp[0]["kind"] == "transporter" and pgp[0]["strength"] == ""
    # Footnote digits fused onto the enzyme name: 1A220 is CYP1A2 + footnote 20,
    # OATP1B113 is OATP1B1 + footnote 13. Generic digit-stripping would
    # mangle both; the vocabulary recovers the real names.
    assert interactions_kg.parse_cell("1A220 inhibitor")[0]["enzyme"] == "1A2"
    assert interactions_kg.parse_cell("OATP1B113 substrate")[0]["enzyme"] == "OATP1B1"
    # 2C19 must not collapse into 2C9.
    assert interactions_kg.parse_cell("2C19 strong inhibitor")[0]["enzyme"] == "2C19"
    # Footnotes after the role word, digit and letter forms.
    assert interactions_kg.parse_cell("3A moderate inhibitor5")[0]["strength"] == "moderate"
    assert interactions_kg.parse_cell("CYP3A moderate inducer b")[0]["enzyme"] == "3A"
    # Unrecognised trailing word: skipped, never guessed.
    assert interactions_kg.parse_cell("3A something else") == []


def test_parse_archived_snapshot_covers_known_pair():
    parsed = interactions_kg.parse_snapshot()
    assert parsed["roles"], "archived FDA snapshot must parse at least one role"
    assert not parsed["unparsed"], f"unparsed cells: {parsed['unparsed'][:5]}"
    roles = {r["drug"]: r for r in parsed["roles"]}
    clarithromycin = [r for r in parsed["roles"] if r["drug"] == "clarithromycin"]
    simvastatin = [r for r in parsed["roles"] if r["drug"] == "simvastatin"]
    assert any(r["enzyme"] == "3A" and r["relationship"] == "INHIBITS"
               for r in clarithromycin)
    assert any(r["enzyme"] == "3A" and r["relationship"] == "METABOLIZED_BY"
               for r in simvastatin)
    assert roles  # non-empty


# ---------------------------------------------------------------------------
# Pair derivation (graph mocked)
# ---------------------------------------------------------------------------


def _mocked_graph_rows(rows):
    """Patch session_scope/run_read so potential_interactions() is unit-testable."""
    @contextlib.contextmanager
    def _session_scope(operation):
        yield object()

    return (
        mock.patch.object(interactions_kg, "session_scope", _session_scope),
        mock.patch.object(interactions_kg, "run_read", lambda *a, **k: rows),
    )


def test_potential_interactions_groups_shared_pathways():
    # One drug pair sharing TWO pathways must collapse to ONE derived result
    # listing both — three findings for one interaction is false-alarm noise.
    rows = [
        {"affecting_drug": "clarithromycin", "affected_drug": "simvastatin",
         "enzyme": "3A", "enzyme_kind": "cyp", "mechanism": "INHIBITS",
         "strength": "strong",
         "affecting_statement": "3A strong inhibitor",
         "affected_statement": "3A sensitive substrate"},
        {"affecting_drug": "clarithromycin", "affected_drug": "simvastatin",
         "enzyme": "OATP1B1", "enzyme_kind": "transporter", "mechanism": "INHIBITS",
         "strength": "",
         "affecting_statement": "OATP1B1 inhibitor",
         "affected_statement": "OATP1B1 substrate"},
    ]
    p1, p2 = _mocked_graph_rows(rows)
    with p1, p2:
        pairs = interactions_kg.potential_interactions(
            ["Simvastatin 20 mg", "Clarithromycin 500 mg"]
        )
    assert len(pairs) == 1, pairs
    pair = pairs[0]
    assert pair["evidence"] == "derived_pharmacokinetic"
    assert pair["requires_clinical_review"] is True
    assert pair["shared_pathways"] == "3A, OATP1B1"
    assert len(pair["pathways"]) == 2
    assert "does not state" in pair["derivation"]


def test_derived_references_from_interactions_keys_by_pair():
    pairs = [{
        "affecting_drug": "clarithromycin",
        "affected_drug": "simvastatin",
        "source": "fda-cyp-transporter-examples",
        "source_url": "https://www.fda.gov/...",
        "shared_pathways": "3A",
        "mechanism": "INHIBITS",
        "strength": "strong",
        "derivation": "...",
        "pathways": [],
    }]
    derived = evidence_grading.derived_references_from_interactions(pairs)
    # Order-independent: the pair key sorts the two drug names.
    assert set(derived) == {"clarithromycin|simvastatin"}, derived
    assert derived["clarithromycin|simvastatin"]["requires_clinical_review"] is True
    # A malformed entry (fewer than two names) is dropped, not invented.
    assert evidence_grading.derived_references_from_interactions(
        [{"affecting_drug": "clarithromycin", "affected_drug": None}]
    ) == {}


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def _simva_clar_report(confidence):
    return {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Simvastatin", "Clarithromycin"],
                "explanation": "Clarithromycin inhibits CYP3A4, raising simvastatin levels.",
                "severity": "high",
                "confidence": confidence,
            },
        ],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    }


def _derived_pair():
    return evidence_grading.derived_references_from_interactions([{
        "affecting_drug": "clarithromycin",
        "affected_drug": "simvastatin",
        "source": "fda-cyp-transporter-examples",
        "source_url": "https://www.fda.gov/...",
        "shared_pathways": "3A, OATP1B1",
        "mechanism": "INHIBITS",
        "strength": "strong",
        "derivation": "...",
        "pathways": [],
    }])


def test_derived_pair_grads_between_the_other_tiers():
    # 0.95 claim is capped at the derived ceiling (0.75) and preserved.
    report = _simva_clar_report(0.95)
    evidence_grading.grade_cross_check(report, derived_references=_derived_pair())
    finding = report["potential_drug_interactions"][0]
    assert finding["evidence_source"] == "derived_reference"
    assert finding["grounded"] is True
    assert finding["requires_clinical_review"] is True
    assert finding["confidence"] == 0.75
    assert finding["model_reported_confidence"] == 0.95
    assert report["evidence_summary"]["derived_reference"] == 1

    # A below-ceiling score keeps its value (capping must never inflate).
    low = _simva_clar_report(0.4)
    evidence_grading.grade_cross_check(low, derived_references=_derived_pair())
    assert low["potential_drug_interactions"][0]["confidence"] == 0.4
    assert "model_reported_confidence" not in low["potential_drug_interactions"][0]


def test_stated_citation_beats_derived_pair():
    """A source that actually NAMES the pair (reference_graph) must not be
    downgraded to the weaker derived tier."""
    graph_backed = {"simvastatin": {"source": "some reference document"}}
    report = _simva_clar_report(0.9)
    evidence_grading.grade_cross_check(
        report, graph_backed_findings=graph_backed, derived_references=_derived_pair()
    )
    finding = report["potential_drug_interactions"][0]
    assert finding["evidence_source"] == "reference_graph"
    assert finding["confidence"] == 0.9  # uncapped


# ---------------------------------------------------------------------------
# Upload-pipeline wiring
# ---------------------------------------------------------------------------


def _auth_override():
    async def override_user():
        return "anon_interactions_user"

    api.app.dependency_overrides[api.get_current_user] = override_user


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def _simva_clar_doc():
    return {
        "document_type": "prescription",
        "date": (date.today() - timedelta(days=1)).isoformat(),
        "provider_or_doctor": "Dr. Smith",
        "patient_name": "John Doe",
        "patient_age": 49,
        "patient_gender": "male",
        "document_language": "English",
        "additional_languages": [],
        "ocr_confidence": 0.95,
        "translation_confidence": 0.95,
        "medications": [
            {
                "name": "Simvastatin",
                "ingredients": ["simvastatin"],
                "dosage": "20 mg",
                "frequency": "nightly",
                "confidence": 0.95,
            },
            {
                "name": "Clarithromycin",
                "ingredients": ["clarithromycin"],
                "dosage": "500 mg",
                "frequency": "twice daily",
                "confidence": 0.95,
            },
        ],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": None,
        "illegible_or_low_confidence_fields": [],
        "overall_confidence": 0.92,
    }


LLM_SIMVA_CLAR_INTERACTION = (
    '{"potential_drug_interactions": [{"medications_involved": ["Simvastatin", "Clarithromycin"], '
    '"explanation": "Clarithromycin inhibits CYP3A4, raising simvastatin levels.", '
    '"severity": "high", "confidence": 0.95}], "duplicate_prescriptions": [], '
    '"conflicting_dosage_instructions": [], "allergy_conflicts": [], '
    '"overall_recommendation": "Consult a professional."}'
)


def _pipeline_patchers(extract_result):
    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.pdf", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents"),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", return_value=extract_result),
        mock.patch.object(api, "index_patient_timeline", return_value=2),
        mock.patch.object(api.audit, "record"),
    ]
    for p in patchers:
        p.start()
    return patchers


def _upload(client, filename="rx.pdf"):
    return client.post(
        "/api/v1/documents",
        files=[("files", (filename, b"%PDF-1.4 fake", "application/pdf"))],
    )


def test_upload_grades_shared_enzyme_pair_as_derived(monkeypatch):
    _auth_override()
    patchers = _pipeline_patchers(_simva_clar_doc())

    def _real_cross_check(timeline, graph_backed_findings=None, **kwargs):
        with mock.patch.object(
            medical_extractor, "_completion_resilient", return_value=LLM_SIMVA_CLAR_INTERACTION
        ):
            return medical_extractor.cross_check_prescriptions(
                timeline,
                graph_backed_findings=graph_backed_findings,
                derived_references=kwargs.get("derived_references"),
            )

    patchers.append(
        mock.patch.object(api, "cross_check_prescriptions", side_effect=_real_cross_check)
    )
    for p in patchers:
        p.start()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    monkeypatch.setattr(poisoning_kg, "lookup_antidote_references", lambda names: {})
    monkeypatch.setattr(
        interactions_kg,
        "potential_interactions",
        lambda names: [{
            "affecting_drug": "clarithromycin",
            "affected_drug": "simvastatin",
            "source": "fda-cyp-transporter-examples",
            "source_url": "https://www.fda.gov/...",
            "shared_pathways": "3A, OATP1B1",
            "mechanism": "INHIBITS",
            "strength": "strong",
            "derivation": "...",
            "pathways": [],
        }],
    )
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        report = resp.json()["cross_check_report"]
        interaction = report["potential_drug_interactions"][0]
        assert interaction["evidence_source"] == "derived_reference"
        assert interaction["grounded"] is True
        assert interaction["requires_clinical_review"] is True
        # 0.95 model claim capped at the derived ceiling, preserved for audit.
        assert interaction["confidence"] == 0.75
        assert interaction["model_reported_confidence"] == 0.95
        assert "shared_pathways" in interaction["reference"]
        assert report["evidence_summary"]["derived_reference"] == 1
        assert report["evidence_summary"]["model_knowledge"] == 0
    finally:
        for p in patchers:
            p.stop()


def test_upload_without_graph_stays_fail_open(monkeypatch):
    """No graph configured: the pair stays at capped model_knowledge and the
    upload never fails."""
    _auth_override()
    patchers = _pipeline_patchers(_simva_clar_doc())

    def _real_cross_check(timeline, graph_backed_findings=None, **kwargs):
        with mock.patch.object(
            medical_extractor, "_completion_resilient", return_value=LLM_SIMVA_CLAR_INTERACTION
        ):
            return medical_extractor.cross_check_prescriptions(
                timeline,
                graph_backed_findings=graph_backed_findings,
                derived_references=kwargs.get("derived_references"),
            )

    patchers.append(
        mock.patch.object(api, "cross_check_prescriptions", side_effect=_real_cross_check)
    )
    for p in patchers:
        p.start()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: False)
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        report = resp.json()["cross_check_report"]
        interaction = report["potential_drug_interactions"][0]
        assert interaction["evidence_source"] == "model_knowledge"
        assert interaction["confidence"] == 0.6  # capped
        assert report["evidence_summary"]["derived_reference"] == 0
    finally:
        for p in patchers:
            p.stop()


def test_upload_survives_unreachable_configured_graph(monkeypatch):
    """Configured but down: the lookup raises inside the pipeline and the
    upload continues with model-knowledge grading (fail-open)."""
    _auth_override()
    patchers = _pipeline_patchers(_simva_clar_doc())

    def _real_cross_check(timeline, graph_backed_findings=None, **kwargs):
        with mock.patch.object(
            medical_extractor, "_completion_resilient", return_value=LLM_SIMVA_CLAR_INTERACTION
        ):
            return medical_extractor.cross_check_prescriptions(
                timeline,
                graph_backed_findings=graph_backed_findings,
                derived_references=kwargs.get("derived_references"),
            )

    patchers.append(
        mock.patch.object(api, "cross_check_prescriptions", side_effect=_real_cross_check)
    )
    for p in patchers:
        p.start()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    monkeypatch.setattr(poisoning_kg, "lookup_antidote_references", lambda names: {})

    def _boom(names):
        raise RuntimeError("neo4j connection refused")

    monkeypatch.setattr(interactions_kg, "potential_interactions", _boom)
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        report = resp.json()["cross_check_report"]
        interaction = report["potential_drug_interactions"][0]
        assert interaction["evidence_source"] == "model_knowledge"
    finally:
        for p in patchers:
            p.stop()
