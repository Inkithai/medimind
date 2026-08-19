"""Record views — timeline, cross-check, medication safety, lab trends,
export, follow-up, appointment prep, and the shared snapshot/trust-state
helpers used by the other route modules.
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv(override=True)
import re  # noqa: E402
from datetime import date  # noqa: E402
from typing import Any, Dict, List, Literal, Optional, Tuple  # noqa: E402

from fastapi import (  # noqa: E402
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from pydantic import BaseModel, Field, field_validator  # noqa: E402

import audit  # noqa: E402
import db  # noqa: E402
import export as export_module  # noqa: E402
import graph_db  # noqa: E402
import jobs  # noqa: E402
import vector_store  # noqa: E402
from appointment_prep import build_appointment_prep  # noqa: E402
from auth import get_current_user  # noqa: E402
from change_detection import detect_record_changes  # noqa: E402
from consult_triage import TRIAGE_OUTPUT_VERSION  # noqa: E402
from follow_up import build_follow_up_plan  # noqa: E402
from lab_trends import track_lab_trends  # noqa: E402
from medical_extractor import (  # noqa: E402
    build_patient_timeline,
)
from medication_safety import analyze_medication_safety  # noqa: E402
from record_integrity import check_record_integrity  # noqa: E402
from record_trust import (  # noqa: E402
    apply_conflict_quarantine,
    detect_conflicts,
    merge_conflict_state,
)
from retrieval import timeline_fingerprint  # noqa: E402
from risk_timeline import build_treatment_windows, concurrent_exposure, risk_calendar  # noqa: E402

logger = logging.getLogger("api.records")


# Shared bounded executor for LLM/cross-check work. One pool for the whole
# process: the upload pipeline (routes/upload.py) and the cross-check path
# here both submit through it, so UPLOAD_FILE_CONCURRENCY bounds the total
# provider concurrency no matter which feature is running.
def _upload_worker_count() -> int:
    """Global extraction concurrency, bounded to protect provider quotas."""
    try:
        return max(1, min(8, int(os.environ.get("UPLOAD_FILE_CONCURRENCY", "1"))))
    except ValueError:
        return 1


UPLOAD_FILE_CONCURRENCY = _upload_worker_count()
_DOCUMENT_EXECUTOR = ThreadPoolExecutor(
    max_workers=UPLOAD_FILE_CONCURRENCY,
    thread_name_prefix="medimind-document",
)


router = APIRouter()


def _lab_trends_need_recompute(report: Any) -> bool:
    """True when a stored snapshot predates recovery / unit-mismatch fixes."""
    if not isinstance(report, dict):
        return True
    trends = report.get("trends")
    if not isinstance(trends, list):
        return True
    for trend in trends:
        if (
            not isinstance(trend, dict)
            or "returned_to_normal" not in trend
            or "risk_level" not in trend
        ):
            return True
    return False


def _lab_trends_for_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    stored = snapshot.get("lab_trends")
    if stored is None or _lab_trends_need_recompute(stored):
        return track_lab_trends(snapshot["patient_timeline"])
    return stored


class PatientProfileRequest(BaseModel):
    legal_name: Optional[str] = Field(default=None, max_length=200)
    preferred_name: Optional[str] = Field(default=None, max_length=200)
    date_of_birth: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    emergency_contact: Optional[str] = Field(default=None, max_length=300)
    preferred_language: Optional[str] = Field(default=None, max_length=50)

    @field_validator("date_of_birth")
    @classmethod
    def validate_birth_date(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        from date_convention import sanitize_clinical_date

        cleaned = sanitize_clinical_date(value)
        if cleaned is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            raise ValueError("Date of birth must be a complete YYYY-MM-DD date.")
        parsed = date.fromisoformat(cleaned)
        if parsed > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return cleaned

    @field_validator(
        "legal_name", "preferred_name", "phone", "emergency_contact", "preferred_language"
    )
    @classmethod
    def trim_optional(cls, value: Optional[str]) -> Optional[str]:
        cleaned = (value or "").strip()
        return cleaned or None


def _empty_cross_check(reason: str) -> Dict[str, Any]:
    return {
        "potential_drug_interactions": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
        "overall_recommendation": reason,
        "reference_date": None,
        "medication_activity": {
            "reference_date": None,
            "active_medications": [],
            "inactive_medications": [],
            "active_count": 0,
            "inactive_count": 0,
        },
    }


def _antidote_context(
    timeline: Dict[str, Any], user_id: str, operation: str
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Best-effort WHO antidote reference-graph lookup for a medication
    timeline. Returns (graph_backed_findings, reference_notes).

    Fail-open by design: an unconfigured, unreachable, or failing graph
    never fails the upload — it just means no reference notes are attached
    and findings grade as model knowledge (the honest default). One round
    trip to the graph per record, reused for both evidence grading and the
    patient-facing reference notes.
    """
    if not graph_db.is_configured():
        logger.debug(
            "%s: user=%s antidote graph not configured (NEO4J_* unset or driver "
            "missing) — skipping reference lookup",
            operation,
            user_id,
        )
        return {}, []

    from evidence_grading import graph_backed_findings_from_antidotes
    from poisoning_kg import lookup_antidote_references

    med_names = sorted(
        {m.get("name") for m in timeline.get("medications_timeline", []) if m.get("name")}
    )
    try:
        logger.info(
            "%s: user=%s querying antidote graph for %d medication name(s)",
            operation,
            user_id,
            len(med_names),
        )
        references = lookup_antidote_references(med_names)
    except Exception as e:
        # graph_db/poisoning_kg have already logged the failing step and the
        # (redacted) URI; this records that the operation CONTINUED without
        # the enrichment — an empty reference_notes list means "not checked",
        # not "checked and found nothing".
        logger.warning(
            "%s: user=%s antidote reference lookup skipped, continuing without it "
            "(findings will grade as unverified model knowledge): %s",
            operation,
            user_id,
            e,
        )
        return {}, []

    notes = [{"medication": name, **ref} for name, ref in sorted(references.items())]
    if notes:
        logger.info(
            "%s: user=%s antidote graph matched %d of %d medication(s): %s",
            operation,
            user_id,
            len(notes),
            len(med_names),
            ", ".join(n["medication"] for n in notes),
        )
    return graph_backed_findings_from_antidotes(references), notes


def _attach_eml_age_safety(
    cross_check: Dict[str, Any], timeline: Dict[str, Any], user_id: Optional[str] = None
) -> None:
    """Attach full-list age restrictions when the optional graph is populated."""
    if not graph_db.is_configured():
        cross_check.setdefault("eml_age_restrictions", [])
        cross_check.setdefault("eml_age_conflicts", [])
        return
    medication_names = sorted(
        {
            str(ingredient).strip().lower()
            for medication in timeline.get("medications_timeline") or []
            for ingredient in medication.get("ingredients") or []
            if str(ingredient).strip()
        }
    )
    if not medication_names:
        return
    try:
        from eml_kg import lookup_age_restrictions
        from eml_safety import evaluate_age_restrictions, patient_age_from_timeline

        restrictions = lookup_age_restrictions(medication_names)
        age = patient_age_from_timeline(timeline)
        if age is None and user_id:
            try:
                profile = db.load_patient_profile(user_id)
                if profile and profile.get("date_of_birth"):
                    born = date.fromisoformat(str(profile["date_of_birth"]))
                    today = date.today()
                    age = (
                        today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                    )
            except Exception:
                pass
        cross_check["eml_age_restrictions"] = restrictions
        cross_check["eml_age_conflicts"] = evaluate_age_restrictions(age, restrictions)
    except Exception as exc:
        logger.warning("full EML age lookup skipped: %s", exc)
        cross_check.setdefault("eml_age_restrictions", [])
        cross_check.setdefault("eml_age_conflicts", [])


async def _cross_check_trusted_timeline(
    timeline: Dict[str, Any],
    graph_backed_findings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not timeline.get("medications_timeline"):
        return _empty_cross_check(
            "No trusted medication facts are currently available for safety analysis. "
            "Resolve quarantined conflicts and consult a doctor or pharmacist before making changes."  # noqa: E501
        )

    def _run() -> Dict[str, Any]:
        return analyze_medication_safety(timeline, graph_backed_findings=graph_backed_findings)

    return await asyncio.get_running_loop().run_in_executor(_DOCUMENT_EXECUTOR, _run)


@router.get("/api/v1/profile")
async def get_patient_profile(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    profile = db.load_patient_profile(user_id)
    return profile or {
        "user_id": user_id,
        "legal_name": None,
        "preferred_name": None,
        "date_of_birth": None,
        "phone": None,
        "emergency_contact": None,
        "preferred_language": None,
        "updated_at": None,
    }


@router.put("/api/v1/profile")
async def update_patient_profile(
    request: PatientProfileRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    profile = db.save_patient_profile(user_id, request.model_dump())
    audit.record(
        user_id,
        "profile.updated",
        {
            "fields": sorted(
                key for key, value in request.model_dump().items() if value is not None
            ),
        },
    )
    return profile


@router.get("/api/v1/clinical-entities/{kind}")
async def get_clinical_entities(
    kind: Literal[
        "clinical_medications",
        "clinical_prescriptions",
        "clinical_allergies",
        "clinical_lab_results",
        "clinical_events",
        "safety_findings",
    ],
    limit: int = Query(default=500, ge=1, le=1000),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = db.load_clinical_entities(user_id, kind, limit)
    return {"kind": kind, "count": len(rows), "items": rows}


# ---------------------------------------------------------------------------
# Documents / timeline / cross-check / lab trends
# ---------------------------------------------------------------------------


def _prepare_current_trust_state_impl(
    user_id: str,
    documents: Optional[List[Dict[str, Any]]] = None,
    *,
    conflict_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    corrected_docs = documents if documents is not None else db.load_documents(user_id)
    detected = detect_conflicts(corrected_docs)
    persisted = db.load_conflicts(user_id) if detected else []
    conflicts = merge_conflict_state(detected, persisted)
    if conflict_overrides:
        conflicts = [
            {**conflict, **conflict_overrides.get(str(conflict.get("conflict_id")), {})}
            for conflict in conflicts
        ]
    trusted_docs, trust_summary = apply_conflict_quarantine(corrected_docs, conflicts)
    return trusted_docs, conflicts, trust_summary, detected


def _timeline_from_trust_state(
    trusted_docs: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    trust_summary: Dict[str, Any],
) -> Dict[str, Any]:
    timeline = build_patient_timeline(trusted_docs)
    timeline["trust_summary"] = trust_summary
    timeline["conflicts"] = conflicts
    timeline["_record_fingerprint"] = timeline_fingerprint(timeline)
    return timeline


async def _derive_record_impl(
    trusted_docs: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    trust_summary: Dict[str, Any],
    user_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    timeline = _timeline_from_trust_state(trusted_docs, conflicts, trust_summary)
    graph_backed_findings, antidote_reference_notes = _antidote_context(
        timeline, user_id, "record_rebuild"
    )
    cross_check = await _cross_check_trusted_timeline(timeline, graph_backed_findings)
    _attach_eml_age_safety(cross_check, timeline, user_id)
    cross_check["antidote_reference_notes"] = antidote_reference_notes
    lab_trends = track_lab_trends(timeline)
    return timeline, cross_check, lab_trends


async def _replace_index_impl(
    user_id: str, timeline: Dict[str, Any]
) -> Tuple[bool, Optional[str], int]:
    try:
        count = await asyncio.to_thread(index_patient_timeline, user_id, timeline, replace=True)
        if count == 0:
            return (
                False,
                "No trusted facts are currently available to index; unresolved conflicts may be quarantined.",  # noqa: E501
                0,
            )
        return True, None, count
    except Exception as exc:
        logger.error(
            "record rebuild: user=%s index replacement failed: %s", user_id, exc, exc_info=True
        )
        return False, str(exc), 0


async def _rebuild_after_document_deletion_impl(
    user_id: str,
    remaining_documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Replace every derived view without retaining facts from a deleted source."""
    db.clear_conflict_history(user_id)
    if not remaining_documents:
        db.delete_patient_snapshot(user_id)
        await asyncio.to_thread(vector_store.delete_collection, user_id)
        return {
            "documents_remaining": 0,
            "timeline": None,
            "indexed": True,
            "index_error": None,
        }

    trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(
        user_id, remaining_documents
    )
    persisted_conflicts = db.sync_conflicts(user_id, detected) if detected else []
    # Re-run the complete safety pipeline immediately. Deletion must remove
    # findings that depended on the deleted source without leaving the
    # remaining medication record temporarily unchecked.
    timeline, cross_check, lab_trends = await _derive_record(
        trusted, persisted_conflicts, trust_summary, user_id
    )
    dosage_report = check_dosages(timeline)
    consult_triage_report = generate_consult_triage(
        cross_check, lab_trends, dosage_report, timeline
    )
    db.save_patient_snapshot(
        user_id,
        timeline,
        cross_check,
        lab_trends=lab_trends,
        dosage_report=dosage_report,
        consult_triage=consult_triage_report,
    )
    indexed, index_error, _ = await _replace_index(user_id, timeline)
    return {
        "documents_remaining": len(remaining_documents),
        "timeline": timeline,
        "indexed": indexed,
        "index_error": index_error,
    }


def _workspace_has_active_upload_impl(user_id: str) -> bool:
    return any(
        job.get("status") in {"pending", "processing"} for job in jobs.list_jobs(user_id, limit=100)
    )


def _rebuild_snapshot_from_documents(user_id: str) -> Optional[Dict[str, Any]]:
    """Reconstruct the patient snapshot directly from the saved documents.

    `patient_snapshots` is a convenience cache: everything in it is derived
    from the append-only `documents` rows. If that cache row is missing
    (never written because the process died mid-upload, or wiped), the
    dashboard must NOT claim the user has no records — the documents are
    still in the database. Rebuilding here is deterministic and free: the
    timeline merge and lab-trend analysis are pure functions. Only the
    safety cross-check needs an LLM, so it is returned empty and refreshed
    on the next upload rather than firing a provider call from a GET.
    """
    try:
        documents = db.load_documents(user_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("snapshot rebuild: user=%s could not load documents: %s", user_id, exc)
        return None
    if not documents:
        return None

    logger.info(
        "snapshot rebuild: user=%s reconstructing from %d persisted document(s)",
        user_id,
        len(documents),
    )
    timeline = build_patient_timeline(documents)
    return {
        "patient_timeline": timeline,
        "cross_check_report": dict(_EMPTY_CROSS_CHECK),
        "lab_trends": track_lab_trends(timeline),
        "updated_at": None,
        "rebuilt_from_documents": True,
    }


def _load_snapshot_or_rebuild_impl(user_id: str) -> Optional[Dict[str, Any]]:
    """Return a current, fail-closed view rebuilt from durable source rows.

    The snapshot remains a cache for expensive safety output, but corrected
    and quarantined documents are replayed on every read so an older cache can
    never re-admit unresolved or non-authoritative facts.
    """
    snapshot = db.load_patient_snapshot(user_id)
    documents = db.load_documents(user_id)
    if not documents:
        return snapshot

    trusted, conflicts, summary, _detected = _prepare_current_trust_state(user_id, documents)
    timeline = _timeline_from_trust_state(trusted, conflicts, summary)
    saved_fingerprint = (snapshot or {}).get("patient_timeline", {}).get("_record_fingerprint")
    cache_is_current = bool(snapshot and saved_fingerprint == timeline.get("_record_fingerprint"))
    if cache_is_current and not summary.get("unresolved_conflicts"):
        cross_check = snapshot.get("cross_check_report") or dict(_EMPTY_CROSS_CHECK)
    else:
        cross_check = _empty_cross_check(
            "Safety analysis is withheld while corrected or conflicting evidence awaits a trusted rebuild. "  # noqa: E501
            "Confirm the source and consult a doctor or pharmacist before making changes."
        )
    result = {
        "patient_timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": track_lab_trends(timeline),
        "updated_at": (snapshot or {}).get("updated_at"),
    }
    if snapshot is None:
        result["rebuilt_from_documents"] = True
    return result


def _enhanced_cross_check_impl(
    snapshot: Dict[str, Any], user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Backfill deterministic findings/source links for older snapshots."""
    from medication_activity import analyze_medication_activity
    from medication_history import detect_medication_transitions, enrich_cross_check_sources

    timeline = snapshot["patient_timeline"]
    report = dict(snapshot.get("cross_check_report") or {})
    report.setdefault("potential_drug_interactions", [])
    report.setdefault("duplicate_prescriptions", [])
    report.setdefault("conflicting_dosage_instructions", [])
    report.setdefault("allergy_conflicts", [])
    # Newer deterministic safety layers (drug-lab, renal/hepatic, condition).
    # Backfilled on read for snapshots saved before these engines existed, so
    # every stored record surfaces them without a re-upload.
    for _key, _mod, _check, _merge in (
        (
            "drug_lab_findings",
            "drug_lab_interactions",
            "check_drug_lab_findings",
            "merge_drug_lab_findings",
        ),
        (
            "renal_hepatic_findings",
            "renal_hepatic_dosing",
            "check_renal_hepatic_findings",
            "merge_renal_hepatic_findings",
        ),
        (
            "condition_contraindications",
            "condition_contraindications",
            "check_condition_contraindications",
            "merge_condition_contraindications",
        ),
    ):
        try:
            if not report.get(_key):
                import importlib

                mod = importlib.import_module(_mod)
                _merge = getattr(mod, _merge)
                _check = getattr(mod, _check)
                _merge(report, _check(timeline))
        except Exception:
            report.setdefault(_key, [])
    transitions = detect_medication_transitions(timeline)
    report.setdefault("medication_changes", transitions["medication_changes"])
    report.setdefault("medication_continuations", transitions["medication_continuations"])
    # Snapshots saved before activity scoping exist: backfill the
    # deterministic active/inactive classification on read (no LLM call)
    # so every stored record gets reference-date awareness.
    if "medication_activity" not in report:
        activity = analyze_medication_activity(timeline)
        report["medication_activity"] = activity
        report["reference_date"] = activity["reference_date"]
    enriched = enrich_cross_check_sources(report, timeline)
    # Alert-fatigue annotation: stamp each finding with its latest reviewer
    # verdict so overridden alerts can be de-emphasised (never silently
    # hidden). Nothing is deleted — safety findings stay visible.
    if user_id:
        try:
            from clinician_feedback import finding_key, latest_verdict

            overridden = 0
            for key in (
                "potential_drug_interactions",
                "duplicate_prescriptions",
                "conflicting_dosage_instructions",
                "allergy_conflicts",
                "drug_lab_findings",
                "renal_hepatic_findings",
                "condition_contraindications",
            ):
                for finding in enriched.get(key) or []:
                    fkey = finding_key(finding)
                    verdict = latest_verdict(user_id, fkey)
                    finding["feedback_verdict"] = verdict
                    finding["is_overridden"] = verdict == "overridden"
                    if finding["is_overridden"]:
                        overridden += 1
            enriched["feedback_summary"] = {"overridden_findings": overridden}
        except Exception:
            pass
    return enriched


def _enhanced_lab_trends(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    saved = snapshot.get("lab_trends")
    if saved and all("risk_level" in trend for trend in saved.get("trends", [])):
        return saved
    return track_lab_trends(snapshot["patient_timeline"])


@router.get("/api/v1/timeline")
async def get_timeline(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's merged timeline (medications, lab
    results, visits, allergies) from the most recent upload/processing run."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return snapshot["patient_timeline"]


@router.get("/api/v1/cross-check")
async def get_cross_check(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's latest cross-check report
    (interactions, duplicates, dosage conflicts, allergy conflicts)."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No cross-check report found for this user.")
    return _enhanced_cross_check(snapshot, user_id)


@router.get("/api/v1/medication-safety")
async def get_medication_safety(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Dedicated medication-safety API.

    Reads the saved patient timeline and returns the structured safety
    analysis produced by ``medication_safety.py``. This is not extraction
    and is not RAG — it is a separate service that writes analyses from
    medications already on the record.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No medication-safety report found for this user.")
    report = _enhanced_cross_check(snapshot, user_id)
    dosage = snapshot.get("dosage_report") or check_dosages(snapshot["patient_timeline"])
    return {
        **report,
        "service": "medication_safety",
        "module": "medication_safety.py",
        "dosage_report": dosage,
        "disclaimer": (
            "This is an observation from uploaded records, not a diagnosis. "
            "Consult a doctor or pharmacist before making any medication changes."
        ),
    }


@router.post("/api/v1/medication-safety/reanalyze")
async def reanalyze_medication_safety(
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Re-run and persist the complete safety/triage pipeline on demand.

    Uses the corrected, conflict-filtered durable documents rather than a
    potentially stale snapshot. The response includes before/after counts so
    clients can explain whether findings were added or resolved.
    """
    if _workspace_has_active_upload(user_id):
        raise HTTPException(
            409, "Wait for the active upload to finish before re-running safety analysis."
        )
    documents = db.load_documents(user_id)
    if not documents:
        raise HTTPException(404, "No documents are available for safety analysis.")

    previous = db.load_patient_snapshot(user_id) or {}
    previous_cross_check = previous.get("cross_check_report") or {}
    trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(user_id, documents)
    if detected:
        conflicts = db.sync_conflicts(user_id, detected)
    timeline, cross_check, lab_trends = await _derive_record(
        trusted, conflicts, trust_summary, user_id
    )
    dosage_report = check_dosages(timeline)
    triage = generate_consult_triage(cross_check, lab_trends, dosage_report, timeline)
    reconciliation = db.save_patient_snapshot(
        user_id,
        timeline,
        cross_check,
        lab_trends=lab_trends,
        dosage_report=dosage_report,
        consult_triage=triage,
    ) or {"available": False, "tables": {}}
    indexed, index_error, indexed_chunks = await _replace_index(user_id, timeline)

    finding_lists = (
        "potential_drug_interactions",
        "duplicate_prescriptions",
        "conflicting_dosage_instructions",
        "allergy_conflicts",
        "guideline_flagged_combinations",
        "concurrent_exposure",
        "eml_age_conflicts",
        "drug_lab_findings",
        "renal_hepatic_findings",
        "condition_contraindications",
    )

    def count(report):
        return sum(len(report.get(key) or []) for key in finding_lists)

    before_count = count(previous_cross_check)
    after_count = count(cross_check)
    audit.record(
        user_id,
        "medication_safety.reanalyzed",
        {
            "findings_before": before_count,
            "findings_after": after_count,
            "indexed": indexed,
        },
    )
    # Record an immutable finding-history snapshot for this run so the audit
    # trail (new / resolved / persisted across re-analyses) builds automatically.
    try:
        import finding_history as fh

        fh.snapshot_findings(user_id, cross_check)
    except Exception:
        pass
    return {
        "reanalyzed": True,
        "findings_before": before_count,
        "findings_after": after_count,
        "net_change": after_count - before_count,
        "resolved_count": max(0, before_count - after_count),
        "finding_reconciliation": reconciliation.get("safety_findings", {}),
        "normalized_projection": reconciliation,
        "cross_check_report": cross_check,
        "dosage_report": dosage_report,
        "consult_triage": triage,
        "indexed": indexed,
        "indexed_chunks": indexed_chunks,
        "index_error": index_error,
    }


@router.get("/api/v1/lab-trends")
async def get_lab_trends(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's lab result trends (direction of
    drift per test, reference-range crossings, plain-language explanations)
    computed from the most recent upload/processing run. Recomputed on the
    fly from the saved timeline for snapshots saved before this field
    existed."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return _lab_trends_for_snapshot(snapshot)


@router.get("/api/v1/risk-timeline")
async def get_risk_timeline(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns this user's safety findings placed in time — a chronological
    risk view of the record: which risks were live during which dates, most
    recent period first, plus any period where two prescriptions supplied the
    same ingredient at once (double-dosing arithmetic).

    Two drugs only interact if they were taken together, so findings whose
    courses never overlapped are grouped separately as history rather than
    presented as current risks. Every finding also carries its evidence
    grade (deterministic vs model knowledge). Computed from the printed
    prescription dates and durations — no model call.

    For snapshots saved before timing/grading existed, the report is
    re-annotated on the fly from the saved timeline."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")

    timeline = snapshot.get("patient_timeline") or {}
    cross_check = dict(snapshot.get("cross_check_report") or {})

    # Backward compat: older snapshots carry findings with no timing/grading.
    if cross_check and "timing_summary" not in cross_check:
        from risk_timeline import annotate_findings_with_timing

        annotate_findings_with_timing(cross_check, timeline)
    if cross_check and "evidence_summary" not in cross_check:
        from evidence_grading import grade_cross_check

        grade_cross_check(cross_check)
    if "concurrent_exposure" not in cross_check:
        cross_check["concurrent_exposure"] = concurrent_exposure(timeline)

    return {
        "calendar": risk_calendar(cross_check, timeline),
        "concurrent_exposure": cross_check.get("concurrent_exposure") or [],
        "treatment_windows": [
            {
                **w,
                "start": w["start"].isoformat() if w["start"] else None,
                "end": w["end"].isoformat() if w["end"] else None,
            }
            for w in build_treatment_windows(timeline)
        ],
        "timing_summary": cross_check.get("timing_summary") or {},
        "evidence_summary": cross_check.get("evidence_summary") or {},
    }


@router.get("/api/v1/consult-triage")
async def get_consult_triage(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns who this user should talk to about what the pipeline found —
    a pharmacist or a doctor, how soon, with what confidence, and for a
    doctor, which specialty. Deterministic routing over the saved
    cross-check, dosage findings, and lab trends (see consult_triage.py);
    recomputed on the fly for snapshots saved before this feature existed.

    Safety properties: never de-escalates (consult_needed=false means "no
    trigger found", not "you're fine") and low confidence never lowers
    urgency."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    cached = snapshot.get("consult_triage")
    if isinstance(cached, dict) and cached.get("output_version") == TRIAGE_OUTPUT_VERSION:
        audit.record(user_id, "records.read", {"view": "consult_triage"})
        return cached
    lab_trends = _lab_trends_for_snapshot(snapshot)
    dosage_report = snapshot.get("dosage_report") or check_dosages(snapshot["patient_timeline"])
    result = generate_consult_triage(
        snapshot["cross_check_report"], lab_trends, dosage_report, snapshot["patient_timeline"]
    )
    try:
        db.save_patient_snapshot(
            user_id,
            snapshot["patient_timeline"],
            snapshot["cross_check_report"],
            lab_trends=lab_trends,
            dosage_report=dosage_report,
            consult_triage=result,
        )
    except Exception as exc:
        logger.warning("consult-triage recompute was not persisted: %s", exc)
    audit.record(user_id, "records.read", {"view": "consult_triage", "recomputed": True})
    return result


@router.get("/api/v1/dosage-report")
async def get_dosage_report(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the deterministic dosage validation report — each medication's
    normalized dose checked against published adult limits (dosage_rules.py).
    Recomputed on the fly for snapshots saved before this feature existed."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    if "dosage_report" in snapshot:
        audit.record(user_id, "records.read", {"view": "dosage_report"})
        return snapshot["dosage_report"]
    result = check_dosages(snapshot["patient_timeline"])
    audit.record(user_id, "records.read", {"view": "dosage_report", "recomputed": True})
    return result


# ---------------------------------------------------------------------------
# Reference knowledge graph (Neo4j) — WHO antidote reference data
# ---------------------------------------------------------------------------


@router.get("/api/v1/export")
async def export_record(
    format: str = Query(
        "json", description="Export format: 'json' (native, lossless) or 'fhir' (FHIR R4 Bundle)"
    ),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Exports the authenticated user's assembled record for portability.

    - format=json: the complete MediMind-native snapshot (timeline +
      cross-check + lab trends) in a self-describing envelope.
    - format=fhir: a FHIR R4 collection Bundle (Patient,
      MedicationStatement, Observation, AllergyIntolerance, Provenance)
      mapping the portable core of the record onto standard resources for
      hand-off to other health systems.

    404s if the user has never been processed. Deterministic — no LLM calls.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user — upload documents first.")
    if "lab_trends" not in snapshot:
        snapshot = {**snapshot, "lab_trends": _lab_trends_for_snapshot(snapshot)}
    try:
        result = export_module.build_export(user_id, snapshot, format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(user_id, "records.export", {"format": format.strip().lower()})
    return result


@router.get("/api/v1/export/validation")
async def validate_record_export(
    format: str = Query(
        "fhir", description="Validation format; currently only 'fhir' is supported"
    ),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate and validate the authenticated user's FHIR export.

    This is a deterministic local structural R4 check, not a substitute for
    the HL7 Java validator. It is exposed separately so the exported Bundle
    remains valid FHIR JSON without application metadata added to it.
    """
    if format.strip().lower() != "fhir":
        raise HTTPException(400, "Validation currently supports only format=fhir.")
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user — upload documents first.")
    bundle = export_module.build_fhir_bundle(user_id, snapshot)
    report = export_module.validate_fhir_bundle(bundle)
    report["format"] = "fhir"
    report["bundle_type"] = bundle.get("type")
    audit.record(user_id, "records.export_validation", {"format": "fhir", "valid": report["valid"]})
    return report


@router.get("/api/v1/changes")
async def get_record_changes(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Explain what changed between consecutive dated records.

    Results are deterministic and include both source records for every
    claim. Missing fields are never interpreted as clinical resolution or a
    discontinued treatment.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return detect_record_changes(snapshot["patient_timeline"])


@router.get("/api/v1/follow-up")
async def get_follow_up_plan(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return a source-grounded action queue without inferred deadlines."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    timeline = snapshot["patient_timeline"]
    lab_trends_data = snapshot.get("lab_trends") or track_lab_trends(timeline)
    return build_follow_up_plan(timeline, snapshot["cross_check_report"], lab_trends_data)


@router.get("/api/v1/record-integrity")
async def get_record_integrity(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Find source-linked cross-document discrepancies for verification."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return check_record_integrity(snapshot["patient_timeline"])


@router.get("/api/v1/appointment-prep")
async def get_appointment_prep(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Build a printable, source-grounded clinician conversation packet."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    timeline = snapshot["patient_timeline"]
    lab_trends_data = snapshot.get("lab_trends") or track_lab_trends(timeline)
    return build_appointment_prep(timeline, snapshot["cross_check_report"], lab_trends_data)


@router.get("/api/v1/patient-snapshot")
async def get_patient_snapshot(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's entire latest snapshot — patient
    timeline, cross-check report, and lab trends — in a single response, so
    the dashboard can render from ONE request instead of three
    (/timeline, /cross-check, /lab-trends). 404s if the user has never
    been processed (frontend treats that as the first-run empty state).

    `lab_trends` is recomputed on the fly for snapshots saved before the
    field existed, mirroring get_lab_trends()'s backward-compat behavior.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient snapshot found for this user.")
    result: Dict[str, Any] = {
        "user_id": user_id,
        "patient_timeline": snapshot["patient_timeline"],
        "cross_check_report": _enhanced_cross_check(snapshot),
        "updated_at": snapshot.get("updated_at"),
    }
    if snapshot.get("rebuilt_from_documents"):
        # Tells the client this view was reconstructed from the durable
        # documents table rather than the cached snapshot row.
        result["rebuilt_from_documents"] = True
    result["lab_trends"] = _lab_trends_for_snapshot(snapshot)
    # Derived safety reports — recomputed for pre-feature snapshots so the
    # dashboard always has them.
    result["dosage_report"] = snapshot.get("dosage_report") or check_dosages(
        snapshot["patient_timeline"]
    )
    cached_triage = snapshot.get("consult_triage")
    result["consult_triage"] = (
        cached_triage
        if isinstance(cached_triage, dict)
        and cached_triage.get("output_version") == TRIAGE_OUTPUT_VERSION
        else generate_consult_triage(
            snapshot["cross_check_report"],
            result["lab_trends"],
            result["dosage_report"],
            snapshot["patient_timeline"],
        )
    )
    try:
        result["patient_profile"] = db.load_patient_profile(user_id)
    except Exception:
        # Profile storage is additive; an older deployment must still serve
        # the clinical dashboard accurately while its schema is upgraded.
        result["patient_profile"] = None
    return result


# ---------------------------------------------------------------------------
# Live local-care recommendations (clinical flag -> specialty -> directory)
# ---------------------------------------------------------------------------


_EMPTY_CROSS_CHECK: Dict[str, Any] = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": (
        "Your records were restored from storage, so the medication safety "
        "check has not been re-run yet. Upload a document or ask a question "
        "to refresh it."
    ),
    "reference_date": None,
    "medication_activity": {
        "reference_date": None,
        "active_medications": [],
        "inactive_medications": [],
        "active_count": 0,
        "inactive_count": 0,
    },
}


# ---------------------------------------------------------------------------
# Patchable indirection
# ---------------------------------------------------------------------------
# These helpers are patched by tests via `mock.patch.object(api, ...)`. The
# route modules keep their own public names but resolve them through the `api`
# module at call time so a patch on api.<name> is observed everywhere.


def _prepare_current_trust_state(*args, **kwargs):
    import api as _api

    return _api._prepare_current_trust_state(*args, **kwargs)


async def _derive_record(*args, **kwargs):
    import api as _api

    return await _api._derive_record(*args, **kwargs)


async def _replace_index(*args, **kwargs):
    import api as _api

    return await _api._replace_index(*args, **kwargs)


async def _rebuild_after_document_deletion(*args, **kwargs):
    import api as _api

    return await _api._rebuild_after_document_deletion(*args, **kwargs)


def _workspace_has_active_upload(*args, **kwargs):
    import api as _api

    return _api._workspace_has_active_upload(*args, **kwargs)


def _load_snapshot_or_rebuild(*args, **kwargs):
    import api as _api

    return _api._load_snapshot_or_rebuild(*args, **kwargs)


def _enhanced_cross_check(*args, **kwargs):
    import api as _api

    return _api._enhanced_cross_check(*args, **kwargs)


# ---------------------------------------------------------------------------
# Patchable indirection
# ---------------------------------------------------------------------------
# Tests patch these names on the `api` module; resolve through api at call time.


def process_document(*args, **kwargs):
    import api as _api

    return _api.process_document(*args, **kwargs)


def index_patient_timeline(*args, **kwargs):
    import api as _api

    return _api.index_patient_timeline(*args, **kwargs)


def check_dosages(*args, **kwargs):
    import api as _api

    return _api.check_dosages(*args, **kwargs)


def generate_consult_triage(*args, **kwargs):
    import api as _api

    return _api.generate_consult_triage(*args, **kwargs)
