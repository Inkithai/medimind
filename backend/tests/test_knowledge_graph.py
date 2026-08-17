"""Endpoint + upload-pipeline tests for the WHO antidote reference
knowledge graph (POST /api/v1/knowledge-graph/antidotes and the
reference-graph evidence grading wiring in the upload pipeline)."""

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
import medical_extractor  # noqa: E402
import poisoning_kg  # noqa: E402


def _auth_override():
    async def override_user():
        return "anon_kg_user"

    api.app.dependency_overrides[api.get_current_user] = override_user


def teardown_function():
    api.app.dependency_overrides.pop(api.get_current_user, None)


def _naloxone_doc():
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
        "medications": [{
            "name": "Naloxone", "ingredients": ["naloxone"],
            "dosage": "400 micrograms", "frequency": "as needed",
            "dosage_value": 400, "dosage_unit": "mcg",
            "frequency_per_day": None, "is_as_needed": True, "confidence": 0.95,
        }],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": None,
        "illegible_or_low_confidence_fields": [],
        "overall_confidence": 0.92,
    }


# ---------------------------------------------------------------------------
# POST /api/v1/knowledge-graph/antidotes
# ---------------------------------------------------------------------------


def test_endpoint_requires_configured_graph(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: False)
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/knowledge-graph/antidotes",
            files=[("file", ("who.pdf", b"%PDF-1.4 fake", "application/pdf"))],
        )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_endpoint_rejects_non_pdf(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/knowledge-graph/antidotes",
            files=[("file", ("notes.txt", b"hello", "text/plain"))],
        )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_endpoint_ingests_and_reports_counts(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    section = {
        "population": "adult",
        "entries": [
            {"name": "naloxone", "dosage_form": "Injection", "subsection": "specific",
             "list_type": "core", "source_page": 1},
            {"name": "charcoal, activated", "dosage_form": "Powder",
             "subsection": "non_specific", "list_type": "core", "source_page": 1},
        ],
    }
    monkeypatch.setattr(poisoning_kg, "extract_antidote_section", lambda path: section)
    monkeypatch.setattr(
        poisoning_kg, "ingest_antidote_entries",
        lambda sec, source_document: len(sec["entries"]),
    )
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/knowledge-graph/antidotes",
            files=[("file", ("who_eml.pdf", b"%PDF-1.4 fake", "application/pdf"))],
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_document"] == "who_eml.pdf"
    assert body["population"] == "adult"
    assert body["entries_ingested"] == 2
    assert body["categories"] == ["non_specific", "specific"]


def test_endpoint_reports_unparseable_pdf(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)

    def _boom(path):
        raise ValueError("not a real PDF")

    monkeypatch.setattr(poisoning_kg, "extract_antidote_section", _boom)
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/knowledge-graph/antidotes",
            files=[("file", ("junk.pdf", b"%PDF-1.4 fake", "application/pdf"))],
        )
    assert resp.status_code == 422


def test_endpoint_reports_missing_antidote_section(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    monkeypatch.setattr(
        poisoning_kg, "extract_antidote_section",
        lambda path: {"population": "adult", "entries": []},
    )
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/knowledge-graph/antidotes",
            files=[("file", ("other.pdf", b"%PDF-1.4 fake", "application/pdf"))],
        )
    assert resp.status_code == 422
    assert "No 'Antidotes" in resp.json()["detail"]


def test_endpoint_reports_unreachable_graph(monkeypatch):
    _auth_override()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    section = {
        "population": "adult",
        "entries": [{"name": "naloxone", "dosage_form": "Injection",
                     "subsection": "specific", "list_type": "core", "source_page": 1}],
    }
    monkeypatch.setattr(poisoning_kg, "extract_antidote_section", lambda path: section)

    def _boom(sec, source_document):
        raise ConnectionError("Aura unreachable")

    monkeypatch.setattr(poisoning_kg, "ingest_antidote_entries", _boom)
    with TestClient(api.app) as client:
        resp = client.post(
            "/api/v1/knowledge-graph/antidotes",
            files=[("file", ("who.pdf", b"%PDF-1.4 fake", "application/pdf"))],
        )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Upload pipeline wiring: lookup -> evidence grading -> notes
# ---------------------------------------------------------------------------

LLM_NALOXONE_INTERACTION = (
    '{"potential_drug_interactions": [{"medications_involved": ["Naloxone", "Morphine"], '
    '"explanation": "Naloxone reverses opioid effects.", "severity": "high", '
    '"confidence": 0.9}], "duplicate_prescriptions": [], '
    '"conflicting_dosage_instructions": [], "allergy_conflicts": [], '
    '"overall_recommendation": "Consult a professional."}'
)


def _pipeline_patchers(extract_result):
    patchers = [
        mock.patch.object(api.storage, "upload_patient_document",
                          return_value={"document_url": "https://cloud/x.pdf",
                                        "cloudinary_public_id": "x"}),
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
        files=[("files", (filename, b"fake", "application/pdf"))],
    )


def test_upload_grades_antidote_finding_as_reference_graph(monkeypatch):
    """A configured graph that documents Naloxone must upgrade the finding
    to reference_graph evidence (confidence uncapped) and attach the
    patient-facing reference note — while remaining fail-open."""
    _auth_override()
    patchers = _pipeline_patchers(_naloxone_doc())

    def _real_cross_check(timeline, graph_backed_findings=None, **kwargs):
        with mock.patch.object(
            medical_extractor, "_completion_resilient", return_value=LLM_NALOXONE_INTERACTION
        ):
            return medical_extractor.cross_check_prescriptions(
                timeline, graph_backed_findings=graph_backed_findings
            )

    patchers.append(mock.patch.object(
        api, "cross_check_prescriptions", side_effect=_real_cross_check
    ))
    for p in patchers:
        p.start()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)
    monkeypatch.setattr(poisoning_kg, "lookup_antidote_references", lambda names: {
        "Naloxone": {
            "display_name": "naloxone",
            "category": "specific",
            "listings": [{
                "population": "adult", "source_document": "who_eml.pdf",
                "list_type": "core", "dosage_form": "Injection: 400 micrograms/mL",
            }],
        },
    })
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()

        notes = body["cross_check_report"]["antidote_reference_notes"]
        assert notes and notes[0]["medication"] == "Naloxone"
        assert notes[0]["listings"][0]["source_document"] == "who_eml.pdf"
        assert body["antidote_reference_notes"] == notes

        interaction = body["cross_check_report"]["potential_drug_interactions"][0]
        assert interaction["evidence_source"] == "reference_graph"
        assert interaction["grounded"] is True
        # confidence is NOT capped (model claimed 0.9, cap is 0.6)
        assert interaction["confidence"] == 0.9
        assert interaction["reference"]["naloxone"]["source"].startswith("WHO")
        assert body["cross_check_report"]["evidence_summary"]["reference_graph"] >= 1
    finally:
        for p in patchers:
            p.stop()


def test_upload_without_graph_stays_fail_open(monkeypatch):
    """Default deployments (no NEO4J_* env) attach no reference notes and
    grade the same finding as model knowledge — the upload never fails."""
    _auth_override()
    patchers = _pipeline_patchers(_naloxone_doc())

    def _real_cross_check(timeline, graph_backed_findings=None, **kwargs):
        with mock.patch.object(
            medical_extractor, "_completion_resilient", return_value=LLM_NALOXONE_INTERACTION
        ):
            return medical_extractor.cross_check_prescriptions(
                timeline, graph_backed_findings=graph_backed_findings
            )

    patchers.append(mock.patch.object(
        api, "cross_check_prescriptions", side_effect=_real_cross_check
    ))
    for p in patchers:
        p.start()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: False)
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["antidote_reference_notes"] == []
        assert body["cross_check_report"]["antidote_reference_notes"] == []
        interaction = body["cross_check_report"]["potential_drug_interactions"][0]
        assert interaction["evidence_source"] == "model_knowledge"
        assert interaction["confidence"] == 0.6  # capped
    finally:
        for p in patchers:
            p.stop()


def test_upload_survives_unreachable_configured_graph(monkeypatch):
    """Configured-but-down graph: the lookup raises inside the pipeline and
    the upload continues with model-knowledge grading (fail-open)."""
    _auth_override()
    patchers = _pipeline_patchers(_naloxone_doc())

    def _real_cross_check(timeline, graph_backed_findings=None, **kwargs):
        with mock.patch.object(
            medical_extractor, "_completion_resilient", return_value=LLM_NALOXONE_INTERACTION
        ):
            return medical_extractor.cross_check_prescriptions(
                timeline, graph_backed_findings=graph_backed_findings
            )

    patchers.append(mock.patch.object(
        api, "cross_check_prescriptions", side_effect=_real_cross_check
    ))
    for p in patchers:
        p.start()
    monkeypatch.setattr(api.graph_db, "is_configured", lambda: True)

    def _boom(names):
        raise ConnectionError("Aura unreachable")

    monkeypatch.setattr(poisoning_kg, "lookup_antidote_references", _boom)
    try:
        with TestClient(api.app) as client:
            resp = _upload(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["antidote_reference_notes"] == []
        interaction = body["cross_check_report"]["potential_drug_interactions"][0]
        assert interaction["evidence_source"] == "model_knowledge"
    finally:
        for p in patchers:
            p.stop()
