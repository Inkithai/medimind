import { useCopy } from "../i18n";
import type { QAResponse, QASource } from "../types/api";
import { classNames, confidenceTone, formatConfidence, formatDate } from "../utils/format";
import { Alert } from "./Alert";
import { FileIcon } from "./icons";

/**
 * Renders one grounded answer.
 *
 * Citations are the point of this card, not decoration: each source is a
 * button that opens the document it came from, so a patient can verify the
 * claim against the original page. An answer with no verifiable source says
 * so explicitly rather than looking equally authoritative.
 */
export function QAResultCard({
  result,
  embedded = false,
  question,
  onOpenSource,
}: {
  result: QAResponse;
  embedded?: boolean;
  question?: string;
  /** Opens the cited document. Omit to render sources as plain text. */
  onOpenSource?: (source: QASource) => void;
}) {
  const copy = useCopy();
  // Defensive dedupe: the server already returns one entry per document, but
  // a cached or older response must never render the same file twice or
  // inflate the source count.
  const sources = dedupeSources(result.sources);
  const hasSources = sources.length > 0;

  return (
    <div
      className={
        embedded
          ? "space-y-3 text-sm"
          : "space-y-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      }
    >
      {result.recommend_professional_consult && (
        <Alert variant="warning" title={copy.askAi.consultTitle}>
          {copy.askAi.consultBody}
        </Alert>
      )}

      {question && !embedded && (
        <div className="rounded-xl bg-slate-50 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            {copy.askAi.askedLabel}
          </p>
          <p className="mt-0.5 break-words text-sm text-slate-700">{question}</p>
        </div>
      )}

      {/* `break-words` keeps a long unbroken token (a URL, a lab code) from
          widening the card on mobile. */}
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800">
        {result.answer}
      </p>

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        {/* Plain-language band leads; the percentage is supporting detail, so
            "98%" cannot read as "98% medically certain". */}
        <span
          className={classNames(
            "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
            confidenceTone(result.confidence)
          )}
          title={copy.askAi.confidenceHelp}
        >
          {copy.askAi.confidenceBand(confidenceBand(result.confidence, copy), sources.length)}
        </span>
        <span className="text-xs text-slate-500">
          {copy.askAi.confidenceLabel(formatConfidence(result.confidence))}
        </span>
        <span className="text-xs text-slate-500">
          {hasSources ? copy.askAi.sourcesTitle(sources.length) : copy.askAi.noSourcesTitle}
        </span>
      </div>

      {hasSources ? (
        <div>
          <ul className="space-y-1.5">
            {sources.map((source) => (
              <li key={source.source_file}>
                <SourceRow source={source} onOpenSource={onOpenSource} />
              </li>
            ))}
          </ul>
          {onOpenSource && (
            <p className="mt-2 text-xs text-slate-400">{copy.askAi.sourceHint}</p>
          )}
        </div>
      ) : (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
          {copy.askAi.noSourcesBody}
        </p>
      )}

      {result.rewritten_query && (
        <div className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <span className="font-semibold text-slate-600">
            {copy.askAi.retrievalQueryLabel}:
          </span>{" "}
          <span className="break-words">{result.rewritten_query}</span>
        </div>
      )}
    </div>
  );
}

function SourceRow({
  source,
  onOpenSource,
}: {
  source: QASource;
  onOpenSource?: (source: QASource) => void;
}) {
  const copy = useCopy();
  const label = (
    <>
      <FileIcon className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
        {source.source_file}
      </span>
      {typeof source.page === "number" && (
        <span className="shrink-0 rounded-full bg-white px-1.5 py-0.5 text-[10px] font-semibold text-slate-500 ring-1 ring-slate-200">
          {copy.askAi.pageLabel(source.page)}
        </span>
      )}
      {/* Every date this document was cited for — one document, one row. */}
      {sourceDates(source).length > 0 && (
        <span className="shrink-0 text-slate-400">
          {sourceDates(source).map(formatDate).join(" · ")}
        </span>
      )}
    </>
  );

  if (!onOpenSource) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
        {label}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onOpenSource(source)}
      aria-label={copy.askAi.openSource(source.source_file)}
      className="flex min-h-[44px] w-full items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-left text-xs text-slate-600 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
    >
      {label}
      <span className="shrink-0 text-brand-600" aria-hidden="true">
        →
      </span>
    </button>
  );
}

/** All dates a source was cited for, newest-first, with `date` as fallback. */
function sourceDates(source: QASource): string[] {
  const dates = source.dates?.length ? source.dates : source.date ? [source.date] : [];
  return [...new Set(dates.filter(Boolean))].sort();
}

/**
 * Collapse citations to one entry per document.
 *
 * A file cited for two visit dates is still a single document the patient
 * can open, so it must count once. Dates from the duplicates are merged so
 * no evidence is lost.
 */
function dedupeSources(sources: QASource[]): QASource[] {
  const byFile = new Map<string, QASource>();
  for (const source of sources || []) {
    const file = source?.source_file?.trim();
    if (!file) continue;
    const existing = byFile.get(file);
    if (!existing) {
      byFile.set(file, { ...source, source_file: file, dates: sourceDates(source) });
      continue;
    }
    existing.dates = [...new Set([...(existing.dates || []), ...sourceDates(source)])].sort();
    // Keep the first page we saw rather than dropping page information.
    if (existing.page == null && typeof source.page === "number") existing.page = source.page;
  }
  return [...byFile.values()];
}

/** Plain-language band for an evidence-match score. */
function confidenceBand(confidence: number, copy: ReturnType<typeof useCopy>): string {
  if (confidence >= 0.85) return copy.askAi.confidenceHigh;
  if (confidence >= 0.6) return copy.askAi.confidenceMedium;
  return copy.askAi.confidenceLow;
}
