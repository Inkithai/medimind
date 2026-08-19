import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { TrustReview } from "../components/TrustReview";
import {
  AlertIcon,
  CheckIcon,
  FileIcon,
  IntegrityIcon,
  RefreshIcon,
  UploadIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type {
  CorrectionEvent,
  IntegrityEvidence,
  IntegrityIssue,
  RecordIntegrityReport,
} from "../types/api";
import { formatDate } from "../utils/format";
import { TabBar, useTabParam, type EmbeddedPageProps, type TabSpec } from "../components/TabBar";

export function RecordIntegrityPage({
  embedded,
  view,
}: EmbeddedPageProps & {
  /**
   * When the Record check hub owns the tab bar it also owns the selected
   * view, so the two sub-views are hoisted into the parent tab strip rather
   * than nesting a second row of tabs inside a tab panel.
   */
  view?: "discrepancies" | "conflicts";
} = {}) {
  const { credentials } = useAuth();
  /* Standalone route only: inside the Record check hub the parent owns the
     tab strip, and `view` is passed instead. */
  const standaloneTabs: TabSpec[] = [
    { id: "discrepancies", label: "Discrepancies" },
    { id: "conflicts", label: "Conflicts to resolve" },
  ];
  const [standaloneTab, setStandaloneTab] = useTabParam(standaloneTabs);
  const tab = view || standaloneTab;
  const [report, setReport] = useState<RecordIntegrityReport | null>(null);
  const [corrections, setCorrections] = useState<CorrectionEvent[]>([]);
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    // The correction history is an independent audit view: it must still
    // load when the integrity check itself has nothing to report.
    void api
      .listCorrections(credentials)
      .then((response) => setCorrections(response.corrections || []))
      .catch(() => setCorrections([]));
    try {
      setReport(await api.getRecordIntegrity(credentials));
      setReviewed(new Set());
    } catch (err) {
      setReport(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  const reviewedCount = report?.issues.filter((issue) => reviewed.has(issue.id)).length || 0;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        {embedded ? (
          <div />
        ) : (
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
              <IntegrityIcon className="h-4 w-4" /> Record integrity
            </div>
            <h1 className="page-title mt-1">Cross-check My Records</h1>
            <p className="secondary-text mt-2 max-w-2xl">
              Find facts that disagree across documents, inspect both sources, and verify them
              before relying on trends or answers.
            </p>
          </div>
        )}{" "}
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="btn-secondary"
        >
          <RefreshIcon className="h-4 w-4" /> Run checks again
        </button>
      </header>

      {/* Hidden when the Record check hub already renders these as top-level
          tabs; kept for the standalone /record-integrity route. */}
      {!view && (
        <TabBar
          tabs={standaloneTabs}
          active={tab}
          onSelect={setStandaloneTab}
          group="record-integrity"
          label="Record check views"
        />
      )}

      {tab === "conflicts" ? (
        <TrustReview />
      ) : (
        <>
          {loading && (
            <LoadingState
              label="Cross-checking structured records"
              description="Comparing identities, allergies, labs, and medication instructions without guessing which source is correct."
            />
          )}
          {!loading && error !== null && (
            <IntegrityError error={error} onRetry={() => void load()} />
          )}

          {!loading && report && (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Metric
                  label="Records checked"
                  value={report.summary.records_checked}
                  tone="neutral"
                />
                <Metric
                  label="Needs verification"
                  value={report.summary.issues_found}
                  tone={report.summary.issues_found ? "warning" : "success"}
                />
                <Metric
                  label="Reviewed this session"
                  value={reviewedCount}
                  tone={reviewedCount === report.summary.issues_found ? "success" : "neutral"}
                />
              </div>

              {report.issues.length === 0 ? (
                <Card>
                  <CardBody className="py-14 text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                      <CheckIcon className="h-7 w-7" />
                    </div>
                    <h2 className="mt-4 section-title">No structured discrepancies found</h2>
                    <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
                      The checks did not find conflicting patient names, allergy statements,
                      same-date lab results, or complete medication instructions. This does not
                      prove every record is complete or correct.
                    </p>
                  </CardBody>
                </Card>
              ) : (
                <section className="space-y-4">
                  <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
                    <p className="font-semibold">Do not choose a value from this screen alone</p>
                    <p className="mt-1 leading-relaxed">
                      Open both original documents and use the suggested verification step. Apparent
                      conflicts may be valid corrections, separate samples, or extraction
                      uncertainty.
                    </p>
                  </div>
                  {report.issues.map((issue) => (
                    <IntegrityCard
                      key={issue.id}
                      issue={issue}
                      reviewed={reviewed.has(issue.id)}
                      onToggleReviewed={() =>
                        setReviewed((previous) => {
                          const next = new Set(previous);
                          if (next.has(issue.id)) next.delete(issue.id);
                          else next.add(issue.id);
                          return next;
                        })
                      }
                    />
                  ))}
                </section>
              )}

              <CorrectionHistorySection corrections={corrections} />

              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-bold text-slate-900">Checks performed</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  {report.checks_performed.map((check) => (
                    <span
                      key={check}
                      className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium capitalize text-slate-700"
                    >
                      {check}
                    </span>
                  ))}
                </div>
                <p className="mt-4 text-xs leading-relaxed text-slate-500">
                  {report.method} {report.note}
                </p>
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}

function IntegrityCard({
  issue,
  reviewed,
  onToggleReviewed,
}: {
  issue: IntegrityIssue;
  reviewed: boolean;
  onToggleReviewed: () => void;
}) {
  const important = issue.severity === "important";
  return (
    <article
      className={`overflow-hidden rounded-2xl border bg-white shadow-sm transition ${reviewed ? "border-emerald-200 opacity-75" : important ? "border-amber-200" : "border-sky-200"}`}
    >
      <div className="p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <div
            className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${reviewed ? "bg-emerald-50 text-emerald-700" : important ? "bg-amber-50 text-amber-700" : "bg-sky-50 text-sky-700"}`}
          >
            {reviewed ? <CheckIcon className="h-5 w-5" /> : <AlertIcon className="h-5 w-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${important ? "bg-amber-100 text-amber-800" : "bg-sky-100 text-sky-800"}`}
              >
                {issue.severity === "important" ? "Verify first" : "Review"}
              </span>
              <span className="text-xs font-medium capitalize text-slate-400">
                {issue.category}
              </span>
              <span className="text-xs text-slate-400">
                · {Math.round(issue.confidence * 100)}% minimum extraction confidence
              </span>
            </div>
            <h2 className="mt-2 card-title">{issue.title}</h2>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{issue.explanation}</p>
          </div>
        </div>

        <div
          className={`mt-5 grid gap-3 ${issue.variants.length === 2 ? "md:grid-cols-2" : "md:grid-cols-3"}`}
        >
          {issue.variants.map((variant, index) => (
            <div
              key={`${variant.label}-${index}`}
              className="rounded-xl border border-slate-200 bg-slate-50/60 p-4"
            >
              <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">
                Source says
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-900">{variant.value}</p>
              <p className="mt-1 text-xs text-slate-500">{variant.label}</p>
              <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-200 pt-2 text-xs">
                {variant.evidence.map((source, evidenceIndex) => (
                  <Evidence source={source} key={evidenceIndex} />
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 rounded-xl border border-brand-100 bg-brand-50/60 p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-brand-700">How to verify</p>
          <p className="mt-1 text-sm leading-relaxed text-brand-950">{issue.suggested_action}</p>
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-slate-100 bg-slate-50/70 px-5 py-3">
        <span className="text-xs text-slate-500">
          This check does not automatically alter your record.
        </span>
        <label className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-slate-700">
          <input
            type="checkbox"
            checked={reviewed}
            onChange={onToggleReviewed}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
          Reviewed
        </label>
      </div>
    </article>
  );
}

function Evidence({ source }: { source: IntegrityEvidence }) {
  const label = source.source_file || formatDate(source.date);
  if (source.document_url)
    return (
      <a
        href={source.document_url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1 font-medium text-brand-700 underline decoration-brand-300 underline-offset-2"
      >
        <FileIcon className="h-3 w-3" />
        {label}
      </a>
    );
  return (
    <span className="inline-flex items-center gap-1 text-slate-600">
      <FileIcon className="h-3 w-3" />
      {label}
    </span>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "neutral" | "warning" | "success";
}) {
  const color =
    tone === "warning"
      ? "text-amber-700 border-amber-200"
      : tone === "success"
        ? "text-emerald-700 border-emerald-200"
        : "text-slate-900 border-slate-200";
  return (
    <div className={`rounded-2xl border bg-white p-5 shadow-sm ${color}`}>
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-3xl font-bold">{value}</p>
    </div>
  );
}

function IntegrityError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404)
    return (
      <Card>
        <CardBody className="py-14 text-center">
          <IntegrityIcon className="mx-auto h-10 w-10 text-brand-600" />
          <h2 className="mt-4 section-title">No records to cross-check</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
            Upload records before running integrity checks.
          </p>
          <Link to="/upload" className="btn-primary mt-5">
            <UploadIcon className="h-5 w-5" /> Upload records
          </Link>
        </CardBody>
      </Card>
    );
  return <ErrorState error={error} onRetry={onRetry} />;
}

/**
 * Corrections you have made (GET /api/v1/corrections).
 *
 * Every fix a user makes to an extracted field is stored as an
 * append-only audit event, but until now that history was only visible
 * one document at a time. Showing the whole list here answers "what have
 * I already corrected, and why?" — the question that decides whether a
 * disagreement between documents is new or already dealt with.
 */
function CorrectionHistorySection({ corrections }: { corrections: CorrectionEvent[] }) {
  const [showAll, setShowAll] = useState(false);
  const ordered = [...corrections].sort((a, b) =>
    String(b.created_at || "").localeCompare(String(a.created_at || "")),
  );
  const visible = showAll ? ordered : ordered.slice(0, 5);

  const describeValue = (value: unknown): string => {
    if (value === null || value === undefined || value === "") return "(empty)";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  };
  const describeField = (path: string): string =>
    path
      .replace(/\[(\d+)\]/g, (_match, index) => ` #${Number(index) + 1}`)
      .replace(/[._]/g, " ")
      .trim();

  return (
    <section
      aria-labelledby="correction-history-title"
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="correction-history-title" className="card-title">
            Corrections you have made
          </h2>
          <p className="secondary-text mt-1">
            Every fix is kept with the reason you gave. The original document is never changed.
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1.5 text-sm font-semibold text-slate-700">
          {ordered.length} correction{ordered.length === 1 ? "" : "s"}
        </span>
      </div>

      {ordered.length === 0 ? (
        <p className="mt-4 text-base text-slate-600">
          You have not corrected anything yet. If MediMind reads a value wrongly, open the document
          and use <span className="font-semibold">Correct this</span> — your change is recorded
          here.
        </p>
      ) : (
        <>
          <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-left text-base">
              <caption className="sr-only">History of field corrections</caption>
              <thead className="bg-slate-50 text-sm uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    What you changed
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Was
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Now
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Why / when
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {visible.map((event) => (
                  <tr key={event.id} className="align-top hover:bg-slate-50">
                    <th scope="row" className="px-4 py-3 text-left font-medium text-slate-800">
                      {describeField(event.field_path)}
                    </th>
                    <td className="px-4 py-3 text-slate-600 line-through decoration-slate-400">
                      {describeValue(event.previous_value)}
                    </td>
                    <td className="px-4 py-3 font-semibold text-slate-900">
                      {describeValue(event.corrected_value)}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      <p>{event.reason}</p>
                      <p className="text-sm text-slate-500">{formatDate(event.created_at)}</p>
                      <Link
                        to={`/documents?document=${encodeURIComponent(event.document_id)}`}
                        className="text-sm font-semibold text-brand-700 hover:underline"
                      >
                        Open the document
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {ordered.length > 5 && (
            <button
              type="button"
              onClick={() => setShowAll((value) => !value)}
              className="btn-secondary mt-3"
              aria-expanded={showAll}
            >
              {showAll ? "Show only the latest 5" : `Show all ${ordered.length} corrections`}
            </button>
          )}
        </>
      )}
    </section>
  );
}
