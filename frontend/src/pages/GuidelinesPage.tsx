import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { GuidelinesStatus } from "../types/api";

export function GuidelinesPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [status, setStatus] = useState<GuidelinesStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await api.getGuidelinesStatus(credentials));
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
          <h1 className="page-title">{t("guidelines.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("guidelines.subtitle")}</p>
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

      {!loading && status && (
        <>
          <Card>
            <CardHeader
              title="Curated sources"
              action={
                status.stale_count > 0 ? (
                  <StatusBadge tone="warning">{status.stale_count} due for review</StatusBadge>
                ) : (
                  <StatusBadge tone="success">all current</StatusBadge>
                )
              }
            />
            <CardBody className="space-y-2">
              {status.sources.map((s) => (
                <div
                  key={s.key}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 p-2 text-sm"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-slate-700">{s.description || s.key}</div>
                    <div className="text-xs text-slate-400">
                      version {s.version} · reviewed {s.reviewed}
                      {s.age_days !== null ? ` · ${s.age_days}d ago` : ""}
                    </div>
                  </div>
                  {s.stale ? (
                    <StatusBadge tone="warning">review due</StatusBadge>
                  ) : (
                    <StatusBadge tone="success">current</StatusBadge>
                  )}
                </div>
              ))}
            </CardBody>
          </Card>
          <p className="text-xs text-slate-400">{status.note}</p>
        </>
      )}
    </div>
  );
}
