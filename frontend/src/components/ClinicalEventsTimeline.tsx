import { Link } from "react-router-dom";
import type { EvidenceRegion, Timeline } from "../types/api";
import { formatDate } from "../utils/format";
import { StatusBadge } from "./StatusBadge";

interface ClinicalEventRow {
  key: string;
  kind: "diagnosis" | "symptom" | "procedure" | "vital" | "imaging";
  date: string | null;
  title: string;
  summary: string;
  sourceFile: string | null;
  documentId: string;
  evidence?: EvidenceRegion;
}

const KIND_LABELS: Record<ClinicalEventRow["kind"], string> = {
  diagnosis: "Documented diagnosis",
  symptom: "Symptom / sign",
  procedure: "Procedure",
  vital: "Vital sign",
  imaging: "Imaging",
};

function rowsFromTimeline(timeline: Timeline): ClinicalEventRow[] {
  const rows: ClinicalEventRow[] = [];
  for (const [index, item] of (timeline.diagnoses_timeline || []).entries()) {
    rows.push({
      key: `diagnosis-${item.document_id}-${index}`,
      kind: "diagnosis",
      date: item.date,
      title: item.name,
      summary: [item.status, item.code ? `code ${item.code}` : null].filter(Boolean).join(" · "),
      sourceFile: item.source_file,
      documentId: item.document_id,
      evidence: item.evidence?.[0],
    });
  }
  for (const [index, item] of (timeline.symptoms_timeline || []).entries()) {
    rows.push({
      key: `symptom-${item.document_id}-${index}`,
      kind: "symptom",
      date: item.date,
      title: item.name,
      summary: [item.severity, item.status].filter(Boolean).join(" · "),
      sourceFile: item.source_file,
      documentId: item.document_id,
      evidence: item.evidence?.[0],
    });
  }
  for (const [index, item] of (timeline.procedures_timeline || []).entries()) {
    rows.push({
      key: `procedure-${item.document_id}-${index}`,
      kind: "procedure",
      date: item.date,
      title: item.name,
      summary: [item.status, item.body_site, item.outcome].filter(Boolean).join(" · "),
      sourceFile: item.source_file,
      documentId: item.document_id,
      evidence: item.evidence?.[0],
    });
  }
  for (const [index, item] of (timeline.vital_signs_timeline || []).entries()) {
    rows.push({
      key: `vital-${item.document_id}-${index}`,
      kind: "vital",
      date: item.date,
      title: item.name,
      summary: `${item.value}${item.unit ? ` ${item.unit}` : ""}`,
      sourceFile: item.source_file,
      documentId: item.document_id,
      evidence: item.evidence?.[0],
    });
  }
  for (const [index, item] of (timeline.imaging_results_timeline || []).entries()) {
    rows.push({
      key: `imaging-${item.document_id}-${index}`,
      kind: "imaging",
      date: item.date,
      title: [item.study_type, item.body_site].filter(Boolean).join(" · "),
      summary: item.impression || item.findings,
      sourceFile: item.source_file,
      documentId: item.document_id,
      evidence: item.evidence?.[0],
    });
  }
  return rows.sort((a, b) => {
    if (!a.date && !b.date) return 0;
    if (!a.date) return 1;
    if (!b.date) return -1;
    const aTime = Date.parse(a.date);
    const bTime = Date.parse(b.date);
    if (!Number.isNaN(aTime) && !Number.isNaN(bTime)) return bTime - aTime;
    return b.date.localeCompare(a.date);
  });
}

export function ClinicalEventsTimeline({ timeline }: { timeline: Timeline }) {
  const rows = rowsFromTimeline(timeline);
  if (rows.length === 0) return null;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Longitudinal clinical events</h2>
          <p className="mt-1 text-xs text-slate-500">
            Event-specific dates from documented diagnoses, symptoms, procedures, vital signs, and imaging.
          </p>
        </div>
        <span className="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-semibold text-brand-700">
          {rows.length} event{rows.length === 1 ? "" : "s"}
        </span>
      </div>

      <ol className="mt-4 space-y-2 border-l-2 border-slate-100 pl-5">
        {rows.map((row) => (
          <li key={row.key} className="relative rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-3">
            <span className="absolute -left-[26px] top-4 h-3 w-3 rounded-full bg-brand-500 ring-4 ring-white" />
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone={row.kind === "diagnosis" ? "brand" : "neutral"}>
                    {KIND_LABELS[row.kind]}
                  </StatusBadge>
                  <p className="font-medium text-slate-800">{row.title}</p>
                </div>
                {row.summary && <p className="mt-1 text-xs leading-relaxed text-slate-600">{row.summary}</p>}
                <p className="mt-1 text-[11px] text-slate-400">Source: {row.sourceFile || "unknown document"}</p>
              </div>
              <div className="text-right">
                <p className="text-xs font-semibold text-slate-600">{formatDate(row.date)}</p>
                {row.documentId && (
                  <Link
                    to={`/documents?document=${encodeURIComponent(row.documentId)}${row.evidence?.evidence_id ? `&evidence=${encodeURIComponent(row.evidence.evidence_id)}` : ""}`}
                    className="mt-1 inline-block text-[11px] font-semibold text-brand-700 hover:underline"
                  >
                    {row.evidence?.evidence_id ? "View evidence →" : "Open source →"}
                  </Link>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>

      <p className="mt-4 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-relaxed text-slate-500">
        These are facts documented in uploaded records, not diagnoses or interpretations generated by MediMind. Confirm clinical history with a qualified professional.
      </p>
    </section>
  );
}
