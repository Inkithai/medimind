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

  let variant: "danger" | "warning" | "info" = "danger";
  let title = "Something went wrong";

  if (status === 401) {
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
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 inline-flex min-h-[44px] items-center rounded-lg bg-white/70 px-4 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-white"
        >
          Try again
        </button>
      )}
    </Alert>
  );
}
