import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { UploadIcon, FileIcon } from "../components/icons";
import { toastMessage, useToast } from "../components/Toast";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import type { FhirImportResult } from "../types/api";
import type { EmbeddedPageProps } from "../components/TabBar";

// NOTE: no sample/mock patient data is bundled here. The import accepts only
// real, user-provided FHIR Bundles (pasted or uploaded). See project policy:
// all displayed information must come from real backend / user-provided data.

const COUNT_LABELS: Record<string, string> = {
  medications: "Medications",
  lab_results: "Lab results",
  vital_signs: "Vital signs",
  conditions: "Conditions",
  allergies: "Allergies",
  encounters: "Encounters",
};

export function FhirImportPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const { toastSuccess, toastError, toastInfo } = useToast();
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

  async function runImport() {
    setError(null);
    setResult(null);
    let bundle: unknown;
    try {
      bundle = JSON.parse(text);
    } catch (e) {
      setError(
        "That isn't valid JSON. Paste a FHIR R4 Bundle (a JSON object with a `resourceType` of `Bundle` and an `entry` array).",
      );
      toastError("That file could not be read", "It is not valid JSON. Check the file and retry.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.importFhir(credentials, bundle);
      setResult(res);
      const total = Object.values(res.imported || {}).reduce((sum, count) => sum + (count || 0), 0);
      if (total > 0) {
        toastSuccess(
          `${total} item${total === 1 ? "" : "s"} imported`,
          "They now appear in your timeline and safety checks.",
        );
      } else {
        toastInfo(
          "Nothing was imported",
          "The file was read, but it contained no records MediMind can use.",
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed.");
      toastError("Import failed", toastMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const imported = result?.imported || {};
  const totalImported = Object.values(imported).reduce((a, b) => a + (b || 0), 0);

  return (
    <div className="space-y-6">
      {embedded ? (
        <p className="secondary-text max-w-2xl">{t("fhir.subtitle")}</p>
      ) : (
        <div className="min-w-0">
          <h1 className="page-title">{t("fhir.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("fhir.subtitle")}</p>
        </div>
      )}

      <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-5 text-sm leading-relaxed text-sky-900">
        <p className="font-semibold">{t("fhir.whoForTitle")}</p>
        <p className="mt-1">{t("fhir.whoForBody")}</p>
        <Link
          to="/upload"
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
        >
          <UploadIcon className="h-4 w-4" /> Upload documents instead
        </Link>
      </div>

      <Card>
        <CardHeader
          title="FHIR R4 Bundle"
          description="If you already have a FHIR record file, upload it here. The importer understands Patient, MedicationStatement/Request, Observation, Condition, AllergyIntolerance, Encounter and DiagnosticReport."
        />
        <CardBody className="space-y-3">
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50">
            <FileIcon className="h-4 w-4" /> Choose a .json record file
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

          <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <summary className="cursor-pointer text-sm font-semibold text-slate-700">
              Advanced: paste the FHIR JSON directly
            </summary>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={'{\n  "resourceType": "Bundle",\n  "entry": [ ... ]\n}'}
              rows={12}
              className="mt-3 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs"
              spellCheck={false}
            />
          </details>

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
            {!text.trim() && (
              <p className="text-xs text-slate-500">
                Choose a .json file, or paste FHIR JSON under “Advanced” above, then import.
              </p>
            )}
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
                ) : null,
              )}
            </div>

            {result.ignored_resource_types.length > 0 && (
              <p className="text-xs text-slate-400">
                Ignored resource types (not modelled): {result.ignored_resource_types.join(", ")}
              </p>
            )}

            {result.persistence_error && (
              <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2 text-xs text-amber-800">
                The bundle parsed correctly, but it could not be saved to the workspace (
                {result.persistence_error}). The backend needs Supabase configured to persist an
                import — the preview above shows what was understood.
              </div>
            )}

            {result.persisted && (
              <div className="flex flex-wrap items-center gap-3">
                <Link
                  to="/documents?tab=timeline"
                  className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700"
                >
                  View timeline
                </Link>
                <Link
                  to="/safety?tab=clinical"
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
