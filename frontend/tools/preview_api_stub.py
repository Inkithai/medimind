"""
Local preview stub for the MediMind API.

The real backend needs Supabase plus an LLM key, neither of which exist in a
sandbox. This stub answers just enough of the contract for the app shell to
boot and for every screen to reach a real (empty) state, so the navigation
rework can be clicked through end to end.

It is a development aid only — never imported by the app, never deployed, and
it never invents clinical data: every list comes back empty, so what you see
is each screen's genuine empty state. The payload shapes are the same ones
asserted by src/pages/__tests__/navigationRender.test.tsx.

Run it alongside `npm run dev`:

    python3 tools/preview_api_stub.py
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

EMPTY_TIMELINE = {
    "visits": [],
    "documents": [],
    "medications_timeline": [],
    "lab_results_timeline": [],
    "conditions_timeline": [],
    "allergies": [],
    "known_allergies": [],
}

EMPTY_CROSS_CHECK = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "guideline_flagged_combinations": [],
    "eml_age_conflicts": [],
    "openfda_recalls": [],
    "medication_changes": [],
    "medication_continuations": [],
    "concurrent_exposure": [],
    "overall_recommendation": "",
}

EMPTY_DOSAGE = {"findings": [], "checked_medications": 0, "note": ""}
EMPTY_TRENDS = {"trends": [], "insufficient_data": [], "summary": {}}

PAYLOADS = {
    "/api/v1/anonymous/session": {"user_id": "anon_preview", "token": "preview-token"},
    "/api/v1/workspace/name": {"user_id": "anon_preview", "name": "Preview workspace"},
    "/api/v1/patient-snapshot": {
        "user_id": "anon_preview",
        "patient_timeline": EMPTY_TIMELINE,
        "cross_check_report": EMPTY_CROSS_CHECK,
        "dosage_report": EMPTY_DOSAGE,
        "lab_trends": EMPTY_TRENDS,
        "rebuilt_from_documents": False,
    },
    "/api/v1/timeline": EMPTY_TIMELINE,
    "/api/v1/documents": {"documents": []},
    "/api/v1/medications/reconciliation": {"medications": [], "summary": {}},
    "/api/v1/cross-check": EMPTY_CROSS_CHECK,
    "/api/v1/dosage-report": EMPTY_DOSAGE,
    # getMedicationSafety returns the report itself with dosage attached.
    "/api/v1/medication-safety": {**EMPTY_CROSS_CHECK, "dosage_report": EMPTY_DOSAGE},
    "/api/v1/risk-timeline": {
        "calendar": [],
        "concurrent_exposure": [],
        "treatment_windows": [],
        "timing_summary": None,
        "evidence_summary": None,
    },
    "/api/v1/findings/alerts": {
        "active_findings": [],
        "active_count": 0,
        "suppressed_findings": [],
        "suppressed_count": 0,
        "collapsed_duplicates": 0,
        "merge_log": [],
    },
    "/api/v1/findings/lifecycle": {"states": {}, "findings": [], "summary": None},
    "/api/v1/findings/feedback": {"entries": [], "feedback": []},
    "/api/v1/findings/feedback/metrics": {"total": 0, "by_verdict": {}},
    "/api/v1/record-integrity": {
        "status": "no_discrepancies_found",
        "summary": {"records_checked": 0, "issues_found": 0, "important_issues": 0},
        "issues": [],
        "checks_performed": [],
        "method": "",
        "note": "",
    },
    "/api/v1/corrections": {"corrections": []},
    "/api/v1/conflicts": {"conflicts": []},
    "/api/v1/changes": {
        "comparisons": [],
        "periods": [],
        "changes": [],
        "summary": {},
        "note": "",
        "method": "",
    },
    "/api/v1/lab-trends": EMPTY_TRENDS,
    "/api/v1/vital-trends": {
        "trends": [],
        "insufficient_data": [],
        "summary": {"vital_types": 0, "abnormal_latest": 0},
    },
    "/api/v1/early-warning": {"score": 0, "components": [], "band": None, "note": ""},
    "/api/v1/adherence": {"signals": [], "note": ""},
    "/api/v1/patient-data/measurements": {"measurements": []},
    "/api/v1/appointment-prep": {
        "handoff": {
            "record_count": 0,
            "record_period": {"from": None, "to": None},
            "providers_documented": [],
            "known_allergies": [],
            "latest_medication_record": None,
            "latest_documented_medications": [],
            "key_findings": [],
        },
        "priorities": [],
        "checklist": [],
        "questions": [],
        "note": "",
        "method": "",
    },
    "/api/v1/follow-up": {
        "tasks": [],
        "summary": {"total": 0, "record_verification": 0},
        "note": "Preview stub: no records uploaded.",
        "method": "",
    },
    "/api/v1/preventive-care": {
        "age": None,
        "sex": None,
        "care_gaps": [],
        "count": 0,
        "note": "Preview stub: add a profile to generate reminders.",
    },
    "/api/v1/provider-messages": {"threads": [], "messages": []},
    "/api/v1/consult-triage": {
        "consult_needed": False,
        "recommended_specialties": [],
        "pharmacist_actions": [],
        "doctor_actions": [],
        "referral_items": [],
        "summary": "",
        "emergency_advice": "",
    },
    "/api/v1/care-recommendations": {
        "eligible": False,
        "flags": [],
        "message": "Preview stub: upload a record to raise a safety flag.",
        "disclaimer": "Preview data. Not medical advice.",
    },
    "/api/v1/care/recommendations": {"recommendations": []},
    "/api/v1/care/suggestion": {"suggestion": None, "specialties": []},
    "/api/v1/care/facilities": {"facilities": [], "count": 0},
    "/api/v1/guidelines/status": {"sources": [], "checked_at": None, "summary": {}},
    "/api/v1/analyses": {"analyses": []},
    "/api/v1/profile": {},
    "/api/v1/sessions": {"sessions": []},
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send({})

    def do_GET(self):
        self._send(PAYLOADS.get(self.path.split("?")[0], {}))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/v1/provider-messages":
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(
                {
                    "thread_id": "preview",
                    "direction": "outbound",
                    "provider": body.get("provider", ""),
                    "body": body.get("body", ""),
                    "created_at": "2026-08-19T10:00:00Z",
                }
            )
            return
        self._send(PAYLOADS.get(path, {}))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Preview API stub on http://0.0.0.0:8000 — empty payloads only.")
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
