import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ConsiderProfessionalCare } from "../components/ConsiderProfessionalCare";
import { CrossCheckView } from "../components/CrossCheckView";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody } from "../components/Card";
import { LoadingState } from "../components/Spinner";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { CrossCheckReport, DosageReport } from "../types/api";
import { collectSafetyAlerts } from "../utils/safety";

export function CrossCheckPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [report, setReport] = useState<CrossCheckReport | null>(null);
  const [dosageReport, setDosageReport] = useState<DosageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [reanalyzing, setReanalyzing] = useState(false);
  const [reanalyzeNotice, setReanalyzeNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getMedicationSafety(credentials);
      setReport(data);
      setDosageReport(data.dosage_report ?? (await api.getDosageReport(credentials)));
    } catch (err) {
      setReport(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load, reloadKey]);

  return (
    <div className="space-y-6">
      <div className="flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row">
        <div className="min-w-0">
          <h1 className="page-title">{t("safety.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("safety.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={reanalyzing}
            onClick={async () => {
              setReanalyzing(true);
              setReanalyzeNotice(null);
              setError(null);
              try {
                const result = await api.reanalyzeMedicationSafety(credentials);
                setReport(result.cross_check_report);
                setDosageReport(result.dosage_report);
                window.dispatchEvent(
                  new CustomEvent("medimind:safety-updated", {
                    detail: {
                      count: collectSafetyAlerts(result.cross_check_report, result.dosage_report)
                        .length,
                    },
                  }),
                );
                setReanalyzeNotice(
                  result.resolved_count > 0
                    ? `Safety analysis updated. ${result.resolved_count} previous finding(s) resolved.`
                    : `Safety analysis is current (${result.findings_after} finding(s)).`,
                );
              } catch (err) {
                setError(err);
              } finally {
                setReanalyzing(false);
              }
            }}
            className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
          >
            <RefreshIcon className="h-4 w-4" />
            {reanalyzing ? "Running full safety check…" : "Run full safety check"}
          </button>
          <button
            type="button"
            onClick={() => setReloadKey((k) => k + 1)}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <RefreshIcon className="h-4 w-4" />
            {t("common.refresh")}
          </button>
        </div>
      </div>

      {reanalyzeNotice && (
        <div
          role="status"
          className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900"
        >
          {reanalyzeNotice}
        </div>
      )}

      {loading && <LoadingState label={t("safety.loading")} />}

      {!loading && error !== null && (
        <NotFoundOrError error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && report && (
        <>
          <CrossCheckView report={report} dosageReport={dosageReport} />
          <MedicalDisclaimer medication />
          {hasSafetyIssues(report) && <ConsiderProfessionalCare />}
        </>
      )}
    </div>
  );
}

function hasSafetyIssues(report: CrossCheckReport): boolean {
  return (
    report.potential_drug_interactions.length > 0 ||
    report.duplicate_prescriptions.length > 0 ||
    report.conflicting_dosage_instructions.length > 0 ||
    report.allergy_conflicts.length > 0
  );
}

function NotFoundOrError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useI18n();
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404) {
    return (
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="text-base font-semibold text-slate-700">{t("safety.noIssues")}</p>
            <p className="max-w-md text-sm text-slate-500">
              Upload at least one document and we'll check your medicines for you.
            </p>
            <Link
              to="/upload"
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            >
              <UploadIcon className="h-4 w-4" />
              Upload a document
            </Link>
          </div>
        </CardBody>
      </Card>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
