"""Correction, conflict detection, and retrieval-quarantine primitives.

This module is deliberately pure Python.  Persistence lives in ``db.py`` and
HTTP orchestration lives in ``api.py``; keeping the trust rules here makes it
possible to test the safety boundary without Supabase, an LLM, or a vector
store.

The immutable document extraction is never edited.  Correction events are
applied to deep copies to create an *effective* view.  Conflict quarantine is
then applied to another copy.  Timelines, safety checks, lab trends, and RAG
must only consume that quarantined view.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_CORRECTABLE_ROOT_FIELDS = {"date", "patient_name", "provider_or_doctor"}
_CORRECTABLE_MEDICATION_FIELDS = {
    "name", "ingredients", "dosage", "frequency", "duration",
    "dosage_value", "dosage_unit", "frequency_per_day", "is_as_needed",
}
_CORRECTABLE_LAB_FIELDS = {
    "test_name", "value", "unit", "reference_range", "flag",
}
_PATH_RE = re.compile(r"^/(medications|lab_results)/(\d+)/([A-Za-z_][A-Za-z0-9_]*)$")


class CorrectionValidationError(ValueError):
    """A correction path/value is invalid or no longer matches the record."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_id(document: Dict[str, Any]) -> str:
    value = document.get("_document_id")
    return str(value) if value is not None else ""


def normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).casefold()


def normalize_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(value)).strip()


def validate_correction_path(path: str) -> Tuple[str, Optional[int], str]:
    """Validate the intentionally narrow editable surface.

    JSON Pointer is used on the wire, but arbitrary pointers are not allowed:
    source provenance, trust metadata, confidence, document URLs, and IDs are
    server-owned and cannot be rewritten by a client.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise CorrectionValidationError("field_path must be a JSON Pointer beginning with '/'.")
    root = path[1:]
    if root in _CORRECTABLE_ROOT_FIELDS:
        return root, None, root
    match = _PATH_RE.match(path)
    if not match:
        raise CorrectionValidationError(
            "Only dates, patient/provider identities, medication fields, and lab fields can be corrected."
        )
    collection, index_text, field = match.groups()
    allowed = _CORRECTABLE_MEDICATION_FIELDS if collection == "medications" else _CORRECTABLE_LAB_FIELDS
    if field not in allowed:
        raise CorrectionValidationError(f"'{field}' is not a correctable {collection} field.")
    return collection, int(index_text), field


def _validate_value(collection: str, field: str, value: Any) -> None:
    if collection == "medications":
        if field == "ingredients" and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            raise CorrectionValidationError("Medication ingredients must be an array of names.")
        if field in {"dosage_value", "frequency_per_day"} and value is not None and not isinstance(value, (int, float)):
            raise CorrectionValidationError(f"{field} must be a number or null.")
        if field == "is_as_needed" and not isinstance(value, bool):
            raise CorrectionValidationError("is_as_needed must be true or false.")
    if collection == "lab_results" and field == "flag" and value not in {"normal", "high", "low", "unknown"}:
        raise CorrectionValidationError("Lab flag must be normal, high, low, or unknown.")
    if field not in {"ingredients", "dosage_value", "frequency_per_day", "is_as_needed"}:
        if value is not None and not isinstance(value, str):
            raise CorrectionValidationError(f"{field} must be text or null.")


def get_path(document: Dict[str, Any], path: str) -> Any:
    collection, index, field = validate_correction_path(path)
    if index is None:
        if field not in document:
            raise CorrectionValidationError(f"Field '{path}' is not present in this extraction.")
        return copy.deepcopy(document.get(field))
    values = document.get(collection)
    if not isinstance(values, list) or index >= len(values):
        raise CorrectionValidationError(f"Field '{path}' no longer exists in this extraction.")
    item = values[index]
    if not isinstance(item, dict) or field not in item:
        raise CorrectionValidationError(f"Field '{path}' is not present in this extraction.")
    return copy.deepcopy(item.get(field))


def set_path(document: Dict[str, Any], path: str, value: Any) -> None:
    collection, index, field = validate_correction_path(path)
    _validate_value(collection, field, value)
    if index is None:
        document[field] = copy.deepcopy(value)
        return
    values = document.get(collection)
    if not isinstance(values, list) or index >= len(values):
        raise CorrectionValidationError(f"Field '{path}' no longer exists in this extraction.")
    values[index][field] = copy.deepcopy(value)


def _evidence_for_path(document: Dict[str, Any], path: str) -> List[Dict[str, Any]]:
    if path.startswith("/medications/") or path.startswith("/lab_results/"):
        parts = path.strip("/").split("/")
        try:
            item = document[parts[0]][int(parts[1])]
        except (KeyError, IndexError, TypeError, ValueError):
            return []
        return [region for region in (item.get("evidence") or []) if isinstance(region, dict)]
    key = path.strip("/").split("/")[0]
    fields = document.get("field_evidence") or {}
    return [region for region in (fields.get(key) or []) if isinstance(region, dict)]


def _base_trust(status: str = "extracted") -> Dict[str, Any]:
    return {
        "status": status,
        "quarantined": False,
        "conflict_ids": [],
        "reasons": [],
    }


def _merge_trust(target: Dict[str, Any], **updates: Any) -> Dict[str, Any]:
    trust = target.setdefault("_trust", _base_trust())
    for list_key in ("conflict_ids", "reasons"):
        if list_key in updates:
            existing = trust.setdefault(list_key, [])
            for value in updates.pop(list_key) or []:
                if value not in existing:
                    existing.append(value)
    trust.update(updates)
    return trust


def apply_correction_events(
    documents: Sequence[Dict[str, Any]],
    events: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the effective extraction after replaying immutable events.

    Events are sorted by ``created_at`` and ``id`` for a deterministic replay.
    The raw rows in ``documents`` are never mutated.  User-corrected fields
    receive trust metadata used by evidence ranking downstream.
    """
    result = copy.deepcopy(list(documents))
    by_id = {document_id(doc): doc for doc in result if document_id(doc)}
    ordered = sorted(events, key=lambda event: (str(event.get("created_at") or ""), str(event.get("id") or "")))
    for event in ordered:
        doc = by_id.get(str(event.get("document_id") or ""))
        if doc is None:
            continue
        path = str(event.get("field_path") or "")
        # Persisted events were validated before insertion.  Re-validate on
        # replay as defense in depth against hand-edited database rows.
        set_path(doc, path, event.get("corrected_value"))
        correction_info = doc.setdefault("_corrections", {"paths": [], "event_ids": []})
        if path not in correction_info["paths"]:
            correction_info["paths"].append(path)
        event_id = str(event.get("id") or event.get("correction_batch_id") or "")
        if event_id and event_id not in correction_info["event_ids"]:
            correction_info["event_ids"].append(event_id)
        correction_info["last_corrected_at"] = event.get("created_at")
        _merge_trust(doc, status="user_corrected")
        for region in _evidence_for_path(doc, path):
            region["verification_status"] = "user_corrected"
            region["original_extracted_value"] = copy.deepcopy(event.get("original_value"))
            region["corrected_value"] = copy.deepcopy(event.get("corrected_value"))

        collection, index, _field = validate_correction_path(path)
        if index is not None:
            item = doc[collection][index]
            _merge_trust(item, status="user_corrected")
    return result


def build_correction_events(
    original_document: Dict[str, Any],
    effective_document: Dict[str, Any],
    changes: Sequence[Dict[str, Any]],
    *,
    user_id: str,
    correction_batch_id: str,
    reason: str,
    created_at: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Validate a correction batch and construct append-only audit rows."""
    if not reason or not reason.strip():
        raise CorrectionValidationError("A short reason is required for the audit history.")
    if not changes:
        raise CorrectionValidationError("At least one field change is required.")
    if len(changes) > 100:
        raise CorrectionValidationError("A correction batch cannot contain more than 100 field changes.")

    now = created_at or utc_now_iso()
    events: List[Dict[str, Any]] = []
    seen_paths = set()
    for change in changes:
        path = str(change.get("field_path") or "")
        if path in seen_paths:
            raise CorrectionValidationError(f"Field '{path}' appears more than once in this correction batch.")
        seen_paths.add(path)
        collection, _index, field = validate_correction_path(path)
        corrected_value = change.get("corrected_value")
        _validate_value(collection, field, corrected_value)
        original_value = get_path(original_document, path)
        previous_value = get_path(effective_document, path)
        if "expected_previous_value" in change and change["expected_previous_value"] != previous_value:
            raise CorrectionValidationError(
                f"Field '{path}' changed since it was opened. Reload the document before saving."
            )
        if corrected_value == previous_value:
            continue
        event_number = len(events) + 1
        events.append({
            "id": f"{correction_batch_id}:{event_number}",
            "correction_batch_id": correction_batch_id,
            "user_id": user_id,
            "document_id": document_id(original_document),
            "field_path": path,
            "original_value": original_value,
            "previous_value": previous_value,
            "corrected_value": copy.deepcopy(corrected_value),
            "reason": reason.strip(),
            "created_at": now,
        })
    if not events:
        raise CorrectionValidationError("None of the submitted values differ from the current extraction.")
    return events


def _stable_conflict_id(kind: str, fact_key: str) -> str:
    digest = hashlib.sha256(f"{kind}|{fact_key}".encode("utf-8")).hexdigest()[:24]
    return f"conflict_{digest}"


def _source_item(doc: Dict[str, Any], path: str, value: Any, confidence: Any = None) -> Dict[str, Any]:
    source = doc.get("_source") if isinstance(doc.get("_source"), dict) else {}
    return {
        "document_id": document_id(doc),
        "field_path": path,
        "value": copy.deepcopy(value),
        "source_file": source.get("file") or "unknown",
        "page": source.get("page"),
        "confidence": confidence if isinstance(confidence, (int, float)) else doc.get("overall_confidence"),
    }


def _different_signatures(items: Iterable[Tuple[Any, ...]]) -> bool:
    return len({json.dumps(item, sort_keys=True, default=str) for item in items}) > 1


def detect_conflicts(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect conservative, deterministic conflicts in the effective data.

    A conflict is only emitted where two sources purport to describe the same
    fact key.  Different visits or dates are expected longitudinal data, not a
    contradiction.  Identity is the exception: multiple patient names inside
    one anonymous patient workspace are always quarantined for review.
    """
    docs = [doc for doc in documents if document_id(doc)]
    conflicts: List[Dict[str, Any]] = []

    # Identity: one workspace must not silently merge two patient names.
    identity_groups: Dict[str, List[Dict[str, Any]]] = {}
    for doc in docs:
        normalized = normalize_name(doc.get("patient_name"))
        if normalized:
            identity_groups.setdefault(normalized, []).append(doc)
    if len(identity_groups) > 1:
        items = [
            _source_item(doc, "/patient_name", doc.get("patient_name"))
            for group_docs in identity_groups.values()
            for doc in group_docs
        ]
        conflicts.append({
            "conflict_id": _stable_conflict_id("identity", "patient_name"),
            "kind": "identity",
            "field_type": "patient_name",
            "fact_key": "patient_name",
            "severity": "critical",
            "summary": "Different patient identities were extracted in this workspace.",
            "items": items,
            "status": "unresolved",
            "authoritative_document_id": None,
            "resolution_note": None,
        })

    # Two pages from the same source file should agree on the document date.
    date_groups: Dict[str, List[Tuple[Dict[str, Any], str]]] = {}
    for doc in docs:
        source = doc.get("_source") if isinstance(doc.get("_source"), dict) else {}
        file_key = normalize_text(source.get("file"))
        date_value = normalize_text(doc.get("date"))
        if file_key and date_value:
            date_groups.setdefault(file_key, []).append((doc, date_value))
    for file_key, group in date_groups.items():
        if len(group) < 2 or len({date for _doc, date in group}) < 2:
            continue
        conflicts.append({
            "conflict_id": _stable_conflict_id("document_date", file_key),
            "kind": "document_date",
            "field_type": "date",
            "fact_key": file_key,
            "severity": "high",
            "summary": "Pages from the same document have conflicting dates.",
            "items": [_source_item(doc, "/date", doc.get("date")) for doc, _date in group],
            "status": "unresolved",
            "authoritative_document_id": None,
            "resolution_note": None,
        })

    medication_groups: Dict[str, List[Tuple[Dict[str, Any], int, Dict[str, Any], Tuple[Any, ...]]]] = {}
    lab_groups: Dict[str, List[Tuple[Dict[str, Any], int, Dict[str, Any], Tuple[Any, ...]]]] = {}
    for doc in docs:
        date_key = normalize_text(doc.get("date")) or "undated"
        for index, med in enumerate(doc.get("medications") or []):
            if not isinstance(med, dict):
                continue
            ingredients = tuple(sorted(normalize_name(item) for item in (med.get("ingredients") or []) if normalize_name(item)))
            medicine_key = "+".join(ingredients) or normalize_name(med.get("name"))
            if not medicine_key:
                continue
            key = f"{date_key}|{medicine_key}"
            if med.get("dosage_value") is not None and med.get("dosage_unit"):
                dose_signature: Tuple[Any, ...] = (
                    "normalized", med.get("dosage_value"), normalize_text(med.get("dosage_unit")),
                )
            else:
                dose_signature = ("printed", normalize_text(med.get("dosage")))
            if med.get("is_as_needed"):
                frequency_signature: Tuple[Any, ...] = ("prn",)
            elif med.get("frequency_per_day") is not None:
                frequency_signature = ("normalized", med.get("frequency_per_day"))
            else:
                frequency_signature = ("printed", normalize_text(med.get("frequency")))
            signature = dose_signature + frequency_signature
            medication_groups.setdefault(key, []).append((doc, index, med, signature))

        for index, lab in enumerate(doc.get("lab_results") or []):
            if not isinstance(lab, dict):
                continue
            test_key = normalize_name(lab.get("test_name"))
            if not test_key:
                continue
            key = f"{date_key}|{test_key}"
            signature = (normalize_text(lab.get("value")), normalize_text(lab.get("unit")))
            lab_groups.setdefault(key, []).append((doc, index, lab, signature))

    for fact_key, group in medication_groups.items():
        source_ids = {document_id(doc) for doc, _index, _med, _signature in group}
        if len(source_ids) < 2 or not _different_signatures(signature for _d, _i, _m, signature in group):
            continue
        medicine_label = (group[0][2].get("ingredients") or [group[0][2].get("name") or "medication"])[0]
        conflicts.append({
            "conflict_id": _stable_conflict_id("medication", fact_key),
            "kind": "medication",
            "field_type": "medication_instruction",
            "fact_key": fact_key,
            "severity": "high",
            "summary": f"Conflicting instructions were found for {medicine_label} on the same date.",
            "items": [
                _source_item(doc, f"/medications/{index}", med, med.get("confidence"))
                for doc, index, med, _signature in group
            ],
            "status": "unresolved",
            "authoritative_document_id": None,
            "resolution_note": None,
        })

    for fact_key, group in lab_groups.items():
        source_ids = {document_id(doc) for doc, _index, _lab, _signature in group}
        if len(source_ids) < 2 or not _different_signatures(signature for _d, _i, _lab, signature in group):
            continue
        test_label = group[0][2].get("test_name") or "lab result"
        conflicts.append({
            "conflict_id": _stable_conflict_id("lab_result", fact_key),
            "kind": "lab_result",
            "field_type": "lab_value",
            "fact_key": fact_key,
            "severity": "high",
            "summary": f"Different values were extracted for {test_label} on the same date.",
            "items": [
                _source_item(doc, f"/lab_results/{index}", lab, lab.get("confidence"))
                for doc, index, lab, _signature in group
            ],
            "status": "unresolved",
            "authoritative_document_id": None,
            "resolution_note": None,
        })

    return sorted(conflicts, key=lambda conflict: (conflict["kind"], conflict["conflict_id"]))


def merge_conflict_state(
    detected: Sequence[Dict[str, Any]],
    persisted: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Overlay valid persisted resolutions on freshly detected conflicts."""
    existing = {str(item.get("conflict_id")): item for item in persisted}
    merged: List[Dict[str, Any]] = []
    for fresh in detected:
        item = copy.deepcopy(fresh)
        old = existing.get(str(item["conflict_id"]))
        source_ids = {str(source.get("document_id")) for source in item.get("items", [])}
        authoritative = str((old or {}).get("authoritative_document_id") or "")
        if old and old.get("status") == "resolved" and authoritative in source_ids:
            item["status"] = "resolved"
            item["authoritative_document_id"] = authoritative
            item["resolution_note"] = old.get("resolution_note")
            item["resolved_at"] = old.get("resolved_at")
        merged.append(item)
    return merged


def _mark_fact(doc: Dict[str, Any], path: str, conflict: Dict[str, Any], quarantined: bool) -> None:
    conflict_id = str(conflict["conflict_id"])
    reason = conflict.get("summary") or "Conflicting source evidence"
    if path.startswith("/medications/") or path.startswith("/lab_results/"):
        parts = path.strip("/").split("/")
        try:
            target = doc[parts[0]][int(parts[1])]
        except (KeyError, IndexError, TypeError, ValueError):
            return
        _merge_trust(
            target,
            status="quarantined" if quarantined else "source_confirmed",
            quarantined=quarantined,
            conflict_ids=[conflict_id],
            reasons=[reason],
        )
    else:
        # Identity and date conflicts taint the document's clinical context,
        # not just a display scalar.  Quarantine the whole source.
        _merge_trust(
            doc,
            status="quarantined" if quarantined else "source_confirmed",
            quarantined=quarantined,
            conflict_ids=[conflict_id],
            reasons=[reason],
        )
    for region in _evidence_for_path(doc, path):
        region["verification_status"] = "quarantined" if quarantined else "source_confirmed"
        region["conflict_id"] = conflict_id


def apply_conflict_quarantine(
    documents: Sequence[Dict[str, Any]],
    conflicts: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Apply fail-closed conflict policy and return a trust summary.

    * unresolved identity/date conflict: every potentially mixed source is
      quarantined (identity quarantines the entire workspace);
    * unresolved factual conflict: all competing facts are quarantined;
    * resolved conflict: only facts from the user-confirmed authoritative
      source are admitted.  Non-authoritative alternatives remain visible in
      the document view but never enter analytics or retrieval.
    """
    result = copy.deepcopy(list(documents))
    by_id = {document_id(doc): doc for doc in result if document_id(doc)}
    for doc in result:
        _merge_trust(doc, status="user_corrected" if doc.get("_corrections") else "extracted")

    unresolved = [item for item in conflicts if item.get("status") != "resolved"]
    resolved = [item for item in conflicts if item.get("status") == "resolved"]

    for conflict in conflicts:
        status = conflict.get("status")
        authoritative = str(conflict.get("authoritative_document_id") or "")
        kind = conflict.get("kind")
        if kind == "identity" and status != "resolved":
            # Unknown-name documents may be the other identity too.  With an
            # unresolved identity mismatch, no source in the workspace is safe.
            for doc in result:
                _mark_fact(doc, "/patient_name", conflict, quarantined=True)
            continue

        if kind == "identity" and status == "resolved":
            authoritative_item = next(
                (item for item in conflict.get("items", []) if str(item.get("document_id")) == authoritative),
                None,
            )
            authoritative_name = normalize_name((authoritative_item or {}).get("value"))
            for doc in result:
                matches = authoritative_name and normalize_name(doc.get("patient_name")) == authoritative_name
                _mark_fact(doc, "/patient_name", conflict, quarantined=not bool(matches))
            continue

        for source in conflict.get("items", []):
            source_id = str(source.get("document_id") or "")
            doc = by_id.get(source_id)
            if doc is None:
                continue
            quarantined = status != "resolved" or source_id != authoritative
            _mark_fact(doc, str(source.get("field_path") or ""), conflict, quarantined)

    quarantined_documents = sum(bool((doc.get("_trust") or {}).get("quarantined")) for doc in result)
    quarantined_facts = 0
    for doc in result:
        for collection in ("medications", "lab_results"):
            for fact in doc.get(collection) or []:
                if isinstance(fact, dict) and (fact.get("_trust") or {}).get("quarantined"):
                    quarantined_facts += 1

    correction_paths = sum(len((doc.get("_corrections") or {}).get("paths", [])) for doc in result)
    summary = {
        "unresolved_conflicts": len(unresolved),
        "resolved_conflicts": len(resolved),
        "quarantined_documents": quarantined_documents,
        "quarantined_facts": quarantined_facts,
        "corrected_fields": correction_paths,
        "retrieval_policy": "exclude_unresolved_and_non_authoritative",
    }
    return result, summary


def prepare_trusted_documents(
    documents: Sequence[Dict[str, Any]],
    persisted_conflicts: Sequence[Dict[str, Any]] = (),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    detected = detect_conflicts(documents)
    conflicts = merge_conflict_state(detected, persisted_conflicts)
    trusted, summary = apply_conflict_quarantine(documents, conflicts)
    return trusted, conflicts, summary
