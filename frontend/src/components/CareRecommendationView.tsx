import type { CareProviderSearchResponse } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";
import { ConsultationPack } from "./ConsultationPack";
import { EmptyState } from "./EmptyState";
import { ProviderResultCard } from "./ProviderResultCard";
import { StatusBadge } from "./StatusBadge";

export function CareRecommendationView({ result }: { result: CareProviderSearchResponse }) {
  const { t, formatNumber } = useI18n();
  const availabilityLabel = {
    any: t("care.anyConsultation"),
    today: t("care.today"),
    this_week: t("care.thisWeek"),
    evenings: t("care.evenings"),
    weekends: t("care.weekends"),
  }[result.availability] || result.availability;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t("care.liveResultsFor", { specialty: result.specialty.label })}
          description={t("care.selectedConcern", { concern: result.clinical_flag.title })}
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="success">{result.provenance.label}</StatusBadge>
            {result.location.resolved_area && <StatusBadge tone="neutral">{t("care.nearArea", { area: result.location.resolved_area })}</StatusBadge>}
            <StatusBadge tone="brand">{t("care.preferenceValue", { preference: availabilityLabel })}</StatusBadge>
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-800">{t("care.whyProviders")}</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{result.ranking_method}</p>
          </div>
          <Alert variant="info" title={t("common.notDiagnosis")}>
            {result.disclaimer}
          </Alert>
        </CardBody>
      </Card>

      {result.providers.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              title={t("care.noLiveResults")}
              description={
                result.no_results_message ||
                t("care.noLiveResultsBody")
              }
            />
          </CardBody>
        </Card>
      ) : (
        <section className="space-y-3" aria-labelledby="live-providers-title">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="live-providers-title" className="section-title">{t("care.providersTitle")}</h2>
            <p className="text-xs text-slate-600">{t("care.resultCountConfirm", { count: formatNumber(result.providers.length) })}</p>
          </div>
          {result.providers.map((provider, index) => (
            <ProviderResultCard key={provider.source_provider_id || `${provider.name}-${index}`} provider={provider} index={index} />
          ))}
        </section>
      )}

      {result.consultation_pack && <ConsultationPack pack={result.consultation_pack} />}
    </div>
  );
}
