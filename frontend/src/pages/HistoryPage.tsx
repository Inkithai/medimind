import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { TimelineView } from "../components/TimelineView";
import { ClinicalEventsTimeline } from "../components/ClinicalEventsTimeline";
import { DocumentViewer } from "../components/DocumentViewer";
import { UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import { documentTypeLabel, formatDate } from "../utils/format";
import type { Timeline, Visit } from "../types/api";
import type { EmbeddedPageProps } from "../components/TabBar";

export function HistoryPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t, formatNumber } = useI18n();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Visit | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getTimeline(credentials);
      setTimeline(data);
    } catch (err) {
      setTimeline(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  // Group visits by year for the bespoke history view
  const grouped = (() => {
    if (!timeline) return [];
    const map = new Map<string, Visit[]>();
    for (const v of timeline.visits) {
      // Try to extract year from date string
      let year = t("common.unknownYear");
      if (v.date) {
        const m = /(\d{4})/.exec(v.date);
        if (m) year = m[1];
        else {
          const d = new Date(v.date);
          if (!isNaN(d.getTime())) year = String(d.getFullYear());
        }
      }
      if (!map.has(year)) map.set(year, []);
      map.get(year)!.push(v);
    }
    // sort years desc, unknown last
    return (
      Array.from(map.entries())
        .sort((a, b) => {
          if (a[0] === t("common.unknownYear")) return 1;
          if (b[0] === t("common.unknownYear")) return -1;
          return parseInt(b[0], 10) - parseInt(a[0], 10);
        })
        // Keep backend chronological order (oldest first). localeCompare on
        // mixed formats ("5 Jan 2026" vs "20 Apr 2026") is not chronological.
        .map(([year, visits]) => ({
          year,
          visits,
        }))
    );
  })();

  return (
    <div className="space-y-6">
      {!embedded && (
        <div>
          <h1 className="page-title">{t("history.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("history.subtitle")}</p>
        </div>
      )}

      {loading && <LoadingState label={t("history.loading")} />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && timeline && (
        <>
          {timeline.visits.length === 0 ? (
            <Card>
              <CardBody className="py-12 text-center">
                <p className="text-sm font-semibold text-slate-800">
                  {timeline.trust_summary?.unresolved_conflicts
                    ? "History withheld pending source review"
                    : t("history.empty")}
                </p>
                <p className="mt-1 text-xs text-slate-600">
                  {timeline.trust_summary?.unresolved_conflicts
                    ? "Conflicting records are available for review but are not shown as settled history."
                    : t("history.emptyBody")}
                </p>
                <Link
                  to={
                    timeline.trust_summary?.unresolved_conflicts
                      ? "/record-integrity?tab=conflicts"
                      : "/upload"
                  }
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
                >
                  <UploadIcon className="h-4 w-4" />
                  {timeline.trust_summary?.unresolved_conflicts ? "Review sources" : "Upload"}
                </Link>
              </CardBody>
            </Card>
          ) : (
            <div className="space-y-6">
              <ClinicalEventsTimeline timeline={timeline} />
              <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="space-y-8">
                  {grouped.map((g) => (
                    <div key={g.year}>
                      <div className="flex items-center gap-3">
                        <div className="flex h-8 w-12 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
                          {g.year}
                        </div>
                        <div className="h-px flex-1 bg-slate-200" />
                        <span className="text-xs text-slate-600">
                          {t("history.events", { count: formatNumber(g.visits.length) })}
                        </span>
                      </div>

                      <div className="mt-4 space-y-4 border-l-2 border-slate-100 pl-6">
                        {g.visits.map((visit, idx) => (
                          <button
                            key={`${visit._source.file}-${idx}`}
                            type="button"
                            onClick={() => setSelected(visit)}
                            aria-pressed={selected === visit}
                            aria-label={`${formatDate(visit.date)} — ${documentTypeLabel(visit.document_type)} — ${visit._source.file}`}
                            className="group relative w-full rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-brand-200 hover:shadow"
                          >
                            <span className="absolute -left-[29px] top-5 flex h-4 w-4 items-center justify-center rounded-full bg-brand-600 ring-4 ring-white">
                              <span className="h-1.5 w-1.5 rounded-full bg-white" />
                            </span>
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <p className="text-sm font-semibold text-slate-900">
                                  {formatDate(visit.date)} — {iconForDoc(visit.document_type)}{" "}
                                  {documentTypeLabel(visit.document_type)}
                                </p>
                                {visit.provider_or_doctor && (
                                  <p className="text-xs text-slate-500">
                                    {visit.provider_or_doctor}
                                  </p>
                                )}
                                <p className="mt-1 line-clamp-2 text-xs text-slate-600">
                                  {visitSummary(visit)}
                                </p>
                              </div>
                              <span
                                className="max-w-full shrink-0 truncate rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-500 ring-1 ring-slate-200 sm:max-w-[45%]"
                                title={visit._source.file}
                              >
                                {visit._source.file}
                              </span>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}

                  <div className="pt-4">
                    <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                      {t("history.full")}
                    </h2>
                    <div className="mt-3">
                      <TimelineView timeline={timeline} />
                    </div>
                  </div>
                </div>

                <div className="lg:sticky lg:top-6">
                  {selected ? (
                    <DocumentViewer visit={selected} onClose={() => setSelected(null)} />
                  ) : (
                    <Card>
                      <CardBody className="py-12 text-center">
                        <h2 className="text-sm font-medium text-slate-800">
                          {t("history.select")}
                        </h2>
                        <p className="mx-auto mt-1 max-w-sm text-xs text-slate-600">
                          {t("history.selectBody")}
                        </p>
                      </CardBody>
                    </Card>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function visitSummary(visit: Visit): string {
  if (visit.clinical_notes) return visit.clinical_notes;
  if (visit.diagnoses?.length)
    return `Diagnoses: ${visit.diagnoses.map((item) => item.name).join(", ")}`;
  if (visit.procedures?.length)
    return `Procedures: ${visit.procedures.map((item) => item.name).join(", ")}`;
  if (visit.imaging_results?.length)
    return `Imaging: ${visit.imaging_results.map((item) => item.study_type).join(", ")}`;
  if (visit.symptoms?.length)
    return `Symptoms: ${visit.symptoms.map((item) => item.name).join(", ")}`;
  if (visit.vital_signs?.length)
    return `Vitals: ${visit.vital_signs.map((item) => `${item.name} ${item.value}`).join(", ")}`;
  if (visit.medications.length) return visit.medications.map((item) => item.name).join(", ");
  if (visit.lab_results.length) return visit.lab_results.map((item) => item.test_name).join(", ");
  return "No extracted summary";
}

function iconForDoc(type: string) {
  switch (type) {
    case "prescription":
      return "💊";
    case "lab_report":
      return "🧪";
    case "discharge_summary":
      return "🏥";
    case "imaging_report":
      return "🩻";
    case "procedure_report":
      return "🩺";
    case "consultation_note":
      return "📋";
    default:
      return "📄";
  }
}
