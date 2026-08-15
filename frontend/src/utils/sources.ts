import type { QASource, Timeline, Visit } from "../types/api";

/**
 * Resolves a citation to the document it came from.
 *
 * The match must be exact on the filename — a fuzzy match could open the
 * wrong record and make an answer look supported when it isn't. When several
 * pages share a filename (a multi-page scan) the page number, then the date,
 * disambiguates. Returns null rather than guessing.
 */
export function findVisitForSource(
  timeline: Timeline | null | undefined,
  source: QASource | null | undefined
): Visit | null {
  if (!timeline?.visits?.length || !source?.source_file) return null;

  const wanted = source.source_file.trim();
  if (!wanted) return null;

  const sameFile = timeline.visits.filter((visit) => visit._source?.file?.trim() === wanted);
  if (!sameFile.length) return null;
  if (sameFile.length === 1) return sameFile[0];

  if (typeof source.page === "number") {
    const byPage = sameFile.find((visit) => visit._source?.page === source.page);
    if (byPage) return byPage;
  }

  if (source.date) {
    const byDate = sameFile.find((visit) => visit.date === source.date);
    if (byDate) return byDate;
  }

  // Same file, no way to tell the pages apart: the first page is the safest
  // landing point, and the viewer shows which page it is.
  return sameFile[0];
}
