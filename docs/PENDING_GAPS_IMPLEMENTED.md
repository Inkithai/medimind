# Remaining gap implementation status

All gaps from the 2026-08-18 comparison are now implemented or intentionally preserved with a safer equivalent.

## Added in the completion pass

- Rebuildable normalized tables for medications, prescriptions, allergies, labs, clinical events, and safety findings.
- Stable deterministic row/issue IDs and created/updated/unchanged/removed reconciliation.
- Patient-scoped normalized-entity query API.
- Complete essential-medicines PDF ingestion, graph constraints, age-restriction lookup, conservative runtime age-conflict evaluation, and triage integration.
- Durable patient profile API/UI for legal/preferred name, DOB, phone, emergency contact, and language metadata.
- Profile name/DOB used only as an additional identity and age-safety signal; it never overrides source documents.
- Fail-closed admission of ambiguous all-numeric AI-extracted dates.

## Deployment migration required

Run the updated `backend/supabase_schema.sql` once in the Supabase SQL editor. It adds only new tables/indexes and does not remove existing data:

- `clinical_medications`
- `clinical_prescriptions`
- `clinical_allergies`
- `clinical_lab_results`
- `clinical_events`
- `safety_findings`
- `patient_profiles`

Until this migration is applied, the existing JSON snapshot pipeline continues to work and normalized projection reports `schema_not_migrated`.

## Runtime configuration

The complete essential-medicines graph requires the existing optional Neo4j configuration. Ingest a full adult or children list using:

```http
POST /api/v1/knowledge-graph/essential-medicines
Content-Type: multipart/form-data
```

Patient records are automatically checked against ingested age restrictions on each safety rebuild/re-analysis. Restrictions that cannot be parsed unambiguously remain visible as reference notes but are not promoted to patient-specific conflicts.
