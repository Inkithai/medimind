import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { toastMessage, useToast } from "../components/Toast";
import { Spinner } from "../components/Spinner";
import { RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { GuidelinesRefreshResult, GuidelinesStatus } from "../types/api";

export function GuidelinesPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const { toastSuccess, toastError, toastInfo } = useToast();
  const [status, setStatus] = useState<GuidelinesStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [checking, setChecking] = useState(false);
  const [lastCheck, setLastCheck] = useState<GuidelinesRefreshResult | null>(null);

  // POST /api/v1/guidelines/refresh: looks for newer published versions of
  // the curated sources and applies any it finds. Fails open ("manual
  // review") when no manifest is configured, which is a normal answer and
  // is reported as information rather than as an error.
  async function handleCheckForUpdates() {
    setChecking(true);
    try {
      const result = await api.refreshGuidelines(credentials);
      setLastCheck(result);
      const applied = result.applied_count ?? result.applied?.length ?? 0;
      if (applied > 0) {
        toastSuccess(
          `${applied} guideline source${applied === 1 ? "" : "s"} updated`,
          "The list below now shows the newest reviewed versions.",
        );
      } else if (result.checked === false) {
        toastInfo(
          "No update service is configured",
          "These sources are reviewed by hand. Nothing was changed.",
        );
      } else {
        toastInfo("Everything is already up to date", "No newer versions were published.");
      }
      setReloadKey((key) => key + 1);
    } catch (err) {
      toastError("Could not check for updates", toastMessage(err));
    } finally {
      setChecking(false);
    }
  }

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
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => setReloadKey((k) => k + 1)}
            disabled={loading || checking}
            className="btn-secondary"
            title="Reload this page's information from the server."
          >
            <RefreshIcon className="h-5 w-5" aria-hidden="true" />
            {t("common.refresh")}
          </button>
          <button
            onClick={() => void handleCheckForUpdates()}
            disabled={checking || loading}
            className="btn-primary"
            title="Asks the guideline publishers whether a newer version exists."
          >
            {checking ? (
              <Spinner className="h-5 w-5" />
            ) : (
              <RefreshIcon className="h-5 w-5" aria-hidden="true" />
            )}
            {checking ? "Checking for updates…" : "Check for newer guidelines"}
          </button>
        </div>
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
          {lastCheck && (
            <Card>
              <CardHeader
                title="Last update check"
                description={
                  lastCheck.checked === false
                    ? "No automatic update service is configured, so these sources are reviewed by hand."
                    : `Checked ${lastCheck.checked_at || "just now"}.`
                }
              />
              <CardBody className="space-y-2 text-sm text-slate-700">
                {(lastCheck.applied_count ?? lastCheck.applied?.length ?? 0) > 0 ? (
                  <ul className="space-y-1">
                    {(lastCheck.applied || []).map((item) => (
                      <li key={item.key} className="flex items-center gap-2">
                        <StatusBadge tone="success">updated</StatusBadge>
                        <span>
                          {item.key} → version {item.version}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>No source needed updating.</p>
                )}
              </CardBody>
            </Card>
          )}
          <p className="text-sm text-slate-500">{status.note}</p>
        </>
      )}
    </div>
  );
}
