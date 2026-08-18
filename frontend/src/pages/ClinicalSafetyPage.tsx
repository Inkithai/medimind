import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ClinicalFindingCard } from "../components/ClinicalFindingCard";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { EmptyState } from "../components/EmptyState";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { ManagedAlertsReport, FeedbackMetrics } from "../types/api";

export function ClinicalSafetyPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [alerts, setAlerts] = useState<ManagedAlertsReport | null>(null);
  const [metrics, setMetrics] = useState<FeedbackMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [a, m] = await Promise.all([
        api.getManagedAlerts(credentials),
        api.getFeedbackMetrics(credentials).catch(() => null),
      ]);
      setAlerts(a);
      setMetrics(m);
    } catch (err) {
      setAlerts(null);
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
          <h1 className="page-title">{t("clinicalSafety.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("clinicalSafety.subtitle")}</p>
        </div>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshIcon className="h-4 w-4" />
          {t("common.refresh")}
        </button>
      </div>

      {loading && <LoadingState label={t("common.loading")} />}

      {!loading && error !== null && (
        <ErrorOrEmpty error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && alerts && (
        <>
          {alerts.active_count === 0 && alerts.suppressed_count === 0 && (
            <Card>
              <CardBody>
                <EmptyState
                  title="No active safety alerts"
                  description="Once documents are uploaded, drug–lab, renal/hepatic, condition-contraindication and interaction findings appear here, with reviewer actions."
                />
              </CardBody>
            </Card>
          )}

          {alerts.active_count > 0 && (
            <div>
              <h2 className="section-title">
                Active findings ({alerts.active_count})
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {alerts.active_findings.map((f, i) => (
                  <ClinicalFindingCard key={f.finding_key || i} finding={f} />
                ))}
              </div>
              {alerts.collapsed_duplicates > 0 && (
                <p className="mt-2 text-xs text-slate-400">
                  {alerts.collapsed_duplicates} near-duplicate alert(s) collapsed.
                </p>
              )}
            </div>
          )}

          {alerts.suppressed_count > 0 && (
            <div>
              <h2 className="section-title">
                Overridden / suppressed ({alerts.suppressed_count})
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {alerts.suppressed_findings.map((f, i) => (
                  <ClinicalFindingCard key={f.finding_key || i} finding={f} />
                ))}
              </div>
            </div>
          )}

          {metrics && metrics.total > 0 && (
            <Card>
              <CardHeader title="Reviewer metrics" />
              <CardBody>
                <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <Metric label="Total reviews" value={metrics.total} />
                  <Metric
                    label="Confirmation rate"
                    value={metrics.confirmation_rate ?? "—"}
                  />
                  <Metric
                    label="False-positive rate"
                    value={metrics.false_positive_rate ?? "—"}
                  />
                  <Metric label="Override rate" value={metrics.override_rate ?? "—"} />
                </dl>
              </CardBody>
            </Card>
          )}

          <MedicalDisclaimer />
        </>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-800">{value}</dd>
    </div>
  );
}

function ErrorOrEmpty({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404) {
    return (
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="text-sm font-semibold text-slate-700">No records yet</p>
            <Link
              to="/upload"
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            >
              <UploadIcon className="h-4 w-4" /> Upload documents
            </Link>
          </div>
        </CardBody>
      </Card>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
