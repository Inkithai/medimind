import { useI18n } from "../i18n/I18nContext";
import { Alert } from "./Alert";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t, formatNumber } = useI18n();
  const message = error instanceof Error ? error.message : t("errors.generic");
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
  // Raw provider text ("Chat completion failed: RateLimitError...") is never
  // the headline; it moves into a collapsible block for support.
  let body = message;
  let technicalDetail: string | null = null;

  if (code === "job_poll_timeout") {
    variant = "info";
    title = t("errors.processingStill");
  } else if (code === "job_status_unavailable") {
    // The upload itself succeeded — only the progress connection dropped.
    // This must NOT read like a failed upload, or users re-upload files
    // that are already saved.
    variant = "warning";
    title = t("errors.uploadSavedNoProgress");
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
  } else if (status === 429) {
    variant = "warning";
    title = t("errors.tooManyRequests");
    body = t("errors.tooManyRequestsBody");
    technicalDetail = message;
  } else if (status === 502 || status === 500) {
    variant = "danger";
    title = t("errors.processingFailed");
    body = t("errors.answerFailedBody");
    technicalDetail = message;
  } else if (status === 0) {
    variant = "danger";
    title = t("errors.server");
    body = t("errors.offlineBody");
    technicalDetail = message;
  } else if (status === 503) {
    variant = "warning";
    title = t("errors.serverSetup");
  }

  return (
    <Alert variant={variant} title={title}>
      <p className="break-words">{body}</p>

      {technicalDetail && technicalDetail !== body && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-medium opacity-80">
            {t("errors.technicalDetails")}
          </summary>
          <p className="mt-1 break-words text-xs opacity-80">{technicalDetail}</p>
        </details>
      )}
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
          {t("errors.retryWait", {
            seconds: formatNumber(Math.max(1, Math.round(retryAfterSeconds))),
          })}
        </p>
      )}
      {retryable === false && <p className="mt-2 text-sm font-medium">{t("errors.noRetry")}</p>}
      {code === "job_status_unavailable" && (
        <p className="mt-2 text-sm font-medium">{t("errors.uploadSavedNoProgressBody")}</p>
      )}
    </Alert>
  );
}
