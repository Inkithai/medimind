import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { CorrectionEvent, LabResult, Medication, Visit } from "../types/api";
import { formatDate } from "../utils/format";
import { Alert } from "./Alert";
import { Spinner } from "./Spinner";

interface Draft {
  date: string;
  patient_name: string;
  provider_or_doctor: string;
  medications: Array<{
    name: string;
    ingredients: string;
    dosage: string;
    frequency: string;
    duration: string;
    dosage_value: string;
    dosage_unit: string;
    frequency_per_day: string;
    is_as_needed: boolean;
  }>;
  lab_results: Array<{
    test_name: string;
    value: string;
    unit: string;
    reference_range: string;
    flag: LabResult["flag"];
  }>;
}

function draftFromVisit(visit: Visit): Draft {
  return {
    date: visit.date || "",
    patient_name: visit.patient_name || "",
    provider_or_doctor: visit.provider_or_doctor || "",
    medications: visit.medications.map((med) => ({
      name: med.name,
      ingredients: med.ingredients.join(", "),
      dosage: med.dosage,
      frequency: med.frequency,
      duration: med.duration || "",
      dosage_value: med.dosage_value == null ? "" : String(med.dosage_value),
      dosage_unit: med.dosage_unit || "",
      frequency_per_day: med.frequency_per_day == null ? "" : String(med.frequency_per_day),
      is_as_needed: med.is_as_needed,
    })),
    lab_results: visit.lab_results.map((lab) => ({
      test_name: lab.test_name,
      value: lab.value,
      unit: lab.unit || "",
      reference_range: lab.reference_range || "",
      flag: lab.flag,
    })),
  };
}

function optionalNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildChanges(visit: Visit, draft: Draft) {
  const changes: Array<{
    field_path: string;
    corrected_value: unknown;
    expected_previous_value: unknown;
  }> = [];
  const add = (field_path: string, previous: unknown, corrected: unknown) => {
    if (JSON.stringify(previous) !== JSON.stringify(corrected)) {
      changes.push({ field_path, corrected_value: corrected, expected_previous_value: previous });
    }
  };
  add("/date", visit.date, draft.date.trim() || null);
  add("/patient_name", visit.patient_name, draft.patient_name.trim() || null);
  add("/provider_or_doctor", visit.provider_or_doctor, draft.provider_or_doctor.trim() || null);

  draft.medications.forEach((item, index) => {
    const old: Medication = visit.medications[index];
    const prefix = `/medications/${index}`;
    add(`${prefix}/name`, old.name, item.name.trim());
    add(
      `${prefix}/ingredients`,
      old.ingredients,
      item.ingredients.split(",").map((value) => value.trim()).filter(Boolean)
    );
    add(`${prefix}/dosage`, old.dosage, item.dosage.trim());
    add(`${prefix}/frequency`, old.frequency, item.frequency.trim());
    add(`${prefix}/duration`, old.duration, item.duration.trim() || null);
    add(`${prefix}/dosage_value`, old.dosage_value, optionalNumber(item.dosage_value));
    add(`${prefix}/dosage_unit`, old.dosage_unit, item.dosage_unit.trim() || null);
    add(`${prefix}/frequency_per_day`, old.frequency_per_day, optionalNumber(item.frequency_per_day));
    add(`${prefix}/is_as_needed`, old.is_as_needed, item.is_as_needed);
  });

  draft.lab_results.forEach((item, index) => {
    const old = visit.lab_results[index];
    const prefix = `/lab_results/${index}`;
    add(`${prefix}/test_name`, old.test_name, item.test_name.trim());
    add(`${prefix}/value`, old.value, item.value.trim());
    add(`${prefix}/unit`, old.unit, item.unit.trim() || null);
    add(`${prefix}/reference_range`, old.reference_range, item.reference_range.trim() || null);
    add(`${prefix}/flag`, old.flag, item.flag);
  });
  return changes;
}

export function CorrectionEditor({ visit, onSaved }: { visit: Visit; onSaved: () => void }) {
  const { credentials } = useAuth();
  const [draft, setDraft] = useState(() => draftFromVisit(visit));
  const [reason, setReason] = useState("");
  const [history, setHistory] = useState<CorrectionEvent[]>([]);
  const [saving, setSaving] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(draftFromVisit(visit));
    setReason("");
    setSaved(false);
    setError(null);
  }, [visit]);

  useEffect(() => {
    let active = true;
    setLoadingHistory(true);
    api.getDocumentCorrections(credentials, visit._document_id)
      .then((response) => {
        if (active) setHistory(response.corrections);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Could not load correction history.");
      })
      .finally(() => {
        if (active) setLoadingHistory(false);
      });
    return () => { active = false; };
  }, [credentials, visit._document_id]);

  const changes = useMemo(() => buildChanges(visit, draft), [visit, draft]);

  async function save() {
    if (!reason.trim() || changes.length === 0) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const result = await api.correctDocument(credentials, visit._document_id, changes, reason.trim());
      setHistory((current) => [...current, ...(result.events || [])]);
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The correction could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <Alert variant="info" title="The original extraction is never overwritten">
        Saving creates an audit event, rebuilds the timeline and lab trends, reruns safety checks,
        and replaces the search index. Previous values remain available below.
      </Alert>

      {visit._trust?.quarantined && (
        <Alert variant="warning" title="This source is quarantined">
          It is visible for review but excluded from answers and analytics until its conflict is resolved.
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Document date">
          <input className="input" value={draft.date} onChange={(e) => setDraft({ ...draft, date: e.target.value })} />
        </Field>
        <Field label="Patient identity">
          <input className="input" value={draft.patient_name} onChange={(e) => setDraft({ ...draft, patient_name: e.target.value })} />
        </Field>
        <Field label="Provider or doctor">
          <input className="input" value={draft.provider_or_doctor} onChange={(e) => setDraft({ ...draft, provider_or_doctor: e.target.value })} />
        </Field>
      </div>

      {draft.medications.map((med, index) => (
        <fieldset key={index} className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Medication {index + 1}
          </legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {(["name", "ingredients", "dosage", "frequency", "duration", "dosage_value", "dosage_unit", "frequency_per_day"] as const).map((key) => (
              <Field key={key} label={key.replace(/_/g, " ")}>
                <input
                  className="input"
                  type={key === "dosage_value" || key === "frequency_per_day" ? "number" : "text"}
                  step="any"
                  value={med[key] as string}
                  onChange={(e) => setDraft({
                    ...draft,
                    medications: draft.medications.map((item, i) => i === index ? { ...item, [key]: e.target.value } : item),
                  })}
                />
              </Field>
            ))}
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={med.is_as_needed}
                onChange={(e) => setDraft({
                  ...draft,
                  medications: draft.medications.map((item, i) => i === index ? { ...item, is_as_needed: e.target.checked } : item),
                })}
              />
              Taken as needed (PRN)
            </label>
          </div>
        </fieldset>
      ))}

      {draft.lab_results.map((lab, index) => (
        <fieldset key={index} className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Lab result {index + 1}</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {(["test_name", "value", "unit", "reference_range"] as const).map((key) => (
              <Field key={key} label={key.replace(/_/g, " ")}>
                <input
                  className="input"
                  value={lab[key]}
                  onChange={(e) => setDraft({
                    ...draft,
                    lab_results: draft.lab_results.map((item, i) => i === index ? { ...item, [key]: e.target.value } : item),
                  })}
                />
              </Field>
            ))}
            <Field label="flag">
              <select
                className="input"
                value={lab.flag}
                onChange={(e) => setDraft({
                  ...draft,
                  lab_results: draft.lab_results.map((item, i) => i === index ? { ...item, flag: e.target.value as LabResult["flag"] } : item),
                })}
              >
                <option value="normal">normal</option>
                <option value="high">high</option>
                <option value="low">low</option>
                <option value="unknown">unknown</option>
              </select>
            </Field>
          </div>
        </fieldset>
      ))}

      <div className="rounded-lg bg-slate-50 p-3 ring-1 ring-slate-200">
        <label className="text-xs font-semibold uppercase tracking-wide text-slate-600" htmlFor="correction-reason">
          Reason for correction
        </label>
        <textarea
          id="correction-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Verified against the printed value on page 2"
          className="mt-2 block min-h-20 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-xs text-slate-500">{changes.length} changed field{changes.length === 1 ? "" : "s"}</p>
          <button
            type="button"
            onClick={() => void save()}
            disabled={saving || changes.length === 0 || reason.trim().length < 3}
            className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving && <Spinner className="h-4 w-4" />} Save & rebuild record
          </button>
        </div>
      </div>

      {error && <Alert variant="danger" title="Correction not saved">{error}</Alert>}
      {saved && <Alert variant="success" title="Correction saved">All derived views were rebuilt from the corrected record.</Alert>}

      <div>
        <h3 className="text-sm font-semibold text-slate-800">Audit history</h3>
        {loadingHistory ? (
          <p className="mt-2 flex items-center gap-2 text-xs text-slate-500"><Spinner className="h-3.5 w-3.5" /> Loading history</p>
        ) : history.length === 0 ? (
          <p className="mt-2 text-xs text-slate-500">No corrections have been made to this document.</p>
        ) : (
          <ol className="mt-2 space-y-2">
            {[...history].reverse().map((event) => (
              <li key={event.id} className="rounded-lg border border-slate-200 bg-white p-3 text-xs">
                <div className="flex justify-between gap-2 text-slate-500">
                  <code className="font-semibold text-brand-700">{event.field_path}</code>
                  <span>{formatDate(event.created_at)}</span>
                </div>
                <p className="mt-1 text-slate-700">
                  <Value value={event.previous_value} /> <span className="text-slate-400">→</span> <Value value={event.corrected_value} />
                </p>
                <p className="mt-1 text-slate-500">Reason: {event.reason}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs font-medium capitalize text-slate-600">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Value({ value }: { value: unknown }) {
  return <span className="font-medium">{value == null ? "empty" : typeof value === "string" ? value : JSON.stringify(value)}</span>;
}
