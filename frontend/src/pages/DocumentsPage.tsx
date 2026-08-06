import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { DocumentViewer } from "../components/DocumentViewer";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { FileIcon, LinkIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type { Timeline, Visit } from "../types/api";
import { documentTypeLabel, formatDate } from "../utils/format";

export function DocumentsPage() {
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

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Medical Records</h1>
          <p className="secondary-text mt-2">
            Every document you've uploaded — and what we found inside each one.
          </p>
        </div>
        <Link to="/upload" className="btn-primary">
          <UploadIcon className="h-5 w-5" /> Upload
        </Link>
      </div>

      {loading && <LoadingState label="Loading documents" />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && timeline && (
        <>
          {timeline.visits.length === 0 ? (
            <Card>
              <CardBody>
                <div className="py-12 text-center">
                  <p className="text-sm font-semibold text-slate-700">No documents yet</p>
                  <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
                    Upload your first prescription, lab report, or discharge summary to build your MediMind record.
                  </p>
                  <Link
                    to="/upload"
                    className="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-700"
                  >
                    <UploadIcon className="h-4 w-4" /> Upload documents
                  </Link>
                </div>
              </CardBody>
            </Card>
          ) : (
            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {timeline.visits.length} document(s)
                  </p>
                  <p className="text-xs text-slate-400">Click a file to view it</p>
                </div>

                <div className="space-y-2">
                  {timeline.visits.map((visit, idx) => {
                    const isSelected = selected?._source.file === visit._source.file && selected?.date === visit.date;
                    return (
                      <button
                        key={`${visit._source.file}-${idx}`}
                        onClick={() => setSelected(visit)}
                        className={`w-full rounded-xl border bg-white px-4 py-3 text-left shadow-sm transition hover:shadow ${
                          isSelected ? "border-brand-300 ring-2 ring-brand-100" : "border-slate-200"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-50 text-slate-500">
                              <FileIcon className="h-5 w-5" />
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-slate-900">{visit._source.file}</p>
                              <p className="flex items-center gap-1.5 text-xs text-slate-500">
                                <StatusBadge tone="brand">{documentTypeLabel(visit.document_type)}</StatusBadge>
                                {formatDate(visit.date)} • {visit._source.method === "text_layer" ? "Digital PDF" : "Scanned or photo"}
                              </p>
                            </div>
                          </div>
                          {visit.document_url && (
                            <span className="inline-flex items-center gap-1 text-xs text-brand-600">
                              <LinkIcon className="h-3.5 w-3.5" /> source
                            </span>
                          )}
                        </div>

                        <div className="mt-2 flex gap-1.5">
                          {visit.medications.length > 0 && (
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                              {visit.medications.length} meds
                            </span>
                          )}
                          {visit.lab_results.length > 0 && (
                            <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700 ring-1 ring-sky-200">
                              {visit.lab_results.length} labs
                            </span>
                          )}
                          {visit.allergies_noted.length > 0 && (
                            <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] text-red-700 ring-1 ring-red-200">
                              {visit.allergies_noted.join(", ")}
                            </span>
                          )}
                        </div>

                        {visit.provider_or_doctor && (
                          <p className="mt-1 truncate text-xs text-slate-400">{visit.provider_or_doctor}</p>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="lg:sticky lg:top-6">
                {selected ? (
                  <DocumentViewer visit={selected} onClose={() => setSelected(null)} />
                ) : (
                  <Card>
                    <CardBody className="py-16 text-center">
                      <p className="text-base font-medium text-slate-700">Select a document</p>
                      <p className="secondary-text mx-auto mt-1 max-w-sm">
                        Choose a file on the left to see the original and everything we found inside it.
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
