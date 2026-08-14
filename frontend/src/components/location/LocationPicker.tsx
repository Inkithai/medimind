import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from "react";
import { locationSecondaryText, reverseGeocode, searchLocations } from "../../services/geocoding";
import { useI18n } from "../../i18n/I18nContext";
import type { ConfirmedLocation, Coordinates, LocationPlace } from "../../types/location";
import { classNames } from "../../utils/format";
import { CheckIcon, CloseIcon, LocationIcon, NavigationIcon, SearchIcon } from "../icons";
import { Spinner } from "../Spinner";
import { LocationMap } from "./LocationMap";

export interface LocationPickerProps {
  onConfirm: (location: ConfirmedLocation) => void | Promise<void>;
  initialValue?: ConfirmedLocation | null;
  title?: string;
  description?: string;
  confirmLabel?: string;
  confirmingLabel?: string;
  /** Limit autocomplete to ISO 3166-1 alpha-2 country codes. It searches worldwide by default. */
  countryCodes?: string[];
  /** Optional center used to rank nearby landmarks above similarly named distant places. */
  proximity?: Coordinates;
  showAddressDetails?: boolean;
  className?: string;
}

type SearchStatus = "idle" | "loading" | "success" | "error";
type PickerStep = "search" | "confirm";

const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 350;

function coordinatesLabel({ latitude, longitude }: Coordinates): string {
  return `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
}

function pinnedFallback(coordinates: Coordinates): LocationPlace {
  return {
    id: `pin-${coordinates.latitude.toFixed(6)}-${coordinates.longitude.toFixed(6)}`,
    name: "Dropped pin",
    displayName: `Pinned at ${coordinatesLabel(coordinates)}`,
    latitude: coordinates.latitude,
    longitude: coordinates.longitude,
    type: "pin",
  };
}

function resultTypeLabel(type?: string): string {
  if (!type) return "Place";
  const labels: Record<string, string> = {
    city: "City",
    town: "Town",
    village: "Village",
    suburb: "Area",
    neighbourhood: "Area",
    beach: "Landmark",
    bus_station: "Transit",
    railway_station: "Transit",
    hospital: "Hospital",
    house: "Address",
    building: "Address",
    road: "Street",
  };
  return labels[type] || type.replace(/_/g, " ").replace(/^./, (letter: string) => letter.toUpperCase());
}

export function LocationPicker({
  onConfirm,
  initialValue,
  title,
  description,
  confirmLabel,
  confirmingLabel,
  countryCodes,
  proximity,
  showAddressDetails = true,
  className,
}: LocationPickerProps) {
  const { t } = useI18n();
  const resolvedTitle = title || t("care.where");
  const resolvedDescription = description || t("care.locationDescription");
  const resolvedConfirmLabel = confirmLabel || t("care.find");
  const resolvedConfirmingLabel = confirmingLabel || t("care.finding");
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const reverseRequestRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const [step, setStep] = useState<PickerStep>(initialValue ? "confirm" : "search");
  const [query, setQuery] = useState(initialValue?.name || "");
  const [results, setResults] = useState<LocationPlace[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [searchError, setSearchError] = useState<string | null>(null);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [selectedPlace, setSelectedPlace] = useState<LocationPlace | null>(initialValue || null);
  const [addressDetails, setAddressDetails] = useState(initialValue?.addressDetails || "");
  const [isLocating, setIsLocating] = useState(false);
  const [isResolvingPin, setIsResolvingPin] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      reverseRequestRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (step !== "search") return;
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < MIN_QUERY_LENGTH) {
      setResults([]);
      setStatus("idle");
      setSearchError(null);
      setActiveIndex(-1);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setStatus("loading");
      setSearchError(null);
      try {
        const places = await searchLocations(trimmedQuery, {
          signal: controller.signal,
          countryCodes,
          proximity,
        });
        setResults(places);
        setStatus("success");
        setActiveIndex(places.length ? 0 : -1);
      } catch (error) {
        if (controller.signal.aborted) return;
        setResults([]);
        setStatus("error");
        setSearchError(error instanceof Error ? error.message : "Location search failed. Please try again.");
        setActiveIndex(-1);
      }
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [countryCodes, proximity, query, step]);

  const showSuggestions =
    step === "search" &&
    isInputFocused &&
    query.trim().length >= MIN_QUERY_LENGTH &&
    (status === "loading" || status === "error" || status === "success");

  function selectPlace(place: LocationPlace) {
    setSelectedPlace(place);
    setQuery(place.name);
    setResults([]);
    setLocationError(null);
    setConfirmError(null);
    setStep("confirm");
  }

  function returnToSearch() {
    reverseRequestRef.current?.abort();
    setStep("search");
    setSelectedPlace(null);
    setStatus("idle");
    setResults([]);
    setConfirmError(null);
    setIsResolvingPin(false);
    window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
  }

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!showSuggestions || !results.length) {
      if (event.key === "Escape") setIsInputFocused(false);
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % results.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      const place = results[activeIndex];
      if (place) selectPlace(place);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setIsInputFocused(false);
    }
  }

  function handleSearchBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsInputFocused(false);
    }
  }

  async function resolveAndSelect(coordinates: Coordinates, fallbackName: string) {
    reverseRequestRef.current?.abort();
    const controller = new AbortController();
    reverseRequestRef.current = controller;
    try {
      const place = await reverseGeocode(coordinates, controller.signal);
      if (!controller.signal.aborted && mountedRef.current) selectPlace(place);
    } catch (error) {
      if (controller.signal.aborted || !mountedRef.current) return;
      const fallback = pinnedFallback(coordinates);
      fallback.name = fallbackName;
      fallback.displayName = `${fallbackName} · ${coordinatesLabel(coordinates)}`;
      selectPlace(fallback);
    }
  }

  function useCurrentLocation() {
    setLocationError(null);
    if (!("geolocation" in navigator)) {
      setLocationError(t("location.unsupported"));
      return;
    }

    setIsLocating(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (!mountedRef.current) return;
        const coordinates = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        void resolveAndSelect(coordinates, "Current location").finally(() => {
          if (mountedRef.current) setIsLocating(false);
        });
      },
      (error) => {
        if (!mountedRef.current) return;
        setIsLocating(false);
        if (error.code === error.PERMISSION_DENIED) {
          setLocationError(t("location.denied"));
        } else if (error.code === error.TIMEOUT) {
          setLocationError(t("location.timedOut"));
        } else {
          setLocationError(t("location.failed"));
        }
      },
      { enableHighAccuracy: true, timeout: 12_000, maximumAge: 60_000 }
    );
  }

  function handlePinChange(coordinates: Coordinates) {
    reverseRequestRef.current?.abort();
    const controller = new AbortController();
    reverseRequestRef.current = controller;
    setSelectedPlace(pinnedFallback(coordinates));
    setIsResolvingPin(true);
    setConfirmError(null);

    void reverseGeocode(coordinates, controller.signal)
      .then((place) => {
        if (!controller.signal.aborted && mountedRef.current) setSelectedPlace(place);
      })
      .catch(() => {
        // Coordinates remain valid even if the address lookup is unavailable.
      })
      .finally(() => {
        if (!controller.signal.aborted && mountedRef.current) setIsResolvingPin(false);
      });
  }

  async function handleConfirm() {
    if (!selectedPlace || isConfirming) return;
    setIsConfirming(true);
    setConfirmError(null);
    const confirmed: ConfirmedLocation = {
      ...selectedPlace,
      addressDetails: addressDetails.trim() || undefined,
      confirmedAt: new Date().toISOString(),
    };
    try {
      await onConfirm(confirmed);
    } catch (error) {
      setConfirmError(error instanceof Error ? error.message : "We couldn't save this location. Please try again.");
    } finally {
      if (mountedRef.current) setIsConfirming(false);
    }
  }

  return (
    <section
      className={classNames(
        "rounded-3xl border border-slate-200 bg-white shadow-xl shadow-slate-200/50",
        className
      )}
      aria-labelledby={`${listboxId}-title`}
    >
      <div className="border-b border-slate-100 px-5 py-5 sm:px-7 sm:py-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-bold uppercase tracking-[0.14em] text-brand-600">
              {step === "search" ? t("location.stepSearch") : t("location.stepConfirm")}
            </p>
            <h2 id={`${listboxId}-title`} className="text-2xl font-bold tracking-tight text-slate-900">
              {step === "search" ? resolvedTitle : t("location.confirmTitle")}
            </h2>
            <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-slate-500">
              {step === "search"
                ? resolvedDescription
                : t("location.confirmDescription")}
            </p>
          </div>
          <div className="hidden items-center gap-2 sm:flex" aria-hidden="true">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
              {step === "search" ? "1" : <CheckIcon className="h-4 w-4" />}
            </span>
            <span className={classNames("h-0.5 w-8", step === "confirm" ? "bg-brand-600" : "bg-slate-200")} />
            <span
              className={classNames(
                "flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold",
                step === "confirm" ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-400"
              )}
            >
              2
            </span>
          </div>
        </div>
      </div>

      {step === "search" ? (
        <div className="px-5 py-6 sm:px-7 sm:py-7">
          <div className="relative" onBlur={handleSearchBlur}>
            <label htmlFor={`${listboxId}-input`} className="mb-2 block text-sm font-semibold text-slate-800">
              {t("location.searchLabel")}
            </label>
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
              <input
                ref={inputRef}
                id={`${listboxId}-input`}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setResults([]);
                  setStatus("idle");
                  setActiveIndex(-1);
                  setIsInputFocused(true);
                }}
                onFocus={() => setIsInputFocused(true)}
                onKeyDown={handleInputKeyDown}
                role="combobox"
                aria-autocomplete="list"
                aria-expanded={showSuggestions}
                aria-controls={listboxId}
                aria-activedescendant={activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined}
                autoComplete="off"
                spellCheck={false}
                placeholder={t("location.searchPlaceholder")}
                className="min-h-[54px] w-full rounded-2xl border border-slate-300 bg-white py-3 pl-12 pr-12 text-base text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 hover:border-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    setResults([]);
                    inputRef.current?.focus();
                  }}
                  className="absolute right-2 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                  aria-label={t("location.clearSearch")}
                >
                  <CloseIcon className="h-5 w-5" />
                </button>
              )}
            </div>

            {showSuggestions && (
              <div className="absolute z-[1000] mt-2 w-full overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-300/50">
                {status === "loading" ? (
                  <div className="flex items-center gap-3 px-4 py-5 text-sm text-slate-600" role="status">
                    <Spinner className="h-5 w-5 text-brand-600" /> {t("location.searching")}
                  </div>
                ) : status === "error" ? (
                  <div className="px-4 py-5" role="alert">
                    <p className="text-sm font-semibold text-slate-900">{t("location.unavailable")}</p>
                    <p className="mt-1 text-sm text-slate-500">{searchError}</p>
                  </div>
                ) : results.length ? (
                  <ul id={listboxId} role="listbox" aria-label={t("location.searchLabel")} className="py-1.5">
                    {results.map((place, index) => (
                      <li
                        key={place.id}
                        id={`${listboxId}-option-${index}`}
                        role="option"
                        aria-selected={activeIndex === index}
                        onMouseDown={(event) => event.preventDefault()}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => selectPlace(place)}
                        className={classNames(
                          "flex cursor-pointer items-start gap-3 border-b border-slate-100 px-4 py-3.5 last:border-0",
                          activeIndex === index ? "bg-brand-50" : "bg-white hover:bg-slate-50"
                        )}
                      >
                        <span
                          className={classNames(
                            "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
                            activeIndex === index
                              ? "bg-brand-600 text-white"
                              : "bg-slate-100 text-slate-500"
                          )}
                        >
                          <LocationIcon className="h-5 w-5" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-slate-900">{place.name}</span>
                            <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                              {resultTypeLabel(place.type)}
                            </span>
                          </span>
                          <span className="mt-0.5 block truncate text-sm text-slate-500">
                            {locationSecondaryText(place)}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="px-4 py-5">
                    <p className="text-sm font-semibold text-slate-900">{t("location.noPlaces")}</p>
                    <p className="mt-1 text-sm text-slate-600">{t("location.noPlacesBody")}</p>
                  </div>
                )}
                <div className="border-t border-slate-100 bg-slate-50 px-4 py-2 text-right text-[11px] text-slate-400">
                  Search data ©{" "}
                  <a className="underline hover:text-slate-600" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
                    OpenStreetMap
                  </a>{" "}
                  ·{" "}
                  <a className="underline hover:text-slate-600" href="https://www.geonames.org/" target="_blank" rel="noreferrer">
                    GeoNames
                  </a>
                </div>
              </div>
            )}
          </div>

          <div className="my-5 flex items-center gap-3" aria-hidden="true">
            <span className="h-px flex-1 bg-slate-200" />
            <span className="text-xs font-medium uppercase tracking-wider text-slate-600">{t("upload.or")}</span>
            <span className="h-px flex-1 bg-slate-200" />
          </div>

          <button
            type="button"
            onClick={useCurrentLocation}
            disabled={isLocating}
            className="flex min-h-[52px] w-full items-center justify-center gap-3 rounded-2xl border border-brand-200 bg-brand-50 px-5 py-3 text-base font-semibold text-brand-700 transition hover:border-brand-300 hover:bg-brand-100 disabled:cursor-wait disabled:opacity-70 sm:w-auto"
          >
            {isLocating ? <Spinner className="h-5 w-5" /> : <NavigationIcon className="h-5 w-5" />}
            {isLocating ? t("location.locating") : t("location.useCurrent")}
          </button>

          {locationError && (
            <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="alert">
              {locationError}
            </div>
          )}
          <p className="mt-4 flex items-center gap-2 text-xs text-slate-400">
            <span aria-hidden="true">🔒</span>
            {t("location.privacy")}
          </p>
        </div>
      ) : selectedPlace ? (
        <div>
          <LocationMap
            coordinates={selectedPlace}
            onCoordinatesChange={handlePinChange}
            className="h-[300px] w-full border-b border-slate-200 sm:h-[360px]"
          />

          <div className="px-5 py-6 sm:px-7">
            <div className="flex items-start gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-brand-50 text-brand-700 ring-1 ring-brand-100">
                {isResolvingPin ? <Spinner className="h-5 w-5" /> : <LocationIcon className="h-6 w-6" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-lg font-bold text-slate-900">
                      {isResolvingPin ? t("location.findingAddress") : selectedPlace.name}
                    </p>
                    <p className="mt-0.5 text-sm leading-relaxed text-slate-500">
                      {isResolvingPin ? t("location.pinSet") : locationSecondaryText(selectedPlace)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={returnToSearch}
                    className="rounded-lg px-2.5 py-1.5 text-sm font-semibold text-brand-700 hover:bg-brand-50"
                  >
                    {t("common.change")}
                  </button>
                </div>
                <p className="mt-2 font-mono text-xs text-slate-400" aria-label={t("location.coordinates")}>
                  {coordinatesLabel(selectedPlace)}
                </p>
              </div>
            </div>

            {showAddressDetails && (
              <div className="mt-5">
                <label htmlFor={`${listboxId}-details`} className="block text-sm font-semibold text-slate-800">
                  {t("location.details")} <span className="font-normal text-slate-600">({t("common.optional")})</span>
                </label>
                <p id={`${listboxId}-details-help`} className="mt-0.5 text-xs text-slate-600">{t("location.detailsHelp")}</p>
                <input
                  id={`${listboxId}-details`}
                  value={addressDetails}
                  onChange={(event) => setAddressDetails(event.target.value)}
                  aria-describedby={`${listboxId}-details-help`}
                  placeholder={t("location.detailsPlaceholder")}
                  className="mt-2 min-h-[48px] w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
                />
              </div>
            )}

            {confirmError && (
              <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
                {confirmError}
              </div>
            )}

            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button type="button" onClick={returnToSearch} className="btn-secondary sm:min-w-[120px]">
                {t("common.back")}
              </button>
              <button
                type="button"
                onClick={() => void handleConfirm()}
                disabled={isConfirming || isResolvingPin}
                className="btn-primary sm:min-w-[190px]"
              >
                {isConfirming ? <Spinner className="h-5 w-5" /> : <CheckIcon className="h-5 w-5" />}
                {isConfirming ? resolvedConfirmingLabel : resolvedConfirmLabel}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
