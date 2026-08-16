import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { AlertIcon, CheckIcon, FileIcon, IntegrityIcon, RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { IntegrityEvidence, IntegrityIssue, RecordIntegrityReport } from "../types/api";
import { formatDate } from "../utils/format";

export function RecordIntegrityPage() {
  const { credentials } = useAuth();
  const [report, setReport] = useState<RecordIntegrityReport | null>(null);
  const [reviewed, setReviewed] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
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
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
            <IntegrityIcon className="h-4 w-4" /> Record integrity
          </div>
          <h1 className="page-title mt-1">Cross-check My Records</h1>
          <p className="secondary-text mt-2 max-w-2xl">
            Find facts that disagree across documents, inspect both sources, and verify them before relying on trends or answers.
          </p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading} className="btn-secondary">
          <RefreshIcon className="h-4 w-4" /> Run checks again
        </button>
      </header>

      {loading && <LoadingState label="Cross-checking structured records" description="Comparing identities, allergies, labs, and medication instructions without guessing which source is correct." />}
      {!loading && error !== null && <IntegrityError error={error} onRetry={() => void load()} />}

      {!loading && report && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Metric label="Records checked" value={report.summary.records_checked} tone="neutral" />
            <Metric label="Needs verification" value={report.summary.issues_found} tone={report.summary.issues_found ? "warning" : "success"} />
            <Metric label="Reviewed this session" value={reviewedCount} tone={reviewedCount === report.summary.issues_found ? "success" : "neutral"} />
          </div>

          {report.issues.length === 0 ? (
            <Card>
              <CardBody className="py-14 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-700"><CheckIcon className="h-7 w-7" /></div>
                <h2 className="mt-4 section-title">No structured discrepancies found</h2>
                <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
                  The checks did not find conflicting patient names, allergy statements, same-date lab results, or complete medication instructions. This does not prove every record is complete or correct.
                </p>
              </CardBody>
            </Card>
          ) : (
            <section className="space-y-4">
              <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
                <p className="font-semibold">Do not choose a value from this screen alone</p>
                <p className="mt-1 leading-relaxed">Open both original documents and use the suggested verification step. Apparent conflicts may be valid corrections, separate samples, or extraction uncertainty.</p>
              </div>
              {report.issues.map((issue) => (
                <IntegrityCard
                  key={issue.id}
                  issue={issue}
                  reviewed={reviewed.has(issue.id)}
                  onToggleReviewed={() => setReviewed((previous) => {
                    const next = new Set(previous);
                    if (next.has(issue.id)) next.delete(issue.id); else next.add(issue.id);
                    return next;
                  })}
                />
              ))}
            </section>
          )}

          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900">Checks performed</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {report.checks_performed.map((check) => (
                <span key={check} className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium capitalize text-slate-700">{check}</span>
              ))}
            </div>
            <p className="mt-4 text-xs leading-relaxed text-slate-500">{report.method} {report.note}</p>
          </section>
        </>
      )}
    </div>
  );
}

function IntegrityCard({ issue, reviewed, onToggleReviewed }: { issue: IntegrityIssue; reviewed: boolean; onToggleReviewed: () => void }) {
  const important = issue.severity === "important";
  return (
    <article className={`overflow-hidden rounded-2xl border bg-white shadow-sm transition ${reviewed ? "border-emerald-200 opacity-75" : important ? "border-amber-200" : "border-sky-200"}`}>
      <div className="p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${reviewed ? "bg-emerald-50 text-emerald-700" : important ? "bg-amber-50 text-amber-700" : "bg-sky-50 text-sky-700"}`}>
            {reviewed ? <CheckIcon className="h-5 w-5" /> : <AlertIcon className="h-5 w-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${important ? "bg-amber-100 text-amber-800" : "bg-sky-100 text-sky-800"}`}>{issue.severity === "important" ? "Verify first" : "Review"}</span>
              <span className="text-xs font-medium capitalize text-slate-400">{issue.category}</span>
              <span className="text-xs text-slate-400">· {Math.round(issue.confidence * 100)}% minimum extraction confidence</span>
            </div>
            <h2 className="mt-2 card-title">{issue.title}</h2>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{issue.explanation}</p>
          </div>
        </div>

        <div className={`mt-5 grid gap-3 ${issue.variants.length === 2 ? "md:grid-cols-2" : "md:grid-cols-3"}`}>
          {issue.variants.map((variant, index) => (
            <div key={`${variant.label}-${index}`} className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-slate-400">Source says</p>
              <p className="mt-1 text-sm font-semibold text-slate-900">{variant.value}</p>
              <p className="mt-1 text-xs text-slate-500">{variant.label}</p>
              <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-slate-200 pt-2 text-xs">
                {variant.evidence.map((source, evidenceIndex) => <Evidence source={source} key={evidenceIndex} />)}
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
        <span className="text-xs text-slate-500">This check does not automatically alter your record.</span>
        <label className="flex cursor-pointer items-center gap-2 text-sm font-semibold text-slate-700">
          <input type="checkbox" checked={reviewed} onChange={onToggleReviewed} className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
          Reviewed
        </label>
      </div>
    </article>
  );
}

function Evidence({ source }: { source: IntegrityEvidence }) {
  const label = source.source_file || formatDate(source.date);
  if (source.document_url) return <a href={source.document_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand-700 underline decoration-brand-300 underline-offset-2"><FileIcon className="h-3 w-3" />{label}</a>;
  return <span className="inline-flex items-center gap-1 text-slate-600"><FileIcon className="h-3 w-3" />{label}</span>;
}

function Metric({ label, value, tone }: { label: string; value: number; tone: "neutral" | "warning" | "success" }) {
  const color = tone === "warning" ? "text-amber-700 border-amber-200" : tone === "success" ? "text-emerald-700 border-emerald-200" : "text-slate-900 border-slate-200";
  return <div className={`rounded-2xl border bg-white p-5 shadow-sm ${color}`}><p className="text-sm font-medium text-slate-500">{label}</p><p className="mt-1 text-3xl font-bold">{value}</p></div>;
}

function IntegrityError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = error && typeof error === "object" && "status" in error ? (error as { status?: number }).status : undefined;
  if (status === 404) return (
    <Card><CardBody className="py-14 text-center"><IntegrityIcon className="mx-auto h-10 w-10 text-brand-600" /><h2 className="mt-4 section-title">No records to cross-check</h2><p className="mx-auto mt-2 max-w-md text-sm text-slate-500">Upload records before running integrity checks.</p><Link to="/upload" className="btn-primary mt-5"><UploadIcon className="h-5 w-5" /> Upload records</Link></CardBody></Card>
  );
  return <ErrorState error={error} onRetry={onRetry} />;
}
