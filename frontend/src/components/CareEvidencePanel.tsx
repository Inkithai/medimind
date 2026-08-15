import type { CarePathwayEvidence, ClinicalFlag, SpecialtyRoute } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
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

const EVIDENCE_KEYS: Record<CarePathwayEvidence["kind"], string> = {
  medication: "care.evidenceMedication",
  allergy: "care.evidenceAllergy",
  lab_result: "care.evidenceLab",
  lab_trend: "care.evidenceTrend",
  visit: "care.evidenceVisit",
  document: "care.evidenceDocument",
  cross_check: "care.evidenceSafety",
};

function route(flag: ClinicalFlag): SpecialtyRoute {
  return flag.specialty.primary || {
    id: flag.specialty.id,
    label: flag.specialty.label,
    provider_query: flag.specialty.provider_query,
  };
}

export function CareEvidencePanel({ flag }: { flag: ClinicalFlag }) {
  const { t, formatNumber } = useI18n();
  const evidence = flag.pathway_evidence || [];
  const primary = route(flag);
  const alternative = flag.specialty.alternative;

  return (
    <Card>
      <CardHeader
        title={t("care.whySuggested")}
        description={t("care.recordInterpretation")}
      />
      <CardBody className="space-y-5">
        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold text-slate-900">{flag.title}</p>
            <StatusBadge tone={flag.trigger === "high_risk" ? "danger" : "warning"}>
              {flag.trigger === "high_risk" ? t("care.highRiskSignal") : t("care.verificationRecommended")}
            </StatusBadge>
            {typeof flag.confidence === "number" && (
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(flag.confidence)}`}>
                {t("care.confidenceValue", { value: formatConfidence(flag.confidence) })}
              </span>
            )}
          </div>
          {flag.evidence && <p className="mt-2 text-sm leading-relaxed text-slate-600">{flag.evidence}</p>}
          {flag.source && <p className="mt-2 text-xs text-slate-500">{t("care.flagSource", { source: flag.source })}</p>}
        </div>

        <section aria-labelledby="care-evidence-title">
          <h3 id="care-evidence-title" className="text-sm font-semibold text-slate-800">{t("care.evidenceTitle")}</h3>
          {evidence.length === 0 ? (
            <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600">
              {t("care.noEvidence")}
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {evidence.map((item, index) => (
                <li key={`${item.kind}-${item.label}-${item.source_file || ""}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t(EVIDENCE_KEYS[item.kind])}</p>
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
                      {item.source_file || t("care.sourceDocument")}
                      {item.date ? ` · ${formatDate(item.date)}` : ""}
                      {item.page ? ` · ${t("common.page")} ${formatNumber(item.page)}` : ""}
                    </p>
                  )}
                  {validSourceUrl(item.document_url) && (
                    <a
                      href={item.document_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-flex text-xs font-medium text-brand-700 hover:text-brand-800 hover:underline"
                    >
                      {t("care.viewSource")}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-brand-100 bg-brand-50/60 p-4" aria-labelledby="suggested-reviewer-title">
          <p id="suggested-reviewer-title" className="text-xs font-semibold uppercase tracking-wide text-brand-700">{t("care.suggestedReviewer")}</p>
          <p className="mt-1 text-base font-semibold text-brand-950">{primary.label}</p>
          <p className="mt-2 text-sm leading-relaxed text-slate-700">
            {flag.care_route_explanation || flag.specialty.reason}
          </p>
          {flag.specialty.reason && flag.care_route_explanation && flag.specialty.reason !== flag.care_route_explanation && (
            <p className="mt-2 text-xs leading-relaxed text-slate-600">{t("care.whyRoute", { reason: flag.specialty.reason })}</p>
          )}
        </section>

        {alternative && (
          <section className="rounded-xl border border-slate-200 bg-white p-4" aria-labelledby="broader-alternative-title">
            <p id="broader-alternative-title" className="text-xs font-semibold uppercase tracking-wide text-slate-600">{t("care.broaderAlternative")}</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{alternative.label}</p>
            <p className="mt-1 text-sm text-slate-600">
              {t("care.broaderAlternativeBody")}
            </p>
          </section>
        )}

        <Alert variant="info" title={t("common.notDiagnosis")}>
          {t("care.routeDisclaimer")}
        </Alert>
      </CardBody>
    </Card>
  );
}
