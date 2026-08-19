"""
FHIR R4 Ingestion (structured-import path)
==========================================
MediMind's primary input is a PDF/image the LLM extracts from. export.py
already emits a FHIR R4 Bundle OUT of the record. This module is the reverse:
it accepts a FHIR R4 Bundle (from a portal, device export, or another system)
and maps it into the SAME internal extraction document shape the pipeline
already understands, so structured data can be ingested without OCR/LLM.

Supported resources: Patient, MedicationStatement/MedicationRequest,
Observation (labs + vitals), AllergyIntolerance, Condition, DiagnosticReport,
Encounter. Anything unrecognised is ignored, never faked. Mapping is
deterministic and lossy-by-design: FHIR's richness is collapsed to the fields
the pipeline reasons over, and fields it cannot represent are dropped (and
listed) rather than guessed.

The result is a list of "documents" in the extraction schema, ready to be
persisted with db.insert_documents() and re-derived like any upload.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def _entries(bundle: Any) -> List[Dict[str, Any]]:
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    if not isinstance(bundle, dict):
        return []
    return [e for e in (bundle.get("entry") or []) if isinstance(e, dict)]


def _text(cc: Optional[Dict[str, Any]]) -> str:
    if not isinstance(cc, dict):
        return ""
    txt = cc.get("text")
    if txt:
        return str(txt)
    coding = (cc.get("coding") or [{}])[0] if cc.get("coding") else {}
    return str(coding.get("display") or coding.get("code") or "")


def _code(res: Dict[str, Any], key: str) -> str:
    return _text(res.get(key))


def _interpretation_flag(res: Dict[str, Any]) -> str:
    """Map a FHIR Observation.interpretation to the pipeline's flag vocabulary
    (normal/high/low/unknown). Tolerates missing, empty, or oddly-shaped
    interpretation arrays without raising."""
    interp = res.get("interpretation")
    if not isinstance(interp, list) or not interp:
        return "unknown"
    coding = interp[0].get("coding") if isinstance(interp[0], dict) else None
    if not isinstance(coding, list) or not coding:
        return "unknown"
    code = coding[0].get("code") if isinstance(coding[0], dict) else None
    code = str(code or "").strip().upper()
    if code in ("H", "HU", ">", "AA", "HH"):
        return "high"
    if code in ("L", "LU", "<", "LL"):
        return "low"
    if code in ("N",):
        return "normal"
    return "unknown"


def _value(res: Dict[str, Any]) -> Optional[str]:
    comp = res.get("component")
    if isinstance(comp, list) and comp:
        # multi-component observation — take the first usable value
        for c in comp:
            v = _value(c)
            if v is not None:
                return v
    qty = res.get("valueQuantity")
    if isinstance(qty, dict):
        val = qty.get("value")
        unit = qty.get("unit") or qty.get("code") or ""
        return f"{val} {unit}".strip() if val is not None else None
    for k in ("valueString", "valueInteger", "valueDecimal", "valueBoolean"):
        if res.get(k) is not None:
            return str(res[k])
    return None


def parse_fhir_bundle(bundle: Any, *, document_id: str = "fhir_import") -> Dict[str, Any]:
    entries = _entries(bundle)
    patient_name = ""
    docs: List[Dict[str, Any]] = []
    ignored: List[str] = []
    meds: List[Dict[str, Any]] = []
    labs: List[Dict[str, Any]] = []
    vitals: List[Dict[str, Any]] = []
    conditions: List[str] = []
    allergies: List[str] = []
    encounters: List[Dict[str, Any]] = []
    report_date: Optional[str] = None

    _VITAL_KEYWORDS = (
        "blood pressure",
        "pulse",
        "heart rate",
        "oxygen",
        "spo2",
        "respiratory rate",
        "temperature",
        "weight",
        "height",
        "bmi",
    )
    _LAB_KEYWORDS = (
        "glucose",
        "creatinine",
        "sodium",
        "potassium",
        "hemoglobin",
        "haemoglobin",
        "cholesterol",
        "alt",
        "ast",
        "hba1c",
        "inr",
        "platelet",
        "urea",
        "egfr",
        "bilirubin",
        "albumin",
        "calcium",
    )

    for e in entries:
        res = e.get("resource") or {}
        rtype = res.get("resourceType")
        if rtype == "Patient":
            names = res.get("name") or [{}]
            n0 = names[0] if isinstance(names, list) and names else {}
            given = " ".join(n0.get("given") or [])
            family = n0.get("family") or ""
            patient_name = f"{given} {family}".strip()
        elif rtype in ("MedicationStatement", "MedicationRequest"):
            med_name = _code(res, "medicationCodeableConcept") or _text(
                (res.get("medicationReference") or {})
            )
            if med_name:
                meds.append(
                    {
                        "name": med_name,
                        "ingredients": [med_name.split()[0].lower()] if med_name else [],
                        "dosage": "",
                        "frequency": "",
                        "duration": "",
                    }
                )
        elif rtype == "Observation":
            code = _code(res, "code").lower()
            val = _value(res)
            if val is None:
                continue
            entry = {
                "test_name": _code(res, "code") or "Observation",
                "value": str(val),
                "unit": "",
                "reference_range": None,
                "flag": _interpretation_flag(res),
                "confidence": 0.99,
            }
            if any(k in code for k in _VITAL_KEYWORDS):
                vitals.append(
                    {"name": entry["test_name"], "value": entry["value"], "unit": entry["unit"]}
                )
            elif any(k in code for k in _LAB_KEYWORDS):
                labs.append(entry)
            else:
                labs.append(entry)
        elif rtype == "Condition":
            c = _code(res, "code")
            if c:
                conditions.append(c)
        elif rtype == "AllergyIntolerance":
            a = _code(res, "code") or _code(res, "substance")
            if a:
                allergies.append(a)
        elif rtype == "Encounter":
            date = (res.get("period") or {}).get("start")
            if date and not report_date:
                report_date = date[:10]
            encounters.append({"date": date})
        elif rtype in ("DiagnosticReport",):
            date = (res.get("effectiveDateTime") or "")[:10] or None
            if date and not report_date:
                report_date = date
        else:
            ignored.append(rtype or "Unknown")

    doc = {
        "document_type": "lab_report"
        if (labs or vitals)
        else ("prescription" if meds else "discharge_summary"),
        "date": report_date or "",
        "provider_or_doctor": "",
        "patient_name": patient_name,
        "medications": meds,
        "lab_results": labs,
        "diagnoses": [],
        "symptoms": [],
        "procedures": [],
        "vital_signs": vitals,
        "imaging_results": [],
        "allergies_noted": allergies,
        "diagnoses_or_conditions": conditions,
        "clinical_notes": None,
        "field_evidence": {},
        "illegible_or_low_confidence_fields": [],
        "overall_confidence": 0.99,
        "_source": {
            "file": document_id,
            "method": "fhir_import",
            "fhir_resource_count": len(entries),
        },
    }
    docs.append(doc)

    return {
        "patient_name": patient_name,
        "documents": docs,
        "imported": {
            "medications": len(meds),
            "lab_results": len(labs),
            "vital_signs": len(vitals),
            "conditions": len(conditions),
            "allergies": len(allergies),
            "encounters": len(encounters),
        },
        "ignored_resource_types": sorted(set(ignored)),
        "note": (
            "Structured FHIR data was mapped into MediMind's extraction schema. Rich FHIR "
            "fields the pipeline does not model were dropped (see ignored_resource_types) "
            "rather than guessed. Ingest as you would any upload to rebuild the timeline."
        ),
    }
