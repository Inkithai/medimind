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
  { id: "upload", label: "Document uploaded", description: "File received by FastAPI /api/v1/documents" },
  { id: "reading", label: "Reading document", description: "Text layer or vision OCR (Groq Llama 4 Scout)" },
  { id: "extracting", label: "Extracting medical information", description: "Medications, labs, allergies, notes → structured JSON" },
  { id: "organizing", label: "Organizing health information", description: "Merge with previous uploads, build timeline" },
  { id: "safety", label: "Running safety checks", description: "Interactions, duplicates, dosage, allergy conflicts + lab trends" },
  { id: "indexing", label: "Preparing for questions", description: "Chunking + embeddings → Chroma for RAG" },
  { id: "ready", label: "Document ready", description: "Timeline, safety, Q&A updated" },
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
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">Processing status</h3>
        <span className="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-200">
          MediMind pipeline
        </span>
      </div>

      <div className="mt-4 space-y-3">
        {STEPS.map((step, idx) => {
          const isPast = idx < currentIdx;
          const isCurrent = idx === currentIdx;
          const isFuture = idx > currentIdx;
          return (
            <div key={step.id} className="flex gap-3">
              <div
                className={classNames(
                  "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                  isPast ? "bg-emerald-600 text-white" : isCurrent ? "bg-brand-600 text-white ring-4 ring-brand-100" : "bg-slate-100 text-slate-400"
                )}
              >
                {isPast ? "✓" : isCurrent ? <Spinner className="h-3.5 w-3.5" /> : "○"}
              </div>
              <div className={classNames("min-w-0", isFuture ? "opacity-50" : "")}>
                <p
                  className={classNames(
                    "text-sm",
                    isCurrent ? "font-semibold text-slate-900" : isPast ? "font-medium text-slate-700" : "font-medium text-slate-500"
                  )}
                >
                  {step.label}
                  {isCurrent && <span className="ml-2 animate-pulse text-brand-600">●</span>}
                </p>
                <p className="text-xs text-slate-500">{step.description}</p>
              </div>
            </div>
          );
        })}
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
          {error}
        </div>
      )}

      <p className="mt-4 text-xs text-slate-400">
        Backend flow: OCR → Extract → Structured store (Supabase + Cloudinary) → Safety checks → Retrieval chunks (Chroma) →
        Patient Record.
      </p>
    </div>
  );
}

export function mapUploadPhaseToStep(isUploading: boolean, hasResult: boolean, hasError: boolean): ProcessingStepId {
  if (hasError) return "reading";
  if (hasResult) return "ready";
  if (isUploading) return "extracting";
  return "upload";
}
