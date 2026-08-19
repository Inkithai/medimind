import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState, Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { ShieldIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { ConflictsResponse, RecordConflict } from "../types/api";
import { formatConfidence } from "../utils/format";

function displayValue(value: unknown): string {
  if (value == null) return "Not present";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const item = value as Record<string, unknown>;
    if ("test_name" in item)
      return `${item.test_name}: ${item.value ?? "?"} ${item.unit ?? ""}`.trim();
    if ("study_type" in item)
      return `${item.study_type}: ${item.impression ?? item.findings ?? ""}`.trim();
    if ("name" in item && "value" in item)
      return `${item.name}: ${item.value ?? "?"} ${item.unit ?? ""}`.trim();
    if ("name" in item && "dosage" in item)
      return `${item.name}: ${item.dosage ?? ""} ${item.frequency ?? ""}`.trim();
    if ("name" in item) return `${item.name}: ${item.status ?? item.severity ?? ""}`.trim();
  }
  return JSON.stringify(value);
}

export function ReviewPage() {
  const { credentials } = useAuth();
  const [data, setData] = useState<ConflictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [working, setWorking] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.getConflicts(credentials, true));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  async function resolve(conflict: RecordConflict) {
    const source = selected[conflict.conflict_id];
    if (!source) return;
    setWorking(conflict.conflict_id);
    setError(null);
    try {
      await api.resolveConflict(
        credentials,
        conflict.conflict_id,
        source,
        notes[conflict.conflict_id],
      );
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setWorking(null);
    }
  }

  async function reopen(conflict: RecordConflict) {
    setWorking(conflict.conflict_id);
    setError(null);
    try {
      await api.reopenConflict(
        credentials,
        conflict.conflict_id,
        "Reopened for another source review",
      );
      await load();
    } catch (err) {
      setError(err);
    } finally {
      setWorking(null);
    }
  }

  const conflicts = data?.conflicts || [];
  const active = conflicts.filter((item) => item.status !== "superseded");
  const unresolved = active.filter((item) => item.status === "unresolved");
  const resolved = active.filter((item) => item.status === "resolved");
  const superseded = conflicts.filter((item) => item.status === "superseded");

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Trust Review</h1>
          <p className="secondary-text mt-2 max-w-2xl">
            Resolve competing source facts before MediMind uses them in answers, lab trends,
            medication safety, or summaries.
          </p>
        </div>
        <Link to="/documents" className="btn-secondary">
          Correct an extraction
        </Link>
      </header>

      {loading && <LoadingState label="Checking source conflicts" />}
      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && data && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <Metric label="Needs review" value={unresolved.length} tone="text-amber-700" />
            <Metric label="Resolved" value={resolved.length} tone="text-emerald-700" />
            <Metric
              label="Quarantined sources"
              value={data.trust_summary?.quarantined_documents || 0}
              tone="text-red-700"
            />
            <Metric
              label="Corrected fields"
              value={data.trust_summary?.corrected_fields || 0}
              tone="text-brand-700"
            />
          </div>

          {unresolved.length > 0 ? (
            <Alert variant="warning" title="Conflicting evidence is quarantined">
              Unresolved facts stay visible below, but are excluded from retrieval and every derived
              clinical view. Choose the source that matches the original document; do not guess.
            </Alert>
          ) : (
            <Alert variant="success" title="No unresolved source conflicts">
              All currently detected conflicts have an authoritative source, or were removed by a
              correction.
            </Alert>
          )}

          <div className="space-y-4">
            {unresolved.map((conflict) => (
              <ConflictCard
                key={conflict.conflict_id}
                conflict={conflict}
                selected={selected[conflict.conflict_id] || ""}
                note={notes[conflict.conflict_id] || ""}
                working={working === conflict.conflict_id}
                onSelect={(value) => setSelected({ ...selected, [conflict.conflict_id]: value })}
                onNote={(value) => setNotes({ ...notes, [conflict.conflict_id]: value })}
                onResolve={() => void resolve(conflict)}
              />
            ))}
          </div>

          {resolved.length > 0 && (
            <details
              className="rounded-xl border border-slate-200 bg-white p-4"
              open={unresolved.length === 0}
            >
              <summary className="cursor-pointer font-semibold text-slate-800">
                Resolved conflicts ({resolved.length})
              </summary>
              <div className="mt-3 space-y-3">
                {resolved.map((conflict) => {
                  const chosen = conflict.items.find(
                    (item) => item.document_id === conflict.authoritative_document_id,
                  );
                  return (
                    <div
                      key={conflict.conflict_id}
                      className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-800">{conflict.summary}</p>
                          <p className="mt-1 text-xs text-slate-600">
                            Authoritative:{" "}
                            {chosen?.source_file || conflict.authoritative_document_id}
                            {chosen?.page ? `, page ${chosen.page}` : ""}
                          </p>
                          {conflict.resolution_note && (
                            <p className="mt-1 text-xs text-slate-500">
                              {conflict.resolution_note}
                            </p>
                          )}
                        </div>
                        <button
                          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700"
                          disabled={working === conflict.conflict_id}
                          onClick={() => void reopen(conflict)}
                        >
                          Reopen
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </details>
          )}

          {superseded.length > 0 && (
            <details className="rounded-xl border border-slate-200 bg-white p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">
                Superseded audit records ({superseded.length})
              </summary>
              <ul className="mt-3 space-y-2 text-xs text-slate-500">
                {superseded.map((item) => (
                  <li key={item.conflict_id}>{item.summary}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <Card>
      <CardBody>
        <p className={`text-2xl font-bold ${tone}`}>{value}</p>
        <p className="mt-1 text-xs font-medium text-slate-500">{label}</p>
      </CardBody>
    </Card>
  );
}

function ConflictCard({
  conflict,
  selected,
  note,
  working,
  onSelect,
  onNote,
  onResolve,
}: {
  conflict: RecordConflict;
  selected: string;
  note: string;
  working: boolean;
  onSelect: (value: string) => void;
  onNote: (value: string) => void;
  onResolve: () => void;
}) {
  return (
    <Card>
      <CardBody>
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700">
            <ShieldIcon className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-slate-900">{conflict.summary}</h2>
              <StatusBadge tone={conflict.kind === "identity" ? "danger" : "warning"}>
                {conflict.kind.replace(/_/g, " ")}
              </StatusBadge>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Select the source that exactly matches the original record.
            </p>

            <div className="mt-4 grid gap-2">
              {conflict.items.map((item, index) => (
                <label
                  key={`${item.document_id}-${item.field_path}-${index}`}
                  className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${selected === item.document_id ? "border-brand-400 bg-brand-50" : "border-slate-200 bg-slate-50"}`}
                >
                  <input
                    type="radio"
                    name={conflict.conflict_id}
                    value={item.document_id}
                    checked={selected === item.document_id}
                    onChange={() => onSelect(item.document_id)}
                    className="mt-1"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-slate-800">
                      {item.source_file}
                      {item.page ? ` · page ${item.page}` : ""}
                    </span>
                    <span className="mt-1 block text-sm text-slate-700">
                      {displayValue(item.value)}
                    </span>
                    <span className="mt-1 block text-xs text-slate-400">
                      {item.confidence != null
                        ? `Extraction confidence ${formatConfidence(item.confidence)}`
                        : "Confidence unavailable"}
                    </span>
                  </span>
                </label>
              ))}
            </div>

            <textarea
              value={note}
              onChange={(e) => onNote(e.target.value)}
              placeholder="Optional review note (e.g. checked against page 2)"
              className="mt-3 block min-h-16 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <div className="mt-3 flex justify-end">
              <button className="btn-primary" disabled={!selected || working} onClick={onResolve}>
                {working && <Spinner className="h-4 w-4" />} Confirm source & rebuild
              </button>
            </div>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}
