import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { locationSecondaryText, searchLocations } from "../../services/geocoding";
import { useI18n } from "../../i18n/I18nContext";
import type { LocationPlace } from "../../types/location";
import { classNames } from "../../utils/format";
import { LocationIcon } from "../icons";
import { Spinner } from "../Spinner";

const MIN_QUERY_LENGTH = 2;
const SEARCH_DEBOUNCE_MS = 350;

type SearchStatus = "idle" | "loading" | "success" | "error";

export interface LocationAutocompleteInputProps {
  /** Current text in the field (kept by the parent so free text still works). */
  value: string;
  /** The place the user picked from the suggestions, if any. */
  selected: LocationPlace | null;
  /** Typing always goes through here; it should clear `selected`. */
  onTextChange: (text: string) => void;
  /** A suggestion was chosen: real name + coordinates from the geocoder. */
  onSelect: (place: LocationPlace) => void;
  label: string;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
}

/**
 * A compact, form-friendly version of the LocationPicker search box: the same
 * live map geocoding (Photon/OSM + Open-Meteo cities), but rendered as a
 * single input + suggestion list so it can sit inside an existing form.
 * Free-typed text remains valid — the geocoder pick just adds coordinates.
 */
export function LocationAutocompleteInput({
  value,
  selected,
  onTextChange,
  onSelect,
  label,
  placeholder,
  disabled,
  required,
}: LocationAutocompleteInputProps) {
  const { t } = useI18n();
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [results, setResults] = useState<LocationPlace[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const [isFocused, setIsFocused] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    // A confirmed selection needs no further lookups until the text changes.
    if (selected) {
      setResults([]);
      setStatus("idle");
      setActiveIndex(-1);
      return;
    }
    const trimmed = value.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setResults([]);
      setStatus("idle");
      setActiveIndex(-1);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const places = await searchLocations(trimmed, { signal: controller.signal, limit: 6 });
        setResults(places);
        setStatus("success");
        setActiveIndex(places.length ? 0 : -1);
      } catch {
        if (controller.signal.aborted) return;
        // Autocomplete is an assist, not a gate: on failure the field keeps
        // working as plain text and the backend geocodes it server-side.
        setResults([]);
        setStatus("error");
        setActiveIndex(-1);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [selected, value]);

  const showSuggestions =
    isFocused &&
    !selected &&
    value.trim().length >= MIN_QUERY_LENGTH &&
    (status === "loading" || status === "success");

  function choose(place: LocationPlace) {
    onSelect(place);
    setResults([]);
    setStatus("idle");
    setActiveIndex(-1);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!showSuggestions || !results.length) {
      if (event.key === "Escape") setIsFocused(false);
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
      if (place) choose(place);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setIsFocused(false);
    }
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setIsFocused(false);
    }
  }

  return (
    <div className="relative" onBlur={handleBlur}>
      <label htmlFor={`${listboxId}-input`} className="block">
        <span className="text-sm font-medium text-slate-700">{label}</span>
        <input
          ref={inputRef}
          id={`${listboxId}-input`}
          value={value}
          onChange={(event) => {
            onTextChange(event.target.value);
            setIsFocused(true);
          }}
          onFocus={() => setIsFocused(true)}
          onKeyDown={handleKeyDown}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={showSuggestions}
          aria-controls={listboxId}
          aria-activedescendant={activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          required={required}
          minLength={MIN_QUERY_LENGTH}
          disabled={disabled}
          className="mt-1.5 block w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </label>
      {selected && (
        <p className="mt-1 flex items-center gap-1 text-xs text-slate-500">
          <LocationIcon className="h-3.5 w-3.5 shrink-0 text-brand-600" aria-hidden="true" />
          <span className="truncate">{selected.displayName}</span>
        </p>
      )}

      {showSuggestions && (
        <div className="absolute z-50 mt-1.5 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl shadow-slate-300/40">
          {status === "loading" ? (
            <div className="flex items-center gap-2 px-3 py-3 text-sm text-slate-600" role="status">
              <Spinner className="h-4 w-4 text-brand-600" /> {t("location.searching")}
            </div>
          ) : results.length ? (
            <ul id={listboxId} role="listbox" aria-label={label} className="py-1">
              {results.map((place, index) => (
                <li
                  key={place.id}
                  id={`${listboxId}-option-${index}`}
                  role="option"
                  aria-selected={activeIndex === index}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => choose(place)}
                  className={classNames(
                    "flex cursor-pointer items-start gap-2 px-3 py-2.5",
                    activeIndex === index ? "bg-brand-50" : "bg-white hover:bg-slate-50",
                  )}
                >
                  <LocationIcon
                    className={classNames(
                      "mt-0.5 h-4 w-4 shrink-0",
                      activeIndex === index ? "text-brand-600" : "text-slate-400",
                    )}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-slate-900">
                      {place.name}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {locationSecondaryText(place)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="px-3 py-3">
              <p className="text-sm font-semibold text-slate-900">{t("location.noPlaces")}</p>
              <p className="mt-0.5 text-xs text-slate-600">{t("location.noPlacesBody")}</p>
            </div>
          )}
          <div className="border-t border-slate-100 bg-slate-50 px-3 py-1.5 text-right text-[10px] text-slate-400">
            Search data ©{" "}
            <a
              className="underline hover:text-slate-600"
              href="https://www.openstreetmap.org/copyright"
              target="_blank"
              rel="noreferrer"
            >
              OpenStreetMap
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
