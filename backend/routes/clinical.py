"""Clinical intelligence routes — finding feedback, vital trends,
symptom analysis, preventive care, alerts, adherence, early warning,
finding lifecycle, FHIR import, measurements, provider messages,
guidelines, reconciliation, deterioration, and finding history.
"""

import logging

from dotenv import load_dotenv

load_dotenv(override=True)


from typing import Any, Dict, List, Optional, Tuple  # noqa: E402

from fastapi import (  # noqa: E402
    APIRouter,
    Depends,
    HTTPException,
)

import audit  # noqa: E402
import db  # noqa: E402
from auth import get_current_user  # noqa: E402

logger = logging.getLogger("api.clinical")

router = APIRouter()


from routes.records import (  # noqa: E402
    _derive_record,
    _enhanced_cross_check,
    _load_snapshot_or_rebuild,
    _prepare_current_trust_state,
    _replace_index,
)


@router.post("/api/v1/findings/feedback")
async def record_finding_feedback(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Record a reviewer's judgement on one finding.

    verdict is one of: confirmed, false_positive, needs_change, overridden
    (overridden = an alert was dismissed — supply a reason). This closes the
    safety loop and feeds alert-fatigue metrics. Anonymous-friendly: `reviewer`
    is a free-text label, not an account.
    """
    from clinician_feedback import finding_key_from, record_feedback

    fkey = (payload.get("finding_key") or "").strip()
    if not fkey:
        # Allow callers that only have the finding's components to derive it.
        fkey = finding_key_from(
            finding_kind=payload.get("finding_kind", ""),
            rule=payload.get("rule", ""),
            medications_involved=payload.get("medications_involved"),
            condition=payload.get("condition", ""),
            organ=payload.get("organ", ""),
        )
    if not fkey:
        raise HTTPException(400, "finding_key (or finding components) is required.")
    try:
        entry = record_feedback(
            user_id,
            fkey,
            payload.get("verdict", ""),
            finding_kind=payload.get("finding_kind", ""),
            rule=payload.get("rule", ""),
            reason=payload.get("reason", ""),
            note=payload.get("note", ""),
            reviewer=payload.get("reviewer", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(
        user_id,
        "finding.feedback",
        {
            "verdict": entry["verdict"],
            "finding_key": fkey,
        },
    )
    return entry


@router.get("/api/v1/findings/feedback")
async def list_finding_feedback(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """List all reviewer feedback recorded for this workspace (newest last)."""
    from clinician_feedback import list_feedback

    return {"feedback": list_feedback(user_id)}


@router.get("/api/v1/findings/feedback/metrics")
async def finding_feedback_metrics(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Aggregate reviewer performance metrics: confirmation / false-positive /
    override rates, per-finding-kind breakdown, and the noisiest rules
    (highest override + false-positive counts) — the alert-fatigue signal."""
    from clinician_feedback import get_feedback_metrics

    return get_feedback_metrics(user_id)


# ---- P1/P2 longitudinal & platform features ------------------------------ #


def _patient_age_sex(user_id: str) -> Tuple[Optional[int], Optional[str]]:
    """Best-effort age/sex from the saved profile (DOB) and extracted record."""
    age: Optional[int] = None
    sex: Optional[str] = None
    try:
        profile = db.load_patient_profile(user_id) or {}
        dob = profile.get("date_of_birth")
        if dob:
            from datetime import date

            d = date.fromisoformat(str(dob)[:10])
            age = (date.today() - d).days // 365
    except Exception:
        pass
    return age, sex


@router.get("/api/v1/vital-trends")
async def get_vital_trends(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Longitudinal analysis of blood pressure, pulse, oxygen saturation,
    weight, temperature, respiratory rate and glucose — direction of drift and
    latest-reading screening flags. Deterministic, no diagnosis. Patient-
    reported measurements are folded in."""
    from patient_data import augment_timeline
    from vital_trends import track_vital_trends

    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    timeline = augment_timeline(snapshot["patient_timeline"], user_id)
    return track_vital_trends(timeline)


@router.post("/api/v1/symptoms/analyse")
async def analyse_patient_symptom(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cross-reference a patient-reported symptom against the record
    (relevant medications, conditions, abnormal labs). NOT a diagnosis."""
    from symptom_intake import analyse_symptom

    # Symptom intake must work even before any document is uploaded, so a
    # missing/unloadable snapshot degrades to an empty record rather than 5xx.
    try:
        snapshot = _load_snapshot_or_rebuild(user_id)
        timeline = snapshot["patient_timeline"] if snapshot else {"medications_timeline": []}
    except Exception:
        timeline = {"medications_timeline": []}
    symptom = (payload.get("symptom") or payload.get("text") or "").strip()
    if not symptom:
        raise HTTPException(400, "symptom is required")
    return analyse_symptom(timeline, symptom, duration=payload.get("duration"))


@router.get("/api/v1/preventive-care")
async def get_preventive_care(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """General preventive-care / care-gap reminders based on age, sex and the
    conditions on record. 'Not seen in your records' is not 'never done'."""
    from preventive_care import generate_care_gaps

    try:
        snapshot = _load_snapshot_or_rebuild(user_id)
        timeline = snapshot["patient_timeline"] if snapshot else {}
    except Exception:
        timeline = {}
    age, sex = _patient_age_sex(user_id)
    return generate_care_gaps(timeline, age, sex)


@router.get("/api/v1/findings/alerts")
async def get_managed_alerts(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Alert-fatigue view of the cross-check: reviewer-overridden findings are
    suppressed (still available) and near-duplicates are collapsed."""
    from alert_management import manage_alerts

    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    report = _enhanced_cross_check(snapshot, user_id)
    return manage_alerts(report, user_id)


@router.get("/api/v1/adherence")
async def get_adherence(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Possible non-adherence signals (refill gaps, late refills, apparent
    stops) inferred from prescription DATES. Supply evidence, not proof of
    intake. Deterministic."""
    from adherence import analyse_adherence

    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    return analyse_adherence(snapshot["patient_timeline"])


@router.get("/api/v1/early-warning")
async def get_early_warning(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Aggregate deterioration-risk screen (NEWS2-style) from the most recent
    vitals and key labs. Patient-reported measurements are folded in."""
    from early_warning import compute_early_warning_score
    from patient_data import augment_timeline

    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    timeline = augment_timeline(snapshot["patient_timeline"], user_id)
    return compute_early_warning_score(timeline)


@router.post("/api/v1/findings/lifecycle")
async def set_finding_lifecycle(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Move a finding through its lifecycle (new/active/reviewed/confirmed/
    dismissed/resolved/reopened). Illegal transitions are rejected."""
    import finding_lifecycle as fl

    finding = {
        "finding_kind": payload.get("finding_kind", ""),
        "rule": payload.get("rule", ""),
        "medications_involved": payload.get("medications_involved"),
        "condition": payload.get("condition", ""),
        "organ": payload.get("organ", ""),
    }
    try:
        return fl.transition(
            user_id,
            finding,
            payload.get("to_state", ""),
            reason=payload.get("reason", ""),
            actor=payload.get("actor", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/v1/findings/lifecycle")
async def get_finding_lifecycle(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    import finding_lifecycle as fl
    from alert_management import FINDING_LISTS

    snapshot = _load_snapshot_or_rebuild(user_id)
    report = _enhanced_cross_check(snapshot, user_id) if snapshot else {}
    findings: List[Dict[str, Any]] = []
    for key in FINDING_LISTS:
        findings.extend(report.get(key) or [])
    return fl.lifecycle_overview(user_id, findings)


@router.post("/api/v1/import/fhir")
async def import_fhir(
    payload: Dict[str, Any], user_id: str = Depends(get_current_user)
) -> Dict[str, Any]:
    """Ingest a FHIR R4 Bundle into the extraction document shape and persist
    it to the workspace (then re-derive like any upload). The parse result is
    always returned so the UI can preview what was understood even when
    persistence is unavailable (best-effort), instead of a bare 502."""
    from fhir_ingestion import parse_fhir_bundle

    bundle = payload.get("bundle") or payload
    try:
        result = parse_fhir_bundle(bundle, document_id=f"fhir_{user_id[:8]}")
    except Exception as e:
        raise HTTPException(400, f"FHIR bundle could not be parsed: {e}")

    # Importing appends documents to the same workspace an in-flight upload
    # is rebuilding; serialize them under the same 409 contract as the other
    # record-mutating endpoints.
    from routes.records import has_active_upload_pipeline
    from routes.upload import workspace_has_active_document_job

    if has_active_upload_pipeline(user_id) or workspace_has_active_document_job(user_id):
        raise HTTPException(
            409,
            "A document is still being processed. Wait for it to finish before importing.",  # noqa: E501
        )

    docs = result.get("documents") or []
    result["persisted"] = False
    result["persistence_error"] = None
    if docs:
        try:
            db.insert_documents(user_id, docs)
            audit.record(user_id, "fhir.import", {"resources": result["imported"]})
            result["persisted"] = True
        except Exception as e:
            # Surface the parse result anyway — the data is valid; only the
            # storage layer (e.g. Supabase not configured) is unavailable.
            result["persistence_error"] = str(e)
            return result

        # Re-derive the whole record like an upload so the imported data
        # enters the timeline, the safety analysis and the search index
        # immediately instead of waiting for the next manual re-analysis.
        # Fail-open: a derivation failure (e.g. the provider is rate-limited)
        # leaves the documents persisted — reads rebuild the timeline from
        # them and the user can re-run the safety analysis.
        try:
            all_docs = db.load_documents(user_id)
            trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(
                user_id, all_docs
            )
            persisted_conflicts = db.sync_conflicts(user_id, detected) if detected else conflicts
            timeline, cross_check, lab_trends = await _derive_record(
                trusted, persisted_conflicts, trust_summary, user_id
            )
            timeline["conflicts"] = persisted_conflicts
            db.save_patient_snapshot(user_id, timeline, cross_check, lab_trends=lab_trends)
            indexed, index_error, _chunks = await _replace_index(user_id, timeline)
            result["derived"] = True
            result["indexed"] = indexed
            result["index_error"] = index_error
        except Exception as e:
            logger.warning(
                "fhir import: user=%s re-derivation failed after persisting %d document(s): %s",
                user_id,
                len(docs),
                e,
            )
            result["derived"] = False
            result["derivation_error"] = str(e)
    return result


@router.post("/api/v1/patient-data/measurements")
async def record_patient_measurement(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    from patient_data import record_measurement

    name = (payload.get("name") or "").strip()
    value = payload.get("value")
    if not name or value is None:
        raise HTTPException(400, "name and value are required")
    return record_measurement(
        user_id,
        name,
        str(value),
        unit=payload.get("unit", ""),
        measured_at=payload.get("measured_at"),
        kind=payload.get("kind"),
        note=payload.get("note", ""),
    )


@router.get("/api/v1/patient-data/measurements")
async def list_patient_measurements(
    kind: Optional[str] = None,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    from patient_data import list_measurements

    return {"measurements": list_measurements(user_id, kind=kind)}


@router.post("/api/v1/provider-messages")
async def send_provider_message(
    payload: Dict[str, Any],
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    from secure_messaging import send_message

    try:
        return send_message(
            user_id,
            payload.get("body", ""),
            provider=payload.get("provider", ""),
            thread_id=payload.get("thread_id"),
            finding_key=payload.get("finding_key"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/v1/provider-messages")
async def list_provider_messages(
    thread_id: Optional[str] = None,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    from secure_messaging import list_messages, list_threads

    if thread_id:
        return {"thread_id": thread_id, "messages": list_messages(user_id, thread_id)}
    return {"threads": list_threads(user_id)}


@router.get("/api/v1/guidelines/status")
async def guidelines_status() -> Dict[str, Any]:
    """Living-guidelines registry: which curated clinical sources are current
    vs due for review."""
    from living_guidelines import registry_status

    return registry_status()


@router.post("/api/v1/guidelines/refresh")
async def refresh_guidelines(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Check the living-guidelines manifest (LIVING_GUIDELINES_MANIFEST_URL) for
    newer published versions and apply any found. Fails open to 'manual review'
    when no manifest is configured. Operator-gated (authenticated)."""
    from living_guidelines import apply_updates

    result = apply_updates()
    audit.record(
        user_id,
        "guidelines.refresh",
        {
            "applied": result.get("applied_count", 0),
            "checked": result.get("checked", False),
        },
    )
    return result


@router.get("/api/v1/medications/reconciliation")
async def get_medication_reconciliation(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Reconciled current medication list: active / duplicate / dose-conflict /
    discontinued / single-supply per ingredient. Deterministic."""
    from medication_reconciliation import reconcile_medications

    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    return reconcile_medications(snapshot["patient_timeline"])


@router.get("/api/v1/deterioration")
async def get_deterioration(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Longitudinal early-warning trajectory across every dated reading, with
    trend, sustained-high detection, and the signals that worsened. Patient-
    reported measurements are folded in."""
    from deterioration import deterioration_trajectory
    from patient_data import augment_timeline

    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    timeline = augment_timeline(snapshot["patient_timeline"], user_id)
    return deterioration_trajectory(timeline)


@router.post("/api/v1/findings/history/snapshot")
async def snapshot_finding_history(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Snapshot the findings currently in the cross-check and return the diff
    against the previous snapshot (new / resolved / persisted)."""
    import finding_history as fh

    snapshot = _load_snapshot_or_rebuild(user_id)
    report = _enhanced_cross_check(snapshot, user_id) if snapshot else {}
    return fh.snapshot_findings(user_id, report)


@router.get("/api/v1/findings/history")
async def get_finding_history(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Chronological list of finding snapshots (audit trail of how findings
    changed across re-analyses)."""
    import finding_history as fh

    return {"snapshots": fh.finding_history(user_id)}


@router.get("/api/v1/findings/history/change-log")
async def get_finding_change_log(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Per-finding change log: first seen, last seen, recurrence."""
    import finding_history as fh

    return fh.finding_change_log(user_id)


# ---------------------------------------------------------------------------
# Patchable indirection
# ---------------------------------------------------------------------------
# Tests patch these names on the `api` module; resolve through api at call time.


def process_document(*args, **kwargs):
    import api as _api

    return _api.process_document(*args, **kwargs)
