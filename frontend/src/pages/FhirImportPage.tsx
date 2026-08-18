import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { UploadIcon, LinkIcon, FileIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import type { FhirImportResult } from "../types/api";

// A compact but realistic FHIR R4 sample so the feature is demonstrable without
// a real export on hand. Covers the resources the importer understands.
const SAMPLE_FHIR = {
  resourceType: "Bundle",
  type: "collection",
  entry: [
    { resource: { resourceType: "Patient", name: [{ given: ["Jane"], family: "Doe" }], gender: "female", birthDate: "1958-03-12" } },
    { resource: { resourceType: "Encounter", period: { start: "2024-05-10" } } },
    { resource: { resourceType: "MedicationStatement", status: "active", medicationCodeableConcept: { text: "Warfarin 5mg" } } },
    { resource: { resourceType: "MedicationStatement", status: "active", medicationCodeableConcept: { text: "Ibuprofen 400mg" } } },
    { resource: { resourceType: "MedicationStatement", status: "active", medicationCodeableConcept: { text: "Metformin 500mg" } } },
    { resource: { resourceType: "Observation", code: { text: "Potassium" }, valueQuantity: { value: 5.9, unit: "mmol/L" }, interpretation: [{ coding: [{ code: "H" }] }] } },
    { resource: { resourceType: "Observation", code: { text: "Creatinine" }, valueQuantity: { value: 160, unit: "umol/L" }, interpretation: [{ coding: [{ code: "H" }] }] } },
    { resource: { resourceType: "Observation", code: { text: "Blood Pressure" }, valueQuantity: { value: "148/94", unit: "mmHg" } } },
    { resource: { resourceType: "Condition", code: { text: "Atrial fibrillation" } } },
    { resource: { resourceType: "Condition", code: { text: "Type 2 diabetes mellitus" } } },
    { resource: { resourceType: "AllergyIntolerance", code: { text: "Penicillin" } } },
  ],
};

const COUNT_LABELS: Record<string, string> = {
  medications: "Medications",
  lab_results: "Lab results",
  vital_signs: "Vital signs",
  conditions: "Conditions",
  allergies: "Allergies",
  encounters: "Encounters",
};

export function FhirImportPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FhirImportResult | null>(null);

  function onFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => setText(String(reader.result || ""));
    reader.onerror = () => setError("Could not read that file.");
    reader.readAsText(file);
  }

  function loadSample() {
    setText(JSON.stringify(SAMPLE_FHIR, null, 2));
    setResult(null);
    setError(null);
  }

  async function runImport() {
    setError(null);
    setResult(null);
    let bundle: unknown;
    try {
      bundle = JSON.parse(text);
    } catch (e) {
      setError("That isn't valid JSON. Paste a FHIR R4 Bundle (a JSON object with a `resourceType` of `Bundle` and an `entry` array).");
      return;
    }
    setBusy(true);
    try {
      const res = await api.importFhir(credentials, bundle);
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  const imported = result?.imported || {};
  const totalImported = Object.values(imported).reduce((a, b) => a + (b || 0), 0);

  return (
    <div className="space-y-6">
      <div className="min-w-0">
        <h1 className="page-title">{t("fhir.title")}</h1>
        <p className="secondary-text mt-2 max-w-2xl">{t("fhir.subtitle")}</p>
      </div>

      <Card>
        <CardHeader
          title="FHIR R4 Bundle"
          description="Paste a Bundle, or upload a .json file. The importer understands Patient, MedicationStatement/Request, Observation, Condition, AllergyIntolerance, Encounter and DiagnosticReport."
          action={
            <button
              type="button"
              onClick={loadSample}
              className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              <LinkIcon className="h-3.5 w-3.5" /> Load sample
            </button>
          }
        />
        <CardBody className="space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={'{\n  "resourceType": "Bundle",\n  "entry": [ ... ]\n}'}
            rows={12}
            className="block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
            spellCheck={false}
          />
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={runImport}
              disabled={busy || !text.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
            >
              <UploadIcon className="h-4 w-4" />
              {busy ? "Importing…" : "Import into workspace"}
            </button>
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
              <FileIcon className="h-4 w-4" /> Upload .json
              <input
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onFile(f);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        </CardBody>
      </Card>

      {error && (
        <Card>
          <CardBody>
            <p className="text-sm text-red-600">{error}</p>
          </CardBody>
        </Card>
      )}

      {result && (
        <Card>
          <CardHeader
            title="Import preview"
            action={
              result.persisted ? (
                <StatusBadge tone="success">saved</StatusBadge>
              ) : (
                <StatusBadge tone="warning">parsed — not saved</StatusBadge>
              )
            }
          />
          <CardBody className="space-y-4">
            <div className="text-sm text-slate-600">
              <span className="font-medium text-slate-700">Patient:</span>{" "}
              {result.patient_name || "Unnamed"} ·{" "}
              <span className="font-medium text-slate-700">{totalImported}</span> items recognised
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {Object.entries(imported).map(([k, v]) =>
                v ? (
                  <div key={k} className="rounded-md border border-slate-200 p-2 text-xs">
                    <div className="font-medium text-slate-600">{COUNT_LABELS[k] || k}</div>
                    <div className="text-lg font-semibold text-slate-800">{v}</div>
                  </div>
                ) : null
              )}
            </div>

            {result.ignored_resource_types.length > 0 && (
              <p className="text-xs text-slate-400">
                Ignored resource types (not modelled): {result.ignored_resource_types.join(", ")}
              </p>
            )}

            {result.persistence_error && (
              <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2 text-xs text-amber-800">
                The bundle parsed correctly, but it could not be saved to the workspace
                ({result.persistence_error}). The backend needs Supabase configured to persist an
                import — the preview above shows what was understood.
              </div>
            )}

            {result.persisted && (
              <div className="flex flex-wrap items-center gap-3">
                <Link
                  to="/history"
                  className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700"
                >
                  View timeline
                </Link>
                <Link
                  to="/clinical-safety"
                  className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50"
                >
                  Run safety check
                </Link>
              </div>
            )}

            <p className="text-xs text-slate-400">{result.note}</p>
          </CardBody>
        </Card>
      )}

      <MedicalDisclaimer />
    </div>
  );
}
