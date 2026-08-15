import { useId, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import type { CareRecommendation, SpecialtyOption } from "../types/recommendations";
import { classNames } from "../utils/format";
import { CheckIcon, CloseIcon, SearchIcon } from "./icons";

/** Patient-facing specialty taxonomy (browseable section). */
const BROWSE_SPECIALTIES: Array<{ key: string; name: string }> = [
  { key: "cardiologist", name: "Cardiologist" },
  { key: "dermatologist", name: "Dermatologist" },
  { key: "gastroenterologist", name: "Gastroenterologist" },
  { key: "hematologist", name: "Hematologist" },
  { key: "neurologist", name: "Neurologist" },
  { key: "oncologist", name: "Oncologist" },
  { key: "ophthalmologist", name: "Ophthalmologist" },
  { key: "orthopedic", name: "Orthopedic Specialist" },
  { key: "psychiatrist", name: "Psychiatrist" },
  { key: "pulmonologist", name: "Pulmonologist" },
  { key: "rheumatologist", name: "Rheumatologist" },
  { key: "clinical_pharmacist", name: "Clinical Pharmacist" },
];

/** Facility types for the top-level dropdown. */
export const FACILITY_TYPES: Array<{ value: string; label: string }> = [
  { value: "all", label: "All care" },
  { value: "doctor", label: "Doctors" },
  { value: "hospital", label: "Hospitals" },
  { value: "clinic", label: "Clinics" },
  { value: "pharmacy", label: "Pharmacies" },
  { value: "laboratory", label: "Laboratories" },
];

interface SpecialtySelectorProps {
  /** Current selected specialty key. */
  value: string;
  /** Called when the user picks a specialty. */
  onChange: (key: string) => void;
  /** Recommendations from the backend, used to populate the "Suggested" section. */
  recommendations?: CareRecommendation[];
}

/**
 * A searchable, grouped specialty combobox that shows:
 *   1. Suggested from patient records (AI recommendations)
 *   2. Browse all specialties (full taxonomy)
 *
 * Mimics a command-palette interaction — search first, grouped results.
 */
export function SpecialtySelector({ value, onChange, recommendations }: SpecialtySelectorProps) {
  const listboxId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);

  // Build recommended options from backend data
  const recommendedOptions: SpecialtyOption[] = useMemo(() => {
    if (!recommendations?.length) return [];
    return recommendations.map((rec) => ({
      key: rec.specialty_key,
      name: rec.specialty,
      group: "recommended" as const,
      recommendationNote: rec.title,
      relevance: rec.relevance,
    }));
  }, [recommendations]);

  // Build browse options from the full taxonomy (exclude ones already in recommended)
  const browseOptions: SpecialtyOption[] = useMemo(() => {
    const recKeys = new Set(recommendedOptions.map((o) => o.key));
    return BROWSE_SPECIALTIES.filter((s) => !recKeys.has(s.key)).map((s) => ({
      key: s.key,
      name: s.name,
      group: "browse" as const,
    }));
  }, [recommendedOptions]);

  // Flat filtered list for keyboard navigation
  const filteredOptions = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    const allOptions = [...recommendedOptions, ...browseOptions];
    if (!trimmed) return allOptions;
    return allOptions.filter(
      (o) =>
        o.name.toLowerCase().includes(trimmed) ||
        o.recommendationNote?.toLowerCase().includes(trimmed)
    );
  }, [query, recommendedOptions, browseOptions]);

  // The currently selected name
  const selectedName = useMemo(() => {
    const all = [...recommendedOptions, ...browseOptions];
    return all.find((o) => o.key === value)?.name || value;
  }, [value, recommendedOptions, browseOptions, value]);

  // Is the selected value from a recommendation?
  const isRecommended = recommendedOptions.some((o) => o.key === value);

  const showSuggestions = open && filteredOptions.length > 0;

  function handleInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!showSuggestions) {
      if (event.key === "Escape") setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => (i + 1) % filteredOptions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => (i <= 0 ? filteredOptions.length - 1 : i - 1));
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      const opt = filteredOptions[activeIndex];
      if (opt) {
        onChange(opt.key);
        setOpen(false);
        setQuery("");
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  }

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setOpen(false);
      setQuery("");
    }
  }

  function selectOption(opt: SpecialtyOption) {
    onChange(opt.key);
    setOpen(false);
    setQuery("");
  }

  // Split filteredOptions into groups
  const groupedOptions = useMemo(() => {
    const recommended = filteredOptions.filter((o) => o.group === "recommended");
    const browse = filteredOptions.filter((o) => o.group === "browse");
    return { recommended, browse };
  }, [filteredOptions]);

  return (
    <div className="relative" onBlur={handleBlur}>
      <label htmlFor={`${listboxId}-specialty`} className="mb-2 block text-sm font-semibold text-slate-800">
        What type of care do you need?
      </label>

      {/* Closed state: show selected value as a button */}
      {!open && (
        <button
          type="button"
          id={`${listboxId}-specialty`}
          onClick={() => { setOpen(true); setActiveIndex(-1); }}
          className={classNames(
            "flex min-h-[52px] w-full items-center gap-3 rounded-2xl border bg-white px-4 py-3 text-left text-base transition",
            "border-slate-300 hover:border-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
          )}
        >
          <SearchIcon className="h-5 w-5 shrink-0 text-slate-400" />
          <span className="flex-1 truncate text-slate-800">{selectedName}</span>
          {isRecommended && (
            <span className="shrink-0 rounded-full bg-brand-50 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-700 ring-1 ring-brand-200">
              ✨ Suggested
            </span>
          )}
          <span className="text-sm text-slate-400">▾</span>
        </button>
      )}

      {/* Open state: search input + dropdown */}
      {open && (
        <div className="rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-300/50">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
            <input
              ref={inputRef}
              id={`${listboxId}-specialty`}
              value={query}
              onChange={(event) => { setQuery(event.target.value); setActiveIndex(-1); }}
              onKeyDown={handleInputKeyDown}
              placeholder="Search specialty or type of care..."
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={showSuggestions}
              aria-controls={`${listboxId}-listbox`}
              aria-activedescendant={activeIndex >= 0 ? `${listboxId}-opt-${activeIndex}` : undefined}
              autoComplete="off"
              spellCheck={false}
              autoFocus
              className="min-h-[52px] w-full rounded-t-2xl border-0 border-b border-slate-100 bg-white py-3 pl-12 pr-12 text-base text-slate-900 outline-none placeholder:text-slate-400"
            />
            <button
              type="button"
              onClick={() => { setOpen(false); setQuery(""); }}
              className="absolute right-2 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              aria-label="Close specialty selector"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          </div>

          {/* Results list */}
          <ul id={`${listboxId}-listbox`} role="listbox" aria-label="Specialty suggestions" className="max-h-[360px] overflow-y-auto py-1.5 scroll-thin">
            {groupedOptions.recommended.length > 0 && (
              <>
                <li className="px-4 py-2 text-[11px] font-bold uppercase tracking-[0.14em] text-brand-600" role="presentation">
                  Suggested from your records
                </li>
                {groupedOptions.recommended.map((opt, idx) => {
                  const globalIdx = idx;
                  return (
                    <li
                      key={opt.key}
                      id={`${listboxId}-opt-${globalIdx}`}
                      role="option"
                      aria-selected={activeIndex === globalIdx || value === opt.key}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveIndex(globalIdx)}
                      onClick={() => selectOption(opt)}
                      className={classNames(
                        "flex cursor-pointer items-start gap-3 border-b border-slate-100 px-4 py-3 last:border-0",
                        activeIndex === globalIdx ? "bg-brand-50" : "bg-white hover:bg-slate-50",
                        value === opt.key && "bg-brand-50/60"
                      )}
                    >
                      <span className={classNames(
                        "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-lg",
                        activeIndex === globalIdx ? "bg-brand-600 text-white" : "bg-brand-50 text-brand-600"
                      )}>
                        🩺
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-900">{opt.name}</span>
                          {value === opt.key && <CheckIcon className="h-4 w-4 text-brand-600" />}
                        </span>
                        {opt.recommendationNote && (
                          <span className="mt-0.5 block text-xs text-slate-500">
                            {opt.recommendationNote}
                            {opt.relevance && (
                              <span className={classNames(
                                "ml-1.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide",
                                relevanceTone(opt.relevance)
                              )}>
                                {opt.relevance}
                              </span>
                            )}
                          </span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </>
            )}

            {groupedOptions.browse.length > 0 && (
              <>
                <li className="px-4 py-2 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500" role="presentation">
                  Browse all specialties
                </li>
                {groupedOptions.browse.map((opt, idx) => {
                  const globalIdx = groupedOptions.recommended.length + idx;
                  return (
                    <li
                      key={opt.key}
                      id={`${listboxId}-opt-${globalIdx}`}
                      role="option"
                      aria-selected={activeIndex === globalIdx || value === opt.key}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveIndex(globalIdx)}
                      onClick={() => selectOption(opt)}
                      className={classNames(
                        "flex cursor-pointer items-start gap-3 border-b border-slate-100 px-4 py-3 last:border-0",
                        activeIndex === globalIdx ? "bg-slate-50" : "bg-white hover:bg-slate-50",
                        value === opt.key && "bg-slate-50"
                      )}
                    >
                      <span className={classNames(
                        "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
                        activeIndex === globalIdx ? "bg-slate-200 text-slate-600" : "bg-slate-100 text-slate-400"
                      )}>
                        📋
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-800">{opt.name}</span>
                          {value === opt.key && <CheckIcon className="h-4 w-4 text-brand-600" />}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

function relevanceTone(relevance: string): string {
  switch (relevance) {
    case "high":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "moderate":
      return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
    case "possible":
      return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
    default:
      return "bg-slate-100 text-slate-600 ring-1 ring-slate-200";
  }
}
