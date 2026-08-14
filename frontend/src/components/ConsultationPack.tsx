import type { ConsultationPack as ConsultationPackData } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
import { confidenceTone, formatConfidence, formatDate } from "../utils/format";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";

function validSourceUrl(value: string | undefined): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

function SourceLink({ url }: { url?: string }) {
  const { t } = useI18n();
  if (!validSourceUrl(url)) return null;
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="mt-1 inline-flex text-xs font-medium text-brand-700 hover:text-brand-800 hover:underline"
    >
      {t("care.viewDocument")}
    </a>
  );
}

export function ConsultationPack({ pack }: { pack: ConsultationPackData }) {
  const { t, formatNumber } = useI18n();
  const hasContent =
    pack.documents_to_bring.length > 0 ||
    pack.medication_records_to_discuss.length > 0 ||
    pack.allergies.length > 0 ||
    pack.relevant_lab_points.length > 0 ||
    pack.low_confidence_items.length > 0 ||
    pack.clinician_questions.length > 0;

  if (!hasContent) return null;

  return (
    <Card>
      <CardHeader
        title={t("care.prepareTitle")}
        description={t("care.prepareBody")}
      />
      <CardBody className="space-y-5">
        {pack.documents_to_bring.length > 0 && (
          <Section title={t("care.documentsToBring")}>
            <ul className="space-y-2">
              {pack.documents_to_bring.map((document, index) => (
                <li key={`${document.source_file}-${index}`} className="rounded-lg border border-slate-200 bg-white p-3">
                  <p className="text-sm font-semibold text-slate-800">✓ {document.source_file}</p>
                  <p className="mt-1 text-sm text-slate-600">{document.reason}</p>
                  {(document.date || document.page) && (
                    <p className="mt-1 text-xs text-slate-500">
                      {document.date ? formatDate(document.date) : ""}
                      {document.date && document.page ? " · " : ""}
                      {document.page ? `${t("common.page")} ${formatNumber(document.page)}` : ""}
                    </p>
                  )}
                  <SourceLink url={document.document_url} />
                </li>
              ))}
            </ul>
          </Section>
        )}

        {pack.medication_records_to_discuss.length > 0 && (
          <Section title={t("care.medicationsToDiscuss")}>
            <ul className="space-y-2">
              {pack.medication_records_to_discuss.map((medication, index) => (
                <li key={`${medication.name}-${medication.source_file || ""}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50/60 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-slate-800">{medication.name}</p>
                      {(medication.dose || medication.frequency) && (
                        <p className="mt-1 text-sm text-slate-600">{[medication.dose, medication.frequency].filter(Boolean).join(" · ")}</p>
                      )}
                    </div>
                    {typeof medication.confidence === "number" && (
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(medication.confidence)}`}>
                        {formatConfidence(medication.confidence)}
                      </span>
                    )}
                  </div>
                  {(medication.source_file || medication.date || medication.page) && (
                    <p className="mt-2 text-xs text-slate-500">
                      {medication.source_file || t("care.sourceDocument")}
                      {medication.date ? ` · ${formatDate(medication.date)}` : ""}
                      {medication.page ? ` · ${t("common.page")} ${formatNumber(medication.page)}` : ""}
                    </p>
                  )}
                  <SourceLink url={medication.document_url} />
                </li>
              ))}
            </ul>
          </Section>
        )}

        {pack.allergies.length > 0 && (
          <Section title={t("common.allergies")}>
            <ul className="space-y-2">
              {pack.allergies.map((allergy, index) => (
                <li key={`${allergy.allergen}-${allergy.source_file || ""}-${index}`} className="rounded-lg border border-red-100 bg-red-50/60 p-3">
                  <p className="text-sm font-semibold text-red-900">{allergy.allergen}</p>
                  {(allergy.source_file || allergy.date || allergy.page) && (
                    <p className="mt-1 text-xs text-red-800/80">
                      {allergy.source_file || t("care.sourceDocument")}
                      {allergy.date ? ` · ${formatDate(allergy.date)}` : ""}
                      {allergy.page ? ` · ${t("common.page")} ${formatNumber(allergy.page)}` : ""}
                    </p>
                  )}
                  <SourceLink url={allergy.document_url} />
                </li>
              ))}
            </ul>
          </Section>
        )}

        {pack.relevant_lab_points.length > 0 && (
          <Section title={t("care.relevantLabs")}>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <caption className="sr-only">{t("care.relevantLabs")}</caption>
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">{t("common.test")}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t("common.value")}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t("common.source")}</th>
                    <th scope="col" className="px-3 py-2 font-medium">{t("care.documentColumn")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {pack.relevant_lab_points.map((point, index) => (
                    <tr key={`${point.test}-${point.source_file || ""}-${point.date || ""}-${index}`}>
                      <td className="px-3 py-2 font-medium text-slate-800">{point.test}</td>
                      <td className="px-3 py-2 text-slate-700">{point.value}{point.unit ? ` ${point.unit}` : ""}</td>
                      <td className="px-3 py-2 text-xs text-slate-500">
                        {point.source_file || "—"}{point.date ? ` · ${formatDate(point.date)}` : ""}
                      </td>
                      <td className="px-3 py-2 text-xs">
                        {validSourceUrl(point.document_url) ? (
                          <a href={point.document_url} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">{t("care.viewDocument")}</a>
                        ) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {pack.low_confidence_items.length > 0 && (
          <Section title={t("care.informationToVerify")}>
            <ul className="space-y-2">
              {pack.low_confidence_items.map((item, index) => (
                <li key={`${item.type}-${item.source_file || ""}-${index}`} className="rounded-lg border border-amber-200 bg-amber-50/70 p-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="text-sm font-semibold text-amber-900">⚠ {item.label}</p>
                      <p className="mt-1 text-sm text-amber-900/80">{item.reason}</p>
                    </div>
                    {typeof item.confidence === "number" && (
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(item.confidence)}`}>
                        {t("care.confidenceValue", { value: formatConfidence(item.confidence) })}
                      </span>
                    )}
                  </div>
                  {(item.source_file || item.date || item.page) && (
                    <p className="mt-2 text-xs text-amber-900/70">
                      {item.source_file || t("care.sourceDocument")}
                      {item.date ? ` · ${formatDate(item.date)}` : ""}
                      {item.page ? ` · ${t("common.page")} ${formatNumber(item.page)}` : ""}
                    </p>
                  )}
                  <SourceLink url={item.document_url} />
                </li>
              ))}
            </ul>
          </Section>
        )}

        {pack.clinician_questions.length > 0 && (
          <Section title={t("care.clinicianQuestions")}>
            <ul className="space-y-2">
              {pack.clinician_questions.map((question) => (
                <li key={question} className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">• {question}</li>
              ))}
            </ul>
          </Section>
        )}

        <Alert variant="info" title={t("care.important")}>
          {pack.disclaimer}
        </Alert>
      </CardBody>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-slate-800">{title}</h3>
      {children}
    </section>
  );
}
