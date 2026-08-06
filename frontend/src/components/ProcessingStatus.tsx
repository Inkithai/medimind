import { classNames } from "../utils/format";
import { Spinner } from "./Spinner";

export type ProcessingStepId =
  | "upload"
  | "reading"
  | "extracting"
  | "organizing"
  | "safety"
  | "indexing"
  | "ready";

interface Step {
  id: ProcessingStepId;
  label: string;
  description: string;
}

const STEPS: Step[] = [
  { id: "upload", label: "Uploaded", description: "Your files arrived safely" },
  { id: "reading", label: "Reading document…", description: "Turning pages into text we can read" },
  { id: "extracting", label: "Extracting medicines…", description: "Finding medicines, diagnoses, allergies and lab results" },
  { id: "organizing", label: "Updating your medical history…", description: "Merging this with your existing records" },
  { id: "safety", label: "Safety check", description: "Looking for anything that needs your attention" },
  { id: "indexing", label: "Making your records searchable…", description: "So you can ask questions about them" },
  { id: "ready", label: "Done", description: "Your health record is up to date" },
];

export function ProcessingStatus({
  current,
  error,
}: {
  current: ProcessingStepId;
  error?: string | null;
}) {
  const currentIdx = STEPS.findIndex((s) => s.id === current);
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="card-title">What we're doing</h3>

      {/* Vertical timeline */}
      <ol className="mt-5">
        {STEPS.map((step, idx) => {
          const isPast = idx < currentIdx;
          const isCurrent = idx === currentIdx;
          const isFuture = idx > currentIdx;
          const isLast = idx === STEPS.length - 1;
          return (
            <li key={step.id} className="flex gap-4">
              {/* Node + connector */}
              <div className="flex flex-col items-center">
                <div
                  className={classNames(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                    isPast
                      ? "bg-emerald-600 text-white"
                      : isCurrent
                      ? "bg-brand-600 text-white ring-4 ring-brand-100"
                      : "bg-slate-100 text-slate-400"
                  )}
                >
                  {isPast ? "✓" : isCurrent ? <Spinner className="h-4 w-4" /> : idx + 1}
                </div>
                {!isLast && (
                  <div
                    className={classNames(
                      "w-0.5 flex-1",
                      idx < currentIdx ? "bg-emerald-500" : "bg-slate-200"
                    )}
                    aria-hidden="true"
                  />
                )}
              </div>
              {/* Label */}
              <div className={classNames("min-w-0 pb-6", isLast && "pb-0", isFuture && "opacity-50")}>
                <p
                  className={classNames(
                    "text-base",
                    isCurrent
                      ? "font-semibold text-slate-900"
                      : isPast
                      ? "font-medium text-slate-700"
                      : "font-medium text-slate-500"
                  )}
                >
                  {step.label}
                </p>
                <p className="secondary-text mt-0.5">{step.description}</p>
              </div>
            </li>
          );
        })}
      </ol>

      {error && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
        </div>
      )}
    </div>
  );
}

export function mapUploadPhaseToStep(isUploading: boolean, hasResult: boolean, hasError: boolean): ProcessingStepId {
  if (hasError) return "reading";
  if (hasResult) return "ready";
  if (isUploading) return "extracting";
  return "upload";
}
