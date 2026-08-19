import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { toastMessage, useToast } from "../components/Toast";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import {
  AlertIcon,
  BeakerIcon,
  ChangesIcon,
  FileIcon,
  PillIcon,
  RefreshIcon,
  UploadIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type {
  FindingChangeLog,
  RecordChange,
  RecordChangesReport,
  RecordComparison,
} from "../types/api";
import { formatDate } from "../utils/format";

export function ChangesPage() {
  const { credentials } = useAuth();
  const { toastSuccess, toastError } = useToast();
  const [report, setReport] = useState<RecordChangesReport | null>(null);
  const [changeLog, setChangeLog] = useState<FindingChangeLog | null>(null);
  const [savingSnapshot, setSavingSnapshot] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const loadChangeLog = useCallback(async () => {
    // Independent of the record comparison above: the safety-finding log
    // exists as soon as one analysis has run, even with a single document.
    try {
      setChangeLog(await api.getFindingChangeLog(credentials));
    } catch {
      setChangeLog(null);
    }
  }, [credentials]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    void loadChangeLog();
    try {
      setReport(await api.getRecordChanges(credentials));
      setSelectedIndex(0);
    } catch (err) {
      setReport(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials, loadChangeLog]);

  async function handleSaveSnapshot() {
    setSavingSnapshot(true);
    try {
      await api.captureFindingSnapshot(credentials);
      await loadChangeLog();
      toastSuccess(
        "Snapshot saved",
        "Today's safety findings were recorded so future changes can be compared against them.",
      );
    } catch (err) {
      toastError("Snapshot not saved", toastMessage(err));
    } finally {
      setSavingSnapshot(false);
    }
  }

  useStrictEffect(() => {
    void load();
  }, [load]);

  const selected = report?.comparisons[selectedIndex] ?? null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
            <ChangesIcon className="h-4 w-4" /> Longitudinal intelligence
          </div>
          <h1 className="page-title mt-1">What Changed?</h1>
          <p className="secondary-text mt-2 max-w-2xl">
            Compare consecutive records, see the exact before and after, and trace every finding
            back to both source documents.
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={loading}
          className="btn-secondary px-4 py-2 text-sm"
        >
          <RefreshIcon className="h-4 w-4" /> Refresh
        </button>
      </header>

      {loading && (
        <LoadingState
          label="Comparing your records"
          description="Checking structured facts without generating new clinical claims."
        />
      )}
      {!loading && error !== null && <ChangesError error={error} onRetry={() => void load()} />}

      {!loading && report && report.comparisons.length === 0 && (
        <NeedsMoreRecords datedRecords={report.summary.dated_records} />
      )}

      {!loading && report && report.comparisons.length > 0 && selected && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Metric
              label="Dated records"
              value={report.summary.dated_records}
              detail="available to compare"
            />
            <Metric
              label="Changes found"
              value={report.summary.changes_found}
              detail="across record history"
            />
            <Metric
              label="Needs attention"
              value={report.summary.attention_items}
              detail="review with a clinician"
              alert={report.summary.attention_items > 0}
            />
          </div>

          <section className="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
            <aside>
              <h2 className="mb-3 text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
                Comparisons
              </h2>
              <div className="space-y-2">
                {report.comparisons.map((comparison, index) => (
                  <button
                    key={`${comparison.from_date}-${comparison.to_date}-${index}`}
                    onClick={() => setSelectedIndex(index)}
                    className={`w-full rounded-xl border p-3 text-left transition ${
                      index === selectedIndex
                        ? "border-brand-300 bg-brand-50 shadow-sm"
                        : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                  >
                    <p className="text-xs font-medium text-slate-500">
                      {index === 0 ? "Latest" : `Earlier · ${index}`}
                    </p>
                    <p className="mt-1 text-sm font-semibold text-slate-900">
                      {formatDate(comparison.from_date)} → {formatDate(comparison.to_date)}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {comparison.change_count}{" "}
                      {comparison.change_count === 1 ? "change" : "changes"}
                    </p>
                  </button>
                ))}
              </div>
            </aside>

            <div className="min-w-0 space-y-4">
              <ComparisonHeader comparison={selected} />
              {selected.changes.length === 0 ? (
                <Card>
                  <CardBody className="py-12 text-center">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
                      <ChangesIcon className="h-6 w-6" />
                    </div>
                    <h2 className="mt-3 card-title">No comparable field changes found</h2>
                    <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
                      The records may cover different kinds of information, or their shared
                      structured values did not change. MediMind does not treat missing information
                      as proof that a condition resolved or a medicine stopped.
                    </p>
                  </CardBody>
                </Card>
              ) : (
                selected.changes.map((change, index) => (
                  <ChangeCard key={`${change.kind}-${change.title}-${index}`} change={change} />
                ))
              )}
            </div>
          </section>

          <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-5 text-sm text-sky-900">
            <p className="font-semibold">How to read this</p>
            <p className="mt-1 leading-relaxed">
              {report.method} {report.note}
            </p>
          </div>
        </>
      )}

      {!loading && error === null && (
        <FindingChangeLogSection
          changeLog={changeLog}
          onSaveSnapshot={() => void handleSaveSnapshot()}
          saving={savingSnapshot}
        />
      )}
    </div>
  );
}

function ComparisonHeader({ comparison }: { comparison: RecordComparison }) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 bg-slate-50/70 px-5 py-3">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
          Selected comparison
        </p>
      </div>
      <div className="grid items-center gap-3 p-5 sm:grid-cols-[1fr_auto_1fr]">
        <SourceBlock label="Before" source={comparison.from_source} />
        <div className="hidden h-9 w-9 items-center justify-center rounded-full bg-brand-50 text-brand-600 sm:flex">
          <span aria-hidden="true">→</span>
        </div>
        <SourceBlock label="After" source={comparison.to_source} alignRight />
      </div>
    </div>
  );
}

function SourceBlock({
  label,
  source,
  alignRight = false,
}: {
  label: string;
  source: RecordComparison["from_source"];
  alignRight?: boolean;
}) {
  return (
    <div className={alignRight ? "sm:text-right" : ""}>
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-base font-bold text-slate-900">{formatDate(source.date)}</p>
      <p className="mt-0.5 truncate text-xs text-slate-500" title={source.source_file || undefined}>
        {source.source_file || "Unknown source"}
      </p>
    </div>
  );
}

function ChangeCard({ change }: { change: RecordChange }) {
  const style = importanceStyle(change.importance);
  const Icon =
    change.category === "lab"
      ? BeakerIcon
      : change.category === "medication"
        ? PillIcon
        : AlertIcon;
  return (
    <article className={`overflow-hidden rounded-2xl border bg-white shadow-sm ${style.border}`}>
      <div className="p-5">
        <div className="flex items-start gap-3">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${style.icon}`}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${style.badge}`}
              >
                {change.importance === "attention" ? "Review" : change.category}
              </span>
              <span className="text-xs capitalize text-slate-400">
                {change.kind.replace(/_/g, " ")}
              </span>
            </div>
            <h2 className="mt-2 card-title">{change.title}</h2>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{change.description}</p>
          </div>
        </div>

        {(change.before !== null || change.after !== null) && (
          <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_1fr] sm:items-stretch">
            <Value
              label="Before"
              value={change.before || "Not shown"}
              muted={change.before === null}
            />
            <div className="hidden items-center text-slate-300 sm:flex">→</div>
            <Value
              label="After"
              value={change.after || "Not shown"}
              muted={change.after === null}
            />
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-100 bg-slate-50/70 px-5 py-3 text-xs text-slate-500">
        <span className="flex items-center gap-1 font-semibold text-slate-600">
          <FileIcon className="h-3.5 w-3.5" /> Evidence
        </span>
        {change.evidence.map((source, index) =>
          source.document_url ? (
            <a
              key={index}
              href={source.document_url}
              target="_blank"
              rel="noreferrer"
              className="text-brand-700 underline decoration-brand-300 underline-offset-2 hover:text-brand-900"
            >
              {source.source_file || formatDate(source.date)}
            </a>
          ) : (
            <span key={index}>{source.source_file || formatDate(source.date)}</span>
          ),
        )}
      </div>
    </article>
  );
}

function Value({ label, value, muted }: { label: string; value: string; muted: boolean }) {
  return (
    <div
      className={`rounded-xl border px-4 py-3 ${muted ? "border-dashed border-slate-200 bg-slate-50" : "border-slate-200 bg-white"}`}
    >
      <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-sm font-semibold ${muted ? "text-slate-400" : "text-slate-800"}`}>
        {value}
      </p>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  alert = false,
}: {
  label: string;
  value: number;
  detail: string;
  alert?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border bg-white p-5 shadow-sm ${alert ? "border-amber-200" : "border-slate-200"}`}
    >
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`mt-1 text-3xl font-bold ${alert ? "text-amber-700" : "text-slate-900"}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{detail}</p>
    </div>
  );
}

function NeedsMoreRecords({ datedRecords }: { datedRecords: number }) {
  return (
    <Card>
      <CardBody className="py-14 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
          <ChangesIcon className="h-7 w-7" />
        </div>
        <h2 className="mt-4 section-title">One more dated record unlocks comparisons</h2>
        <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
          {datedRecords === 0
            ? "No dated records are available yet."
            : "MediMind found one dated record, but needs at least two to show what changed."}
        </p>
        <Link to="/upload" className="btn-primary mt-5">
          <UploadIcon className="h-5 w-5" /> Upload another record
        </Link>
      </CardBody>
    </Card>
  );
}

function ChangesError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404) return <NeedsMoreRecords datedRecords={0} />;
  return <ErrorState error={error} onRetry={onRetry} />;
}

function importanceStyle(importance: RecordChange["importance"]) {
  if (importance === "attention")
    return {
      border: "border-amber-200",
      icon: "bg-amber-50 text-amber-700",
      badge: "bg-amber-100 text-amber-800",
    };
  if (importance === "review")
    return {
      border: "border-sky-200",
      icon: "bg-sky-50 text-sky-700",
      badge: "bg-sky-100 text-sky-800",
    };
  return {
    border: "border-slate-200",
    icon: "bg-slate-100 text-slate-600",
    badge: "bg-slate-100 text-slate-600",
  };
}

/**
 * Safety-finding history (GET /api/v1/findings/history/change-log,
 * POST /api/v1/findings/history/snapshot).
 *
 * The comparison above answers "what changed between two documents".
 * This answers the different and equally important question "is this
 * warning new, or has it been there for months — and did one I thought
 * was gone come back?". Recurrence is called out in words, because a
 * finding that disappears and returns is the pattern most likely to be
 * dismissed as already handled.
 */
function FindingChangeLogSection({
  changeLog,
  onSaveSnapshot,
  saving,
}: {
  changeLog: FindingChangeLog | null;
  onSaveSnapshot: () => void;
  saving: boolean;
}) {
  const findings = changeLog?.findings || [];
  return (
    <section
      aria-labelledby="finding-change-log-title"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 id="finding-change-log-title" className="card-title">
            How your safety warnings changed
          </h2>
          <p className="secondary-text mt-1">
            Each time your records are analysed, MediMind stores which warnings were present. This
            shows when each one first appeared, when it was last seen, and whether it went away and
            came back.
          </p>
        </div>
        <button
          type="button"
          onClick={onSaveSnapshot}
          disabled={saving}
          className="btn-secondary"
          title="Records today's warnings so you can see later what changed."
        >
          {saving ? <Spinner className="h-5 w-5" /> : <ChangesIcon className="h-5 w-5" />}
          {saving ? "Saving snapshot…" : "Save today's snapshot"}
        </button>
      </div>

      {findings.length === 0 ? (
        <p className="mt-4 text-base text-slate-600">
          No warning history has been recorded yet. Use{" "}
          <span className="font-semibold">Save today&apos;s snapshot</span> after an analysis, and
          future changes will be listed here.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
          <table className="min-w-full text-left text-base">
            <caption className="sr-only">Safety findings with first and last seen dates</caption>
            <thead className="bg-slate-50 text-sm uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Warning
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  First seen
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Last seen
                </th>
                <th scope="col" className="px-4 py-3 font-semibold">
                  Pattern
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {findings.map((finding) => (
                <tr key={finding.finding_key} className="align-top hover:bg-slate-50">
                  <th scope="row" className="px-4 py-3 text-left font-medium text-slate-800">
                    {finding.subject || finding.rule || finding.finding_key}
                    {finding.kind && (
                      <span className="mt-1 block text-sm font-normal text-slate-600">
                        {finding.kind.replace(/_/g, " ")}
                      </span>
                    )}
                  </th>
                  <td className="px-4 py-3 text-slate-700">{formatDate(finding.first_seen)}</td>
                  <td className="px-4 py-3 text-slate-700">{formatDate(finding.last_seen)}</td>
                  <td className="px-4 py-3">
                    {finding.absent_then_recurred ? (
                      <StatusBadge tone="warning">
                        <span aria-hidden="true" className="font-bold">
                          ↻
                        </span>
                        Went away and came back
                      </StatusBadge>
                    ) : (
                      <StatusBadge tone="neutral">
                        Seen in {finding.seen_in_runs} analysis
                        {finding.seen_in_runs === 1 ? "" : "es"}
                      </StatusBadge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {changeLog && (
        <p className="mt-3 text-sm text-slate-600">
          Based on {changeLog.snapshots} recorded analysis
          {changeLog.snapshots === 1 ? "" : "es"}.
        </p>
      )}
    </section>
  );
}
