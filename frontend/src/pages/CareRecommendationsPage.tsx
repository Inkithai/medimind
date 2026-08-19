import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { CareRecommendationView } from "../components/CareRecommendationView";
import { CareEvidencePanel } from "../components/CareEvidencePanel";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LocationAutocompleteInput } from "../components/location";
import { LoadingState, Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type {
  AvailabilityPreference,
  CareProviderSearchResponse,
  CareRecommendationContext,
} from "../types/api";
import type { LocationPlace } from "../types/location";
import { confidenceTone, formatConfidence } from "../utils/format";
import type { EmbeddedPageProps } from "../components/TabBar";

const SEARCH_RADII_KM = [5, 10, 20, 50] as const;

export function CareRecommendationsPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t, formatNumber } = useI18n();
  const availabilityOptions: Array<{ value: AvailabilityPreference; label: string }> = [
    { value: "any", label: t("care.anyConsultation") },
    { value: "today", label: t("care.today") },
    { value: "this_week", label: t("care.thisWeek") },
    { value: "evenings", label: t("care.evenings") },
    { value: "weekends", label: t("care.weekends") },
  ];
  const [context, setContext] = useState<CareRecommendationContext | null>(null);
  const [selectedFlagId, setSelectedFlagId] = useState("");
  const [location, setLocation] = useState("");
  const [selectedPlace, setSelectedPlace] = useState<LocationPlace | null>(null);
  const [radiusKm, setRadiusKm] = useState<number>(10);
  const [availability, setAvailability] = useState<AvailabilityPreference>("any");
  const [result, setResult] = useState<CareProviderSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getCareRecommendationContext(credentials);
      setContext(data);
      setSelectedFlagId((current) => current || data.flags[0]?.id || "");
    } catch (err) {
      setContext(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load, reloadKey]);

  async function search() {
    if (!selectedFlagId || location.trim().length < 2) return;
    setSearching(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.searchCareProviders(credentials, {
        flag_id: selectedFlagId,
        // A picked suggestion sends its precise map name + coordinates, so
        // the backend skips its own geocoding of ambiguous free text.
        location: selectedPlace ? selectedPlace.displayName : location.trim(),
        availability,
        radius_km: radiusKm,
        latitude: selectedPlace?.latitude,
        longitude: selectedPlace?.longitude,
      });
      setResult(data);
    } catch (err) {
      setError(err);
    } finally {
      setSearching(false);
    }
  }

  if (loading) return <LoadingState label={t("care.reviewLoading")} />;
  if (error && !context)
    return <ErrorState error={error} onRetry={() => setReloadKey((value) => value + 1)} />;
  if (!context) return null;

  const selectedFlag = context.flags.find((flag) => flag.id === selectedFlagId) || null;

  return (
    <div className="space-y-6">
      {!embedded && (
        <header>
          <h1 className="page-title">{t("care.localTitle")}</h1>
          <p className="secondary-text mt-2 max-w-3xl">{t("care.localSubtitle")}</p>
        </header>
      )}

      <Alert variant="info" title={t("care.medicalNotice")}>
        {context.disclaimer}
      </Alert>

      {!context.eligible ? (
        <Card>
          <CardBody>
            <div className="py-8 text-center">
              <p className="text-base font-semibold text-slate-800">{t("care.noActiveFlag")}</p>
              <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-slate-600">
                {context.message}
              </p>
              <p className="mt-3 text-xs text-slate-500">{t("care.noActiveFlagBody")}</p>
            </div>
          </CardBody>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader title={t("care.selectFlagTitle")} description={t("care.selectFlagBody")} />
            <fieldset className="space-y-3 px-5 py-4">
              <legend className="sr-only">{t("care.selectFlagTitle")}</legend>
              {context.flags.map((flag) => {
                const selected = selectedFlagId === flag.id;
                return (
                  <label
                    key={flag.id}
                    className={`block cursor-pointer rounded-xl border p-4 transition focus-within:outline-none focus-within:ring-4 focus-within:ring-brand-200 ${
                      selected
                        ? "border-brand-300 bg-brand-50/50 ring-2 ring-brand-100"
                        : "border-slate-200 bg-white hover:border-slate-300"
                    }`}
                  >
                    <input
                      className="sr-only"
                      type="radio"
                      name="clinical-flag"
                      checked={selected}
                      onChange={() => {
                        setSelectedFlagId(flag.id);
                        setResult(null);
                      }}
                    />
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-semibold text-slate-900">{flag.title}</p>
                          <StatusBadge tone={flag.trigger === "high_risk" ? "danger" : "warning"}>
                            {flag.trigger === "high_risk"
                              ? t("care.highRiskSignal")
                              : t("care.lowConfidenceSignal")}
                          </StatusBadge>
                          {typeof flag.confidence === "number" && (
                            <span
                              className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(flag.confidence)}`}
                            >
                              {t("care.confidenceValue", {
                                value: formatConfidence(flag.confidence),
                              })}
                            </span>
                          )}
                        </div>
                        <p className="mt-2 text-sm text-slate-600">{flag.evidence}</p>
                        <p className="mt-2 text-xs text-slate-500">
                          {t("care.sourceValue", { source: flag.source })}
                        </p>
                      </div>
                      <div className="max-w-xs rounded-lg bg-white px-3 py-2 text-xs ring-1 ring-slate-200">
                        <p className="font-semibold text-slate-700">
                          {t("care.suggestedSearch", { specialty: flag.specialty.label })}
                        </p>
                        <p className="mt-1 leading-relaxed text-slate-500">
                          {flag.specialty.reason}
                        </p>
                      </div>
                    </div>
                  </label>
                );
              })}
            </fieldset>
          </Card>

          {selectedFlag && <CareEvidencePanel flag={selectedFlag} />}

          <Card>
            <CardHeader
              title={t("care.findProfessional")}
              description={t("care.directoryPrivacy")}
            />
            <CardBody>
              <form
                className="grid gap-4 sm:grid-cols-3"
                aria-busy={searching}
                onSubmit={(event) => {
                  event.preventDefault();
                  void search();
                }}
              >
                <LocationAutocompleteInput
                  label={t("care.cityArea")}
                  placeholder={t("care.cityPlaceholder")}
                  value={location}
                  selected={selectedPlace}
                  onTextChange={(text) => {
                    setLocation(text);
                    setSelectedPlace(null);
                  }}
                  onSelect={(place) => {
                    setSelectedPlace(place);
                    setLocation(place.name);
                  }}
                  disabled={searching}
                  required
                />
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">{t("care.radius")}</span>
                  <select
                    value={radiusKm}
                    onChange={(event) => setRadiusKm(Number(event.target.value))}
                    className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                    disabled={searching}
                  >
                    {SEARCH_RADII_KM.map((radius) => (
                      <option key={radius} value={radius}>
                        {formatNumber(radius)} km
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">
                    {t("care.consultationPreference")}
                  </span>
                  <select
                    value={availability}
                    onChange={(event) =>
                      setAvailability(event.target.value as AvailabilityPreference)
                    }
                    className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                    disabled={searching}
                  >
                    {availabilityOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="sm:col-span-3 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                  <p className="max-w-2xl text-xs leading-relaxed text-slate-500">
                    {t("care.hoursRankingNotice")}
                  </p>
                  <button
                    type="submit"
                    disabled={searching || location.trim().length < 2 || !selectedFlagId}
                    className="btn-primary"
                  >
                    {searching && <Spinner className="h-4 w-4" />}
                    {searching ? t("care.finding") : t("care.searchLive")}
                  </button>
                </div>
              </form>
            </CardBody>
          </Card>

          {error && <ErrorState error={error} onRetry={() => void search()} />}
          {result && <CareRecommendationView result={result} />}
        </>
      )}
    </div>
  );
}
