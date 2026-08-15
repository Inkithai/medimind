import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { LocationPicker } from "../components/location";
import { LocationIcon, RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type {
  CareFacility,
  CareSpecialty,
  FacilityKind,
  MatchLevel,
} from "../types/facility";
import type { ConfirmedLocation } from "../types/location";
import type { Timeline } from "../types/api";
import { classNames } from "../utils/format";
import { patientName, specialtyLabel, suggestSpecialty } from "../utils/specialty";

const STORAGE_KEY = "medimind.find-care.location.v1";
const SEARCH_RADIUS_METRES = 5_000;

type SearchStatus = "idle" | "loading" | "success" | "error";
type SearchKind = "any" | FacilityKind;

const KIND_FILTERS: Array<{ value: SearchKind; label: string }> = [
  { value: "any", label: "All" },
  { value: "hospital", label: "Hospitals" },
  { value: "clinic", label: "Clinics" },
  { value: "doctor", label: "Doctors" },
  { value: "pharmacy", label: "Pharmacies" },
  { value: "laboratory", label: "Laboratories" },
  { value: "other", label: "Other" },
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

export function FindCarePage() {
  const { credentials } = useAuth();
  const [savedLocation, setSavedLocation] = useState<ConfirmedLocation | null>(readSavedLocation);
  const [pickerKey, setPickerKey] = useState(0);
  const [facilities, setFacilities] = useState<CareFacility[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  // Specialty context -------------------------------------------------------
  const [specialties, setSpecialties] = useState<CareSpecialty[]>([]);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [suggestedSpecialty, setSuggestedSpecialty] = useState<string | null>(null);
  // The specialty actually applied to the search. "" means none / any.
  const [specialty, setSpecialty] = useState<string>("");
  const [specialtyChanged, setSpecialtyChanged] = useState(false);
  const [openNowOnly, setOpenNowOnly] = useState(false);
  const [kindFilter, setKindFilter] = useState<SearchKind>("any");

  const requestRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  // Load specialty catalog + patient snapshot once, to suggest a specialty.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [catalog, snapshot] = await Promise.all([
          api.getCareSpecialties(credentials).catch(() => [] as CareSpecialty[]),
          api.getPatientSnapshot(credentials).catch(() => null),
        ]);
        if (cancelled) return;
        setSpecialties(catalog);
        if (snapshot) {
          setTimeline(snapshot.patient_timeline);
          const suggested = suggestSpecialty(snapshot.patient_timeline);
          setSuggestedSpecialty(suggested);
          // Only pre-select when the user hasn't touched the selector.
          if (suggested) setSpecialty(suggested);
        }
      } catch {
        // Specialty suggestion is best-effort; absence is non-fatal.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [credentials]);

  useEffect(() => () => requestRef.current?.abort(), []);

  const patient = patientName(timeline);
  const specialtyName = specialtyLabel(specialty || null, specialties);

  function handleConfirm(location: ConfirmedLocation) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(location));
    setSavedLocation(location);
    void loadFacilities(location, specialty);
    window.setTimeout(
      () => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      150
    );
  }

  async function loadFacilities(location: ConfirmedLocation, selectedSpecialty: string) {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setStatus("loading");
    setError(null);
    setFacilities([]);

    try {
      const nearby = await api.getCareFacilities(credentials, {
        location: location.displayName || location.name,
        kind: "any",
        radiusKm: SEARCH_RADIUS_METRES / 1_000,
        latitude: location.latitude,
        longitude: location.longitude,
        specialty: selectedSpecialty || undefined,
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
    setKindFilter("any");
    setOpenNowOnly(false);
    setPickerKey((value) => value + 1);
  }

  function onSpecialtyChange(value: string) {
    setSpecialty(value);
    setSpecialtyChanged(true);
    if (savedLocation && status !== "loading") {
      void loadFacilities(savedLocation, value);
    }
  }

  // Filtering + grouping for display ---------------------------------------
  const filtered = useMemo(
    () =>
      facilities.filter((facility) => {
        if (kindFilter !== "any" && facility.kind !== kindFilter) return false;
        if (openNowOnly && facility.openNow !== true) return false;
        return true;
      }),
    [facilities, kindFilter, openNowOnly]
  );

  const countByKind = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const f of facilities) counts[f.kind] = (counts[f.kind] ?? 0) + 1;
    return counts;
  }, [facilities]);

  const exactMatches = useMemo(
    () => filtered.filter((f) => f.matchLevel === "exact"),
    [filtered]
  );
  const relatedMatches = useMemo(
    () => filtered.filter((f) => f.matchLevel === "related" || f.matchLevel === undefined),
    [filtered]
  );
  const otherMatches = useMemo(
    () => filtered.filter((f) => f.matchLevel === "other"),
    [filtered]
  );

  return (
    <div className="space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
            <CareIcon className="h-3.5 w-3.5" /> Find care
          </div>
          <h1 className="page-title">Find nearby care</h1>
          <p className="secondary-text mt-2 max-w-2xl leading-relaxed">
            Choose a location and a clinical need. MediMind ranks public directory listings by whether
            they explicitly mention that specialty, then by distance. Listings are directory information
            only — not a medical recommendation.
          </p>
        </div>
        {savedLocation && (
          <button type="button" onClick={clearLocation} className="btn-secondary shrink-0">
            Change search area
          </button>
        )}
      </header>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900">
        <p className="font-semibold">Need urgent help?</p>
        <p className="mt-0.5 text-amber-800">
          For a life-threatening emergency, contact your local emergency service immediately. Facility
          information comes from public directory listings and should be verified before travelling.
        </p>
      </div>

      {/* Specialty context */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <label htmlFor="care-specialty" className="block text-sm font-semibold text-slate-800">
          What are you looking for?
        </label>
        <p className="mt-1 text-xs text-slate-500">
          {patient ? (
            <>
              Based on {patient}&apos;s records
              {suggestedSpecialty && !specialtyChanged && specialtyName ? (
                <>
                  {" "}
                  — we suggested <span className="font-semibold text-brand-700">{specialtyName}</span>.
                </>
              ) : null}
              . A listing only matches when it explicitly states this specialty.
            </>
          ) : (
            <>Choose a clinical need. A listing only matches when it explicitly states this specialty.</>
          )}
        </p>
        <select
          id="care-specialty"
          value={specialty}
          onChange={(event) => onSpecialtyChange(event.target.value)}
          className="mt-3 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100 sm:max-w-md"
        >
          <option value="">Any healthcare (general nearby listings)</option>
          {specialties.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </section>

      <LocationPicker
        key={pickerKey}
        initialValue={savedLocation}
        onConfirm={handleConfirm}
        title="Where should we search?"
        description="Search for a city, area or landmark, or use your current location."
        confirmLabel="Find listings nearby"
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
              Confirm the map pin above and nearby healthcare listings will appear here.
            </p>
          </section>
        ) : status === "loading" ? (
          <FacilityLoading locationName={savedLocation?.name || "your location"} />
        ) : status === "error" ? (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
            <h2 className="text-lg font-semibold text-red-900">Nearby search didn&apos;t load</h2>
            <p className="mx-auto mt-1 max-w-lg text-sm text-red-700">{error}</p>
            {savedLocation && (
              <button
                type="button"
                onClick={() => void loadFacilities(savedLocation, specialty)}
                className="btn-secondary mt-5"
              >
                <RefreshIcon className="h-4 w-4" /> Try again
              </button>
            )}
          </section>
        ) : (
          <FacilityResults
            facilities={facilities}
            filtered={filtered}
            exactMatches={exactMatches}
            relatedMatches={relatedMatches}
            otherMatches={otherMatches}
            countByKind={countByKind}
            kindFilter={kindFilter}
            onKindFilterChange={setKindFilter}
            openNowOnly={openNowOnly}
            onOpenNowChange={setOpenNowOnly}
            location={savedLocation}
            specialtyApplied={Boolean(specialty)}
            specialtyName={specialtyName}
          />
        )}
      </div>
    </div>
  );
}

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

interface ResultsProps {
  facilities: CareFacility[];
  filtered: CareFacility[];
  exactMatches: CareFacility[];
  relatedMatches: CareFacility[];
  otherMatches: CareFacility[];
  countByKind: Record<string, number>;
  kindFilter: SearchKind;
  onKindFilterChange: (value: SearchKind) => void;
  openNowOnly: boolean;
  onOpenNowChange: (value: boolean) => void;
  location: ConfirmedLocation | null;
  specialtyApplied: boolean;
  specialtyName: string | null;
}

function FacilityResults({
  facilities,
  filtered,
  exactMatches,
  relatedMatches,
  otherMatches,
  countByKind,
  kindFilter,
  onKindFilterChange,
  openNowOnly,
  onOpenNowChange,
  location,
  specialtyApplied,
  specialtyName,
}: ResultsProps) {
  const sources = [...new Set(facilities.map((f) => f.source))].join(", ");

  if (!facilities.length) {
    return (
      <section className="space-y-5" aria-live="polite">
        <ResultsHeader
          location={location}
          total={0}
          specialtyApplied={specialtyApplied}
          specialtyName={specialtyName}
          sources={sources}
        />
        <ZeroResults specialtyApplied={specialtyApplied} specialtyName={specialtyName} />
      </section>
    );
  }

  return (
    <section className="space-y-5" aria-live="polite">
      <ResultsHeader
        location={location}
        total={facilities.length}
        specialtyApplied={specialtyApplied}
        specialtyName={specialtyName}
        sources={sources}
      />

      {/* Filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-2 overflow-x-auto pb-1 scroll-thin" aria-label="Filter by type">
          {KIND_FILTERS.map((item) => {
            const count =
              item.value === "any" ? facilities.length : countByKind[item.value] ?? 0;
            const active = kindFilter === item.value;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => onKindFilterChange(item.value)}
                className={classNames(
                  "min-h-[40px] shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition",
                  active
                    ? "bg-slate-900 text-white"
                    : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                )}
              >
                {item.label}{" "}
                <span className={active ? "text-slate-300" : "text-slate-400"}>{count}</span>
              </button>
            );
          })}
        </div>
        <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm font-medium text-slate-600">
          <input
            type="checkbox"
            checked={openNowOnly}
            onChange={(e) => onOpenNowChange(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
          Open now only
        </label>
      </div>

      {!filtered.length ? (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-8 text-center text-sm text-slate-500">
          No listings match this filter. Choose another category or clear “Open now only”.
        </div>
      ) : specialtyApplied ? (
        <div className="space-y-8">
          <ResultGroup
            title={`Recommended matches${specialtyName ? ` for ${specialtyName}` : ""}`}
            tone="brand"
            facilities={exactMatches}
            emptyText={`No nearby listing explicitly mentions ${specialtyName || "this specialty"}.`}
          />
          <ResultGroup
            title="Nearby alternatives"
            subtitle="Doctors, hospitals and clinics — verify the specialty by calling ahead."
            tone="slate"
            facilities={relatedMatches}
          />
          {otherMatches.length > 0 && (
            <ResultGroup
              title="Other nearby healthcare"
              subtitle="These list a different specialty and are shown for context only."
              tone="slate"
              facilities={otherMatches}
              dimmed
            />
          )}
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {filtered.map((facility) => (
            <FacilityCard key={facility.id} facility={facility} />
          ))}
        </div>
      )}

      <Disclaimer />
    </section>
  );
}

function ResultsHeader({
  location,
  total,
  specialtyApplied,
  specialtyName,
  sources,
}: {
  location: ConfirmedLocation | null;
  total: number;
  specialtyApplied: boolean;
  specialtyName: string | null;
  sources: string;
}) {
  return (
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
      <div>
        <p className="text-sm font-medium text-brand-700">
          <LocationIcon className="mr-1 inline h-4 w-4" /> Near {location?.name || "selected location"}
        </p>
        <h2 className="section-title mt-1">
          {total
            ? `${total} nearby healthcare listing${total === 1 ? "" : "s"} found`
            : "No healthcare listings found nearby"}
        </h2>
        {specialtyApplied && total > 0 && (
          <p className="mt-1 text-sm text-slate-500">
            Showing matches for <span className="font-semibold text-slate-700">{specialtyName}</span>{" "}
            first, then nearby alternatives.
          </p>
        )}
      </div>
      {total > 0 && (
        <p className="text-xs leading-relaxed text-slate-400">
          Sorted by specialty match, then distance · Source: {sources || "public directory listings"}
        </p>
      )}
    </div>
  );
}

function ResultGroup({
  title,
  subtitle,
  facilities,
  tone,
  emptyText,
  dimmed,
}: {
  title: string;
  subtitle?: string;
  facilities: CareFacility[];
  tone: "brand" | "slate";
  emptyText?: string;
  dimmed?: boolean;
}) {
  return (
    <div>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3
          className={classNames(
            "text-base font-bold",
            tone === "brand" ? "text-brand-800" : "text-slate-800"
          )}
        >
          {title}
        </h3>
        <span className="text-xs font-semibold text-slate-400">{facilities.length}</span>
      </div>
      {subtitle && <p className="mb-3 text-xs text-slate-500">{subtitle}</p>}
      {facilities.length ? (
        <div
          className={classNames(
            "grid gap-4 md:grid-cols-2",
            dimmed && "opacity-90"
          )}
        >
          {facilities.map((facility) => (
            <FacilityCard key={facility.id} facility={facility} />
          ))}
        </div>
      ) : (
        emptyText && (
          <p className="rounded-2xl border border-dashed border-slate-200 bg-white px-5 py-6 text-sm text-slate-500">
            {emptyText}
          </p>
        )
      )}
    </div>
  );
}

function ZeroResults({
  specialtyApplied,
  specialtyName,
}: {
  specialtyApplied: boolean;
  specialtyName: string | null;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-6 py-10 text-center shadow-sm">
      <CareIcon className="mx-auto h-8 w-8 text-slate-300" />
      <p className="mt-3 font-semibold text-slate-800">
        {specialtyApplied ? `No ${specialtyName || "specialty"} listings found nearby` : "Try a different area"}
      </p>
      <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
        {specialtyApplied
          ? "We couldn't identify a nearby provider that explicitly lists this specialty. Try widening the search area or choosing “Any healthcare” to see nearby hospitals and clinics — call ahead to confirm the service is available."
          : "The selected directory doesn't list any supported healthcare facilities within 5 km of this pin."}
      </p>
    </div>
  );
}

function Disclaimer() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-xs leading-relaxed text-slate-500">
      <span className="font-semibold text-slate-600">Directory information only — not a medical recommendation.</span>{" "}
      MediMind does not verify provider specialty, availability, or clinical quality. A “match” means the
      specialty appears in the public listing; always confirm details directly with the provider.
    </div>
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
            {facility.matchLevel && (
              <MatchBadge level={facility.matchLevel} />
            )}
          </div>
          <h3 className="mt-2 text-base font-bold text-slate-900">{facility.name}</h3>
          {facility.matchReason && (
            <p className="mt-0.5 text-xs font-medium text-slate-500">{facility.matchReason}</p>
          )}
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
          <LocationIcon className="h-4 w-4" /> Directions
        </a>
        {facility.phone && (
          <a href={`tel:${facility.phone}`} className="btn-ghost min-h-[40px] px-4 py-2 text-sm">
            Call
          </a>
        )}
        {facility.website && (
          <a href={facility.website} target="_blank" rel="noreferrer" className="btn-ghost min-h-[40px] px-4 py-2 text-sm">
            Website
          </a>
        )}
      </div>
    </article>
  );
}

function MatchBadge({ level }: { level: MatchLevel }) {
  if (level === "exact") {
    return (
      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-700 ring-1 ring-emerald-200">
        Specialty match
      </span>
    );
  }
  if (level === "related") {
    return (
      <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-sky-700">
        Nearby option
      </span>
    );
  }
  return (
    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
      Different specialty
    </span>
  );
}

function kindLabel(kind: FacilityKind): string {
  const labels: Record<FacilityKind, string> = {
    hospital: "Hospital",
    clinic: "Clinic",
    doctor: "Doctor",
    pharmacy: "Pharmacy",
    laboratory: "Laboratory",
    other: "Other healthcare",
  };
  return labels[kind];
}

function kindTone(kind: FacilityKind): string {
  if (kind === "hospital") return "bg-red-50 text-red-700";
  if (kind === "pharmacy") return "bg-emerald-50 text-emerald-700";
  if (kind === "laboratory") return "bg-amber-50 text-amber-700";
  if (kind === "doctor") return "bg-violet-50 text-violet-700";
  if (kind === "other") return "bg-slate-100 text-slate-500";
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
