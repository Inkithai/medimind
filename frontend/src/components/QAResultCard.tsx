import { Link } from "react-router-dom";
import type { QAResponse, QASource } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
import { classNames, confidenceTone, formatConfidence, formatDate } from "../utils/format";
import { Alert } from "./Alert";
import { ConsiderProfessionalCare } from "./ConsiderProfessionalCare";

export function QAResultCard({
  result,
  embedded = false,
  onOpenSource,
}: {
  result: QAResponse;
  embedded?: boolean;
  /** Opens the cited document. Omit to render sources as plain text. */
  onOpenSource?: (source: QASource) => void;
}) {
  const { t, formatNumber } = useI18n();
  // One entry per DOCUMENT. A file cited for two visit dates is still one
  // source the patient can open, so counting it twice overstated the
  // evidence ("4 sources" for 2 documents).
  const sources = dedupeSources(result.sources);
  return (
    <div
      className={
        embedded
          ? "space-y-2 text-sm"
          : "space-y-3 rounded-lg border border-slate-200 bg-white p-4"
      }
    >
      {result.trust_notice && (
        <Alert variant="warning" title="Some evidence was excluded">
          {result.trust_notice}
          {result.quarantined_conflict_count
            ? ` ${result.quarantined_conflict_count} conflict(s) still need review.`
            : ""}
        </Alert>
      )}

      {result.recommend_professional_consult && (
        <ConsiderProfessionalCare message={t("ask.consult")} />
      )}

      {result.evidence_sufficiency && result.evidence_sufficiency.level !== "sufficient" && (
        <Alert
          variant="warning"
          title={
            result.evidence_sufficiency.level === "insufficient"
              ? "Not enough matching evidence"
              : "Evidence is limited"
          }
        >
          {result.evidence_sufficiency.reason}
        </Alert>
      )}

      {result.question_intent && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="rounded-full bg-brand-50 px-2.5 py-1 font-semibold text-brand-700 ring-1 ring-brand-100">
            Intent · {result.question_intent.label}
          </span>
          {result.evidence_sufficiency?.level === "sufficient" && (
            <span className="rounded-full bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-700 ring-1 ring-emerald-100">
              Evidence coverage sufficient
            </span>
          )}
        </div>
      )}

      {/* break-words stops a long unbroken token (a URL or lab code) from
          widening the card on a narrow screen. */}
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-800">
        {result.answer}
      </p>

      {result.confidence_reason && (
        <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <span className="font-semibold text-slate-800">{t("ask.confidenceWhy")}:</span>{" "}
          {result.confidence_reason}
        </div>
      )}

      {result.confidence < 0.6 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <p>{t("ask.lowConfidence")}</p>
          <Link to="/find-care?from=low-confidence-answer" className="mt-1 inline-flex font-semibold text-brand-700 hover:underline">
            {t("safety.findCare")} →
          </Link>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
        <span
          className={classNames(
            "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
            confidenceTone(result.confidence)
          )}
        >
          {t("common.confidence")} {formatConfidence(result.confidence)}
        </span>
        {sources.length > 0 ? (
          <span className="text-xs text-slate-500">
            {sources.length === 1
              ? t("ask.citedSourcesOne")
              : t("ask.citedSources", { count: formatNumber(sources.length) })}
          </span>
        ) : (
          <span className="text-xs text-slate-600">{t("ask.noSources")}</span>
        )}
      </div>

      {sources.length > 0 && (
        <ul className="space-y-1">
          {sources.map((src) => {
            const label = (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                <span className="min-w-0 flex-1 truncate font-medium text-slate-700">
                  {src.source_file}
                </span>
                {sourceDates(src).length > 0 && (
                  <span className="shrink-0 text-slate-400">
                    {sourceDates(src).map((d) => formatDate(d)).join(" · ")}
                  </span>
                )}
                {typeof src.page === "number" && (
                  <span className="shrink-0 text-slate-400">
                    {t("common.page")} {formatNumber(src.page)}
                  </span>
                )}
                {src.evidence_tier && (
                  <span className="shrink-0 rounded-full bg-white px-2 py-0.5 font-semibold text-slate-500 ring-1 ring-slate-200">
                    Evidence {src.evidence_tier}
                  </span>
                )}
              </>
            );
            const sourceTarget = `/documents?document=${encodeURIComponent(src.document_id || "")}${src.evidence_id ? `&evidence=${encodeURIComponent(src.evidence_id)}` : ""}`;
            const rowClass = "flex min-h-[44px] w-full items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-left text-xs text-slate-600 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500";
            return (
              <li key={src.source_file} className="rounded-md bg-slate-50">
                {onOpenSource ? (
                  <button
                    type="button"
                    onClick={() => onOpenSource(src)}
                    aria-label={t("ask.openSource", { file: src.source_file })}
                    className={rowClass}
                  >
                    {label}
                    <span className="shrink-0 text-brand-600" aria-hidden="true">→</span>
                  </button>
                ) : src.document_id ? (
                  <Link to={sourceTarget} className={rowClass}>
                    {label}
                    <span className="shrink-0 font-semibold text-brand-700">
                      {src.evidence_id ? "Open highlight →" : "Open source →"}
                    </span>
                  </Link>
                ) : (
                  <div className="flex items-center gap-2 rounded-md px-3 py-2 text-xs text-slate-600">
                    {label}
                  </div>
                )}
                {src.quote && (
                  <blockquote className="mx-3 mb-2 border-l-2 border-amber-400 pl-2 text-xs text-slate-600">
                    “{src.quote}”
                  </blockquote>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {result.rewritten_query && (
        <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
          <span className="font-semibold text-slate-700">{t("ask.retrievalQuery")}:</span>{" "}
          {result.rewritten_query}
        </div>
      )}
    </div>
  );
}

/** All dates a source was cited for, de-duplicated and sorted. */
function sourceDates(source: QASource): string[] {
  const dates = source.dates?.length ? source.dates : source.date ? [source.date] : [];
  return [...new Set(dates.filter(Boolean))].sort();
}

/**
 * Collapse citations to one entry per document.
 *
 * The server already returns one entry per document; this is defensive so a
 * cached or older response cannot re-inflate the count.
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
    if (existing.page == null && typeof source.page === "number") existing.page = source.page;
  }
  return [...byFile.values()];
}
