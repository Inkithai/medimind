import { useI18n } from "../i18n/I18nContext";
import { Alert } from "./Alert";

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const { t, formatNumber } = useI18n();
  const message =
    error instanceof Error ? error.message : t("errors.generic");
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  const code =
    error && typeof error === "object" && "code" in error
      ? (error as { code?: string }).code
      : undefined;
  const retryable =
    error && typeof error === "object" && "retryable" in error
      ? (error as { retryable?: boolean }).retryable
      : undefined;
  const retryAfterSeconds =
    error && typeof error === "object" && "retryAfterSeconds" in error
      ? (error as { retryAfterSeconds?: number | null }).retryAfterSeconds
      : undefined;

  let variant: "danger" | "warning" | "info" = "danger";
  let title = t("errors.genericTitle");

  if (code === "job_poll_timeout") {
    variant = "info";
    title = t("errors.processingStill");
  } else if (code === "provider_model_unavailable") {
    variant = "warning";
    title = t("errors.serverUpdate");
  } else if (code === "provider_quota_exhausted") {
    variant = "warning";
    title = t("errors.temporarilyUnavailable");
  } else if (code === "provider_rate_limited") {
    variant = "warning";
    title = t("errors.readerBusy");
  } else if (code === "city_not_found") {
    variant = "warning";
    title = t("errors.cityNotFound");
  } else if (code === "directory_unavailable") {
    variant = "warning";
    title = t("errors.directoryUnavailable");
  } else if (status === 401) {
    variant = "warning";
    title = t("errors.expired");
  } else if (status === 404) {
    variant = "info";
    title = t("errors.notFound");
  } else if (status === 422) {
    variant = "warning";
    title = t("errors.validation");
  } else if (status === 502) {
    variant = "danger";
    title = t("errors.processingFailed");
  } else if (status === 0) {
    variant = "danger";
    title = t("errors.server");
  } else if (status === 503) {
    variant = "warning";
    title = t("errors.serverSetup");
  }

  return (
    <Alert variant={variant} title={title}>
      <p className="break-words">{message}</p>
      {onRetry && retryable !== false && (
        <button
          onClick={onRetry}
          className="mt-2 inline-flex min-h-[44px] items-center rounded-lg bg-white/70 px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-white"
        >
          {t("common.retry")}
        </button>
      )}
      {retryable !== false && retryAfterSeconds && (
        <p className="mt-2 text-sm font-medium">
          {t("errors.retryWait", { seconds: formatNumber(Math.max(1, Math.round(retryAfterSeconds))) })}
        </p>
      )}
      {retryable === false && (
        <p className="mt-2 text-sm font-medium">
          {t("errors.noRetry")}
        </p>
      )}
    </Alert>
  );
}
