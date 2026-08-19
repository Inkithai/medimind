import type { LiveProvider } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
import { Card, CardBody } from "./Card";
import { StatusBadge } from "./StatusBadge";

function validExternalUrl(value: string | null | undefined): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:";
  } catch {
    return false;
  }
}

export function ProviderResultCard({ provider, index }: { provider: LiveProvider; index: number }) {
  const { t, formatNumber } = useI18n();
  // External directories may omit any optional field. Render only values that
  // are actually present; an omitted value must never become a placeholder
  // score, rating, distance, or availability claim.
  const rating = typeof provider.rating === "number" ? provider.rating : null;
  const distanceKm = typeof provider.distance_km === "number" ? provider.distance_km : null;
  const hours = Array.isArray(provider.opening_hours) ? provider.opening_hours : [];

  return (
    <Card>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">
                {formatNumber(index + 1)}
              </span>
              <h3 className="text-base font-semibold text-slate-900">{provider.name}</h3>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {provider.provider_type && (
                <StatusBadge tone="brand">{provider.provider_type}</StatusBadge>
              )}
              {provider.source_specialties.map((specialty) => (
                <StatusBadge key={specialty} tone="success">
                  {specialty}
                </StatusBadge>
              ))}
              {provider.open_now === true && (
                <StatusBadge tone="success">{t("care.reportedOpen")}</StatusBadge>
              )}
            </div>
          </div>
          <span
            className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600"
            title={t("care.directoryScoreTitle")}
          >
            {t("care.directoryMatch", {
              score: formatNumber(provider.ranking.score, { maximumFractionDigits: 0 }),
            })}
          </span>
        </div>

        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
          {provider.address && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {t("care.address")}
              </dt>
              <dd className="mt-0.5 text-slate-700">{provider.address}</dd>
            </div>
          )}
          {distanceKm !== null && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {t("care.distance")}
              </dt>
              <dd className="mt-0.5 text-slate-700">
                {t("care.distanceApprox", {
                  distance: formatNumber(distanceKm, { maximumFractionDigits: 1 }),
                })}
              </dd>
            </div>
          )}
          {rating !== null && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {t("care.rating")}
              </dt>
              <dd className="mt-0.5 text-slate-700">
                {t("care.ratingValue", {
                  rating: formatNumber(rating, {
                    minimumFractionDigits: 1,
                    maximumFractionDigits: 1,
                  }),
                })}
                {typeof provider.rating_count === "number"
                  ? ` (${t("care.ratingCount", { count: formatNumber(provider.rating_count) })})`
                  : ""}
              </dd>
            </div>
          )}
          {provider.phone && (
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-400">
                {t("care.contact")}
              </dt>
              <dd className="mt-0.5 text-slate-700">
                <a
                  className="text-brand-700 hover:underline"
                  href={`tel:${provider.phone.replace(/\s/g, "")}`}
                >
                  {provider.phone}
                </a>
              </dd>
            </div>
          )}
        </dl>

        {hours.length > 0 && (
          <details className="rounded-lg bg-slate-50 px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-slate-700">
              {t("care.directoryHours")}
            </summary>
            <ul className="mt-2 space-y-1 text-xs text-slate-600">
              {hours.map((hours) => (
                <li key={hours}>{hours}</li>
              ))}
            </ul>
          </details>
        )}

        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          {validExternalUrl(provider.map_url) && (
            <a
              href={provider.map_url}
              target="_blank"
              rel="noreferrer"
              className="btn-secondary text-xs"
            >
              {t("care.mapDirections")}
            </a>
          )}
          {validExternalUrl(provider.website_url) && provider.website_url !== provider.map_url && (
            <a
              href={provider.website_url}
              target="_blank"
              rel="noreferrer"
              className="btn-secondary text-xs"
            >
              {t("care.providerWebsite")}
            </a>
          )}
        </div>

        <details className="rounded-lg border border-slate-100 px-3 py-2">
          <summary className="cursor-pointer text-xs font-medium text-slate-500">
            {t("care.whyDirectoryMatch")}
          </summary>
          <ul className="mt-2 space-y-1 text-xs leading-relaxed text-slate-600">
            <li>• {provider.ranking.specialty_relevance}</li>
            <li>• {provider.ranking.distance}</li>
            <li>• {provider.ranking.rating}</li>
            <li>• {provider.ranking.availability}</li>
          </ul>
          {provider.ranking.components && provider.ranking.components.length > 0 && (
            <dl className="mt-3 space-y-1 border-t border-slate-100 pt-2 text-xs text-slate-600">
              {provider.ranking.components.map((component) => {
                const label = {
                  specialty_relevance: t("care.rankingComponentSpecialty"),
                  distance: t("care.rankingComponentDistance"),
                  rating: t("care.rankingComponentRating"),
                  availability: t("care.rankingComponentAvailability"),
                }[component.signal];
                return (
                  <div
                    key={component.signal}
                    className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5"
                  >
                    <dt className="font-medium text-slate-700">
                      {label}
                      <span className="ml-2 font-normal text-slate-500">
                        {t("care.rankingWeightContribution", {
                          weight: formatNumber(component.weight, { maximumFractionDigits: 0 }),
                          contribution: formatNumber(component.contribution, {
                            maximumFractionDigits: 1,
                          }),
                        })}
                      </span>
                    </dt>
                    <dd className="text-slate-500">{component.explanation}</dd>
                  </div>
                );
              })}
            </dl>
          )}
        </details>
      </CardBody>
    </Card>
  );
}
