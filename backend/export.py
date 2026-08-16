"""
Record Export / Interoperability
=========================================
Builds portable exports of a patient's assembled record (the persisted
snapshot: timeline + cross-check + lab trends) in two formats:

  * "json" — the complete MediMind-native snapshot, self-describing and
    lossless. For personal backup or moving between MediMind deployments.
  * "fhir" — a FHIR R4 `Bundle` (type: collection) mapping the portable
    core of the record onto standard resources:
        Patient              one anonymous-reference resource
        MedicationStatement  one per medications_timeline entry
        Observation          one per lab_results_timeline entry (category
                             laboratory; valueQuantity when the numeric
                             value parses, valueString otherwise)
        AllergyIntolerance   one per known allergy
        Provenance           one, tying every resource to this export

    Mapping discipline: only fields the extractor actually produced are
    emitted — nothing is invented to look more complete. Free-text values
    that don't parse cleanly (e.g. non-numeric lab values) are exported as
    strings rather than dropped, so the FHIR bundle is honest about data
    quality. The LLM cross-check report is deliberately NOT mapped to FHIR
    (it's advisory content, not clinical source data); it stays in the
    native JSON export.

Deterministic, no LLM calls, read-only over the snapshot dict.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

EXPORT_FORMATS = ("json", "fhir")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fhir_date(value: Optional[str]) -> Optional[str]:
    """Passes through ISO dates; anything else is omitted rather than
    emitting a non-conformant date."""
    if isinstance(value, str) and _DATE_RE.match(value.strip()):
        return value.strip()
    return None


def _parse_numeric(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*$", value)
        if m:
            return float(m.group(1))
    return None


def build_native_export(user_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """The lossless MediMind-native export: snapshot content plus an
    envelope stating what this file is and when it was generated."""
    return {
        "format": "medimind-record-export",
        "format_version": "1.0",
        "exported_at": _now_iso(),
        "user_id": user_id,
        "patient_timeline": snapshot.get("patient_timeline"),
        "cross_check_report": snapshot.get("cross_check_report"),
        "lab_trends": snapshot.get("lab_trends"),
        "snapshot_updated_at": snapshot.get("updated_at"),
    }


def build_fhir_bundle(user_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Maps the snapshot's portable core onto a FHIR R4 collection Bundle."""
    timeline = snapshot.get("patient_timeline") or {}
    entries: List[Dict[str, Any]] = []

    patient_fullurl = f"urn:uuid:{uuid.uuid4()}"
    entries.append({
        "fullUrl": patient_fullurl,
        "resource": {
            "resourceType": "Patient",
            # Deliberately anonymous: MediMind keys records by opaque
            # user_id, and the export shouldn't leak more than the app knows.
            "identifier": [{"system": "urn:medimind:user", "value": user_id}],
        },
    })
    patient_ref = {"reference": patient_fullurl}

    for med in timeline.get("medications_timeline", []) or []:
        resource: Dict[str, Any] = {
            "resourceType": "MedicationStatement",
            "status": "recorded",
            "subject": patient_ref,
            "medication": {
                "concept": {"text": med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown"},
            },
        }
        effective = _fhir_date(med.get("date"))
        if effective:
            resource["effectiveDateTime"] = effective
        dosage_bits = [b for b in (med.get("dosage"), med.get("frequency"), med.get("duration")) if b]
        if dosage_bits:
            resource["dosage"] = [{"text": ", ".join(str(b) for b in dosage_bits)}]
        if med.get("source_file"):
            resource["note"] = [{"text": f"Source document: {med['source_file']}"}]
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": resource})

    for lab in timeline.get("lab_results_timeline", []) or []:
        resource = {
            "resourceType": "Observation",
            "status": "final",
            "category": [{
                "coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "laboratory",
                }],
            }],
            "code": {"text": lab.get("test_name") or "unknown test"},
            "subject": patient_ref,
        }
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

    for allergy in timeline.get("known_allergies", []) or []:
        entries.append({
            "fullUrl": f"urn:uuid:{uuid.uuid4()}",
            "resource": {
                "resourceType": "AllergyIntolerance",
                "patient": patient_ref,
                "code": {"text": str(allergy)},
            },
        })

    entries.append({
        "fullUrl": f"urn:uuid:{uuid.uuid4()}",
        "resource": {
            "resourceType": "Provenance",
            "target": [{"reference": e["fullUrl"]} for e in entries],
            "recorded": _now_iso(),
            "agent": [{
                "who": {"display": "MediMind record export"},
            }],
        },
    })

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": _now_iso(),
        "total": len(entries),
        "entry": entries,
    }


def build_export(user_id: str, snapshot: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    """Dispatches to the requested export format. Raises ValueError on an
    unknown format so the API layer can turn it into a 400."""
    fmt = (fmt or "json").strip().lower()
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"Unknown export format '{fmt}'. Supported: {', '.join(EXPORT_FORMATS)}")
    if fmt == "fhir":
        return build_fhir_bundle(user_id, snapshot)
    return build_native_export(user_id, snapshot)
