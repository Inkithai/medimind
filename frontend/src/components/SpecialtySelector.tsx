import { useId, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import type { CareSpecialtyOption } from "../types/api";
import { classNames } from "../utils/format";
import { CheckIcon, CloseIcon, SearchIcon } from "./icons";

interface SpecialtySelectorProps {
  /** Currently selected specialty id (e.g. "cardiology"). */
  value: string;
  /** Called when the user picks a specialty. */
  onChange: (id: string) => void;
  /**
   * Suggested specialties derived from the patient record by
   * `GET /api/v1/care/suggestion` (primary first, then alternatives).
   */
  suggestions?: CareSpecialtyOption[];
  /** Full taxonomy returned by the same endpoint (id + label). */
  allSpecialties: CareSpecialtyOption[];
  /** Accessible label (already translated by caller). */
  label: string;
  /** Placeholder shown while no specialty is selected. */
  placeholder?: string;
}

/**
 * A searchable, grouped specialty combobox:
 *   1. "Suggested from your records" — AI suggestions with reasons.
 *   2. "Browse all specialties" — the full taxonomy.
 *
 * Keyboard: ArrowUp/Down to move, Enter to select, Escape to close.
 */
export function SpecialtySelector({
  value,
  onChange,
  suggestions,
  allSpecialties,
  label,
  placeholder = "Search specialty or type of care…",
}: SpecialtySelectorProps) {
  const baseId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);

  // De-duplicate: a specialty that appears in suggestions should not also
  // appear in the browse list.
  const suggestedIds = useMemo(
    () => new Set((suggestions ?? []).map((s) => s.id)),
    [suggestions],
  );

  const suggestedOptions = useMemo(
    () => (suggestions ?? []).map((s) => ({ ...s, group: "suggested" as const })),
    [suggestions],
  );

  const browseOptions = useMemo(
    () =>
      allSpecialties
        .filter((s) => !suggestedIds.has(s.id))
        .map((s) => ({ ...s, group: "browse" as const })),
    [allSpecialties, suggestedIds],
  );

  const filteredOptions = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    const all = [...suggestedOptions, ...browseOptions];
    if (!trimmed) return all;
    return all.filter((o) => {
      const haystack = [o.label, o.id, ...(o.reasons ?? [])].join(" ").toLowerCase();
      return haystack.includes(trimmed);
    });
  }, [query, suggestedOptions, browseOptions]);

  const selectedOption = useMemo(
    () => [...suggestedOptions, ...browseOptions].find((o) => o.id === value),
    [value, suggestedOptions, browseOptions],
  );

  const isSuggested = suggestedIds.has(value);

  const showListbox = open && filteredOptions.length > 0;

  const grouped = useMemo(() => {
    const suggested = filteredOptions.filter((o) => o.group === "suggested");
    const browse = filteredOptions.filter((o) => o.group === "browse");
    return { suggested, browse };
  }, [filteredOptions]);

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!showListbox) {
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
        onChange(opt.id);
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

  function selectOption(id: string) {
    onChange(id);
    setOpen(false);
    setQuery("");
  }

  return (
    <div className="relative" onBlur={handleBlur}>
      <label
        htmlFor={`${baseId}-specialty`}
        className="mb-2 block text-sm font-semibold text-slate-800"
      >
        {label}
      </label>

      {!open && (
        <button
          type="button"
          id={`${baseId}-specialty`}
          onClick={() => {
            setOpen(true);
            setActiveIndex(-1);
          }}
          className={classNames(
            "flex min-h-[52px] w-full items-center gap-3 rounded-2xl border bg-white px-4 py-3 text-left text-base transition",
            "border-slate-300 hover:border-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100",
          )}
          aria-haspopup="listbox"
          aria-expanded={false}
        >
          <SearchIcon className="h-5 w-5 shrink-0 text-slate-400" />
          <span className={classNames("flex-1 truncate", selectedOption ? "text-slate-800" : "text-slate-400")}>
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          {isSuggested && (
            <span className="shrink-0 rounded-full bg-brand-50 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-700 ring-1 ring-brand-200">
              ✨ Suggested
            </span>
          )}
          <span className="text-sm text-slate-400">▾</span>
        </button>
      )}

      {open && (
        <div className="rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-300/50">
          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
            <input
              ref={inputRef}
              id={`${baseId}-specialty`}
              name="care-specialty-search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActiveIndex(-1);
              }}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={showListbox}
              aria-controls={`${baseId}-listbox`}
              aria-activedescendant={
                activeIndex >= 0 ? `${baseId}-opt-${activeIndex}` : undefined
              }
              autoComplete="off"
              spellCheck={false}
              autoFocus
              className="min-h-[52px] w-full rounded-t-2xl border-0 border-b border-slate-100 bg-white py-3 pl-12 pr-12 text-base text-slate-900 outline-none placeholder:text-slate-400"
            />
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setQuery("");
              }}
              className="absolute right-2 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-xl text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              aria-label="Close specialty selector"
            >
              <CloseIcon className="h-5 w-5" />
            </button>
          </div>

          <ul
            id={`${baseId}-listbox`}
            role="listbox"
            aria-label="Specialty suggestions"
            className="max-h-[360px] overflow-y-auto py-1.5 scroll-thin"
          >
            {grouped.suggested.length > 0 && (
              <>
                <li
                  className="px-4 py-2 text-[11px] font-bold uppercase tracking-[0.14em] text-brand-600"
                  role="presentation"
                >
                  Suggested from your records
                </li>
                {grouped.suggested.map((opt, idx) => (
                  <li
                    key={opt.id}
                    id={`${baseId}-opt-${idx}`}
                    role="option"
                    aria-selected={activeIndex === idx || value === opt.id}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => selectOption(opt.id)}
                    className={classNames(
                      "flex cursor-pointer items-start gap-3 border-b border-slate-100 px-4 py-3 last:border-0",
                      activeIndex === idx ? "bg-brand-50" : "bg-white hover:bg-slate-50",
                      value === opt.id && "bg-brand-50/60",
                    )}
                  >
                    <span
                      className={classNames(
                        "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-lg",
                        activeIndex === idx
                          ? "bg-brand-600 text-white"
                          : "bg-brand-50 text-brand-600",
                      )}
                    >
                      🩺
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900">{opt.label}</span>
                        {value === opt.id && <CheckIcon className="h-4 w-4 text-brand-600" />}
                      </span>
                      {opt.reasons && opt.reasons.length > 0 && (
                        <span className="mt-0.5 block truncate text-xs text-slate-500">
                          {opt.reasons[0]}
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </>
            )}

            {grouped.browse.length > 0 && (
              <>
                <li
                  className="px-4 py-2 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500"
                  role="presentation"
                >
                  Browse all specialties
                </li>
                {grouped.browse.map((opt, idx) => {
                  const globalIdx = grouped.suggested.length + idx;
                  return (
                    <li
                      key={opt.id}
                      id={`${baseId}-opt-${globalIdx}`}
                      role="option"
                      aria-selected={activeIndex === globalIdx || value === opt.id}
                      onMouseDown={(event) => event.preventDefault()}
                      onMouseEnter={() => setActiveIndex(globalIdx)}
                      onClick={() => selectOption(opt.id)}
                      className={classNames(
                        "flex cursor-pointer items-start gap-3 border-b border-slate-100 px-4 py-3 last:border-0",
                        activeIndex === globalIdx ? "bg-slate-50" : "bg-white hover:bg-slate-50",
                        value === opt.id && "bg-slate-50",
                      )}
                    >
                      <span
                        className={classNames(
                          "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
                          activeIndex === globalIdx
                            ? "bg-slate-200 text-slate-600"
                            : "bg-slate-100 text-slate-400",
                        )}
                      >
                        📋
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-slate-800">{opt.label}</span>
                          {value === opt.id && <CheckIcon className="h-4 w-4 text-brand-600" />}
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
