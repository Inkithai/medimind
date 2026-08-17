"""Deterministic native and FHIR R4-oriented record exports.

The FHIR export is deliberately conservative: mapped codes are emitted only
from a small curated dictionary; unknown facts retain human-readable text and
are reported as unmapped rather than guessed.  ``validate_fhir_bundle`` is a
local structural R4 check suitable for the demo.  A standards-validator
integration can be added later without changing the export contract.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

EXPORT_FORMATS = ("json", "fhir")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Curated, deterministic examples. These are deliberately not presented as a
# complete terminology server. Text is always retained alongside a code.
LOINC_CODES = {
    "hba1c": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "hemoglobin a1c": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "glucose": ("2345-7", "Glucose [Mass/volume] in Blood"),
    "fasting glucose": ("1558-6", "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "hemoglobin": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "wbc": ("6690-2", "Leukocytes [#/volume] in Blood"),
    "white blood cell count": ("6690-2", "Leukocytes [#/volume] in Blood"),
    "creatinine": ("2160-0", "Creatinine [Mass/volume] in Serum or Plasma"),
}
RXNORM_CODES = {
    "metformin": ("860975", "metformin"),
    "amoxicillin": ("308047", "amoxicillin"),
    "ibuprofen": ("310965", "ibuprofen"),
    "atorvastatin": ("859747", "atorvastatin"),
    "warfarin": ("855334", "warfarin"),
    "paracetamol": ("313782", "acetaminophen"),
    "acetaminophen": ("161", "acetaminophen"),
}
SNOMED_CODES = {
    "type 2 diabetes": ("44054006", "Type 2 diabetes mellitus"),
    "diabetes mellitus": ("73211009", "Diabetes mellitus"),
    "hypertension": ("38341003", "Hypertensive disorder"),
    "asthma": ("195967001", "Asthma"),
}
ICD10_CODES = {
    "type 2 diabetes": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "diabetes mellitus": ("E11.9", "Type 2 diabetes mellitus without complications"),
    "hypertension": ("I10", "Essential (primary) hypertension"),
    "asthma": ("J45.909", "Unspecified asthma, uncomplicated"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fhir_date(value: Optional[str]) -> Optional[str]:
    return value.strip() if isinstance(value, str) and _DATE_RE.match(value.strip()) else None


def _parse_numeric(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*", value)
        if match:
            return float(match.group(1))
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _coding(system: str, code: str, display: str) -> Dict[str, str]:
    return {"system": system, "code": code, "display": display}


def build_native_export(user_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "format": "medimind-record-export", "format_version": "1.0",
        "exported_at": _now_iso(), "user_id": user_id,
        "patient_timeline": snapshot.get("patient_timeline"),
        "cross_check_report": snapshot.get("cross_check_report"),
        "lab_trends": snapshot.get("lab_trends"),
        "snapshot_updated_at": snapshot.get("updated_at"),
    }


def _condition_resources(timeline: Dict[str, Any], patient_ref: Dict[str, str], unmapped: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: List[Any] = []
    for key in ("diagnoses_timeline", "conditions_timeline"):
        values.extend(timeline.get(key) or [])
    result = []
    seen = set()
    for item in values:
        name = _text(item.get("name") if isinstance(item, dict) else item)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        key = name.lower()
        codings = []
        if key in SNOMED_CODES:
            code, display = SNOMED_CODES[key]
            codings.append(_coding("http://snomed.info/sct", code, display))
        if key in ICD10_CODES:
            code, display = ICD10_CODES[key]
            codings.append(_coding("http://hl7.org/fhir/sid/icd-10-cm", code, display))
        if not codings:
            unmapped.append({"domain": "condition", "value": name, "target": "SNOMED CT / ICD-10"})
        codeable = {"text": name}
        if codings:
            codeable["coding"] = codings
        resource = {"resourceType": "Condition", "clinicalStatus": {"coding": [_coding("http://terminology.hl7.org/CodeSystem/condition-clinical", "active", "Active")]}, "code": codeable, "subject": patient_ref}
        date = _fhir_date((item or {}).get("date") if isinstance(item, dict) else None)
        if date:
            resource["onsetDateTime"] = date
        result.append(resource)
    return result


def build_fhir_bundle(user_id: str, snapshot: Dict[str, Any], *, return_metadata: bool = False) -> Dict[str, Any]:
    timeline = snapshot.get("patient_timeline") or {}
    entries: List[Dict[str, Any]] = []
    unmapped: List[Dict[str, Any]] = []
    patient_fullurl = f"urn:uuid:{uuid.uuid4()}"
    entries.append({"fullUrl": patient_fullurl, "resource": {"resourceType": "Patient", "identifier": [{"system": "urn:medimind:user", "value": user_id}]}})
    patient_ref = {"reference": patient_fullurl}

    for med in timeline.get("medications_timeline", []) or []:
        name = _text(med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown")
        key = name.lower()
        coding = RXNORM_CODES.get(key)
        medication = {"text": name}
        if coding:
            medication["coding"] = [_coding("http://www.nlm.nih.gov/research/umls/rxnorm", coding[0], coding[1])]
        else:
            unmapped.append({"domain": "medication", "value": name, "target": "RxNorm"})
        resource: Dict[str, Any] = {"resourceType": "MedicationStatement", "status": "unknown", "subject": patient_ref, "medicationCodeableConcept": medication}
        effective = _fhir_date(med.get("date"))
        if effective:
            resource["effectiveDateTime"] = effective
        dosage_bits = [b for b in (med.get("dosage"), med.get("frequency"), med.get("duration")) if b]
        if dosage_bits:
            resource["dosage"] = [{"text": ", ".join(str(b) for b in dosage_bits)}]
        if med.get("source_file"):
            resource["note"] = [{"text": f"Source document: {med['source_file']}"}]
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource})
        # MedicationRequest represents the documented prescription intent.
        request = {"resourceType": "MedicationRequest", "status": "active", "intent": "order", "subject": patient_ref, "medicationCodeableConcept": medication}
        if effective:
            request["authoredOn"] = effective
        if dosage_bits:
            request["dosageInstruction"] = [{"text": ", ".join(str(b) for b in dosage_bits)}]
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": request})

    for lab in timeline.get("lab_results_timeline", []) or []:
        name = _text(lab.get("test_name") or "unknown test")
        code = LOINC_CODES.get(name.lower())
        codeable = {"text": name}
        if code:
            codeable["coding"] = [_coding("http://loinc.org", code[0], code[1])]
        else:
            unmapped.append({"domain": "laboratory", "value": name, "target": "LOINC"})
        resource: Dict[str, Any] = {"resourceType": "Observation", "status": "final", "category": [{"coding": [_coding("http://terminology.hl7.org/CodeSystem/observation-category", "laboratory", "Laboratory")]}], "code": codeable, "subject": patient_ref}
        effective = _fhir_date(lab.get("date"))
        if effective:
            resource["effectiveDateTime"] = effective
        numeric = _parse_numeric(lab.get("value"))
        if numeric is not None:
            quantity: Dict[str, Any] = {"value": numeric}
            if lab.get("unit"):
                quantity["unit"] = str(lab["unit"])
            resource["valueQuantity"] = quantity
        elif lab.get("value") is not None:
            resource["valueString"] = str(lab["value"])
        if lab.get("reference_range"):
            resource["referenceRange"] = [{"text": str(lab["reference_range"])}]
        if lab.get("flag"):
            resource["interpretation"] = [{"text": str(lab["flag"])}]
        if lab.get("source_file"):
            resource["note"] = [{"text": f"Source document: {lab['source_file']}"}]
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource})

    entries.extend({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource} for resource in _condition_resources(timeline, patient_ref, unmapped))
    for event in timeline.get("visits", []) or []:
        if not isinstance(event, dict):
            continue
        resource = {"resourceType": "Encounter", "status": "finished", "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"}, "subject": patient_ref}
        date = _fhir_date(event.get("date"))
        if date:
            resource["period"] = {"start": date}
        if event.get("provider_or_doctor"):
            resource["participant"] = [{"individual": {"display": str(event["provider_or_doctor"])}}]
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource})

    for allergy in timeline.get("known_allergies", []) or []:
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": {"resourceType": "AllergyIntolerance", "patient": patient_ref, "code": {"text": str(allergy)}}})

    provenance_targets = [e["fullUrl"] for e in entries]
    entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": {"resourceType": "Provenance", "target": [{"reference": ref} for ref in provenance_targets], "recorded": _now_iso(), "agent": [{"who": {"display": "MediMind record export"}}]}})
    bundle = {"resourceType": "Bundle", "type": "collection", "timestamp": _now_iso(), "total": len(entries), "entry": entries}
    if return_metadata:
        bundle["_medimind_export_metadata"] = {"unmapped_terminology": unmapped, "mapping_systems": ["LOINC", "SNOMED CT", "RxNorm", "ICD-10-CM"]}
    return bundle


def validate_fhir_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """Local structural checks for the generated R4 subset.

    This is intentionally explicit and deterministic; it is not a replacement
    for the HL7 validator service. It catches the conformance regressions that
    matter for this export and produces a demo-friendly report.
    """
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    if bundle.get("resourceType") != "Bundle": errors.append({"path": "resourceType", "message": "Must be Bundle"})
    if bundle.get("type") != "collection": errors.append({"path": "type", "message": "Must be collection"})
    entries = bundle.get("entry") or []
    if bundle.get("total") != len(entries): errors.append({"path": "total", "message": "Must equal entry count"})
    valid_types = {"Patient", "MedicationStatement", "MedicationRequest", "Observation", "AllergyIntolerance", "Condition", "Encounter", "Provenance"}
    urls = set()
    for i, entry in enumerate(entries):
        resource = entry.get("resource") or {}
        path = f"entry[{i}].resource"
        kind = resource.get("resourceType")
        if kind not in valid_types: errors.append({"path": path, "message": "Unsupported resource type"})
        if not entry.get("fullUrl"): errors.append({"path": f"entry[{i}].fullUrl", "message": "Required"})
        urls.add(entry.get("fullUrl"))
        if kind == "MedicationStatement" and ("medicationCodeableConcept" not in resource and "medicationReference" not in resource): errors.append({"path": path, "message": "MedicationStatement requires medicationCodeableConcept or medicationReference"})
        if kind == "MedicationRequest" and resource.get("status") not in {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"}: errors.append({"path": path, "message": "Invalid MedicationRequest.status"})
        if kind == "MedicationStatement" and resource.get("status") not in {"active", "completed", "entered-in-error", "intended", "stopped", "on-hold", "unknown"}: errors.append({"path": path, "message": "Invalid MedicationStatement.status"})
    if not any((e.get("resource") or {}).get("resourceType") == "Patient" for e in entries): errors.append({"path": "entry", "message": "Bundle must contain Patient"})
    for entry in entries:
        resource = entry.get("resource") or {}
        if resource.get("resourceType") == "Provenance":
            for target in resource.get("target", []):
                if target.get("reference") not in urls: errors.append({"path": "Provenance.target", "message": "Reference does not resolve"})
    return {"valid": not errors, "validator": "MediMind local FHIR R4 structural validator", "errors": errors, "warnings": warnings, "resource_count": len(entries)}


def build_export(user_id: str, snapshot: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    fmt = (fmt or "json").strip().lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"Unknown export format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}")
    return build_fhir_bundle(user_id, snapshot) if fmt == "fhir" else build_native_export(user_id, snapshot)
