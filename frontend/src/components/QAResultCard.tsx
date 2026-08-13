import type { QAResponse } from "../types/api";
import { classNames, confidenceTone, formatConfidence, formatDate } from "../utils/format";
import { Alert } from "./Alert";
import { ConsiderProfessionalCare } from "./ConsiderProfessionalCare";

export function QAResultCard({
  result,
  embedded = false,
}: {
  result: QAResponse;
  embedded?: boolean;
}) {
  return (
    <div
      className={
        embedded
          ? "space-y-2 text-sm"
          : "space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      }
    >
      {result.recommend_professional_consult && (
        <ConsiderProfessionalCare message="You may want to discuss this with a healthcare professional." />
      )}

      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
        {result.answer}
      </p>

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <span
          className={classNames(
            "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
            confidenceTone(result.confidence)
          )}
        >
          Answer confidence {formatConfidence(result.confidence)}
        </span>
        {result.sources.length > 0 ? (
          <span className="text-xs text-slate-500">
            {result.sources.length} source{result.sources.length === 1 ? "" : "s"}
          </span>
        ) : (
          <span className="text-xs text-slate-400">No cited sources</span>
        )}
      </div>

      {result.sources.length > 0 && (
        <ul className="space-y-1">
          {result.sources.map((src, i) => (
            <li
              key={i}
              className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-1.5 text-xs text-slate-600"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-3.5 w-3.5 text-slate-400">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              <span className="font-medium text-slate-700">{src.source_file}</span>
              {src.date && <span className="text-slate-400">· {formatDate(src.date)}</span>}
            </li>
          ))}
        </ul>
      )}

      {result.rewritten_query && (
        <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <span className="font-semibold text-slate-600">Retrieval query used:</span>{" "}
          {result.rewritten_query}
        </div>
      )}
    </div>
  );
}
