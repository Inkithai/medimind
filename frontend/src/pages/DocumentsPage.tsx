import { useCallback, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
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
  const [documentAction, setDocumentAction] = useState<{
    id: string;
    kind: "reprocess" | "delete";
  } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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
      // 404 = no record yet (fresh workspace or snapshot still building) — the
      // API's documented first-run contract. Show the page's normal empty
      // state instead of a hard error, exactly like the Dashboard and Labs
      // pages do for the same response.
      if (err instanceof ApiError && err.status === 404) {
        setTimeline({
          visits: [],
          documents: [],
          medications_timeline: [],
          lab_results_timeline: [],
          known_allergies: [],
        });
      } else {
        setTimeline(null);
        setError(err);
      }
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
                <strong>{timeline.trust_summary?.unresolved_conflicts || 0}</strong> unresolved
                conflict(s); quarantined or non-authoritative evidence is excluded from answers and
                analytics.
              </span>
              <Link to="/review" className="font-semibold text-amber-900 underline">
                Review conflicts
              </Link>
            </div>
          )}
          {documentVisits.length === 0 ? (
            <Card>
              <CardBody>
                <div className="py-12 text-center">
                  <h2 className="text-sm font-semibold text-slate-800">
                    {t("documentsPage.emptyTitle")}
                  </h2>
                  <p className="mx-auto mt-1 max-w-md text-sm text-slate-600">
                    {t("documentsPage.emptyBody")}
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
                    {formatNumber(documentVisits.length)} {t("common.documents")}
                  </p>
                  <p className="text-xs text-slate-600">{t("documentsPage.clickFile")}</p>
                </div>

                {actionError && (
                  <div
                    role="alert"
                    className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
                  >
                    Document action failed: {actionError}
                  </div>
                )}
                <div className="space-y-2">
                  {documentVisits.map((visit, idx) => {
                    const isSelected = selected?._document_id === visit._document_id;
                    const clinicalCount =
                      (visit.diagnoses?.length || 0) +
                      (visit.symptoms?.length || 0) +
                      (visit.procedures?.length || 0) +
                      (visit.vital_signs?.length || 0) +
                      (visit.imaging_results?.length || 0);
                    return (
                      <div
                        key={`${visit._source.file}-${idx}`}
                        className={`overflow-hidden rounded-xl border bg-white shadow-sm transition hover:shadow ${
                          isSelected ? "border-brand-300 ring-2 ring-brand-100" : "border-slate-200"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => setSelected(visit)}
                          aria-pressed={isSelected}
                          aria-label={`${visit._source.file} — ${documentTypeLabel(visit.document_type)} — ${formatDate(visit.date)}`}
                          className="w-full px-4 py-3 text-left"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-50 text-slate-500">
                                <FileIcon className="h-5 w-5" />
                              </div>
                              <div className="min-w-0">
                                <p className="truncate text-sm font-semibold text-slate-900">
                                  {visit._source.file}
                                </p>
                                <p className="flex items-center gap-1.5 text-xs text-slate-500">
                                  <StatusBadge tone="brand">
                                    {documentTypeLabel(visit.document_type)}
                                  </StatusBadge>
                                  {visit._trust?.quarantined && (
                                    <StatusBadge tone="danger">quarantined</StatusBadge>
                                  )}
                                  {visit._corrections?.paths.length ? (
                                    <StatusBadge tone="success">corrected</StatusBadge>
                                  ) : null}
                                  {formatDate(visit.date)} •{" "}
                                  {visit._source.method === "text_layer"
                                    ? "Digital PDF"
                                    : "Scanned or photo"}
                                </p>
                              </div>
                            </div>
                            {(visit.document_url || visit.storage_path) && (
                              <span className="inline-flex items-center gap-1 text-xs text-brand-600">
                                <LinkIcon className="h-3.5 w-3.5" /> source
                              </span>
                            )}
                          </div>

                          <div className="mt-2 flex flex-wrap gap-1.5">
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
                            {clinicalCount > 0 && (
                              <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] text-indigo-700 ring-1 ring-indigo-200">
                                {clinicalCount} clinical events
                              </span>
                            )}
                            {visit.allergies_noted.length > 0 && (
                              <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] text-red-700 ring-1 ring-red-200">
                                {visit.allergies_noted.join(", ")}
                              </span>
                            )}
                          </div>

                          {visit.provider_or_doctor && (
                            <p className="mt-1 truncate text-xs text-slate-400">
                              {visit.provider_or_doctor}
                            </p>
                          )}
                        </button>
                        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 bg-slate-50/70 px-3 py-2">
                          <button
                            type="button"
                            onClick={() => setSelected(visit)}
                            className="rounded-md px-2.5 py-1.5 text-xs font-semibold text-brand-700 hover:bg-brand-50"
                          >
                            View & correct
                          </button>
                          <button
                            type="button"
                            disabled={documentAction !== null}
                            onClick={async () => {
                              setDocumentAction({ id: visit._document_id, kind: "reprocess" });
                              setActionError(null);
                              try {
                                await api.reprocessDocument(credentials, visit._document_id);
                                await load();
                              } catch (err) {
                                setActionError(err instanceof Error ? err.message : String(err));
                              } finally {
                                setDocumentAction(null);
                              }
                            }}
                            className="rounded-md px-2.5 py-1.5 text-xs font-semibold text-slate-700 hover:bg-white disabled:opacity-50"
                          >
                            {documentAction?.id === visit._document_id &&
                            documentAction.kind === "reprocess"
                              ? "Reprocessing…"
                              : "Reprocess"}
                          </button>
                          <button
                            type="button"
                            disabled={documentAction !== null}
                            onClick={async () => {
                              if (
                                !window.confirm(
                                  `Permanently delete “${visit._source.file}”? Its facts will be removed and all safety checks rebuilt.`,
                                )
                              )
                                return;
                              setDocumentAction({ id: visit._document_id, kind: "delete" });
                              setActionError(null);
                              try {
                                await api.deleteDocument(credentials, visit._document_id);
                                if (selected?._document_id === visit._document_id)
                                  setSelected(null);
                                await load();
                              } catch (err) {
                                setActionError(err instanceof Error ? err.message : String(err));
                              } finally {
                                setDocumentAction(null);
                              }
                            }}
                            className="ml-auto rounded-md px-2.5 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-50"
                          >
                            {documentAction?.id === visit._document_id &&
                            documentAction.kind === "delete"
                              ? "Deleting…"
                              : "Delete"}
                          </button>
                        </div>
                      </div>
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
                    onReprocess={async () => {
                      await api.reprocessDocument(credentials, selected._document_id);
                      await load();
                    }}
                    onDelete={async () => {
                      await api.deleteDocument(credentials, selected._document_id);
                      setSelected(null);
                      await load();
                    }}
                    onOpenOriginal={async () => {
                      if (selected.document_url) return selected.document_url;
                      const signed = await api.getDocumentSignedUrl(
                        credentials,
                        selected._document_id,
                      );
                      return signed.url;
                    }}
                    onProcessText={async () => {
                      await api.processDocumentText(credentials, selected._document_id);
                      await load();
                    }}
                    initialEvidenceId={requestedEvidenceId}
                  />
                ) : (
                  <Card>
                    <CardBody className="py-16 text-center">
                      <h2 className="text-base font-medium text-slate-800">
                        {t("documentsPage.select")}
                      </h2>
                      <p className="secondary-text mx-auto mt-1 max-w-sm">
                        {t("documentsPage.selectBody")}
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
