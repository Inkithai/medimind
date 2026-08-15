import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { LocationPicker } from "../components/location";
import { LocationIcon, RefreshIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type {
  CareAvailability,
  CareFacility,
  CareRecommendation,
  FacilityKind,
} from "../types/facility";
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
  const requestRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => {
    localStorage.setItem(PREFERENCES_KEY, JSON.stringify({ specialty, availability, radiusKm }));
  }, [availability, radiusKm, specialty]);

  useStrictEffect(() => {
    api.getCareRecommendation(credentials)
      .then((value) => {
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
  }, [credentials]);

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

  return (
    <div className="space-y-7">
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
            <CareIcon className="h-3.5 w-3.5" /> Find care
          </div>
          <h1 className="page-title">{t("care.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl leading-relaxed">{t("care.subtitle")}</p>
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

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
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

          <label className="text-sm font-semibold text-slate-800">
            {t("care.specialty")}
            <input
              value={specialty}
              onChange={(event) => setSpecialty(event.target.value.slice(0, 80))}
              onBlur={() => {
                if (savedLocation) void loadFacilities(savedLocation, searchKind, specialty, availability);
              }}
              list="care-specialties"
              placeholder={t("care.specialtyPlaceholder")}
              className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 outline-none focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
            />
            <datalist id="care-specialties">
              <option value="cardiology" />
              <option value="clinical pharmacist" />
              <option value="dermatology" />
              <option value="gastroenterology" />
              <option value="hematology" />
              <option value="general physician" />
            </datalist>
          </label>

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
        <a href={mapUrl} target="_blank" rel="noreferrer" className="btn-secondary min-h-[40px] px-4 py-2 text-sm">
          <LocationIcon className="h-4 w-4" /> {t("care.viewMap")}<span className="sr-only"> ({t("common.opensNewWindow")})</span>
        </a>
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
