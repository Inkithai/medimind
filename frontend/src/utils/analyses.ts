/**
 * AI analysis log helpers.
 *
 * The log mixes two record shapes: document extractions (whose confidence
 * lives on the record, and — for older/derived payloads — inside
 * `result.confidence_score`) and saved Q&A answers (whose confidence is
 * only ever inside the result). Reading just `record.confidence` silently
 * dropped the badge for the second kind, which made a scored answer look
 * unscored.
 *
 * Confidence is also normalized here: a value above 1 is a percentage
 * (0-100) and is converted to the 0-1 fraction the formatters expect, so
 * a 92% answer can never render as "9200%".
 */
import type { AnalysisLogRecord } from "../types/api";

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function asFraction(value: unknown): number | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  const fraction = value > 1 ? value / 100 : value;
  if (fraction < 0) return null;
  return Math.min(fraction, 1);
}

/** Confidence for one analysis card as a 0-1 fraction, or null if unscored. */
export function analysisConfidence(record: AnalysisLogRecord): number | null {
  const result = asRecord(record.result);
  const candidates = [record.confidence, result.confidence_score, result.confidence];
  for (const candidate of candidates) {
    const fraction = asFraction(candidate);
    if (fraction !== null) return fraction;
  }
  return null;
}

/** Entity counts persisted for an extraction, defaulting every slot to 0. */
export function analysisCounts(record: AnalysisLogRecord): Record<string, number> {
  const counts = asRecord(asRecord(record.result).persisted_counts);
  const normalized: Record<string, number> = {};
  for (const [key, value] of Object.entries(counts)) {
    normalized[key] = typeof value === "number" && !Number.isNaN(value) ? value : 0;
  }
  return normalized;
}

/** How many extracted pages an extraction entry covers (at least 1). */
export function analysisPageCount(record: AnalysisLogRecord): number {
  const value = asRecord(record.result).page_count;
  return typeof value === "number" && value > 1 ? Math.round(value) : 1;
}

/**
 * Drop repeated ids, keeping the first occurrence.
 *
 * The backend already emits one entry per uploaded document, but a stale
 * cache or a legacy deployment can still return two rows with the same id;
 * rendering those as sibling cards duplicates React keys and tells the user
 * the same document was analysed twice.
 */
export function dedupeAnalyses(records: AnalysisLogRecord[]): AnalysisLogRecord[] {
  const seen = new Set<string>();
  const unique: AnalysisLogRecord[] = [];
  for (const record of records || []) {
    const id = String(record?.id ?? "");
    if (id && seen.has(id)) continue;
    if (id) seen.add(id);
    unique.push(record);
  }
  return unique;
}
