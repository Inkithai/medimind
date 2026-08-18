import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { EmptyState } from "../components/EmptyState";
import { RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { PreventiveCareReport } from "../types/api";

const PRIORITY_TONE: Record<string, "warning" | "neutral"> = {
  soon: "warning",
};

const KIND_LABEL: Record<string, string> = {
  vaccination: "Vaccination",
  screening: "Screening",
  monitoring: "Monitoring",
};

export function PreventiveCarePage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [report, setReport] = useState<PreventiveCareReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await api.getPreventiveCare(credentials));
    } catch (err) {
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
          <h1 className="page-title">{t("preventive.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("preventive.subtitle")}</p>
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
        <ErrorState error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && report && (
        <>
          {report.count === 0 ? (
            <Card>
              <CardBody>
                <EmptyState
                  title="No reminders right now"
                  description="Add your date of birth in Settings to unlock age-based screening reminders."
                />
              </CardBody>
            </Card>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {report.care_gaps.map((g, i) => (
                <Card key={i}>
                  <CardBody className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone="info">{KIND_LABEL[g.kind] ?? g.kind}</StatusBadge>
                      <StatusBadge tone={PRIORITY_TONE[g.priority] ?? "neutral"}>
                        {g.priority}
                      </StatusBadge>
                    </div>
                    <h3 className="text-sm font-semibold text-slate-800">{g.title}</h3>
                    <p className="text-xs leading-relaxed text-slate-600">{g.detail}</p>
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
          <p className="text-xs text-slate-400">{report.note}</p>
        </>
      )}
    </div>
  );
}
