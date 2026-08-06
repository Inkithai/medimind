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
  let title = "Request failed";

  if (status === 401) {
    variant = "warning";
    title = "Authentication required";
  } else if (status === 404) {
    variant = "info";
    title = "No data yet";
  } else if (status === 422) {
    variant = "warning";
    title = "The backend could not process the request";
  } else if (status === 502) {
    variant = "danger";
    title = "ML pipeline error";
  } else if (status === 0) {
    variant = "danger";
    title = "Cannot reach the API";
  }

  return (
    <Alert variant={variant} title={title}>
      <p className="break-words">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 inline-flex items-center rounded-md bg-white/70 px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-white"
        >
          Try again
        </button>
      )}
    </Alert>
  );
}
