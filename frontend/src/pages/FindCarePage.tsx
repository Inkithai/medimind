import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { LocationPicker } from "../components/location";
import { SpecialtySelector, FACILITY_TYPES } from "../components/SpecialtySelector";
import {
  LocationIcon,
  RefreshIcon,
  SparkleIcon,
} from "../components/icons";
import { Spinner } from "../components/Spinner";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { CareFacility, FacilityKind } from "../types/facility";
import type { ConfirmedLocation } from "../types/location";
import type { CareRecommendation } from "../types/recommendations";
import { classNames } from "../utils/format";

const STORAGE_KEY = "medimind.find-care.location.v1";
const SEARCH_RADIUS_METRES = 5_000;

type SearchStatus = "idle" | "loading" | "success" | "error";
type FacilityFilter = "all" | FacilityKind;
type SearchKind = Exclude<FacilityFilter, "healthcare">;

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
      typeof value.name === "string" &&
      typeof value.displayName === "string"
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
  const [savedLocation, setSavedLocation] = useState<ConfirmedLocation | null>(readSavedLocation);
  const [pickerKey, setPickerKey] = useState(0);
  const [facilities, setFacilities] = useState<CareFacility[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [searchKind, setSearchKind] = useState<SearchKind>("all");
  const [specialty, setSpecialty] = useState<string>("");
  const [filter, setFilter] = useState<FacilityFilter>("all");
  const requestRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  // Recommendations state
  const [recommendations, setRecommendations] = useState<CareRecommendation[]>([]);
  const [recsLoading, setRecsLoading] = useState(true);
  const [recsError, setRecsError] = useState<string | null>(null);
  const [recsNote, setRecsNote] = useState<string | null>(null);

  // Expand/collapse evidence per recommendation
  const [expandedEvidence, setExpandedEvidence] = useState<Set<number>>(new Set());

  const recsRequestRef = useRef<AbortController | null>(null);

  // Load care recommendations on mount
  useStrictEffect(() => {
    const controller = new AbortController();
    recsRequestRef.current = controller;
    setRecsLoading(true);
    setRecsError(null);

    api
      .getCareRecommendations(credentials, controller.signal)
      .then((res) => {
        if (controller.signal.aborted) return;
        setRecommendations(res.recommendations || []);
        setRecsNote(res.note || null);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        // Non-critical: if recommendations fail, page still works
        setRecsError(err instanceof Error ? err.message : "Could not load recommendations");
        setRecommendations([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setRecsLoading(false);
      });

    return () => controller.abort();
  }, [credentials]);

  useEffect(() => () => requestRef.current?.abort(), []);

  const visibleFacilities = useMemo(
    () => facilities.filter((facility) => filter === "all" || facility.kind === filter),
    [facilities, filter]
  );

  const handleConfirm = useCallback(
    (location: ConfirmedLocation) => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(location));
      setSavedLocation(location);
      setFilter(searchKind);
      void loadFacilities(location, searchKind);
      window.setTimeout(
        () => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
        150
      );
    },
    [searchKind]
  );

  async function loadFacilities(location: ConfirmedLocation, requestedKind: SearchKind) {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setStatus("loading");
    setError(null);
    setFacilities([]);

    try {
      const nearby = await api.getCareFacilities(credentials, {
        location: location.displayName || location.name,
        kind: requestedKind === "all" ? "any" : requestedKind,
        radiusKm: SEARCH_RADIUS_METRES / 1_000,
        latitude: location.latitude,
        longitude: location.longitude,
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

  /** Called when user clicks "Find nearby" on a recommendation card. */
  function handleUseRecommendation(rec: CareRecommendation) {
    setSpecialty(rec.specialty_key);
    setSearchKind("doctor");
    // Scroll to the search form
    window.setTimeout(() => {
      document.getElementById("care-search-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  }

  function toggleEvidence(idx: number) {
    setExpandedEvidence((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  return (
    <div className="space-y-7">
      {/* ─── Header ────────────────────────────────────────────────────── */}
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
            Change search area
          </button>
        )}
      </header>

      {/* ─── Urgent help banner ────────────────────────────────────────── */}
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <p className="font-semibold">Need urgent help?</p>
        <p className="mt-0.5 text-amber-800">
          For a life-threatening emergency, contact your local emergency service immediately. Facility
          information comes from public directory listings and should be verified before travelling.
        </p>
      </div>

      {/* ─── Care Recommendations ──────────────────────────────────────── */}
      {recsLoading ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-3">
            <Spinner className="h-5 w-5 text-brand-600" />
            <p className="text-sm font-medium text-slate-600">Analysing your records for care options…</p>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-28 animate-pulse rounded-2xl bg-slate-100" />
            ))}
          </div>
        </section>
      ) : recsError ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
          <p className="font-semibold">Recommendations unavailable</p>
          <p className="mt-0.5 text-amber-800">{recsError}. You can still search for nearby care below.</p>
        </section>
      ) : recommendations.length > 0 ? (
        <section className="space-y-4">
          <div>
            <h2 className="section-title">Care recommendations</h2>
            <p className="secondary-text mt-1">
              Based on diagnoses, medications, allergies, and lab results in your records.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {recommendations.map((rec, idx) => (
              <RecommendationCard
                key={`${rec.specialty_key}-${idx}`}
                rec={rec}
                expanded={expandedEvidence.has(idx)}
                onToggleEvidence={() => toggleEvidence(idx)}
                onFindNearby={() => handleUseRecommendation(rec)}
              />
            ))}
          </div>
          {recsNote && (
            <p className="text-xs text-slate-400">{recsNote}</p>
          )}
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

      {/* ─── Search Form ───────────────────────────────────────────────── */}
      <section
        id="care-search-form"
        className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm scroll-mt-8"
      >
        <h2 className="section-title mb-5">Find nearby care</h2>

        <div className="grid gap-5 sm:grid-cols-2">
          {/* Facility type */}
          <div>
            <label htmlFor="care-facility-type" className="mb-2 block text-sm font-semibold text-slate-800">
              Care type
            </label>
            <select
              id="care-facility-type"
              value={searchKind}
              onChange={(event) => setSearchKind(event.target.value as SearchKind)}
              className="min-h-[52px] w-full rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
            >
              {FACILITY_TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {/* Specialty selector */}
          <SpecialtySelector
            value={specialty}
            onChange={setSpecialty}
            recommendations={recommendations.length > 0 ? recommendations : undefined}
          />
        </div>

        {/* Availability and radius */}
        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="care-availability" className="mb-2 block text-sm font-semibold text-slate-800">
              When are you available?
            </label>
            <select
              id="care-availability"
              className="min-h-[52px] w-full rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
              defaultValue="any"
            >
              <option value="any">Any time</option>
              <option value="today">Available today</option>
              <option value="week">This week</option>
            </select>
          </div>
          <div>
            <label htmlFor="care-radius" className="mb-2 block text-sm font-semibold text-slate-800">
              Search within
            </label>
            <select
              id="care-radius"
              className="min-h-[52px] w-full rounded-2xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
              defaultValue="5"
            >
              <option value="2">2 km</option>
              <option value="5">5 km</option>
              <option value="10">10 km</option>
              <option value="25">25 km</option>
            </select>
          </div>
        </div>
      </section>

      {/* ─── Location Picker ───────────────────────────────────────────── */}
      <LocationPicker
        key={pickerKey}
        initialValue={savedLocation}
        onConfirm={handleConfirm}
        title="Where should we search?"
        description="Search for a city, area or landmark, or use your current location."
        confirmLabel="Search nearby care"
        showAddressDetails={false}
      />

      {/* ─── Results ───────────────────────────────────────────────────── */}
      <div ref={resultsRef} className="scroll-mt-8">
        {status === "idle" ? (
          <section className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
              <CareIcon className="h-6 w-6" />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-slate-900">Select an area to begin</h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
              Confirm the map pin above and nearby care options will appear here.
            </p>
          </section>
        ) : status === "loading" ? (
          <FacilityLoading locationName={savedLocation?.name || "your location"} />
        ) : status === "error" ? (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <h2 className="text-lg font-semibold text-red-900">Nearby search didn't load</h2>
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
          />
        )}
      </div>

      {/* ─── About section ─────────────────────────────────────────────── */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <details>
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">
            About these recommendations
          </summary>
          <div className="mt-3 space-y-2 text-sm text-slate-600 leading-relaxed">
            <p>
              MediMind analysed diagnoses, medications, allergies, and laboratory results in your uploaded
              records to generate the care recommendations shown above.
            </p>
            <p>
              These suggestions are intended to help you decide what type of care to search for. They are
              <strong> not a diagnosis or medical referral</strong>.
            </p>
            <p>
              Facility information comes from public directory listings. MediMind does not verify clinical
              quality, availability, or affiliation of any listed provider.
            </p>
            <Link to="/safety" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:text-brand-800 hover:underline">
              View supporting records →
            </Link>
          </div>
        </details>
      </section>
    </div>
  );
}

// ─── Recommendation Card ────────────────────────────────────────────────────

function RecommendationCard({
  rec,
  expanded,
  onToggleEvidence,
  onFindNearby,
}: {
  rec: CareRecommendation;
  expanded: boolean;
  onToggleEvidence: () => void;
  onFindNearby: () => void;
}) {
  return (
    <article className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={classNames(
                "inline-flex items-center rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                relevanceTone(rec.relevance)
              )}
            >
              {relevanceLabel(rec.relevance)}
            </span>
            {rec.source_records > 0 && (
              <span className="text-[10px] font-medium text-slate-400">
                {rec.source_records} {rec.source_records === 1 ? "record" : "records"}
              </span>
            )}
          </div>
          <h3 className="mt-2 text-base font-bold text-slate-900">{rec.specialty}</h3>
          <p className="mt-0.5 text-sm font-medium text-slate-600">{rec.title}</p>
        </div>
      </div>

      {/* Explanation */}
      <p className="mt-3 flex-1 text-sm leading-relaxed text-slate-500">{rec.explanation}</p>

      {/* Evidence section */}
      {rec.evidence.length > 0 && (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <button
            type="button"
            onClick={onToggleEvidence}
            className="flex items-center gap-1.5 text-xs font-medium text-brand-700 hover:text-brand-800"
          >
            <span className="inline-flex items-center rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-bold text-brand-600 ring-1 ring-brand-100">
              Evidence · {rec.evidence.length}
            </span>
            {expanded ? "Hide" : "View"} evidence
          </button>
          {expanded && (
            <ul className="mt-2 space-y-1">
              {rec.evidence.map((e, i) => (
                <li key={i} className="text-xs text-slate-500 leading-relaxed">
                  {e.date && <span className="font-medium text-slate-600">{e.date}: </span>}
                  {e.description}
                  {e.source_file && (
                    <span className="ml-1 text-slate-400">({e.source_file})</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-4 flex flex-wrap gap-2">
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

// ─── Facility sub-components ────────────────────────────────────────────────

function FacilityLoading({ locationName }: { locationName: string }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
        <div>
          <h2 className="font-semibold text-slate-900">Finding care near {locationName}…</h2>
          <p className="text-sm text-slate-500">Searching within 5 km</p>
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
}: {
  facilities: CareFacility[];
  visibleFacilities: CareFacility[];
  filter: FacilityFilter;
  onFilterChange: (filter: FacilityFilter) => void;
  location: ConfirmedLocation | null;
}) {
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
              ? `${facilities.length} care ${facilities.length === 1 ? "option" : "options"} found`
              : "No facilities found nearby"}
          </h2>
        </div>
        {facilities.length > 0 && (
          <p className="text-xs text-slate-400">
            Sorted by distance · Source: {sources || "public directory listings"} · Not a MediMind recommendation
          </p>
        )}
      </div>

      {facilities.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1 scroll-thin" aria-label="Filter facilities">
          {FILTERS_LIST.map((item) => {
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
                {item.label} <span className={filter === item.value ? "text-slate-300" : "text-slate-400"}>{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {!facilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
          <CareIcon className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 font-semibold text-slate-800">Try a different area</p>
          <p className="mt-1 text-sm text-slate-500">
            The selected directory doesn't list any supported healthcare facilities within 5 km of this pin.
          </p>
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

      {facilities.length > 0 && (
        <p className="text-xs text-slate-400 leading-relaxed">
          Public directory information · MediMind does not verify clinical quality, availability, or affiliation.
        </p>
      )}
    </section>
  );
}

function FacilityCard({ facility }: { facility: CareFacility }) {
  const mapUrl =
    facility.mapsUrl ||
    `https://www.openstreetmap.org/?mlat=${facility.latitude}&mlon=${facility.longitude}#map=17/${facility.latitude}/${facility.longitude}`;
  return (
    <article className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="flex items-start gap-3">
        <span className={classNames("flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", kindTone(facility.kind))}>
          <CareIcon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
              {kindLabel(facility.kind)}
            </span>
            {facility.openNow !== undefined && (
              <span
                className={classNames(
                  "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider",
                  facility.openNow ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                )}
              >
                {facility.openNow ? "Open now" : "Closed now"}
              </span>
            )}
          </div>
          <h3 className="mt-2 text-base font-bold text-slate-900">{facility.name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {facility.distanceKm !== null && (
              <span className="font-semibold text-brand-700">{distanceLabel(facility.distanceKm)} away</span>
            )}
            {facility.rating !== undefined && (
              <span className="text-amber-700">
                ★ {facility.rating.toFixed(1)}
                {facility.userRatingCount !== undefined && (
                  <span className="text-slate-400"> ({facility.userRatingCount})</span>
                )}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="mt-4 flex-1 space-y-2 border-t border-slate-100 pt-4 text-sm text-slate-500">
        <p>{facility.address || "Address not listed"}</p>
        {Boolean(facility.openingHours?.length) && (
          <details>
            <summary className="cursor-pointer font-medium text-slate-700">Opening hours</summary>
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
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <a href={mapUrl} target="_blank" rel="noreferrer" className="btn-secondary min-h-[40px] px-4 py-2 text-sm">
          <LocationIcon className="h-4 w-4" /> View map
        </a>
        {facility.website && (
          <a href={facility.website} target="_blank" rel="noreferrer" className="btn-ghost min-h-[40px] px-4 py-2 text-sm">
            Website
          </a>
        )}
      </div>
    </article>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const FILTERS_LIST: Array<{ value: FacilityFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "hospital", label: "Hospitals" },
  { value: "clinic", label: "Clinics" },
  { value: "pharmacy", label: "Pharmacies" },
  { value: "laboratory", label: "Laboratories" },
  { value: "doctor", label: "Doctors" },
];

function relevanceTone(relevance: string): string {
  switch (relevance) {
    case "high":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "moderate":
      return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
    case "possible":
      return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
    case "needs_clinical_review":
      return "bg-purple-50 text-purple-700 ring-1 ring-purple-200";
    default:
      return "bg-slate-100 text-slate-600 ring-1 ring-slate-200";
  }
}

function relevanceLabel(relevance: string): string {
  switch (relevance) {
    case "high":
      return "High relevance";
    case "moderate":
      return "Moderate relevance";
    case "possible":
      return "Possible";
    case "needs_clinical_review":
      return "Needs clinical review";
    default:
      return relevance;
  }
}

function kindLabel(kind: FacilityKind): string {
  const labels: Record<FacilityKind, string> = {
    hospital: "Hospital",
    clinic: "Clinic",
    pharmacy: "Pharmacy",
    laboratory: "Laboratory",
    doctor: "Doctor",
    healthcare: "Healthcare",
  };
  return labels[kind];
}

function kindTone(kind: FacilityKind): string {
  if (kind === "hospital") return "bg-red-50 text-red-700";
  if (kind === "pharmacy") return "bg-emerald-50 text-emerald-700";
  if (kind === "laboratory") return "bg-amber-50 text-amber-700";
  if (kind === "doctor") return "bg-violet-50 text-violet-700";
  return "bg-sky-50 text-sky-700";
}

function distanceLabel(distanceKm: number): string {
  if (distanceKm < 1) return `${Math.max(1, Math.round(distanceKm * 1_000))} m`;
  return `${distanceKm.toFixed(distanceKm < 10 ? 1 : 0)} km`;
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
