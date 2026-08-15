import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { LocationPicker } from "../components/location";
import { LocationIcon, RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type { CareFacility, FacilityKind, SpecialtySuggestion } from "../types/facility";
import type { ConfirmedLocation } from "../types/location";
import { classNames } from "../utils/format";

const STORAGE_KEY = "medimind.find-care.location.v1";
const RADIUS_KEY = "medimind.find-care.radius.v1";
const RADIUS_OPTIONS_KM = [5, 10, 20, 50] as const;
const DEFAULT_RADIUS_KM = 5;

type SearchStatus = "idle" | "loading" | "success" | "error";
type FacilityFilter = "all" | FacilityKind;
type SearchKind = "all" | Exclude<FacilityKind, "healthcare">;

const SEARCH_KINDS: Array<{ value: SearchKind; label: string }> = [
  { value: "all", label: "All" },
  { value: "hospital", label: "Hospitals" },
  { value: "clinic", label: "Clinics" },
  { value: "doctor", label: "Doctors" },
  { value: "pharmacy", label: "Pharmacies" },
  { value: "laboratory", label: "Laboratories" },
];

const RESULT_FILTERS: Array<{ value: FacilityFilter; label: string }> = [
  { value: "all", label: "All" },
  { value: "hospital", label: "Hospitals" },
  { value: "clinic", label: "Clinics" },
  { value: "doctor", label: "Doctors" },
  { value: "pharmacy", label: "Pharmacies" },
  { value: "laboratory", label: "Laboratories" },
  { value: "healthcare", label: "Other" },
];

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

function readSavedRadius(): number {
  try {
    const value = Number(localStorage.getItem(RADIUS_KEY));
    if ((RADIUS_OPTIONS_KM as readonly number[]).includes(value)) return value;
  } catch {
    // Fall through to the default.
  }
  return DEFAULT_RADIUS_KM;
}

export function FindCarePage() {
  const { credentials } = useAuth();
  const [savedLocation, setSavedLocation] = useState<ConfirmedLocation | null>(readSavedLocation);
  const [pickerKey, setPickerKey] = useState(0);
  const [facilities, setFacilities] = useState<CareFacility[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [searchKind, setSearchKind] = useState<SearchKind>("all");
  const [radiusKm, setRadiusKm] = useState<number>(readSavedRadius);
  const [searchedRadiusKm, setSearchedRadiusKm] = useState<number>(readSavedRadius);
  const [filter, setFilter] = useState<FacilityFilter>("all");
  const [suggestion, setSuggestion] = useState<SpecialtySuggestion | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const suggestionRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  useEffect(
    () => () => {
      requestRef.current?.abort();
      suggestionRef.current?.abort();
    },
    []
  );

  // Load the evidence-graded specialty suggestion once. It is a
  // directory-search aid derived from the user's own records — never a
  // diagnosis or referral — and Find Care works fine without it.
  useEffect(() => {
    const controller = new AbortController();
    suggestionRef.current = controller;
    api
      .getSpecialtySuggestion(credentials, { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setSuggestion(value);
      })
      .catch(() => {
        /* Suggestion is optional; ignore failures. */
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const visibleFacilities = useMemo(
    () => facilities.filter((facility) => filter === "all" || facility.kind === filter),
    [facilities, filter]
  );

  function handleConfirm(location: ConfirmedLocation) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(location));
    setSavedLocation(location);
    setFilter(searchKind === "all" ? "all" : searchKind);
    void loadFacilities(location, searchKind, radiusKm);
    window.setTimeout(
      () => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      150
    );
  }

  function handleRadiusChange(nextRadius: number) {
    setRadiusKm(nextRadius);
    try {
      localStorage.setItem(RADIUS_KEY, String(nextRadius));
    } catch {
      /* best-effort persistence */
    }
    if (savedLocation && status !== "idle") {
      void loadFacilities(savedLocation, searchKind, nextRadius);
    }
  }

  async function loadFacilities(
    location: ConfirmedLocation,
    requestedKind: SearchKind,
    requestedRadiusKm: number
  ) {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setStatus("loading");
    setError(null);
    setFacilities([]);
    setSearchedRadiusKm(requestedRadiusKm);

    try {
      const nearby = await api.getCareFacilities(credentials, {
        location: location.displayName || location.name,
        kind: requestedKind === "all" ? "any" : requestedKind,
        radiusKm: requestedRadiusKm,
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
          : "We couldn't load nearby listings. Please try again."
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

  return (
    <div className="space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
            <CareIcon className="h-3.5 w-3.5" /> Find care
          </div>
          <h1 className="page-title">Find nearby healthcare</h1>
          <p className="secondary-text mt-2 max-w-2xl leading-relaxed">
            Search healthcare locations from publicly available directory data. Choose a location,
            facility type, and search radius.
          </p>
        </div>
        {savedLocation && (
          <button type="button" onClick={clearLocation} className="btn-secondary shrink-0">
            Change location
          </button>
        )}
      </header>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <p className="font-semibold">Need urgent help?</p>
        <p className="mt-0.5 text-amber-800">
          For a life-threatening emergency, contact your local emergency service immediately.
        </p>
      </div>

      {suggestion && <SpecialtySuggestionCard suggestion={suggestion} />}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-6 sm:grid-cols-2">
          <div>
            <span className="block text-sm font-semibold text-slate-800">Facility type</span>
            <p className="mt-1 text-xs text-slate-500">
              Choose a category or search all publicly listed healthcare locations.
            </p>
            <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label="Facility type">
              {SEARCH_KINDS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={searchKind === option.value}
                  onClick={() => setSearchKind(option.value)}
                  className={classNames(
                    "min-h-[40px] rounded-full px-4 py-2 text-sm font-semibold transition",
                    searchKind === option.value
                      ? "bg-slate-900 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  )}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <span className="block text-sm font-semibold text-slate-800">Search within</span>
            <p className="mt-1 text-xs text-slate-500">
              Only listings inside this distance are returned.
            </p>
            <div className="mt-3 flex flex-wrap gap-2" role="radiogroup" aria-label="Search radius">
              {RADIUS_OPTIONS_KM.map((option) => (
                <button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={radiusKm === option}
                  onClick={() => handleRadiusChange(option)}
                  className={classNames(
                    "min-h-[40px] rounded-full px-4 py-2 text-sm font-semibold transition",
                    radiusKm === option
                      ? "bg-brand-600 text-white"
                      : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  )}
                >
                  {option} km
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <LocationPicker
        key={pickerKey}
        initialValue={savedLocation}
        onConfirm={handleConfirm}
        title="Where should we search?"
        description="Search for a city, area or landmark, or use your current location."
        confirmLabel="Search nearby listings"
        showAddressDetails={false}
      />

      <div ref={resultsRef} className="scroll-mt-8">
        {status === "idle" ? (
          <section className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
              <CareIcon className="h-6 w-6" />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-slate-900">Select an area to begin</h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
              Confirm the map pin above and publicly listed healthcare locations will appear here.
            </p>
          </section>
        ) : status === "loading" ? (
          <FacilityLoading locationName={savedLocation?.name || "your location"} radiusKm={searchedRadiusKm} />
        ) : status === "error" ? (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <h2 className="text-lg font-semibold text-red-900">Nearby search didn't load</h2>
            <p className="mx-auto mt-1 max-w-lg text-sm text-red-700">{error}</p>
            {savedLocation && (
              <button
                type="button"
                onClick={() => void loadFacilities(savedLocation, searchKind, radiusKm)}
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
            radiusKm={searchedRadiusKm}
          />
        )}
      </div>
    </div>
  );
}

function SpecialtySuggestionCard({ suggestion }: { suggestion: SpecialtySuggestion }) {
  const [expanded, setExpanded] = useState(false);
  // "none" carries no useful signal — keep the page clean.
  if (suggestion.evidence_level === "none") return null;
  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-label="Specialty search suggestion"
    >
      <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
        From your uploaded records
      </p>
      <h2 className="mt-1 text-base font-bold text-slate-900">{suggestion.headline}</h2>
      <p className="mt-2 text-sm leading-relaxed text-slate-600">{suggestion.explanation}</p>
      {suggestion.search_options.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-slate-500">You can search for:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {suggestion.search_options.map((option) => (
              <span
                key={option}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600"
              >
                {option}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">
        <span aria-hidden="true">⚠️ </span>
        This is a directory search aid, not a diagnosis or medical referral.{" "}
        {expanded ? (
          <>
            {suggestion.disclaimer}{" "}
            {suggestion.hint && <span>{suggestion.hint}</span>}
          </>
        ) : (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="font-semibold underline hover:text-amber-700"
          >
            Learn more
          </button>
        )}
      </div>
    </section>
  );
}

function FacilityLoading({ locationName, radiusKm }: { locationName: string; radiusKm: number }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
        <div>
          <h2 className="font-semibold text-slate-900">Searching near {locationName}…</h2>
          <p className="text-sm text-slate-500">Healthcare listings within {radiusKm} km</p>
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
  radiusKm,
}: {
  facilities: CareFacility[];
  visibleFacilities: CareFacility[];
  filter: FacilityFilter;
  onFilterChange: (filter: FacilityFilter) => void;
  location: ConfirmedLocation | null;
  radiusKm: number;
}) {
  const sources = [...new Set(facilities.map((facility) => facility.source))].join(", ");
  // Counts always come from the normalized per-listing categories.
  const counts = useMemo(() => {
    const byKind = new Map<string, number>();
    for (const facility of facilities) {
      byKind.set(facility.kind, (byKind.get(facility.kind) || 0) + 1);
    }
    return byKind;
  }, [facilities]);

  return (
    <section className="space-y-5" aria-live="polite">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">
            <LocationIcon className="mr-1 inline h-4 w-4" /> Search location:{" "}
            {location?.name || "selected location"}
          </p>
          <h2 className="section-title mt-1">
            {facilities.length
              ? `${facilities.length} healthcare ${facilities.length === 1 ? "listing" : "listings"} within ${radiusKm} km`
              : `No healthcare listings within ${radiusKm} km`}
          </h2>
          {facilities.length > 0 && (
            <p className="mt-1 text-xs text-slate-400">Ordered by distance.</p>
          )}
        </div>
      </div>

      {facilities.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1 scroll-thin" aria-label="Filter listings">
          {RESULT_FILTERS.map((item) => {
            const count = item.value === "all" ? facilities.length : counts.get(item.value) || 0;
            if (item.value !== "all" && count === 0) return null;
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
                {item.label}{" "}
                <span className={filter === item.value ? "text-slate-300" : "text-slate-400"}>{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {!facilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
          <CareIcon className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 font-semibold text-slate-800">Try a wider radius or a different area</p>
          <p className="mt-1 text-sm text-slate-500">
            The public directory doesn't list any matching healthcare locations within {radiusKm} km of
            this pin.
          </p>
        </div>
      ) : !visibleFacilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-8 text-center text-sm text-slate-500">
          No listings match this filter. Choose another category to continue.
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {visibleFacilities.map((facility) => (
            <FacilityCard key={facility.id} facility={facility} />
          ))}
        </div>
      )}

      {facilities.length > 0 && (
        <div className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-xs text-slate-500">
          <p className="font-semibold text-slate-600">Data transparency</p>
          <p className="mt-1">
            Data source: {sources || "public directory listings"}. MediMind does not verify or endorse
            these listings. Information may be incomplete or outdated — verify specialty, availability,
            and contact details directly with the provider.
          </p>
        </div>
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
        {facility.address && <p>{facility.address}</p>}
        {Boolean(facility.specialties?.length) && (
          <p>
            <span className="font-medium text-slate-700">Listed specialties:</span>{" "}
            {facility.specialties?.join(", ")}
          </p>
        )}
        {Boolean(facility.openingHours?.length) && (
          <details>
            <summary className="cursor-pointer font-medium text-slate-700">Listed hours</summary>
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
        <p className="text-xs text-slate-400">Source: {facility.source}</p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <a href={mapUrl} target="_blank" rel="noreferrer" className="btn-secondary min-h-[40px] px-4 py-2 text-sm">
          <LocationIcon className="h-4 w-4" /> View on map
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

function kindLabel(kind: FacilityKind): string {
  const labels: Record<FacilityKind, string> = {
    hospital: "Hospital",
    clinic: "Clinic",
    pharmacy: "Pharmacy",
    laboratory: "Laboratory",
    doctor: "Doctor",
    healthcare: "Other healthcare",
  };
  return labels[kind];
}

function kindTone(kind: FacilityKind): string {
  if (kind === "hospital") return "bg-red-50 text-red-700";
  if (kind === "pharmacy") return "bg-emerald-50 text-emerald-700";
  if (kind === "laboratory") return "bg-amber-50 text-amber-700";
  if (kind === "doctor") return "bg-violet-50 text-violet-700";
  if (kind === "healthcare") return "bg-slate-100 text-slate-600";
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
