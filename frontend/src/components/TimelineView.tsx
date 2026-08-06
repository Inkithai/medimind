import type { Timeline, Visit } from "../types/api";
import {
  classNames,
  documentTypeLabel,
  formatConfidence,
  formatDate,
} from "../utils/format";
import { Card, CardBody, CardHeader } from "./Card";
import { EmptyState } from "./EmptyState";
import { BeakerIcon, FileIcon, LinkIcon, PillIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";

export function TimelineView({ timeline }: { timeline: Timeline }) {
  const hasVisits = timeline.visits.length > 0;

  return (
    <Card>
      <CardHeader
        title="Patient timeline"
        description={`${timeline.visits.length} visit(s) · ${timeline.medications_timeline.length} medication(s) · ${timeline.lab_results_timeline.length} lab result(s)`}
        icon={<TimelineIconSmall />}
      />
      <CardBody className="space-y-6">
        {timeline.known_allergies.length > 0 && (
          <div className="rounded-lg border border-red-100 bg-red-50/60 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-red-700">
              Known allergies
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {timeline.known_allergies.map((a) => (
                <StatusBadge key={a} tone="danger">
                  {a}
                </StatusBadge>
              ))}
            </div>
          </div>
        )}

        {!hasVisits ? (
          <EmptyState
            title="No visits in this timeline"
            description="Upload medical documents to build this patient's record."
          />
        ) : (
          <ol className="relative space-y-6 border-l-2 border-slate-100 pl-6">
            {timeline.visits.map((visit, idx) => (
              <TimelineVisit key={idx} visit={visit} />
            ))}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}

function TimelineVisit({ visit }: { visit: Visit }) {
  const lowConfidence = visit.overall_confidence < 0.6;
  return (
    <li className="relative">
      <span
        className={classNames(
          "absolute -left-[31px] top-1 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-white",
          lowConfidence ? "bg-amber-500" : "bg-brand-500"
        )}
      >
        <span className="h-2 w-2 rounded-full bg-white" />
      </span>

      <div className="rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          <div className="flex items-center gap-2">
            <StatusBadge tone="brand">{documentTypeLabel(visit.document_type)}</StatusBadge>
            <span className="text-sm font-semibold text-slate-800">
              {formatDate(visit.date)}
            </span>
            {visit.provider_or_doctor && (
              <span className="text-sm text-slate-500">· {visit.provider_or_doctor}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span
              className={classNames(
                "text-xs font-medium",
                lowConfidence ? "text-amber-600" : "text-slate-400"
              )}
            >
              confidence {formatConfidence(visit.overall_confidence)}
            </span>
            {visit.document_url && (
              <a
                href={visit.document_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline"
              >
                <LinkIcon className="h-3.5 w-3.5" /> source
              </a>
            )}
          </div>
        </div>

        <div className="space-y-4 px-4 py-4">
          {visit.patient_name && (
            <p className="text-sm text-slate-600">
              <span className="text-slate-400">Patient:</span> {visit.patient_name}
            </p>
          )}

          {visit.illegible_or_low_confidence_fields.length > 0 && (
            <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <span className="font-semibold">Low-confidence fields:</span>{" "}
              {visit.illegible_or_low_confidence_fields.join("; ")}
            </div>
          )}

          {visit.medications.length > 0 && (
            <div>
              <SectionLabel icon={<PillIcon className="h-4 w-4" />}>
                Medications ({visit.medications.length})
              </SectionLabel>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {visit.medications.map((med, i) => (
                  <div
                    key={i}
                    className="rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2 text-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium text-slate-800">{med.name}</p>
                      <StatusBadge
                        tone={med.confidence >= 0.85 ? "success" : med.confidence >= 0.6 ? "warning" : "danger"}
                      >
                        {formatConfidence(med.confidence)}
                      </StatusBadge>
                    </div>
                    {med.ingredients.length > 0 && (
                      <p className="mt-0.5 text-xs text-slate-500">
                        {med.ingredients.join(", ")}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-slate-600">
                      {[med.dosage, med.frequency, med.duration].filter(Boolean).join(" · ") || "—"}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {visit.lab_results.length > 0 && (
            <div>
              <SectionLabel icon={<BeakerIcon className="h-4 w-4" />}>
                Lab results ({visit.lab_results.length})
              </SectionLabel>
              <div className="mt-2 overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                      <th className="py-1.5 pr-3 font-medium">Test</th>
                      <th className="py-1.5 pr-3 font-medium">Value</th>
                      <th className="py-1.5 pr-3 font-medium">Range</th>
                      <th className="py-1.5 pr-3 font-medium">Flag</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visit.lab_results.map((lab, i) => (
                      <tr key={i}>
                        <td className="py-1.5 pr-3 font-medium text-slate-700">
                          {lab.test_name}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-600">
                          {lab.value}
                          {lab.unit ? ` ${lab.unit}` : ""}
                        </td>
                        <td className="py-1.5 pr-3 text-slate-500">
                          {lab.reference_range || "—"}
                        </td>
                        <td className="py-1.5 pr-3">
                          <StatusBadge
                            tone={
                              lab.flag === "normal"
                                ? "success"
                                : lab.flag === "high"
                                ? "danger"
                                : lab.flag === "low"
                                ? "info"
                                : "neutral"
                            }
                          >
                            {lab.flag}
                          </StatusBadge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {visit.allergies_noted.length > 0 && (
            <div>
              <SectionLabel>Allergies noted</SectionLabel>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {visit.allergies_noted.map((a) => (
                  <StatusBadge key={a} tone="danger">
                    {a}
                  </StatusBadge>
                ))}
              </div>
            </div>
          )}

          {visit.clinical_notes && (
            <div>
              <SectionLabel>Clinical notes</SectionLabel>
              <p className="mt-1 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
                {visit.clinical_notes}
              </p>
            </div>
          )}

          <p className="flex items-center gap-1.5 text-xs text-slate-400">
            <FileIcon className="h-3.5 w-3.5" />
            {visit._source.file} · {visit._source.method === "text_layer" ? "Digital PDF" : "Scanned or photo"}
            {visit._source.page ? ` · page ${visit._source.page}` : ""}
          </p>
        </div>
      </div>
    </li>
  );
}

function SectionLabel({
  children,
  icon,
}: {
  children: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
      {icon}
      {children}
    </p>
  );
}

function TimelineIconSmall() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-5 w-5">
      <circle cx="12" cy="5" r="2" />
      <circle cx="12" cy="19" r="2" />
      <circle cx="5" cy="12" r="2" />
      <circle cx="19" cy="12" r="2" />
      <path d="M12 7v10M7 12h10" strokeLinecap="round" />
    </svg>
  );
}
