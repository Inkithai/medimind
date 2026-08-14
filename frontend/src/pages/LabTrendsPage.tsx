import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody } from "../components/Card";
import { LabTrendsView } from "../components/LabTrendsView";
import { ConsiderProfessionalCare } from "../components/ConsiderProfessionalCare";
import { LoadingState } from "../components/Spinner";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { LabTrendsReport } from "../types/api";

export function LabTrendsPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [report, setReport] = useState<LabTrendsReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getLabTrends(credentials);
      setReport(data);
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
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title">{t("labs.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("labs.subtitle")}</p>
        </div>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshIcon className="h-4 w-4" />
          {t("common.refresh")}
        </button>
      </div>

      {loading && <LoadingState label={t("labs.loading")} />}

      {!loading && error !== null && (
        <NotFoundOrError
          error={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      )}

      {!loading && report && (
        <>
          <LabTrendsView report={report} />
          {worthDiscussing(report) && (
            <ConsiderProfessionalCare message={t("care.labReview")} />
          )}
        </>
      )}
    </div>
  );
}

function worthDiscussing(report: LabTrendsReport): boolean {
  return report.trends.some((trend) => {
    const last = trend.data_points[trend.data_points.length - 1];
    const recovered =
      trend.returned_to_normal === true ||
      (Boolean(trend.crossed_into_abnormal_at) && last?.flag === "normal");
    if (trend.approaching_threshold) return true;
    if (trend.crossed_into_abnormal_at && !recovered) return true;
    return last?.flag === "high" || last?.flag === "low";
  });
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
            <p className="text-sm font-semibold text-slate-700">
              {t("labs.noTrends")}
            </p>
            <p className="max-w-md text-sm text-slate-500">
              {t("labs.noTrendsBody")}
            </p>
            <Link
              to="/upload"
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            >
              <UploadIcon className="h-4 w-4" />
              Upload lab reports
            </Link>
          </div>
        </CardBody>
      </Card>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
