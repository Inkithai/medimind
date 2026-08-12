import type { CarePathwayEvidence, ClinicalFlag, SpecialtyRoute } from "../types/api";
import { confidenceTone, formatConfidence, formatDate } from "../utils/format";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";
import { StatusBadge } from "./StatusBadge";

function validSourceUrl(value: string | undefined): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function evidenceHeading(kind: CarePathwayEvidence["kind"]): string {
  switch (kind) {
    case "medication":
      return "Medication record";
    case "allergy":
      return "Recorded allergy";
    case "lab_result":
      return "Lab result";
    case "lab_trend":
      return "Lab trend";
    case "visit":
      return "Visit";
    case "document":
      return "Document";
    case "cross_check":
      return "Safety check";
  }
}

function route(flag: ClinicalFlag): SpecialtyRoute {
  return flag.specialty.primary || {
    id: flag.specialty.id,
    label: flag.specialty.label,
    provider_query: flag.specialty.provider_query,
  };
}

export function CareEvidencePanel({ flag }: { flag: ClinicalFlag }) {
  const evidence = flag.pathway_evidence || [];
  const primary = route(flag);
  const alternative = flag.specialty.alternative;

  return (
    <Card>
      <CardHeader
        title="Why MediMind suggests this care route"
        description="This is a record-level interpretation, not a diagnosis."
      />
      <CardBody className="space-y-5">
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-900">{flag.title}</p>
            <StatusBadge tone={flag.trigger === "high_risk" ? "danger" : "warning"}>
              {flag.trigger === "high_risk" ? "high-risk signal" : "verification recommended"}
            </StatusBadge>
            {typeof flag.confidence === "number" && (
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(flag.confidence)}`}>
                confidence {formatConfidence(flag.confidence)}
              </span>
            )}
          </div>
          {flag.evidence && <p className="mt-2 text-sm leading-relaxed text-slate-600">{flag.evidence}</p>}
          {flag.source && <p className="mt-2 text-xs text-slate-500">Flag source: {flag.source}</p>}
        </div>

        <section aria-label="Evidence from your record">
          <h3 className="text-sm font-semibold text-slate-800">Evidence from your record</h3>
          {evidence.length === 0 ? (
            <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
              No additional source-linked evidence is available for this flag.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {evidence.map((item, index) => (
                <li key={`${item.kind}-${item.label}-${item.source_file || ""}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{evidenceHeading(item.kind)}</p>
                      <p className="mt-0.5 text-sm font-medium text-slate-800">{item.label}</p>
                      {item.details && <p className="mt-1 text-sm text-slate-600">{item.details}</p>}
                    </div>
                    {typeof item.confidence === "number" && (
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(item.confidence)}`}>
                        {formatConfidence(item.confidence)}
                      </span>
                    )}
                  </div>
                  {(item.source_file || item.date || item.page) && (
                    <p className="mt-2 text-xs text-slate-500">
                      {item.source_file || "Source document"}
                      {item.date ? ` · ${formatDate(item.date)}` : ""}
                      {item.page ? ` · page ${item.page}` : ""}
                    </p>
                  )}
                  {validSourceUrl(item.document_url) && (
                    <a
                      href={item.document_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex text-xs font-medium text-brand-700 hover:text-brand-800 hover:underline"
                    >
                      View source document
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-brand-100 bg-brand-50/60 p-4" aria-label="Suggested care route">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-700">Suggested first reviewer</p>
          <p className="mt-1 text-base font-semibold text-brand-950">{primary.label}</p>
          <p className="mt-2 text-sm leading-relaxed text-slate-700">
            {flag.care_route_explanation || flag.specialty.reason}
          </p>
          {flag.specialty.reason && flag.care_route_explanation && flag.specialty.reason !== flag.care_route_explanation && (
            <p className="mt-2 text-xs leading-relaxed text-slate-600">Why this route: {flag.specialty.reason}</p>
          )}
        </section>

        {alternative && (
          <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label="Broader alternative">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Broader alternative</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{alternative.label}</p>
            <p className="mt-1 text-sm text-slate-600">
              A broader route is available if the primary specialty is not accessible or the record does not support a narrower route.
            </p>
          </section>
        )}

        <Alert variant="info" title="Not a diagnosis">
          MediMind identifies potential issues and uncertainty in uploaded records. A care route is intended to help find an appropriate professional to review the original information.
        </Alert>
      </CardBody>
    </Card>
  );
}
