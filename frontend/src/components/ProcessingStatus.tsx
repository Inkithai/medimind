import type { JobFileProgress } from "../api/client";
import { useI18n } from "../i18n/I18nContext";
import { classNames } from "../utils/format";
import { Spinner } from "./Spinner";

export type ProcessingStepId =
  | "upload"
  | "reading"
  | "extracting"
  | "organizing"
  | "safety"
  | "saving"
  | "indexing"
  | "ready"
  // Records are saved in the database, but the derived search index did
  // not finish. This is a success state with a caveat, never an error.
  | "partial"
  | "failed";

interface FinalStep {
  id: "organizing" | "safety" | "saving" | "indexing" | "ready";
  label: string;
  description: string;
}

const FINAL_STEPS: FinalStep[] = [
  {
    id: "organizing",
    label: "Update medical history",
    description: "Merge the readable files with your existing record",
  },
  {
    id: "safety",
    label: "Run safety check",
    description: "Check medicines, dosages and allergies together",
  },
  {
    id: "saving",
    label: "Save to your record",
    description: "Store the results so they survive any restart",
  },
  {
    id: "indexing",
    label: "Make records searchable",
    description: "Prepare the record so you can ask questions",
  },
  {
    id: "ready",
    label: "Record ready",
    description: "Your health record is up to date",
  },
];

function fileStepLabel(file: JobFileProgress, t: (key: string) => string): string {
  if (file.status === "failed") return t("processing.attention");
  if (file.status === "completed") return t("processing.detailsReady");
  switch (file.step) {
    case "reading":
      return t("processing.reading");
    case "extracting":
      return t("processing.extracting");
    case "saving":
      return t("processing.saving");
    default:
      return t("processing.waiting");
  }
}

function fileIcon(file: JobFileProgress) {
  if (file.status === "completed") return "✓";
  if (file.status === "failed") return "!";
  if (file.status === "processing") return <Spinner className="h-4 w-4" />;
  return file.index;
}

function progressPercent(current: ProcessingStepId, files: JobFileProgress[]): number {
  const total = files.length || 1;
  const fileUnits = files.reduce((sum, file) => {
    if (file.status === "completed" || file.status === "failed") return sum + 1;
    if (file.step === "saving") return sum + 0.8;
    if (file.step === "extracting") return sum + 0.5;
    if (file.step === "reading") return sum + 0.2;
    return sum;
  }, 0);
  const filePortion = Math.round((fileUnits / total) * 65);
  if (current === "ready" || current === "partial") return 100;
  if (current === "indexing") return 94;
  if (current === "saving") return 88;
  if (current === "safety") return 82;
  if (current === "organizing") return 72;
  return filePortion;
}

export function ProcessingStatus({
  current,
  files = [],
  error,
  workerLimit,
}: {
  current: ProcessingStepId;
  files?: JobFileProgress[];
  error?: string | null;
  workerLimit?: number;
}) {
  const { t, formatNumber } = useI18n();
  const successful = files.filter((file) => file.status === "completed").length;
  const failed = files.filter((file) => file.status === "failed").length;
  const processed = successful + failed;
  const total = files.length;
  // "partial" means everything up to and including saving succeeded, so the
  // checklist should show progress frozen at the indexing step.
  const isPartial = current === "partial";
  const finalIdx = isPartial
    ? FINAL_STEPS.findIndex((step) => step.id === "indexing")
    : FINAL_STEPS.findIndex((step) => step.id === current);
  const isFinalizing = finalIdx >= 0;
  const percent = progressPercent(current, files);

  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      aria-live="polite"
      aria-busy={current !== "ready" && current !== "failed"}
      aria-label={t("processing.status")}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="card-title">
            {current === "ready"
              ? t("processing.complete")
              : isPartial
              ? t("processing.recordsSaved")
              : current === "failed"
              ? t("processing.stopped")
              : t("processing.documents")}
          </h3>
          <p className="secondary-text mt-1">
            {total > 0
              ? t("processing.progress", { processed: formatNumber(processed), total: formatNumber(total) })
              : t("processing.preparing")}
          </p>
        </div>
        {total > 0 && (
          <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
            {percent}%
          </span>
        )}
      </div>

      {total > 0 && (
        <div
          className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100"
          role="progressbar"
          aria-label={t("processing.status")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-valuetext={`${formatNumber(percent)}%`}
        >
          <div
            className={classNames(
              "h-full rounded-full transition-all duration-500",
              current === "failed"
                ? "bg-amber-500"
                : isPartial
                ? "bg-amber-400"
                : "bg-brand-600"
            )}
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {files.length > 0 && (
        <div className="mt-5">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
                {t("processing.eachFile")}
              </h4>
              {files.length > 1 && (
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  Files move independently. A large scan can still be reading while another file is ready.
                  {workerLimit
                    ? ` Up to ${workerLimit} ${workerLimit === 1 ? "file is" : "files are"} processed at once to prevent overload.`
                    : " Waiting files start as processing capacity becomes available."}
                </p>
              )}
            </div>
            {(successful > 0 || failed > 0) && (
              <p className="shrink-0 text-xs text-slate-500">
                <span className="font-medium text-emerald-700">{successful} ready</span>
                {failed > 0 && <span className="ml-2 font-medium text-red-700">{failed} failed</span>}
              </p>
            )}
          </div>

          <ul className="mt-3 space-y-2">
            {files.map((file) => {
              const isFailed = file.status === "failed";
              const isComplete = file.status === "completed";
              const isActive = file.status === "processing";
              return (
                <li
                  key={file.id}
                  className={classNames(
                    "rounded-xl border px-3.5 py-3",
                    isFailed
                      ? "border-red-200 bg-red-50/70"
                      : isComplete
                      ? "border-emerald-200 bg-emerald-50/60"
                      : isActive
                      ? "border-brand-200 bg-brand-50/50"
                      : "border-slate-200 bg-slate-50/70"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={classNames(
                        "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                        isFailed
                          ? "bg-red-600 text-white"
                          : isComplete
                          ? "bg-emerald-600 text-white"
                          : isActive
                          ? "bg-brand-600 text-white"
                          : "bg-slate-200 text-slate-600"
                      )}
                      aria-hidden="true"
                    >
                      {fileIcon(file)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                        <p className="truncate text-sm font-semibold text-slate-800" title={file.name}>
                          {file.name}
                        </p>
                        <span
                          className={classNames(
                            "shrink-0 text-xs font-semibold",
                            isFailed
                              ? "text-red-700"
                              : isComplete
                              ? "text-emerald-700"
                              : isActive
                              ? "text-brand-700"
                              : "text-slate-500"
                          )}
                        >
                          {fileStepLabel(file, t)}
                        </span>
                      </div>
                      <p
                        className={classNames(
                          "mt-0.5 text-xs leading-5",
                          isFailed ? "text-red-700" : "text-slate-500"
                        )}
                      >
                        {file.error || file.message}
                      </p>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <div className="mt-6 border-t border-slate-100 pt-5">
        <div>
          <h4 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {t("processing.finalize")}
          </h4>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            {t("processing.finalizeBody")}
          </p>
        </div>

        <ol className="mt-4 grid gap-2 sm:grid-cols-2">
          {FINAL_STEPS.map((step, index) => {
            const isPast = isFinalizing && index < finalIdx;
            const isCurrent = isFinalizing && index === finalIdx;
            return (
              <li
                key={step.id}
                className={classNames(
                  "flex gap-3 rounded-xl border px-3 py-3",
                  isPast
                    ? "border-emerald-200 bg-emerald-50/60"
                    : isCurrent && isPartial
                    ? "border-amber-200 bg-amber-50/70"
                    : isCurrent
                    ? "border-brand-200 bg-brand-50/60"
                    : "border-slate-100 bg-slate-50/60 opacity-60"
                )}
              >
                <span
                  className={classNames(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                    isPast
                      ? "bg-emerald-600 text-white"
                      : isCurrent && isPartial
                      ? "bg-amber-500 text-white"
                      : isCurrent
                      ? "bg-brand-600 text-white"
                      : "bg-slate-200 text-slate-500"
                  )}
                  aria-hidden="true"
                >
                  {isPast || (current === "ready" && step.id === "ready") ? (
                    "✓"
                  ) : isCurrent && isPartial ? (
                    "!"
                  ) : isCurrent && current !== "ready" ? (
                    <Spinner className="h-3.5 w-3.5" />
                  ) : (
                    index + 1
                  )}
                </span>
                <div>
                  <p className="text-sm font-medium text-slate-700">{step.label}</p>
                  <p className="mt-0.5 text-xs leading-4 text-slate-500">{step.description}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {isPartial && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">Saved — search is still catching up</p>
          <p className="mt-1 leading-5">
            {successful > 0
              ? `All ${successful} ${successful === 1 ? "file is" : "files are"} stored in your record and visible on your dashboard. `
              : "Your record is stored and visible on your dashboard. "}
            Only the question-answering index did not finish, and it rebuilds
            automatically the next time you ask a question.
          </p>
        </div>
      )}

      {error && (
        <div role="alert" className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {error}
        </div>
      )}
    </section>
  );
}

export function mapUploadPhaseToStep(
  isUploading: boolean,
  hasResult: boolean,
  hasError: boolean
): ProcessingStepId {
  if (hasError) return "failed";
  if (hasResult) return "ready";
  if (isUploading) return "extracting";
  return "upload";
}
