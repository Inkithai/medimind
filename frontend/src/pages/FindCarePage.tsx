import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { LocationPicker } from "../components/location";
import { SpecialtySelector } from "../components/SpecialtySelector";
import { AlertIcon, LocationIcon, RefreshIcon, SparkleIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type {
  CareAvailability,
  CareFacility,
  CareRecommendation,
  FacilityKind,
} from "../types/facility";
import type { CareSpecialtyOption, CareSuggestion } from "../types/api";
import type { ScoredCareRecommendation } from "../types/recommendations";
import { finderSpecialtyFor } from "../types/recommendations";
import type { ConfirmedLocation } from "../types/location";
import { classNames } from "../utils/format";

const STORAGE_KEY = "medimind.find-care.location.v1";
const PREFERENCES_KEY = "medimind.find-care.preferences.v1";
const SEARCH_RADII = [5, 10, 20, 50] as const;

type SearchStatus = "idle" | "loading" | "success" | "error";
type FacilityFilter = "all" | FacilityKind;
type SearchKind = Exclude<FacilityFilter, "healthcare">;

const FILTERS: Array<{ value: SearchKind; labelKey: string }> = [
  { value: "all", labelKey: "care.all" },
  { value: "hospital", labelKey: "care.hospitals" },
  { value: "clinic", labelKey: "care.clinics" },
  { value: "pharmacy", labelKey: "care.pharmacies" },
  { value: "laboratory", labelKey: "care.laboratories" },
  { value: "doctor", labelKey: "care.doctors" },
];

function readPreferences(): { specialty: string; availability: CareAvailability; radiusKm: number } {
  try {
    const value = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || "null") as {
      specialty?: unknown;
      availability?: unknown;
      radiusKm?: unknown;
    } | null;
    const allowed = new Set<CareAvailability>(["any", "today", "this_week", "evening", "weekend"]);
    const radius = typeof value?.radiusKm === "number" && SEARCH_RADII.includes(value.radiusKm as typeof SEARCH_RADII[number])
      ? value.radiusKm
      : 5;
    return {
      specialty: typeof value?.specialty === "string" ? value.specialty.slice(0, 80) : "",
      availability:
        typeof value?.availability === "string" && allowed.has(value.availability as CareAvailability)
          ? (value.availability as CareAvailability)
          : "any",
      radiusKm: radius,
    };
  } catch {
    return { specialty: "", availability: "any", radiusKm: 5 };
  }
}

function readSavedLocation(): ConfirmedLocation | null {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (
      value &&
      typeof value === "object" &&
      "latitude" in value &&
      "longitude" in value &&
      "name" in value &&
      "displayName" in value &&
      typeof value.latitude === "number" &&
      typeof value.longitude === "number" &&
      Number.isFinite(value.latitude) &&
      Number.isFinite(value.longitude) &&
      value.latitude >= -90 &&
      value.latitude <= 90 &&
      value.longitude >= -180 &&
      value.longitude <= 180 &&
      typeof value.name === "string" &&
      value.name.trim().length > 0 &&
      typeof value.displayName === "string" &&
      value.displayName.trim().length > 0
    ) {
      return value as ConfirmedLocation;
    }
  } catch {
    // Ignore an old or malformed browser value.
  }
  return null;
}

export function FindCarePage() {
  const { credentials } = useAuth();
  const { t, formatNumber } = useI18n();
  const referralSource = new URLSearchParams(window.location.search).get("from") || "";
  const lowConfidenceReferral = referralSource.startsWith("low-confidence");
  const [savedLocation, setSavedLocation] = useState<ConfirmedLocation | null>(readSavedLocation);
  const [pickerKey, setPickerKey] = useState(0);
  const [facilities, setFacilities] = useState<CareFacility[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [searchKind, setSearchKind] = useState<SearchKind>("all");
  const [filter, setFilter] = useState<FacilityFilter>("all");
  const [specialty, setSpecialty] = useState(() => readPreferences().specialty);
  const [availability, setAvailability] = useState<CareAvailability>(() => readPreferences().availability);
  const [radiusKm, setRadiusKm] = useState(() => readPreferences().radiusKm);
  const [recommendation, setRecommendation] = useState<CareRecommendation | null>(null);
  const [suggestion, setSuggestion] = useState<CareSuggestion | null>(null);
  const [suggestionLoading, setSuggestionLoading] = useState(true);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);

  // Scored care recommendations (percentage-based ranking)
  const [recommendations, setRecommendations] = useState<ScoredCareRecommendation[]>([]);
  const [recsLoading, setRecsLoading] = useState(true);
  const [recsError, setRecsError] = useState<string | null>(null);
  const [recsNote, setRecsNote] = useState<string | null>(null);
  const [showAllRecs, setShowAllRecs] = useState(false);
  const [expandedFactors, setExpandedFactors] = useState<Set<number>>(new Set());
  const [showHowCalculated, setShowHowCalculated] = useState(false);

  const requestRef = useRef<AbortController | null>(null);
  const recsRequestRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);
  const formRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => {
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ specialty, availability, radiusKm }));
  }, [availability, radiusKm, specialty]);

  useStrictEffect(() => {
    let cancelled = false;
    api.getCareRecommendation(credentials)
      .then((value) => {
        if (cancelled) return;
        setRecommendation(value);
        if (!specialty.trim()) setSpecialty(value.specialty_query);
        if (value.triggered) {
          setSearchKind(value.facility_kind);
          setFilter(value.facility_kind);
        }
      })
      .catch(() => {
        // No patient snapshot yet: manual care search remains fully available.
      });
    // Catalog + record-derived specialty suggestions drive the grouped
    // combobox. The page still works without them.
    setSuggestionLoading(true);
    setSuggestionError(null);
    api.getCareSuggestion(credentials)
      .then((value) => {
        if (cancelled) return;
        setSuggestion(value);
      })
      .catch((error) => {
        if (cancelled) return;
        setSuggestionError(
          error instanceof Error ? error.message : "Could not load specialty suggestions.",
        );
      })
      .finally(() => {
        if (!cancelled) setSuggestionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [credentials]);

  // Load the scored care recommendations (StrictMode-safe, cancellable
  // without affecting the facility search).
  useStrictEffect(() => {
    const controller = new AbortController();
    recsRequestRef.current = controller;
    setRecsLoading(true);
    setRecsError(null);

    api
      .getScoredCareRecommendations(credentials, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        setRecommendations(res.recommendations || []);
        setRecsNote(res.note || null);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setRecsError(err instanceof Error ? err.message : "Could not load recommendations");
        setRecommendations([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setRecsLoading(false);
      });

    return () => controller.abort();
  }, [credentials]);

  // Split recommendations into the top one + the "other" list. Sorted by
  // score, then safety-signal tiebreak, then key.
  const { topRecommendation, otherRecommendations } = useMemo(() => {
    if (recommendations.length === 0) {
      return { topRecommendation: null, otherRecommendations: [] as ScoredCareRecommendation[] };
    }
    const sorted = [...recommendations].sort((a, b) => {
      if (b.relevance_score !== a.relevance_score) {
        return b.relevance_score - a.relevance_score;
      }
      if (a.has_safety_signal !== b.has_safety_signal) {
        return a.has_safety_signal ? -1 : 1;
      }
      return a.specialty_key.localeCompare(b.specialty_key);
    });
    return { topRecommendation: sorted[0], otherRecommendations: sorted.slice(1) };
  }, [recommendations]);

  const visibleFacilities = useMemo(
    () => facilities.filter((facility) => filter === "all" || facility.kind === filter),
    [facilities, filter]
  );

  async function handleConfirm(location: ConfirmedLocation) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(location));
    setSavedLocation(location);
    setFilter(searchKind);
    window.setTimeout(
      () => resultsRef.current?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start",
      }),
      150
    );
    // Let LocationPicker keep its action disabled until this search settles;
    // otherwise repeated clicks abort and restart the same request.
    await loadFacilities(location, searchKind);
  }

  async function loadFacilities(
    location: ConfirmedLocation,
    requestedKind: SearchKind,
    requestedSpecialty = specialty,
    requestedAvailability = availability,
    requestedRadiusKm = radiusKm
  ) {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    // Keep the result chips aligned with the server-side category. Without
    // this, retrying after changing the category could load pharmacies while
    // the old hospital filter hid every returned result.
    setFilter(requestedKind);
    setStatus("loading");
    setError(null);
    setFacilities([]);

    try {
      const nearby = await api.getCareFacilities(credentials, {
        location: location.displayName || location.name,
        kind: requestedKind === "all" ? "any" : requestedKind,
        radiusKm: requestedRadiusKm,
        latitude: location.latitude,
        longitude: location.longitude,
        specialty: requestedSpecialty.trim() || undefined,
        availability: requestedAvailability,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setFacilities(nearby);
      setStatus("success");
    } catch (requestError) {
      if (controller.signal.aborted) return;
      setError(
        requestError instanceof Error
          ? requestError.message
          : "We couldn't load nearby facilities. Please try again."
      );
      setStatus("error");
    }
  }

  function clearLocation() {
    requestRef.current?.abort();
    localStorage.removeItem(STORAGE_KEY);
    setSavedLocation(null);
    setFacilities([]);
    setStatus("idle");
    setError(null);
    setFilter("all");
    setPickerKey((value) => value + 1);
  }

  /** "Find nearby" on a suggested-specialty card. */
  function handleUseSuggestion(option: CareSpecialtyOption) {
    setSpecialty(option.id);
    setSearchKind("doctor");
    setFilter("doctor");
    window.setTimeout(() => {
      formRef.current?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start",
      });
    }, 100);
  }

  /** "Find nearby" on a scored recommendation card: seed the search form. */
  function handleUseRecommendation(rec: ScoredCareRecommendation) {
    setSpecialty(finderSpecialtyFor(rec.specialty_key));
    setSearchKind("doctor");
    setFilter("doctor");
    window.setTimeout(() => {
      formRef.current?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
        block: "start",
      });
    }, 100);
  }

  function toggleFactors(idx: number) {
    setExpandedFactors((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
            <CareIcon className="h-3.5 w-3.5" /> Find care
          </div>
          <h1 className="page-title">Find care based on your records</h1>
          <p className="secondary-text mt-2 max-w-2xl leading-relaxed">
            MediMind found care options that may be relevant to the information in your medical records.
          </p>
        </div>
        {savedLocation && (
          <button type="button" onClick={clearLocation} className="btn-secondary shrink-0">
            {t("common.change")}
          </button>
        )}
      </header>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <p className="font-semibold">{t("care.urgentTitle")}</p>
        <p className="mt-0.5 text-amber-900">{t("care.urgentBody")}</p>
      </div>

      {/* ─── Scored care recommendations (percentage relevance) ────────── */}
      {recsLoading ? (
        <section aria-busy="true" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
            <p className="text-sm font-medium text-slate-600">Analysing your records for care options…</p>
          </div>
          <div className="mt-4 space-y-3">
            <div className="h-32 animate-pulse rounded-2xl bg-slate-100" />
            <div className="h-20 animate-pulse rounded-2xl bg-slate-100" />
            <div className="h-20 animate-pulse rounded-2xl bg-slate-100" />
          </div>
        </section>
      ) : recsError ? (
        <SpecialtySuggestionsSection
          loading={suggestionLoading}
          error={suggestionError}
          suggestion={suggestion}
          onFindNearby={handleUseSuggestion}
        />
      ) : recommendations.length > 0 ? (
        <section className="space-y-5" data-testid="care-recommendations">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="section-title">Care recommendations</h2>
              <p className="secondary-text mt-1">
                Based on diagnoses, medications, allergies, and lab results in your records.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowHowCalculated((v) => !v)}
              className="text-sm font-medium text-brand-700 hover:text-brand-800 hover:underline"
              aria-expanded={showHowCalculated}
            >
              How is relevance calculated?
            </button>
          </div>

          {showHowCalculated && <HowIsRelevanceCalculated />}

          {topRecommendation && (
            <TopRecommendationCard
              rec={topRecommendation}
              expanded={expandedFactors.has(0)}
              onToggleFactors={() => toggleFactors(0)}
              onFindNearby={() => handleUseRecommendation(topRecommendation)}
            />
          )}

          {otherRecommendations.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
                Other care options
              </h3>
              <ul className="space-y-2">
                {(showAllRecs ? otherRecommendations : otherRecommendations.slice(0, 3)).map(
                  (rec, idx) => (
                    <li key={`${rec.specialty_key}-${idx}`}>
                      <OtherCareCard
                        rec={rec}
                        onFindNearby={() => handleUseRecommendation(rec)}
                      />
                    </li>
                  )
                )}
              </ul>
              {otherRecommendations.length > 3 && (
                <button
                  type="button"
                  onClick={() => setShowAllRecs((v) => !v)}
                  className="text-sm font-semibold text-brand-700 hover:text-brand-800 hover:underline"
                >
                  {showAllRecs
                    ? "Show fewer care options"
                    : `Show all ${otherRecommendations.length} care options`}
                </button>
              )}
            </div>
          )}

          {recsNote && <p className="text-xs text-slate-400">{recsNote}</p>}
        </section>
      ) : (
        <section className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
            <SparkleIcon className="h-6 w-6" />
          </span>
          <h2 className="mt-4 text-lg font-semibold text-slate-900">No specific care needs detected</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
            Upload medical records to receive personalised care recommendations based on your health history.
          </p>
          <Link to="/upload" className="btn-primary mt-5">
            Upload Documents
          </Link>
        </section>
      )}

      {lowConfidenceReferral && (!recommendation || !recommendation.triggered) && (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
          <p className="font-semibold">{t("care.lowConfidence")}</p>
          <p className="mt-1">
            The previous result was uncertain. Use the location, availability, and specialty fields below to find a real professional who can check it against the original records.
          </p>
        </section>
      )}

      {recommendation && (
        <section className={classNames(
          "rounded-2xl border px-5 py-4 text-sm",
          recommendation.triggered ? "border-red-200 bg-red-50 text-red-900" : "border-sky-200 bg-sky-50 text-sky-900"
        )}>
          <p className="font-semibold">
            {recommendation.triggered ? t("care.recommendation") : t("care.startingSpecialty")}: {recommendation.specialty}
          </p>
          <p className="mt-1">{recommendation.reason}</p>
          <p className="mt-2 text-xs opacity-80">{recommendation.disclaimer}</p>
          {recommendation.evidence.length > 0 && (
            <p className="mt-2 text-xs font-medium">
              Evidence: {recommendation.evidence.map((item) => `${item.source_file || "record"}${item.page ? ` p.${item.page}` : ""}`).join(", ")}
            </p>
          )}
        </section>
      )}

      <section
        ref={formRef}
        id="care-search-form"
        className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm scroll-mt-8"
      >
        <h2 className="text-sm font-semibold text-slate-900">{t("care.preferences")}</h2>
        <p className="mt-1 text-xs text-slate-600">{t("care.preferencesBody")}</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-sm font-semibold text-slate-800">
            {t("care.facilityType")}
            <select
              id="care-kind"
              value={searchKind}
              onChange={(event) => {
                const nextKind = event.target.value as SearchKind;
                setSearchKind(nextKind);
                if (savedLocation) void loadFacilities(savedLocation, nextKind);
              }}
              className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
            >
              {FILTERS.map((option) => (
                <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
              ))}
            </select>
          </label>

          <SpecialtySelector
            value={specialty}
            onChange={(id) => {
              setSpecialty(id);
              if (savedLocation) void loadFacilities(savedLocation, searchKind, id, availability);
            }}
            suggestions={suggestion ? [suggestion.suggested, ...suggestion.alternatives] : undefined}
            allSpecialties={suggestion?.all ?? []}
            label="What type of care do you need?"
            placeholder="Search specialty or type of care…"
          />

          <label className="text-sm font-semibold text-slate-800">
            {t("care.availability")}
            <select
              value={availability}
              onChange={(event) => {
                const next = event.target.value as CareAvailability;
                setAvailability(next);
                if (savedLocation) void loadFacilities(savedLocation, searchKind, specialty, next);
              }}
              className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
            >
              <option value="any">{t("care.anytime")}</option>
              <option value="today">{t("care.today")}</option>
              <option value="this_week">{t("care.thisWeek")}</option>
              <option value="evening">{t("care.evening")}</option>
              <option value="weekend">{t("care.weekend")}</option>
            </select>
          </label>

          <label className="text-sm font-semibold text-slate-800">
            {t("care.radius")}
            <select
              value={radiusKm}
              onChange={(event) => {
                const next = Number(event.target.value);
                setRadiusKm(next);
                if (savedLocation) void loadFacilities(savedLocation, searchKind, specialty, availability, next);
              }}
              className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
            >
              {SEARCH_RADII.map((radius) => (
                <option key={radius} value={radius}>{formatNumber(radius)} km</option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <LocationPicker
        key={pickerKey}
        initialValue={savedLocation}
        onConfirm={handleConfirm}
        title={t("care.where")}
        description={t("care.locationDescription")}
        confirmLabel={t("care.find")}
        confirmingLabel={t("care.finding")}
        showAddressDetails={false}
      />

      <div ref={resultsRef} className="scroll-mt-8">
        {status === "idle" ? (
          <section className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
              <CareIcon className="h-6 w-6" />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-slate-900">{t("care.selectArea")}</h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-600">{t("care.selectAreaBody")}</p>
          </section>
        ) : status === "loading" ? (
          <FacilityLoading locationName={savedLocation?.name || "your location"} radiusKm={radiusKm} />
        ) : status === "error" ? (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <h2 className="text-lg font-semibold text-red-900">{t("care.searchFailed")}</h2>
            <p className="mx-auto mt-1 max-w-lg text-sm text-red-700">{error}</p>
            {savedLocation && (
              <button
                type="button"
                onClick={() => void loadFacilities(savedLocation, searchKind)}
                className="btn-secondary mt-5"
              >
                <RefreshIcon className="h-4 w-4" /> Try again
              </button>
            )}
          </section>
        ) : (
          <FacilityResults
            facilities={facilities}
            visibleFacilities={visibleFacilities}
            filter={filter}
            onFilterChange={setFilter}
            location={savedLocation}
            specialty={specialty}
            radiusKm={radiusKm}
            onExpandRadius={() => {
              const nextRadius = SEARCH_RADII.find((radius) => radius > radiusKm);
              if (nextRadius && savedLocation) {
                setRadiusKm(nextRadius);
                void loadFacilities(savedLocation, searchKind, specialty, availability, nextRadius);
              }
            }}
            onBroadenSpecialty={() => {
              setSpecialty("");
              if (savedLocation) void loadFacilities(savedLocation, searchKind, "", availability);
            }}
          />
        )}
      </div>
    </div>
  );
}

function FacilityLoading({ locationName, radiusKm }: { locationName: string; radiusKm: number }) {
  const { t, formatNumber } = useI18n();
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
        <div>
          <h2 className="font-semibold text-slate-900">{t("care.finding")} {locationName}</h2>
          <p className="text-sm text-slate-600">{formatNumber(radiusKm)} km</p>
        </div>
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-36 animate-pulse rounded-2xl bg-slate-100" />
        ))}
      </div>
    </section>
  );
}

function FacilityResults({
  facilities,
  visibleFacilities,
  filter,
  onFilterChange,
  location,
  specialty,
  radiusKm,
  onExpandRadius,
  onBroadenSpecialty,
}: {
  facilities: CareFacility[];
  visibleFacilities: CareFacility[];
  filter: FacilityFilter;
  onFilterChange: (filter: FacilityFilter) => void;
  location: ConfirmedLocation | null;
  specialty: string;
  radiusKm: number;
  onExpandRadius: () => void;
  onBroadenSpecialty: () => void;
}) {
  const { t, formatNumber } = useI18n();
  const sources = [...new Set(facilities.map((facility) => facility.source))].join(", ");
  return (
    <section className="space-y-5" aria-live="polite">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">
            <LocationIcon className="mr-1 inline h-4 w-4" /> Near {location?.name || "selected location"}
          </p>
          <h2 className="section-title mt-1">
            {facilities.length
              ? t("care.resultCount", { count: formatNumber(facilities.length) })
              : t("care.noResults")}
          </h2>
        </div>
        {facilities.length > 0 && (
          <p className="max-w-xl text-xs text-slate-400">
            {t("care.ranked")} {t("common.source")}: {sources || t("common.notAvailable")} · {t("care.notRecommendation")}
          </p>
        )}
      </div>

      {facilities.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1 scroll-thin" aria-label={t("care.filter")}>
          {FILTERS.map((item) => {
            const count =
              item.value === "all"
                ? facilities.length
                : facilities.filter((facility) => facility.kind === item.value).length;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => onFilterChange(item.value)}
                className={classNames(
                  "min-h-[40px] shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition",
                  filter === item.value
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                )}
              >
                {t(item.labelKey)} <span className={filter === item.value ? "text-slate-300" : "text-slate-400"}>{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {!facilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
          <CareIcon className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 font-semibold text-slate-900">{t("care.noResults")}</p>
          <p className="mt-1 text-sm text-slate-600">
            {t("care.noResultsBody", { radius: formatNumber(radiusKm) })}
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {radiusKm < SEARCH_RADII[SEARCH_RADII.length - 1] && (
              <button type="button" onClick={onExpandRadius} className="btn-primary">
                {t("care.expand")}
              </button>
            )}
            {specialty && (
              <button type="button" onClick={onBroadenSpecialty} className="btn-secondary">
                {t("care.broaden")}
              </button>
            )}
          </div>
        </div>
      ) : !visibleFacilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-8 text-center text-sm text-slate-500">
          No facilities match this filter. Choose another category to continue.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {visibleFacilities.map((facility) => (
            <FacilityCard key={facility.id} facility={facility} />
          ))}
        </div>
      )}
    </section>
  );
}

function FacilityCard({ facility }: { facility: CareFacility }) {
  const { t, formatNumber } = useI18n();
  // "Open in Google Maps" must open Google Maps, never OpenStreetMap. OSM
  // remains the keyless DISCOVERY/tile layer, but navigation goes to Google:
  // prefer a canonical Google URI, else build a Maps search from the real
  // facility name + address, with coordinates as the last resort.
  const mapUrl = googleMapsUrl(facility);
  const callHref = telHref(facility.phone);
  return (
    <article className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-start gap-3">
        <span className={classNames("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", kindTone(facility.kind))}>
          <CareIcon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
              {kindLabel(facility.kind, t)}
            </span>
            {facility.openNow !== undefined && (
              <span
                className={classNames(
                  "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                  facility.openNow ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                )}
              >
                {facility.openNow ? t("care.openNow") : t("care.closedNow")}
              </span>
            )}
          </div>
          <h3 className="mt-2 text-base font-bold text-slate-900">{facility.name}</h3>
          {facility.specialty && (
            <p className="mt-1 text-xs font-semibold text-violet-700">
              {t("care.specialty")}: {facility.specialty} · {t("care.verifySpecialty")}
            </p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {facility.distanceKm !== null && (
              <span className="font-semibold text-brand-700">{distanceLabel(facility.distanceKm, formatNumber)}</span>
            )}
            {facility.rating !== undefined && (
              <span className="text-amber-700">
                ★ {formatNumber(facility.rating, { maximumFractionDigits: 1 })}
                {facility.userRatingCount !== undefined && (
                  <span className="text-slate-400"> ({formatNumber(facility.userRatingCount)})</span>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex-1 space-y-2 border-t border-slate-100 pt-4 text-sm text-slate-500">
        <p>{facility.address || t("care.addressMissing")}</p>
        {Boolean(facility.openingHours?.length) && (
          <details>
            <summary className="cursor-pointer font-medium text-slate-800">{t("care.openingHours")}</summary>
            <ul className="mt-1 space-y-0.5 text-xs">
              {facility.openingHours?.map((hours) => <li key={hours}>{hours}</li>)}
            </ul>
          </details>
        )}
        {facility.phone && (
          <p>
            <a href={`tel:${facility.phone}`} className="font-medium text-brand-700 hover:underline">
              {facility.phone}
            </a>
          </p>
        )}
        {facility.rankingReason && (
          <p className="rounded-md bg-slate-50 px-2.5 py-2 text-xs text-slate-500">
            <span className="font-semibold text-slate-800">{t("care.whyRanked")}:</span> {facility.rankingReason}
          </p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <a
          href={mapUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={t("care.openInGoogleMapsAria", { name: facility.name })}
          className="btn-secondary min-h-[44px] px-4 py-2 text-sm"
        >
          <LocationIcon className="h-4 w-4" aria-hidden="true" /> {t("care.openInGoogleMaps")}
          <span className="sr-only"> ({t("common.opensNewWindow")})</span>
        </a>
        {callHref && (
          <a
            href={callHref}
            aria-label={t("care.callAria", { name: facility.name })}
            className="btn-secondary min-h-[44px] px-4 py-2 text-sm"
          >
            {t("care.call")}
          </a>
        )}
        {facility.website && (
          <a href={facility.website} target="_blank" rel="noreferrer" className="btn-ghost min-h-[40px] px-4 py-2 text-sm">
            {t("care.website")}<span className="sr-only"> ({t("common.opensNewWindow")})</span>
          </a>
        )}
      </div>
    </article>
  );
}

function kindLabel(kind: FacilityKind, t: (key: string) => string): string {
  const keys: Record<FacilityKind, string> = {
    hospital: "care.hospitals",
    clinic: "care.clinics",
    pharmacy: "care.pharmacies",
    laboratory: "care.laboratories",
    doctor: "care.doctors",
    healthcare: "care.all",
  };
  return t(keys[kind]);
}

function kindTone(kind: FacilityKind): string {
  if (kind === "hospital") return "bg-red-50 text-red-700";
  if (kind === "pharmacy") return "bg-emerald-50 text-emerald-700";
  if (kind === "laboratory") return "bg-amber-50 text-amber-700";
  if (kind === "doctor") return "bg-violet-50 text-violet-700";
  return "bg-sky-50 text-sky-700";
}

function distanceLabel(
  distanceKm: number,
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string
): string {
  if (distanceKm < 1) return `${formatNumber(Math.max(1, Math.round(distanceKm * 1_000)))} m`;
  return `${formatNumber(distanceKm, { maximumFractionDigits: distanceKm < 10 ? 1 : 0 })} km`;
}

function SpecialtySuggestionsSection({
  loading,
  error,
  suggestion,
  onFindNearby,
}: {
  loading: boolean;
  error: string | null;
  suggestion: CareSuggestion | null;
  onFindNearby: (option: CareSpecialtyOption) => void;
}) {
  if (loading) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
          <p className="text-sm font-medium text-slate-600">Analysing your records for care options…</p>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-2xl bg-slate-100" />
          ))}
        </div>
      </section>
    );
  }

  if (error || !suggestion) {
    return (
      <section className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <p className="font-semibold">Specialty suggestions unavailable</p>
        <p className="mt-0.5 text-amber-800">
          {error || "You can still search for nearby care below."}
        </p>
      </section>
    );
  }

  const cards = [suggestion.suggested, ...suggestion.alternatives];

  if (!suggestion.has_records) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
        <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
          <SparkleIcon className="h-6 w-6" />
        </span>
        <h2 className="mt-4 text-lg font-semibold text-slate-900">No specific care needs detected</h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
          Upload medical records to receive personalised care recommendations based on your health history.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="section-title">Care recommendations</h2>
        <p className="secondary-text mt-1">
          Based on diagnoses, medications, allergies, and lab results in your records.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {cards.map((option, idx) => (
          <article
            key={option.id}
            className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={classNames(
                      "inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                      idx === 0
                        ? "bg-red-50 text-red-700 ring-1 ring-red-200"
                        : "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
                    )}
                  >
                    {idx === 0 ? "Top suggestion" : "Alternative"}
                  </span>
                </div>
                <h3 className="mt-2 text-base font-bold text-slate-900">{option.label}</h3>
              </div>
            </div>
            {option.reasons && option.reasons.length > 0 ? (
              <ul className="mt-3 flex-1 space-y-1 text-sm leading-relaxed text-slate-500">
                {option.reasons.slice(0, 3).map((reason, i) => (
                  <li key={i} className="flex gap-2">
                    <span aria-hidden="true" className="select-none text-brand-500">•</span>
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 flex-1 text-sm text-slate-500">
                General practice can review your full record and refer if needed.
              </p>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => onFindNearby(option)}
                className="btn-primary min-h-[40px] px-4 py-2 text-sm"
              >
                <LocationIcon className="h-4 w-4" /> Find nearby
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

// ─── Scored recommendations UI (percentage relevance) ──────────────────────

function relevanceTone(relevance: string): string {
  switch (relevance) {
    case "high":
      return "bg-red-50 text-red-700 ring-red-200";
    case "moderate":
      return "bg-amber-50 text-amber-800 ring-amber-200";
    case "possible":
      return "bg-sky-50 text-sky-700 ring-sky-200";
    default:
      return "bg-slate-100 text-slate-600 ring-slate-200";
  }
}

function scoredRelevanceLabel(relevance: string): string {
  switch (relevance) {
    case "high":
      return "High relevance";
    case "moderate":
      return "Moderate relevance";
    case "possible":
      return "Possible";
    default:
      return relevance;
  }
}

function RelevanceBadge({
  relevance,
  score,
  size = "md",
}: {
  relevance: ScoredCareRecommendation["relevance"];
  score: number;
  size?: "sm" | "md" | "lg";
}) {
  const sizeClasses =
    size === "lg"
      ? "px-3 py-1 text-sm"
      : size === "sm"
      ? "px-2 py-0.5 text-[11px]"
      : "px-2.5 py-0.5 text-xs";
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1.5 rounded-full font-bold uppercase tracking-wide ring-1",
        relevanceTone(relevance),
        sizeClasses
      )}
    >
      <span>{scoredRelevanceLabel(relevance)}</span>
      <span className="font-mono text-current opacity-80">{score}%</span>
    </span>
  );
}

function HowIsRelevanceCalculated() {
  return (
    <div
      className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-600"
      role="region"
      aria-label="How relevance is calculated"
    >
      <p>
        <strong className="text-slate-800">Relevance is an informational ranking, not a medical
        probability or diagnosis.</strong> MediMind considers documented diagnoses, medications,
        allergies, laboratory trends, explicit safety flags, and the strength of supporting evidence in
        your records. Each recommendation's percentage is the sum of points from its contributing
        factors (visible when you click <em>View supporting records</em>).
      </p>
      <p className="mt-2 text-xs text-slate-500">
        Top suggestion picks the highest-scoring record-backed care type. Safety-flagged findings
        (allergy conflicts, drug interactions, duplicate prescriptions) get a small tiebreaker.
      </p>
    </div>
  );
}

function TopRecommendationCard({
  rec,
  expanded,
  onToggleFactors,
  onFindNearby,
}: {
  rec: ScoredCareRecommendation;
  expanded: boolean;
  onToggleFactors: () => void;
  onFindNearby: () => void;
}) {
  return (
    <article
      className="relative overflow-hidden rounded-2xl border-2 border-brand-200 bg-gradient-to-br from-white via-white to-brand-50/60 p-6 shadow-sm"
      aria-labelledby="top-rec-title"
    >
      {/* Soft top stripe so the top recommendation visually stands out */}
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-400 via-brand-500 to-brand-600" />

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <RelevanceBadge relevance={rec.relevance} score={rec.relevance_score} size="lg" />
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-800 ring-1 ring-amber-200">
            <SparkleIcon className="h-3 w-3" /> Top suggestion
          </span>
        </div>
      </div>

      <h3 id="top-rec-title" className="mt-3 text-xl font-bold text-slate-900">
        {rec.specialty}
      </h3>
      <p className="mt-1 text-base font-semibold text-brand-800">{rec.title}</p>

      {rec.has_safety_signal && rec.safety_message && (
        <div
          className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
          role="note"
        >
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
          <div>
            <p className="font-semibold">Medication/allergy conflict</p>
            <p className="mt-0.5 text-amber-800">{rec.safety_message}</p>
          </div>
        </div>
      )}

      <p className="mt-4 text-sm leading-relaxed text-slate-700">{rec.reason}</p>

      {rec.evidence.length > 0 && (
        <div className="mt-4 border-t border-slate-200/70 pt-4">
          <button
            type="button"
            onClick={onToggleFactors}
            className="flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:text-brand-800"
            aria-expanded={expanded}
          >
            <span className="inline-flex items-center rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-bold text-brand-700 ring-1 ring-brand-200">
              Evidence · {rec.evidence.length}
            </span>
            {expanded ? "Hide" : "View"} supporting records
          </button>
          {expanded && (
            <div className="mt-3 space-y-3">
              <ul className="space-y-1.5 text-sm text-slate-600">
                {rec.evidence.slice(0, 5).map((e, i) => (
                  <li key={i} className="leading-relaxed">
                    {e.date && <span className="font-medium text-slate-700">{e.date}: </span>}
                    {e.description}
                    {e.source_file && (
                      <span className="ml-1 text-xs text-slate-400">({e.source_file})</span>
                    )}
                  </li>
                ))}
                {rec.evidence.length > 5 && (
                  <li className="text-xs text-slate-400">…and {rec.evidence.length - 5} more</li>
                )}
              </ul>

              {rec.score_factors.length > 0 && (
                <div className="rounded-xl border border-slate-200 bg-white p-3">
                  <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
                    How the {rec.relevance_score}% score was assembled
                  </p>
                  <ul className="mt-2 space-y-1.5">
                    {rec.score_factors.map((f, i) => (
                      <li key={i} className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="text-slate-700">
                          <span className="font-semibold">{f.label}</span>
                          {f.note && <span className="ml-1.5 text-xs text-slate-500">— {f.note}</span>}
                        </span>
                        <span className="shrink-0 font-mono text-xs font-semibold text-brand-700">
                          +{f.points}
                        </span>
                      </li>
                    ))}
                    <li className="flex items-baseline justify-between gap-3 border-t border-slate-100 pt-1.5 text-sm">
                      <span className="font-semibold text-slate-700">Total (capped at 100)</span>
                      <span className="shrink-0 font-mono text-sm font-bold text-slate-900">
                        {rec.relevance_score}%
                      </span>
                    </li>
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onFindNearby}
          className="btn-primary min-h-[40px] px-4 py-2 text-sm"
        >
          <LocationIcon className="h-4 w-4" /> Find nearby
        </button>
      </div>
    </article>
  );
}

function OtherCareCard({
  rec,
  onFindNearby,
}: {
  rec: ScoredCareRecommendation;
  onFindNearby: () => void;
}) {
  return (
    <div
      className={classNames(
        "group rounded-2xl border bg-white p-4 shadow-sm transition hover:border-brand-200 hover:shadow-md",
        rec.has_safety_signal ? "border-amber-200" : "border-slate-200"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <RelevanceBadge relevance={rec.relevance} score={rec.relevance_score} size="sm" />
            {rec.has_safety_signal && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-800 ring-1 ring-amber-200"
                title={rec.safety_message || "Safety signal in records"}
              >
                <AlertIcon className="h-3 w-3" /> Safety signal
              </span>
            )}
          </div>
          <h4 className="mt-1.5 text-base font-bold text-slate-900">{rec.specialty}</h4>
          <p className="text-sm font-medium text-slate-600">{rec.title}</p>
          <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-slate-500">{rec.reason}</p>
        </div>
        <button
          type="button"
          onClick={onFindNearby}
          className="inline-flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition hover:border-brand-300 hover:bg-brand-50 hover:text-brand-800"
        >
          <LocationIcon className="h-4 w-4" /> Find nearby
          <span className="text-slate-400 group-hover:text-brand-600" aria-hidden="true">›</span>
        </button>
      </div>
    </div>
  );
}

function CareIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M4 21V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v15" />
      <path d="M9 4V2h6v2M3 21h18M9 21v-4h6v4" />
      <path d="M12 8v5M9.5 10.5h5" />
    </svg>
  );
}

/**
 * Always a Google Maps deep link — never OpenStreetMap.
 *
 * Google's canonical URI is preferred; otherwise a Maps search is built from
 * the facility's real name + address, with coordinates as a last resort so
 * the pin still lands on the right building.
 */
function googleMapsUrl(facility: CareFacility): string {
  const isGoogleHost = /^https?:\/\/([a-z0-9-]+\.)*(google\.[a-z.]+|goo\.gl)(\/|$)/i;
  if (facility.mapsUrl && isGoogleHost.test(facility.mapsUrl)) return facility.mapsUrl;

  const hasCoordinates =
    Number.isFinite(facility.latitude) && Number.isFinite(facility.longitude);
  const query = [facility.name, facility.address].filter(Boolean).join(", ");
  if (!query && hasCoordinates) {
    return `https://www.google.com/maps/search/?api=1&query=${facility.latitude},${facility.longitude}`;
  }
  const params = new URLSearchParams({
    api: "1",
    // Coordinates keep the map centred when several listings share a name.
    query: hasCoordinates ? `${query} ${facility.latitude},${facility.longitude}` : query,
  });
  return `https://www.google.com/maps/search/?${params.toString()}`;
}

/** `tel:` target, or null when the directory published no usable number. */
function telHref(phone: string | undefined): string | null {
  if (!phone) return null;
  const cleaned = phone.replace(/[^\d+]/g, "");
  return cleaned.length >= 3 ? `tel:${cleaned}` : null;
}
