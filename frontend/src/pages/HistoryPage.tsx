import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { TimelineView } from "../components/TimelineView";
import { DocumentViewer } from "../components/DocumentViewer";
import { UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { Timeline, Visit } from "../types/api";

export function HistoryPage() {
  const { credentials } = useAuth();
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
      let year = "Unknown year";
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
    return Array.from(map.entries())
      .sort((a, b) => {
        if (a[0] === "Unknown year") return 1;
        if (b[0] === "Unknown year") return -1;
        return parseInt(b[0], 10) - parseInt(a[0], 10);
      })
      // Keep backend chronological order (oldest first). localeCompare on
      // mixed formats ("5 Jan 2026" vs "20 Apr 2026") is not chronological.
      .map(([year, visits]) => ({
        year,
        visits,
      }));
  })();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">Timeline</h1>
        <p className="secondary-text mt-2 max-w-2xl">
          Your medical history in date order — built automatically from your uploaded documents. Nothing to
          type in.
        </p>
      </div>

      {loading && <LoadingState label="Loading history" />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && timeline && (
        <>
          {timeline.visits.length === 0 ? (
            <Card>
              <CardBody className="py-12 text-center">
                <p className="text-sm font-semibold text-slate-700">No history yet</p>
                <p className="mt-1 text-xs text-slate-500">
                  Upload documents to see them organized along a timeline.
                </p>
                <Link
                  to="/upload"
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
                >
                  <UploadIcon className="h-4 w-4" /> Upload
                </Link>
              </CardBody>
            </Card>
          ) : (
            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="space-y-8">
                {grouped.map((g) => (
                  <div key={g.year}>
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-12 items-center justify-center rounded-full bg-slate-900 text-xs font-bold text-white">
                        {g.year}
                      </div>
                      <div className="h-px flex-1 bg-slate-200" />
                      <span className="text-xs text-slate-500">{g.visits.length} events</span>
                    </div>

                    <div className="mt-4 space-y-4 border-l-2 border-slate-100 pl-6">
                      {g.visits.map((visit, idx) => (
                        <button
                          key={`${visit._source.file}-${idx}`}
                          onClick={() => setSelected(visit)}
                          className="group relative w-full rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm hover:border-brand-200 hover:shadow"
                        >
                          <span className="absolute -left-[29px] top-5 flex h-4 w-4 items-center justify-center rounded-full bg-brand-600 ring-4 ring-white">
                            <span className="h-1.5 w-1.5 rounded-full bg-white" />
                          </span>
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <p className="text-sm font-semibold text-slate-900">
                                {visit.date || "Undated"} — {iconForDoc(visit.document_type)} {visit.document_type.replace("_", " ")}
                              </p>
                              {visit.provider_or_doctor && (
                                <p className="text-xs text-slate-500">{visit.provider_or_doctor}</p>
                              )}
                              <p className="mt-1 line-clamp-2 text-xs text-slate-600">
                                {visit.clinical_notes ||
                                  (visit.medications.length
                                    ? visit.medications.map((m) => m.name).join(", ")
                                    : visit.lab_results.length
                                    ? visit.lab_results.map((l) => l.test_name).join(", ")
                                    : "No extracted summary")}
                              </p>
                            </div>
                            <span className="rounded-full bg-slate-50 px-2 py-0.5 text-[11px] text-slate-500 ring-1 ring-slate-200">
                              {visit._source.file}
                            </span>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}

                <div className="pt-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Full structured timeline</p>
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
                      <p className="text-sm font-medium text-slate-700">Select an event</p>
                      <p className="mx-auto mt-1 max-w-sm text-xs text-slate-500">
                        Click any history item to see its full structured extraction and original document.
                      </p>
                    </CardBody>
                  </Card>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function iconForDoc(type: string) {
  switch (type) {
    case "prescription":
      return "💊";
    case "lab_report":
      return "🧪";
    case "discharge_summary":
      return "🏥";
    default:
      return "📄";
  }
}
