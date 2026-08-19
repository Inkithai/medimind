/**
 * Shared tab chrome for the parent ("hub") pages.
 *
 * The information architecture groups sibling screens that answer the same
 * patient question under one sidebar entry — Safety, Record check, Ask AI,
 * Find care, Next steps. Each tab is still the original page component; this
 * file only supplies the selector and the URL contract around it.
 *
 * Two rules the rest of the app depends on:
 *
 *  1. The active tab lives in the query string (`?tab=…`), so every view keeps
 *     a shareable, bookmarkable URL. Old top-level paths redirect onto the
 *     matching `?tab=` value instead of 404-ing.
 *  2. The default tab is represented by the *absence* of the parameter, so the
 *     canonical URL of a hub stays clean (`/safety`, not `/safety?tab=alerts`).
 *
 * Keyboard behaviour follows the WAI-ARIA tabs pattern: arrows move between
 * tabs, Home/End jump to the ends, and only the selected tab is in the tab
 * order (roving tabindex).
 */
import { useCallback, useRef, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { classNames } from "../utils/format";

/**
 * Props shared by every screen that can render either standalone (its own
 * route) or inside a hub tab. When `embedded` is true the page drops its own
 * title block — the hub already printed one — but keeps its toolbar actions.
 */
export interface EmbeddedPageProps {
  embedded?: boolean;
}

export interface TabSpec {
  /** Value written to `?tab=`. The first tab's id is the default and is omitted from the URL. */
  id: string;
  label: string;
  /** Optional count/dot rendered after the label (e.g. number of open safety alerts). */
  badge?: ReactNode;
}

/**
 * Reads and writes the active tab from the query string.
 *
 * Unknown or misspelled values fall back to the default tab rather than
 * rendering an empty page — a typo mid-demo must not blank the screen.
 * Other query parameters (a selected document, a deep-linked finding) are
 * preserved when the tab changes.
 */
export function useTabParam(
  tabs: readonly TabSpec[],
  { param = "tab" }: { param?: string } = {},
): [string, (next: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const fallback = tabs[0]?.id || "";
  const requested = searchParams.get(param);
  const active = tabs.some((tab) => tab.id === requested) ? (requested as string) : fallback;

  const setActive = useCallback(
    (next: string) => {
      const params = new URLSearchParams(searchParams);
      if (next === fallback) params.delete(param);
      else params.set(param, next);
      setSearchParams(params, { replace: true });
    },
    [fallback, param, searchParams, setSearchParams],
  );

  return [active, setActive];
}

export function tabId(group: string, id: string) {
  return `${group}-tab-${id}`;
}

export function panelId(group: string, id: string) {
  return `${group}-panel-${id}`;
}

export function TabBar({
  tabs,
  active,
  onSelect,
  label,
  group,
  className,
}: {
  tabs: readonly TabSpec[];
  active: string;
  onSelect: (id: string) => void;
  /** Accessible name for the tab list, e.g. "Safety views". */
  label: string;
  /** Prefix used to link each tab to its panel; unique per hub page. */
  group: string;
  className?: string;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  function focusTab(index: number) {
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    if (!buttons?.length) return;
    const bounded = (index + buttons.length) % buttons.length;
    buttons[bounded].focus();
    onSelect(tabs[bounded].id);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const current = tabs.findIndex((tab) => tab.id === active);
    if (current < 0) return;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        focusTab(current + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        focusTab(current - 1);
        break;
      case "Home":
        event.preventDefault();
        focusTab(0);
        break;
      case "End":
        event.preventDefault();
        focusTab(tabs.length - 1);
        break;
      default:
        break;
    }
  }

  return (
    /* Horizontally scrollable on narrow screens: four tabs must never wrap
       into a second row that pushes the content out of view. */
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={classNames(
        "-mx-1 flex gap-1 overflow-x-auto border-b border-slate-200 px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={tabId(group, tab.id)}
            aria-selected={selected}
            /* Only the active panel is mounted (so a hidden tab never fires
               its request), and aria-controls must not point at an element
               that is not in the document — screen readers announce a
               dangling reference as a broken control. Advertise the
               relationship only for the tab whose panel actually exists. */
            aria-controls={selected ? panelId(group, tab.id) : undefined}
            tabIndex={selected ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            className={classNames(
              "shrink-0 whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold transition focus:outline-none focus-visible:rounded-t focus-visible:ring-2 focus-visible:ring-brand-400",
              selected
                ? "border-brand-600 text-brand-700"
                : "border-transparent text-slate-500 hover:text-slate-800",
            )}
          >
            {tab.label}
            {tab.badge != null && tab.badge !== false && (
              <span className="ml-2 inline-flex min-w-5 items-center justify-center rounded-full bg-slate-100 px-1.5 py-0.5 text-[11px] font-bold text-slate-700">
                {tab.badge}
              </span>
            )}
            {selected && <span className="sr-only"> (selected)</span>}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Panel wrapper. Only the active panel is mounted, so a hidden tab never
 * fires its data request — switching to Safety must not also load the map
 * bundle or the provider directory.
 */
export function TabPanel({
  group,
  id,
  active,
  children,
}: {
  group: string;
  id: string;
  active: string;
  children: ReactNode;
}) {
  if (id !== active) return null;
  return (
    <div
      role="tabpanel"
      id={panelId(group, id)}
      aria-labelledby={tabId(group, id)}
      tabIndex={-1}
      className="focus:outline-none"
    >
      {children}
    </div>
  );
}

/**
 * Standard hub header: eyebrow, title, one sentence, then the tab bar.
 * Hubs share this so the six parents read as one product, not six designs.
 */
export function HubHeader({
  eyebrow,
  icon,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  icon?: ReactNode;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && (
          <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
            {icon}
            {eyebrow}
          </div>
        )}
        <h1 className={classNames("page-title", eyebrow && "mt-1")}>{title}</h1>
        <p className="secondary-text mt-2">{description}</p>
      </div>
      {action}
    </header>
  );
}
