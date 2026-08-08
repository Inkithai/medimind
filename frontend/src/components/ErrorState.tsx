import { Alert } from "./Alert";

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const message =
    error instanceof Error ? error.message : "Something went wrong.";
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
  let title = "Something went wrong";

  if (code === "job_poll_timeout") {
    variant = "info";
    title = "This upload may still be processing";
  } else if (code === "provider_model_unavailable") {
    variant = "warning";
    title = "Document reading needs a server update";
  } else if (code === "provider_quota_exhausted") {
    variant = "warning";
    title = "Document reading is temporarily unavailable";
  } else if (code === "provider_rate_limited") {
    variant = "warning";
    title = "The document reader is busy";
  } else if (status === 401) {
    variant = "warning";
    title = "Your session has expired";
  } else if (status === 404) {
    variant = "info";
    title = "Nothing here yet";
  } else if (status === 422) {
    variant = "warning";
    title = "We couldn't process that file";
  } else if (status === 502) {
    variant = "danger";
    title = "Something went wrong while processing";
  } else if (status === 0) {
    variant = "danger";
    title = "Can't reach the server";
  } else if (status === 503) {
    variant = "warning";
    title = "The server is still being set up";
  }

  return (
    <Alert variant={variant} title={title}>
      <p className="break-words">{message}</p>
      {onRetry && retryable !== false && (
        <button
          onClick={onRetry}
          className="mt-2 inline-flex min-h-[44px] items-center rounded-lg bg-white/70 px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-white"
        >
          Try again
        </button>
      )}
      {retryable !== false && retryAfterSeconds && (
        <p className="mt-2 text-sm font-medium">
          Wait about {Math.max(1, Math.round(retryAfterSeconds))} seconds before retrying.
        </p>
      )}
      {retryable === false && (
        <p className="mt-2 text-sm font-medium">
          Retrying immediately will not help. Your files are not the cause of this problem.
        </p>
      )}
    </Alert>
  );
}
