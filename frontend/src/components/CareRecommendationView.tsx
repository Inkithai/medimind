import type { CareProviderSearchResponse } from "../types/api";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";
import { ConsultationPack } from "./ConsultationPack";
import { EmptyState } from "./EmptyState";
import { ProviderResultCard } from "./ProviderResultCard";
import { StatusBadge } from "./StatusBadge";

export function CareRecommendationView({ result }: { result: CareProviderSearchResponse }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={`Live directory results for ${result.specialty.label}`}
          description={`Based on the selected record-level concern: ${result.clinical_flag.title}`}
        />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="success">{result.provenance.label}</StatusBadge>
            {result.location.resolved_area && <StatusBadge tone="neutral">Near {result.location.resolved_area}</StatusBadge>}
            <StatusBadge tone="brand">Preference: {result.availability.replace(/_/g, " ")}</StatusBadge>
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-800">Why these providers are shown</p>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">{result.ranking_method}</p>
          </div>
          <Alert variant="info" title="Not a diagnosis">
            {result.disclaimer}
          </Alert>
        </CardBody>
      </Card>

      {result.providers.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              title="No suitable live results found"
              description={
                result.no_results_message ||
                "The live directory did not return suitable providers. Try a broader city or area, or use the broader provider category."
              }
            />
          </CardBody>
        </Card>
      ) : (
        <section className="space-y-3" aria-label="Live provider recommendations">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="section-title">Providers returned by live directory</h2>
            <p className="text-xs text-slate-500">{result.providers.length} result(s) · confirm services and appointment availability directly</p>
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
