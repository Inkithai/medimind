import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { FacilityCard, CareIcon, kindLabel } from "../components/care/FacilityCard";
import { FacilityResultsMap } from "../components/care/FacilityResultsMap";
import { LocationPicker } from "../components/location";
import { LocationIcon, RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useCopy } from "../i18n";
import type { PatientSnapshot } from "../types/api";
import type { CareFacility, FacilityKind } from "../types/facility";
import type { ConfirmedLocation } from "../types/location";
import { classNames } from "../utils/format";
import {
  countByFilter,
  filterFacilities,
  type FacilityFilter,
} from "../utils/facilities";
import {
  SPECIALTY_OPTIONS,
  specialtyLabel,
  suggestSpecialty,
  type SpecialtySuggestion,
} from "../utils/specialty";

const STORAGE_KEY = "medimind.find-care.location.v1";
const RADIUS_OPTIONS_KM = [2, 5, 10, 25];
const DEFAULT_RADIUS_KM = 5;

type SearchStatus = "idle" | "loading" | "success" | "error";
type SearchKind = "all" | FacilityKind;

const FILTER_ORDER: FacilityFilter[] = [
  "all",
  "hospital",
  "clinic",
  "pharmacy",
  "laboratory",
  "doctor",
  "other",
];

/** Facility types offered as a *search* narrowing (no "other" — it is a
 *  result bucket, not something a user asks for). */
const SEARCH_KINDS: SearchKind[] = ["all", "hospital", "clinic", "pharmacy", "laboratory", "doctor"];

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
  const copy = useCopy();
  const { credentials } = useAuth();
  const [savedLocation, setSavedLocation] = useState<ConfirmedLocation | null>(readSavedLocation);
  const [pickerKey, setPickerKey] = useState(0);
  const [facilities, setFacilities] = useState<CareFacility[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [searchKind, setSearchKind] = useState<SearchKind>("all");
  const [radiusKm, setRadiusKm] = useState<number>(DEFAULT_RADIUS_KM);
  const [specialty, setSpecialty] = useState<string>("");
  const [specialtyTouched, setSpecialtyTouched] = useState(false);
  const [suggestion, setSuggestion] = useState<SpecialtySuggestion | null>(null);
  const [filter, setFilter] = useState<FacilityFilter>("all");
  const [activeFacilityId, setActiveFacilityId] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  // Pull the specialty signal out of the already-extracted record. A failure
  // here must never block the directory search.
  useEffect(() => {
    let cancelled = false;
    api
      .getPatientSnapshot(credentials)
      .then((snapshot: PatientSnapshot) => {
        if (cancelled) return;
        const next = suggestSpecialty(snapshot);
        setSuggestion(next);
        // Pre-select it so the user does not repeat information MediMind
        // already extracted — they can still change or clear it.
        setSpecialty((current) => (current || specialtyTouched ? current : next?.specialty || ""));
      })
      .catch(() => {
        if (!cancelled) setSuggestion(null);
      });
    return () => {
      cancelled = true;
    };
    // Runs once per credential change; specialtyTouched is read, not tracked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credentials]);

  /**
   * BUG-001/002/003 fix: the counts and the rendered list are both derived
   * from `facilities` through the same predicate, in the same render. They
   * cannot disagree, and no stale array can survive a filter change.
   */
  const visibleFacilities = useMemo(
    () => filterFacilities(facilities, filter),
    [facilities, filter]
  );
  const counts = useMemo(() => countByFilter(facilities, FILTER_ORDER), [facilities]);

  const loadFacilities = useCallback(
    async (
      location: ConfirmedLocation,
      requestedKind: SearchKind,
      requestedRadiusKm: number,
      requestedSpecialty: string
    ) => {
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      setStatus("loading");
      setError(null);
      setFacilities([]);
      setActiveFacilityId(null);

      try {
        const nearby = await api.getCareFacilities(credentials, {
          location: location.displayName || location.name,
          kind: requestedKind === "all" ? "any" : requestedKind,
          radiusKm: requestedRadiusKm,
          latitude: location.latitude,
          longitude: location.longitude,
          specialty: requestedSpecialty || undefined,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setFacilities(nearby);
        // Always land on a filter that has results, so "N found" and the list
        // below it can never contradict each other.
        setFilter(
          requestedKind !== "all" && nearby.some((facility) => facility.kind === requestedKind)
            ? requestedKind
            : "all"
        );
        setStatus("success");
      } catch (requestError) {
        if (controller.signal.aborted) return;
        setError(
          requestError instanceof Error ? requestError.message : copy.findCare.errorFallback
        );
        setStatus("error");
      }
    },
    [copy.findCare.errorFallback, credentials]
  );

  function handleConfirm(location: ConfirmedLocation) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(location));
    setSavedLocation(location);
    void loadFacilities(location, searchKind, radiusKm, specialty);
    window.setTimeout(
      () => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      150
    );
  }

  /** Re-run the search whenever a preference changes after a first search. */
  function applyPreference(next: {
    kind?: SearchKind;
    radiusKm?: number;
    specialty?: string;
  }) {
    const nextKind = next.kind ?? searchKind;
    const nextRadius = next.radiusKm ?? radiusKm;
    const nextSpecialty = next.specialty ?? specialty;
    if (next.kind !== undefined) setSearchKind(next.kind);
    if (next.radiusKm !== undefined) setRadiusKm(next.radiusKm);
    if (next.specialty !== undefined) {
      setSpecialty(next.specialty);
      setSpecialtyTouched(true);
    }
    if (savedLocation && status !== "idle") {
      void loadFacilities(savedLocation, nextKind, nextRadius, nextSpecialty);
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
    setActiveFacilityId(null);
    setPickerKey((value) => value + 1);
  }

  return (
    <div className="space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
            <CareIcon className="h-3.5 w-3.5" /> {copy.findCare.eyebrow}
          </div>
          <h1 className="page-title">{copy.findCare.title}</h1>
          <p className="secondary-text mt-2 max-w-2xl leading-relaxed">{copy.findCare.subtitle}</p>
        </div>
        {savedLocation && (
          <button type="button" onClick={clearLocation} className="btn-secondary shrink-0">
            {copy.findCare.changeSearchArea}
          </button>
        )}
      </header>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900" role="note">
        <p className="font-semibold">{copy.findCare.urgentTitle}</p>
        <p className="mt-0.5 text-amber-800">{copy.findCare.urgentBody}</p>
      </div>

      {suggestion && (
        <SuggestedSpecialty
          suggestion={suggestion}
          isApplied={specialty === suggestion.specialty}
          onApply={() => applyPreference({ specialty: suggestion.specialty })}
          onClear={() => applyPreference({ specialty: "" })}
        />
      )}

      <CarePreferences
        searchKind={searchKind}
        radiusKm={radiusKm}
        specialty={specialty}
        onChange={applyPreference}
      />

      <LocationPicker
        key={pickerKey}
        initialValue={savedLocation}
        onConfirm={handleConfirm}
        title={copy.findCare.locationTitle}
        description={copy.findCare.locationDescription}
        confirmLabel={copy.findCare.confirmLabel}
        showAddressDetails={false}
      />

      <div ref={resultsRef} className="scroll-mt-8">
        {status === "idle" ? (
          <section className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
              <CareIcon className="h-6 w-6" />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-slate-900">{copy.findCare.idleTitle}</h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{copy.findCare.idleBody}</p>
          </section>
        ) : status === "loading" ? (
          <FacilityLoading
            locationName={savedLocation?.name || copy.location.selectedLocation}
            radiusKm={radiusKm}
          />
        ) : status === "error" ? (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center" role="alert">
            <h2 className="text-lg font-semibold text-red-900">{copy.findCare.errorTitle}</h2>
            <p className="mx-auto mt-1 max-w-lg text-sm text-red-700">{error}</p>
            <p className="mx-auto mt-2 max-w-lg text-sm text-red-600">
              {copy.findCare.errorDirectoryHint}
            </p>
            {savedLocation && (
              <button
                type="button"
                onClick={() => void loadFacilities(savedLocation, searchKind, radiusKm, specialty)}
                className="btn-secondary mt-5"
              >
                <RefreshIcon className="h-4 w-4" /> {copy.findCare.tryAgain}
              </button>
            )}
          </section>
        ) : (
          <FacilityResults
            facilities={facilities}
            visibleFacilities={visibleFacilities}
            counts={counts}
            filter={filter}
            onFilterChange={setFilter}
            location={savedLocation}
            radiusKm={radiusKm}
            activeFacilityId={activeFacilityId}
            onFocusFacility={(facility) => setActiveFacilityId(facility.id)}
          />
        )}
      </div>
    </div>
  );
}

/**
 * BUG-004/005/006/007 fix: shows the already-extracted specialty as applied,
 * separates finding → reasoning → search, and never presents it as a
 * diagnosis.
 */
function SuggestedSpecialty({
  suggestion,
  isApplied,
  onApply,
  onClear,
}: {
  suggestion: SpecialtySuggestion;
  isApplied: boolean;
  onApply: () => void;
  onClear: () => void;
}) {
  const copy = useCopy();
  return (
    <section
      className="rounded-2xl border border-brand-200 bg-brand-50/60 p-5"
      aria-labelledby="suggested-specialty-title"
    >
      <h2 id="suggested-specialty-title" className="text-sm font-bold uppercase tracking-wider text-brand-700">
        {copy.findCare.suggestedSpecialtyTitle}
      </h2>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <p className="text-xl font-bold text-slate-900">{suggestion.label}</p>
        {isApplied ? (
          <>
            <span className="rounded-full bg-brand-600 px-2.5 py-1 text-xs font-bold text-white">
              {copy.findCare.suggestedSpecialtyApplied(suggestion.label)}
            </span>
            <button type="button" onClick={onClear} className="btn-ghost min-h-[40px] px-3 py-1.5 text-sm">
              {copy.findCare.clearSpecialty}
            </button>
          </>
        ) : (
          <button type="button" onClick={onApply} className="btn-secondary min-h-[40px] px-3 py-1.5 text-sm">
            {copy.findCare.useSuggested}
          </button>
        )}
      </div>
      <p className="mt-2 max-w-2xl text-sm text-slate-600">
        {copy.findCare.suggestedSpecialtyDisclaimer}
      </p>
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-semibold text-brand-700 hover:underline">
          {copy.findCare.suggestedSpecialtyWhy}
        </summary>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">
          {copy.findCare.suggestedSpecialtyReason(suggestion.keyword, suggestion.label)}
        </p>
        {suggestion.evidence.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            {copy.findCare.suggestedSpecialtyEvidence}: {suggestion.evidence.join(", ")}
          </p>
        )}
        {suggestion.lowConfidenceCount > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            {copy.findCare.lowConfidenceNote(suggestion.lowConfidenceCount)}
          </p>
        )}
      </details>
    </section>
  );
}

function CarePreferences({
  searchKind,
  radiusKm,
  specialty,
  onChange,
}: {
  searchKind: SearchKind;
  radiusKm: number;
  specialty: string;
  onChange: (next: { kind?: SearchKind; radiusKm?: number; specialty?: string }) => void;
}) {
  const copy = useCopy();
  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
      aria-labelledby="care-preferences-title"
    >
      <h2 id="care-preferences-title" className="text-base font-bold text-slate-900">
        {copy.findCare.preferencesTitle}
      </h2>
      <p className="mt-1 text-xs text-slate-500">{copy.findCare.preferencesSubtitle}</p>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <div>
          <label htmlFor="care-kind" className="block text-sm font-semibold text-slate-800">
            {copy.findCare.facilityTypeLabel}
          </label>
          <select
            id="care-kind"
            value={searchKind}
            onChange={(event) => onChange({ kind: event.target.value as SearchKind })}
            className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
          >
            {SEARCH_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind === "all" ? copy.findCare.filterAll : filterLabel(kind, copy)}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">{copy.findCare.facilityTypeHelp}</p>
        </div>

        <div>
          <label htmlFor="care-specialty" className="block text-sm font-semibold text-slate-800">
            {copy.findCare.specialtyLabel}
          </label>
          <select
            id="care-specialty"
            value={specialty}
            onChange={(event) => onChange({ specialty: event.target.value })}
            className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
          >
            <option value="">{copy.findCare.specialtyNone}</option>
            {SPECIALTY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
            {specialty && !SPECIALTY_OPTIONS.some((option) => option.value === specialty) && (
              <option value={specialty}>{specialtyLabel(specialty)}</option>
            )}
          </select>
          <p className="mt-1 text-xs text-slate-500">{copy.findCare.specialtyHelp}</p>
        </div>

        <div>
          <label htmlFor="care-radius" className="block text-sm font-semibold text-slate-800">
            {copy.findCare.radiusLabel}
          </label>
          <select
            id="care-radius"
            value={radiusKm}
            onChange={(event) => onChange({ radiusKm: Number(event.target.value) })}
            className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
          >
            {RADIUS_OPTIONS_KM.map((km) => (
              <option key={km} value={km}>
                {copy.findCare.radiusOption(km)}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}

function FacilityLoading({ locationName, radiusKm }: { locationName: string; radiusKm: number }) {
  const copy = useCopy();
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" aria-live="polite">
      <div className="flex items-center gap-3">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
        <div>
          <h2 className="font-semibold text-slate-900">{copy.findCare.loadingTitle(locationName)}</h2>
          <p className="text-sm text-slate-500">{copy.findCare.loadingSubtitle(radiusKm)}</p>
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
  counts,
  filter,
  onFilterChange,
  location,
  radiusKm,
  activeFacilityId,
  onFocusFacility,
}: {
  facilities: CareFacility[];
  visibleFacilities: CareFacility[];
  counts: Record<string, number>;
  filter: FacilityFilter;
  onFilterChange: (filter: FacilityFilter) => void;
  location: ConfirmedLocation | null;
  radiusKm: number;
  activeFacilityId: string | null;
  onFocusFacility: (facility: CareFacility) => void;
}) {
  const copy = useCopy();
  const sources = [...new Set(facilities.map((facility) => facility.source))].join(", ");
  // Only offer categories that this result set actually contains, so the chips
  // can never advertise an empty view (plus the active one, to stay stable).
  const availableFilters = FILTER_ORDER.filter(
    (value) => value === "all" || counts[value] > 0 || value === filter
  );
  const nonEmptyLabels = FILTER_ORDER.filter((value) => value !== "all" && counts[value] > 0)
    .map((value) => `${filterLabel(value as FacilityKind, copy)} (${counts[value]})`)
    .join(", ");

  return (
    <section className="space-y-5" aria-live="polite">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <p className="text-sm font-medium text-brand-700">
            <LocationIcon className="mr-1 inline h-4 w-4" aria-hidden="true" />{" "}
            {copy.findCare.nearLocation(location?.name || copy.location.selectedLocation)}
          </p>
          <h2 className="section-title mt-1">
            {facilities.length
              ? copy.findCare.resultsCount(facilities.length)
              : copy.findCare.noResultsTitle}
          </h2>
        </div>
        {facilities.length > 0 && (
          <p className="text-xs text-slate-400">
            {copy.findCare.sortedByDistance} · {copy.findCare.sourcePrefix}:{" "}
            {sources || "public directory listings"} · {copy.findCare.notARecommendation}
          </p>
        )}
      </div>

      {facilities.length > 0 && (
        <div
          className="flex gap-2 overflow-x-auto pb-1 scroll-thin"
          role="group"
          aria-label={copy.findCare.filtersLabel}
        >
          {availableFilters.map((value) => {
            const label = value === "all" ? copy.findCare.filterAll : filterLabel(value, copy);
            const count = counts[value] ?? 0;
            const isActive = filter === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => onFilterChange(value)}
                aria-pressed={isActive}
                className={classNames(
                  "min-h-[44px] shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
                  isActive
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                )}
              >
                {label}{" "}
                <span className={isActive ? "text-slate-300" : "text-slate-400"}>{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {!facilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
          <CareIcon className="mx-auto h-8 w-8 text-slate-300" />
          <p className="mt-3 font-semibold text-slate-800">{copy.findCare.emptyAreaTitle}</p>
          <p className="mt-1 text-sm text-slate-500">{copy.findCare.emptyAreaBody(radiusKm)}</p>
        </div>
      ) : !visibleFacilities.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-8 text-center shadow-sm">
          <p className="font-semibold text-slate-800">
            {copy.findCare.emptyFilterTitle(
              filter === "all" ? copy.findCare.filterAll : filterLabel(filter, copy)
            )}
          </p>
          <p className="mt-1 text-sm text-slate-500">{copy.findCare.emptyFilterBody(nonEmptyLabels)}</p>
          <button type="button" onClick={() => onFilterChange("all")} className="btn-secondary mt-4">
            {copy.findCare.showAll}
          </button>
        </div>
      ) : (
        <>
          {location && (
            <FacilityResultsMap
              facilities={visibleFacilities}
              center={location}
              activeFacilityId={activeFacilityId}
              className="h-64 sm:h-80"
            />
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {visibleFacilities.map((facility) => (
              <FacilityCard
                key={facility.id}
                facility={facility}
                isActive={activeFacilityId === facility.id}
                onFocusFacility={onFocusFacility}
              />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function filterLabel(kind: FacilityKind, copy: ReturnType<typeof useCopy>): string {
  const labels: Record<FacilityKind, string> = {
    hospital: copy.findCare.filterHospital,
    clinic: copy.findCare.filterClinic,
    pharmacy: copy.findCare.filterPharmacy,
    laboratory: copy.findCare.filterLaboratory,
    doctor: copy.findCare.filterDoctor,
    other: copy.findCare.filterOther,
  };
  return labels[kind];
}

export { kindLabel };
