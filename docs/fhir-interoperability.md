# FHIR interoperability

MediMind now exposes a deterministic FHIR R4-oriented export and validation flow:

```text
GET /api/v1/export?format=fhir
GET /api/v1/export/validation?format=fhir
```

Both routes require the normal authenticated request headers. The validation route returns a separate report so the exported Bundle remains pure FHIR JSON.

## Exported resources

- `Patient` with an opaque MediMind identifier
- `MedicationStatement` with `medicationCodeableConcept` and curated RxNorm mappings when known
- `MedicationRequest` for documented prescription intent
- `Observation` for laboratory results, with curated LOINC mappings when known
- `AllergyIntolerance` for recorded allergies
- `Condition` for documented diagnoses/conditions, with curated SNOMED CT and ICD-10-CM mappings when known
- `Encounter` for documented visits
- `Provenance` linking the export resources to the export operation

Unknown terminology is never guessed. The human-readable text remains in the resource, and unmapped values are surfaced in the export metadata when using the Python export builder with `return_metadata=True`.

## Validation

`backend/export.py::validate_fhir_bundle()` performs deterministic local structural checks for the generated R4 subset, including:

- Bundle type and entry count
- resource types and `fullUrl` values
- required medication choice fields
- valid MedicationStatement and MedicationRequest status values
- Patient presence
- resolvable Provenance references

The API returns `valid`, `errors`, `warnings`, `resource_count`, and validator identity. This is a local structural validator, not a replacement for the HL7 Java validator. A standards-validator integration should be added before making a formal conformance claim.

## End-to-end demo flow

```text
medical document
  -> AI extraction and evidence
  -> deterministic safety analysis
  -> patient timeline / snapshot
  -> FHIR R4-oriented Bundle export
  -> local structural validation report
```
