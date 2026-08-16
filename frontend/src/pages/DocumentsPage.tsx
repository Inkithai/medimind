import { useCallback, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { DocumentViewer } from "../components/DocumentViewer";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { FileIcon, LinkIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { Timeline, Visit } from "../types/api";
import { documentTypeLabel, formatDate } from "../utils/format";

export function DocumentsPage() {
  const { credentials } = useAuth();
  const { t, formatNumber } = useI18n();
  const [searchParams] = useSearchParams();
  const requestedDocumentId = searchParams.get("document");
  const requestedEvidenceId = searchParams.get("evidence");
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
      setSelected((current) => {
        const documents = data.documents || data.visits;
        const targetId = requestedDocumentId || current?._document_id;
        return targetId ? documents.find((visit) => visit._document_id === targetId) || null : null;
      });
    } catch (err) {
      setTimeline(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials, requestedDocumentId]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  const documentVisits = timeline?.documents || timeline?.visits || [];

  return (
    <div className="space-y-6">
      <div className="flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row">
        <div className="min-w-0">
          <h1 className="page-title">{t("documentsPage.title")}</h1>
          <p className="secondary-text mt-2">{t("documentsPage.subtitle")}</p>
        </div>
        <Link to="/upload" className="btn-primary">
          <UploadIcon className="h-5 w-5" /> {t("upload.upload")}
        </Link>
      </div>

      {loading && <LoadingState label={t("documentsPage.loading")} />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && timeline && (
        <>
          {((timeline.trust_summary?.unresolved_conflicts || 0) > 0 ||
            (timeline.trust_summary?.quarantined_documents || 0) > 0 ||
            (timeline.trust_summary?.quarantined_facts || 0) > 0) && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <span>
                <strong>{timeline.trust_summary?.unresolved_conflicts || 0}</strong> unresolved conflict(s); quarantined or non-authoritative evidence is excluded from answers and analytics.
              </span>
              <Link to="/review" className="font-semibold text-amber-900 underline">Review conflicts</Link>
            </div>
          )}
          {documentVisits.length === 0 ? (
            <Card>
              <CardBody>
                <div className="py-12 text-center">
                  <h2 className="text-sm font-semibold text-slate-800">{t("documentsPage.emptyTitle")}</h2>
                  <p className="mx-auto mt-1 max-w-md text-sm text-slate-600">{t("documentsPage.emptyBody")}</p>
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
                    {formatNumber(documentVisits.length)} {t("common.documents")}
                  </p>
                  <p className="text-xs text-slate-600">{t("documentsPage.clickFile")}</p>
                </div>

                <div className="space-y-2">
                  {documentVisits.map((visit, idx) => {
                    const isSelected = selected?._document_id === visit._document_id;
                    return (
                      <button
                        type="button"
                        key={`${visit._source.file}-${idx}`}
                        onClick={() => setSelected(visit)}
                        aria-pressed={isSelected}
                        aria-label={`${visit._source.file} — ${documentTypeLabel(visit.document_type)} — ${formatDate(visit.date)}`}
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
                                {visit._trust?.quarantined && <StatusBadge tone="danger">quarantined</StatusBadge>}
                                {visit._corrections?.paths.length ? <StatusBadge tone="success">corrected</StatusBadge> : null}
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
                  <DocumentViewer
                    visit={selected}
                    onClose={() => setSelected(null)}
                    onUpdated={() => void load()}
                    initialEvidenceId={requestedEvidenceId}
                  />
                ) : (
                  <Card>
                    <CardBody className="py-16 text-center">
                      <h2 className="text-base font-medium text-slate-800">{t("documentsPage.select")}</h2>
                      <p className="secondary-text mx-auto mt-1 max-w-sm">{t("documentsPage.selectBody")}</p>
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
