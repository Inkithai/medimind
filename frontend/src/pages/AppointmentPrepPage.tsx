import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { AppointmentIcon, CheckIcon, FileIcon, PrintIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { AppointmentEvidence, AppointmentPrepReport, AppointmentPriority } from "../types/api";
import { formatDate } from "../utils/format";
import type { EmbeddedPageProps } from "../components/TabBar";

export function AppointmentPrepPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const [report, setReport] = useState<AppointmentPrepReport | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await api.getAppointmentPrep(credentials));
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

  const importantCount =
    report?.priorities.filter((item) => item.level === "important").length || 0;

  return (
    <div className="space-y-6 appointment-prep-page">
      <header className="flex flex-wrap items-start justify-between gap-4 print:mb-6">
        {embedded ? (
          <p className="secondary-text max-w-2xl">
            A focused clinician handoff and question list built from your records—with evidence
            attached.
          </p>
        ) : (
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
              <AppointmentIcon className="h-4 w-4" /> Visit preparation
            </div>
            <h1 className="page-title mt-1">Prepare for My Appointment</h1>
            <p className="secondary-text mt-2 max-w-2xl">
              A focused clinician handoff and question list built from your records—with evidence
              attached.
            </p>
          </div>
        )}
        <button
          type="button"
          onClick={() => window.print()}
          disabled={!report}
          className="btn-primary print:hidden"
        >
          <PrintIcon className="h-5 w-5" /> Print or save PDF
        </button>
      </header>

      {loading && (
        <LoadingState
          label="Preparing your appointment packet"
          description="Prioritizing record-backed questions and assembling a concise handoff."
        />
      )}
      {!loading && error !== null && <PrepError error={error} onRetry={() => void load()} />}

      {!loading && report && (
        <>
          <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm print:shadow-none">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50/70 px-6 py-4">
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
                  Clinician handoff
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {report.handoff.record_count} records ·{" "}
                  {formatDate(report.handoff.record_period.from)} to{" "}
                  {formatDate(report.handoff.record_period.to)}
                </p>
              </div>
              {importantCount > 0 && (
                <span className="rounded-full bg-amber-100 px-3 py-1.5 text-xs font-bold text-amber-800">
                  {importantCount} priority {importantCount === 1 ? "item" : "items"}
                </span>
              )}
            </div>

            <div className="grid gap-6 p-6 lg:grid-cols-2">
              <HandoffSection title="Key points to review">
                {report.handoff.key_findings.length ? (
                  <ul className="space-y-2.5">
                    {report.handoff.key_findings.map((finding, index) => (
                      <li key={index} className="flex items-start gap-2.5 text-sm text-slate-700">
                        <span
                          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${finding.level === "important" ? "bg-amber-500" : "bg-sky-500"}`}
                        />
                        <span>{finding.text}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-slate-500">No prioritized findings available.</p>
                )}
              </HandoffSection>

              <HandoffSection title="Known allergies">
                {report.handoff.known_allergies.length ? (
                  <div className="flex flex-wrap gap-2">
                    {report.handoff.known_allergies.map((allergy) => (
                      <span
                        key={allergy}
                        className="rounded-full bg-red-50 px-3 py-1.5 text-sm font-semibold text-red-800 ring-1 ring-red-200"
                      >
                        {allergy}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    No allergies were extracted from the uploaded records.
                  </p>
                )}
              </HandoffSection>

              <HandoffSection title="Latest documented medication list" wide>
                {report.handoff.latest_medication_record && (
                  <p className="mb-3 text-xs text-slate-500">
                    From {report.handoff.latest_medication_record.source_file || "record"} ·{" "}
                    {formatDate(report.handoff.latest_medication_record.date)}
                  </p>
                )}
                {report.handoff.latest_documented_medications.length ? (
                  <div className="overflow-hidden rounded-xl border border-slate-200">
                    <table className="w-full text-left text-sm">
                      <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                        <tr>
                          <th className="px-4 py-2.5">Medication</th>
                          <th className="px-4 py-2.5">Dose</th>
                          <th className="px-4 py-2.5">Frequency</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {report.handoff.latest_documented_medications.map((med, index) => (
                          <tr key={`${med.name}-${index}`}>
                            <td className="px-4 py-3 font-semibold text-slate-800">{med.name}</td>
                            <td className="px-4 py-3 text-slate-600">
                              {med.dosage || "Not extracted"}
                            </td>
                            <td className="px-4 py-3 text-slate-600">
                              {med.frequency || "Not extracted"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">
                    No medications were extracted from the uploaded records.
                  </p>
                )}
                <p className="mt-3 text-xs leading-relaxed text-amber-700">
                  This is not labeled “current medications.” Verify it against what you actually
                  take and bring packaging when possible.
                </p>
              </HandoffSection>

              {report.handoff.providers_documented.length > 0 && (
                <HandoffSection title="Providers named in records" wide>
                  <p className="text-sm text-slate-700">
                    {report.handoff.providers_documented.join(" · ")}
                  </p>
                </HandoffSection>
              )}
            </div>
          </section>

          <section>
            <div className="mb-4">
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-brand-700">
                Suggested agenda
              </p>
              <h2 className="section-title mt-1">Questions for your clinician</h2>
              <p className="secondary-text mt-1">
                Start with the first three if appointment time is limited.
              </p>
            </div>
            <div className="space-y-4">
              {report.priorities.map((priority, index) => (
                <PriorityCard key={priority.id} priority={priority} number={index + 1} />
              ))}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm print:break-before-page print:shadow-none">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                <CheckIcon className="h-5 w-5" />
              </div>
              <div>
                <h2 className="card-title">Before you go</h2>
                <p className="text-sm text-slate-500">A practical checklist for the visit.</p>
              </div>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              {report.checklist.map((item) => {
                const done = checked.has(item.id);
                return (
                  <label
                    key={item.id}
                    className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition print:border-slate-300 ${done ? "border-emerald-200 bg-emerald-50" : "border-slate-200 hover:bg-slate-50"}`}
                  >
                    <input
                      type="checkbox"
                      checked={done}
                      onChange={() =>
                        setChecked((previous) => {
                          const next = new Set(previous);
                          if (next.has(item.id)) next.delete(item.id);
                          else next.add(item.id);
                          return next;
                        })
                      }
                      className="mt-0.5 h-5 w-5 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span
                      className={`text-sm leading-relaxed ${done ? "text-emerald-900" : "text-slate-700"}`}
                    >
                      {item.text}
                    </span>
                  </label>
                );
              })}
            </div>
          </section>

          <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-5 text-sm leading-relaxed text-sky-900 print:border-slate-300 print:bg-white print:text-slate-700">
            <p className="font-semibold">Record-grounded, not a diagnosis</p>
            <p className="mt-1">
              {report.method} {report.note}
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function HandoffSection({
  title,
  children,
  wide = false,
}: {
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "lg:col-span-2" : ""}>
      <h2 className="mb-3 text-sm font-bold text-slate-900">{title}</h2>
      {children}
    </div>
  );
}

function PriorityCard({ priority, number }: { priority: AppointmentPriority; number: number }) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const style = priorityStyle(priority.level);
  return (
    <article
      className={`overflow-hidden rounded-2xl border bg-white shadow-sm print:break-inside-avoid print:shadow-none ${style.border}`}
    >
      <div className="p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ${style.number}`}
          >
            {number}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${style.badge}`}
              >
                {priority.level}
              </span>
              <span className="text-xs font-medium text-slate-400">{priority.category}</span>
            </div>
            <h3 className="mt-2 text-base font-bold text-slate-900">{priority.title}</h3>
            <blockquote className="mt-3 rounded-xl border-l-4 border-brand-400 bg-brand-50/60 px-4 py-3 text-base font-medium leading-relaxed text-slate-800">
              “{priority.question}”
            </blockquote>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">{priority.rationale}</p>
          </div>
        </div>
      </div>
      {priority.evidence.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/70 px-5 py-3 text-xs text-slate-500 print:bg-white">
          <button
            type="button"
            onClick={() => setEvidenceOpen((value) => !value)}
            className="flex items-center gap-1.5 font-semibold text-brand-700 print:hidden"
          >
            <FileIcon className="h-3.5 w-3.5" /> {evidenceOpen ? "Hide" : "Show"} source evidence (
            {priority.evidence.length})
          </button>
          <div
            className={`${evidenceOpen ? "mt-2 flex" : "hidden"} flex-wrap gap-x-4 gap-y-1 print:mt-0 print:flex`}
          >
            <span className="hidden font-semibold text-slate-600 print:inline">Evidence:</span>
            {priority.evidence.map((source, index) => (
              <EvidenceLink source={source} key={index} />
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

function EvidenceLink({ source }: { source: AppointmentEvidence }) {
  const label = source.source_file || formatDate(source.date);
  if (source.document_url)
    return (
      <a
        href={source.document_url}
        target="_blank"
        rel="noreferrer"
        className="text-brand-700 underline decoration-brand-300 underline-offset-2"
      >
        {label}
      </a>
    );
  return <span>{label}</span>;
}

function PrepError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404) {
    return (
      <Card>
        <CardBody className="py-14 text-center">
          <AppointmentIcon className="mx-auto h-10 w-10 text-brand-600" />
          <h2 className="mt-4 section-title">Upload records before preparing a visit</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
            MediMind needs your medical records to create a grounded handoff and question list.
          </p>
          <Link to="/upload" className="btn-primary mt-5">
            <UploadIcon className="h-5 w-5" /> Upload records
          </Link>
        </CardBody>
      </Card>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}

function priorityStyle(level: AppointmentPriority["level"]) {
  if (level === "important")
    return {
      border: "border-amber-200",
      badge: "bg-amber-100 text-amber-800",
      number: "bg-amber-500 text-white",
    };
  if (level === "review")
    return {
      border: "border-sky-200",
      badge: "bg-sky-100 text-sky-800",
      number: "bg-sky-600 text-white",
    };
  return {
    border: "border-slate-200",
    badge: "bg-slate-100 text-slate-700",
    number: "bg-slate-700 text-white",
  };
}
