import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { CareRecommendationView } from "../components/CareRecommendationView";
import { CareEvidencePanel } from "../components/CareEvidencePanel";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState, Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type {
  AvailabilityPreference,
  CareProviderSearchResponse,
  CareRecommendationContext,
} from "../types/api";
import { confidenceTone, formatConfidence } from "../utils/format";

const AVAILABILITY_OPTIONS: Array<{ value: AvailabilityPreference; label: string }> = [
  { value: "any", label: "Any consultation time" },
  { value: "today", label: "Today" },
  { value: "this_week", label: "This week" },
  { value: "evenings", label: "Evenings" },
  { value: "weekends", label: "Weekends" },
];

export function CareRecommendationsPage() {
  const { credentials } = useAuth();
  const [context, setContext] = useState<CareRecommendationContext | null>(null);
  const [selectedFlagId, setSelectedFlagId] = useState("");
  const [location, setLocation] = useState("");
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
        location: location.trim(),
        availability,
      });
      setResult(data);
    } catch (err) {
      setError(err);
    } finally {
      setSearching(false);
    }
  }

  if (loading) return <LoadingState label="Checking your existing care-review flags" />;
  if (error && !context) return <ErrorState error={error} onRetry={() => setReloadKey((value) => value + 1)} />;
  if (!context) return null;

  const selectedFlag = context.flags.find((flag) => flag.id === selectedFlagId) || null;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Find Local Care</h1>
        <p className="secondary-text mt-2 max-w-3xl">
          When MediMind finds an existing high-risk medication-safety signal or a low-confidence record,
          it can help you search a live provider directory for an appropriate professional near you.
        </p>
      </header>

      <Alert variant="info" title="Important medical notice">
        {context.disclaimer}
      </Alert>

      {!context.eligible ? (
        <Card>
          <CardBody>
            <div className="py-8 text-center">
              <p className="text-base font-semibold text-slate-800">No care-search flag is active</p>
              <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-slate-600">{context.message}</p>
              <p className="mt-3 text-xs text-slate-500">
                This feature activates from existing high-risk medication-safety signals or low-confidence extraction/trend results. It does not diagnose a medical condition.
              </p>
            </div>
          </CardBody>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader
              title="1. Select the record flag to review"
              description="Specialty matching is explained from existing extracted-record evidence, not a diagnosis."
            />
            <CardBody className="space-y-3">
              {context.flags.map((flag) => {
                const selected = selectedFlagId === flag.id;
                return (
                  <label
                    key={flag.id}
                    className={`block cursor-pointer rounded-xl border p-4 transition ${
                      selected ? "border-brand-300 bg-brand-50/50 ring-2 ring-brand-100" : "border-slate-200 bg-white hover:border-slate-300"
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
                            {flag.trigger === "high_risk" ? "high-risk signal" : "low-confidence signal"}
                          </StatusBadge>
                          {typeof flag.confidence === "number" && (
                            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${confidenceTone(flag.confidence)}`}>
                              confidence {formatConfidence(flag.confidence)}
                            </span>
                          )}
                        </div>
                        <p className="mt-2 text-sm text-slate-600">{flag.evidence}</p>
                        <p className="mt-2 text-xs text-slate-500">Source: {flag.source}</p>
                      </div>
                      <div className="max-w-xs rounded-lg bg-white px-3 py-2 text-xs ring-1 ring-slate-200">
                        <p className="font-semibold text-slate-700">Suggested search: {flag.specialty.label}</p>
                        <p className="mt-1 leading-relaxed text-slate-500">{flag.specialty.reason}</p>
                      </div>
                    </div>
                  </label>
                );
              })}
            </CardBody>
          </Card>

          {selectedFlag && <CareEvidencePanel flag={selectedFlag} />}

          <Card>
            <CardHeader title="Find a local professional" description="Your city/area and preference are sent only to the selected live directory search." />
            <CardBody>
              <form
                className="grid gap-4 sm:grid-cols-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void search();
                }}
              >
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">City or area</span>
                  <input
                    value={location}
                    onChange={(event) => setLocation(event.target.value)}
                    placeholder="e.g. Negombo"
                    autoComplete="address-level2"
                    className="mt-1.5 block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                    disabled={searching}
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Consultation preference</span>
                  <select
                    value={availability}
                    onChange={(event) => setAvailability(event.target.value as AvailabilityPreference)}
                    className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                    disabled={searching}
                  >
                    {AVAILABILITY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <div className="sm:col-span-2 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
                  <p className="max-w-2xl text-xs leading-relaxed text-slate-500">
                    Opening hours are only used in ranking if the live directory actually returns them. Hours do not confirm appointment availability.
                  </p>
                  <button type="submit" disabled={searching || location.trim().length < 2 || !selectedFlagId} className="btn-primary">
                    {searching && <Spinner className="h-4 w-4" />}
                    Search live providers
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
