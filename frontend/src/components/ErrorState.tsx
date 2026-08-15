import { Alert } from "./Alert";

/**
 * Turns any thrown value into a message a patient can act on.
 *
 * Raw provider text ("Chat completion failed while answering question:
 * openai.RateLimitError…") is never the headline — it goes into a
 * collapsible detail block for support, while the visible copy explains
 * what happened and what to do next.
 */
export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const rawMessage =
    error instanceof Error ? error.message : typeof error === "string" ? error : "";
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
  let body = rawMessage || "Something went wrong. Please try again.";
  // Raw text is only worth surfacing when it isn't already the body.
  let technicalDetail: string | null = null;

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
    body = "Reload the page to start a new session, then try again.";
    technicalDetail = rawMessage;
  } else if (status === 404) {
    variant = "info";
    title = "Nothing here yet";
  } else if (status === 422) {
    variant = "warning";
    title = "We couldn't process that request";
    // FastAPI validation payloads are objects, not sentences.
    body = looksTechnical(rawMessage)
      ? "Please check what you entered and try again."
      : rawMessage;
    technicalDetail = looksTechnical(rawMessage) ? rawMessage : null;
  } else if (status === 429) {
    variant = "warning";
    title = "Too many requests";
    body = "You've asked a lot in a short time. Wait a moment, then try again.";
    technicalDetail = rawMessage;
  } else if (status === 502 || status === 500) {
    variant = "danger";
    title = "We couldn't get an answer just now";
    body =
      "MediMind reached your records but couldn't finish the answer. This is usually temporary — please try again.";
    technicalDetail = rawMessage;
  } else if (status === 0) {
    variant = "danger";
    title = "Can't reach MediMind";
    body =
      "We couldn't reach the server. Check your internet connection, then try again.";
    technicalDetail = rawMessage;
  } else if (status === 503) {
    variant = "warning";
    title = "The server is still being set up";
  }

  return (
    <Alert variant={variant} title={title}>
      <p className="break-words">{body}</p>

      {technicalDetail && technicalDetail !== body && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-medium opacity-80">
            Technical details
          </summary>
          <p className="mt-1 break-words text-xs opacity-80">{technicalDetail}</p>
        </details>
      )}

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

/** Heuristic for text that reads like a stack trace or serialized payload. */
function looksTechnical(message: string): boolean {
  if (!message) return true;
  return (
    message.startsWith("[") ||
    message.startsWith("{") ||
    message.includes("Traceback") ||
    message.includes("Error:") ||
    /\b[a-z_]+\.[a-z_]+Error\b/.test(message)
  );
}
