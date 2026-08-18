import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { classNames } from "../utils/format";
import {
  AppointmentIcon,
  BeakerIcon,
  ChangesIcon,
  ChatIcon,
  ClockIcon,
  FileIcon,
  PillIcon,
  LocationIcon,
  IntegrityIcon,
  ReminderIcon,
  SettingsIcon,
  ShieldIcon,
  TimelineIcon,
  UploadIcon,
} from "./icons";
import { LanguageSelector } from "./LanguageSelector";

interface NavItem {
  to: string;
  labelKey: string;
  descriptionKey: string;
  icon: (props: { className?: string }) => ReactNode;
  chip: string;
}

interface SidebarTooltipState {
  id: string;
  title: string;
  description: string;
  top: number;
}

const NAV: NavItem[] = [
  // Semantic, muted icon tiles (spec: pale background ~7-10% + medium-dark
  // stroke; teal/cyan = records & communication, blue/violet = timelines &
  // analysis, amber/orange = trust & safety review, rose = alerts/risk,
  // slate = utilities).
  { to: "/dashboard", labelKey: "nav.dashboard", descriptionKey: "nav.descriptions.dashboard", icon: TimelineIcon, chip: "bg-brand-50 text-brand-700" },
  { to: "/documents", labelKey: "nav.records", descriptionKey: "nav.descriptions.records", icon: FileIcon, chip: "bg-cyan-50 text-cyan-800" },
  { to: "/review", labelKey: "nav.trustReview", descriptionKey: "nav.descriptions.trustReview", icon: ShieldIcon, chip: "bg-amber-50 text-amber-800" },
  { to: "/medicines", labelKey: "nav.medications", descriptionKey: "nav.descriptions.medications", icon: PillIcon, chip: "bg-emerald-50 text-emerald-800" },
  { to: "/labs", labelKey: "nav.labs", descriptionKey: "nav.descriptions.labs", icon: BeakerIcon, chip: "bg-violet-50 text-violet-800" },
  { to: "/history", labelKey: "nav.timeline", descriptionKey: "nav.descriptions.timeline", icon: TimelineIcon, chip: "bg-sky-50 text-sky-800" },
  { to: "/changes", labelKey: "nav.changes", descriptionKey: "nav.descriptions.changes", icon: ChangesIcon, chip: "bg-indigo-50 text-indigo-800" },
  { to: "/appointment-prep", labelKey: "nav.appointmentPrep", descriptionKey: "nav.descriptions.appointmentPrep", icon: AppointmentIcon, chip: "bg-teal-50 text-teal-800" },
  { to: "/follow-up", labelKey: "nav.actionCenter", descriptionKey: "nav.descriptions.actionCenter", icon: ReminderIcon, chip: "bg-teal-50 text-teal-800" },
  { to: "/record-integrity", labelKey: "nav.recordCheck", descriptionKey: "nav.descriptions.recordCheck", icon: IntegrityIcon, chip: "bg-orange-50 text-orange-800" },
  { to: "/safety", labelKey: "nav.safety", descriptionKey: "nav.descriptions.safety", icon: ShieldIcon, chip: "bg-amber-50 text-amber-800" },
  { to: "/risk-timeline", labelKey: "nav.riskTimeline", descriptionKey: "nav.descriptions.riskTimeline", icon: ClockIcon, chip: "bg-rose-50 text-rose-800" },
  { to: "/ask", labelKey: "nav.ask", descriptionKey: "nav.descriptions.ask", icon: ChatIcon, chip: "bg-brand-50 text-brand-700" },
  { to: "/find-care", labelKey: "nav.care", descriptionKey: "nav.descriptions.care", icon: LocationIcon, chip: "bg-cyan-50 text-cyan-800" },
  { to: "/settings", labelKey: "nav.settings", descriptionKey: "nav.descriptions.settings", icon: SettingsIcon, chip: "bg-slate-100 text-slate-700" },
];

const COLLAPSE_KEY = "medimind.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function useDesktopLayout(): boolean {
  const [desktop, setDesktop] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia("(min-width: 1024px)").matches : false
  );
  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    const update = () => setDesktop(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return desktop;
}

export function Layout() {
  const { isConfigured, credentials, createNewWorkspace, clearCredentials } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Desktop-only: collapse the sidebar to an icon rail (persisted).
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [tooltip, setTooltip] = useState<SidebarTooltipState | null>(null);
  const desktop = useDesktopLayout();

  useEffect(() => {
    if (!desktop || !collapsed) setTooltip(null);
  }, [collapsed, desktop, location.pathname]);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      // Persistence is best-effort only.
    }
  }, [collapsed]);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const firstNavRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (!sidebarOpen || desktop) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.setTimeout(() => firstNavRef.current?.focus(), 0);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSidebarOpen(false);
        menuButtonRef.current?.focus();
        return;
      }
      if (event.key === "Tab" && sidebarRef.current) {
        const focusable = Array.from(
          sidebarRef.current.querySelectorAll<HTMLElement>(
            'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"]), select:not([disabled]), input:not([disabled])'
          )
        );
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [desktop, sidebarOpen]);

  const closeSidebar = () => setSidebarOpen(false);
  const navInteractive = desktop || sidebarOpen;

  const showCollapsedTooltip = (
    anchor: HTMLElement,
    id: string,
    title: string,
    description: string
  ) => {
    if (!desktop || !collapsed) return;
    const rect = anchor.getBoundingClientRect();
    setTooltip({
      id,
      title,
      description,
      top: Math.max(64, Math.min(window.innerHeight - 64, rect.top + rect.height / 2)),
    });
  };

  return (
    <div className="min-h-full lg:flex">
      <a href="#main-content" className="skip-link">
        {t("common.skipToContent")}
      </a>

      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
        <div className="flex min-w-0 items-center gap-2">
          <Logo small />
          <span className="truncate text-lg font-bold text-slate-900">MediMind</span>
        </div>
        <div className="flex items-center gap-2">
          <LanguageSelector compact />
          <button
            ref={menuButtonRef}
            type="button"
            onClick={() => setSidebarOpen((value) => !value)}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-slate-700 hover:bg-slate-100"
            aria-label={t("nav.toggle")}
            aria-expanded={sidebarOpen}
            aria-controls="primary-sidebar"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-6 w-6" aria-hidden="true">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
        </div>
      </header>

      {/* Mobile drawer; desktop sticky sidebar remains visible on long pages.
          Three-part fixed-height structure: header + upload stay visible, the
          workflow navigation scrolls independently, and the utility region
          (About, language, workspace controls) stays pinned at the bottom. */}
      <aside
        ref={sidebarRef}
        id="primary-sidebar"
        className={classNames(
          "fixed bottom-0 left-0 top-0 z-30 h-dvh w-[min(18rem,calc(100vw-2rem))] transform border-r border-[#e3e9e8] bg-[#fcfdfd] transition-all duration-200",
          // Keep the desktop sidebar pinned to the viewport rather than stretching with page content.
          "lg:sticky lg:bottom-auto lg:top-0 lg:h-dvh lg:shrink-0 lg:self-start lg:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
          collapsed ? "lg:w-[72px]" : "lg:w-[280px]"
        )}
        aria-label={t("nav.main")}
        aria-modal={!desktop && sidebarOpen ? true : undefined}
        role={!desktop && sidebarOpen ? "dialog" : undefined}
      >
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
          <div
            className={classNames(
              "flex min-h-16 shrink-0 items-center gap-3 px-4 py-3",
              collapsed && "lg:justify-center lg:px-2"
            )}
          >
            {/* When collapsed the logo/name hide and the toggle stays — the
                expand control must NEVER disappear, or the rail could not be
                opened again (collapse state persists in localStorage). */}
            <div className={classNames("contents", collapsed && "lg:hidden")}>
              <Logo />
              <div className="min-w-0 flex-1">
                <p className="text-xl font-bold leading-tight text-slate-900">MediMind</p>
              </div>
            </div>
            {desktop && (
              <button
                type="button"
                onClick={() => setCollapsed((value) => !value)}
                className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 lg:flex"
                aria-label={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
                aria-expanded={!collapsed}
                title={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={classNames("h-5 w-5 transition-transform", collapsed && "rotate-180")}
                  aria-hidden="true"
                >
                  <polyline points="11 17 6 12 11 7" />
                  <polyline points="18 17 13 12 18 7" />
                </svg>
              </button>
            )}
            {!desktop && (
              <button type="button" onClick={closeSidebar} className="btn-ghost !min-h-[44px] !px-3" aria-label={t("nav.close")}>
                <span aria-hidden="true">✕</span>
              </button>
            )}
          </div>

          {isConfigured && (
            <div className="shrink-0 px-3 pb-3">
              <NavLink
                to="/upload"
                onClick={closeSidebar}
                onMouseEnter={(event) => showCollapsedTooltip(
                  event.currentTarget,
                  "sidebar-tooltip-upload",
                  t("nav.upload"),
                  t("nav.descriptions.upload")
                )}
                onMouseLeave={() => setTooltip(null)}
                onFocus={(event) => showCollapsedTooltip(
                  event.currentTarget,
                  "sidebar-tooltip-upload",
                  t("nav.upload"),
                  t("nav.descriptions.upload")
                )}
                onBlur={() => setTooltip(null)}
                tabIndex={navInteractive ? undefined : -1}
                aria-describedby={desktop && collapsed ? "sidebar-tooltip-upload" : undefined}
                className={classNames(
                  "flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-brand-600 px-3 text-[15px] font-semibold text-white shadow-sm transition hover:bg-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2",
                  collapsed && "lg:px-0"
                )}
              >
                <UploadIcon className="h-5 w-5 shrink-0" />
                <span className={classNames(collapsed && "lg:hidden")}>{t("nav.upload")}</span>
              </NavLink>
            </div>
          )}

          <nav
            className="scroll-thin min-h-0 flex-1 space-y-0.5 overflow-y-auto overscroll-contain px-2 py-1"
            aria-label={t("nav.main")}
          >
            {NAV.map((item, index) => {
              const Icon = item.icon;
              const worksWithoutWorkspace = item.to === "/settings";
              const disabled = !worksWithoutWorkspace && !isConfigured;
              return (
                <NavLink
                  ref={index === (isConfigured ? 0 : NAV.length - 1) ? firstNavRef : undefined}
                  key={item.to}
                  to={disabled ? "#" : item.to}
                  tabIndex={!navInteractive || disabled ? -1 : undefined}
                  onClick={(event) => {
                    if (disabled) {
                      event.preventDefault();
                      return;
                    }
                    closeSidebar();
                  }}
                  onMouseEnter={(event) => showCollapsedTooltip(
                    event.currentTarget,
                    `sidebar-tooltip-${index}`,
                    t(item.labelKey),
                    t(item.descriptionKey)
                  )}
                  onMouseLeave={() => setTooltip(null)}
                  onFocus={(event) => showCollapsedTooltip(
                    event.currentTarget,
                    `sidebar-tooltip-${index}`,
                    t(item.labelKey),
                    t(item.descriptionKey)
                  )}
                  onBlur={() => setTooltip(null)}
                  aria-disabled={disabled}
                  aria-describedby={desktop && collapsed ? `sidebar-tooltip-${index}` : undefined}
                  className={({ isActive }) =>
                    classNames(
                      "group flex min-h-[44px] items-center gap-2.5 rounded-[9px] px-2.5 text-[15px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-1 lg:min-h-[42px]",
                      collapsed && "lg:justify-center lg:px-0",
                      // Settings stays in place but gets a little separation
                      // to read as a utility destination (no group label added).
                      item.to === "/settings" && "mt-2",
                      disabled
                        ? "cursor-not-allowed text-slate-400"
                        : isActive
                        ? // Pale-teal active treatment: background + weight/color
                          // + teal edge marker — selection never relies on color alone.
                          "bg-[#eaf6f4] font-semibold text-[#123c3a] shadow-[inset_3px_0_0_#0F766E]"
                        : "text-slate-600 hover:bg-[#f3f7f6] hover:text-slate-900"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span className={classNames("flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px]", item.chip)}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className={classNames("min-w-0 flex-1 break-words", collapsed && "lg:hidden")}>{t(item.labelKey)}</span>
                      {isActive && <span className="sr-only">({t("nav.currentPage")})</span>}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Secondary and informational — deliberately outside the workflow
              nav above, and available with or without a workspace. Same row
              treatment and active state as the main navigation, so About reads
              as part of the application rather than an unrelated footer box. */}
          <div className="shrink-0 border-t border-[#e5ebe9] px-2 pb-3 pt-2">
            <NavLink
              to="/about"
              onClick={closeSidebar}
              onMouseEnter={(event) => showCollapsedTooltip(
                event.currentTarget,
                "sidebar-tooltip-about",
                t("about.nav"),
                t("nav.descriptions.about")
              )}
              onMouseLeave={() => setTooltip(null)}
              onFocus={(event) => showCollapsedTooltip(
                event.currentTarget,
                "sidebar-tooltip-about",
                t("about.nav"),
                t("nav.descriptions.about")
              )}
              onBlur={() => setTooltip(null)}
              aria-label={collapsed ? t("about.nav") : undefined}
              aria-describedby={desktop && collapsed ? "sidebar-tooltip-about" : undefined}
              className={({ isActive }) =>
                classNames(
                  "flex min-h-[44px] items-center gap-2.5 rounded-[9px] px-2.5 text-[15px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-1",
                  collapsed && "lg:justify-center lg:px-0",
                  isActive
                    ? "bg-[#eaf6f4] font-semibold text-[#123c3a] shadow-[inset_3px_0_0_#0F766E]"
                    : "text-slate-600 hover:bg-[#f3f7f6] hover:text-slate-900"
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-brand-50 text-brand-700">
                    <InfoIcon className="h-4 w-4" />
                  </span>
                  <span className={classNames("min-w-0 truncate", collapsed && "lg:hidden")}>
                    {t("about.nav")}
                  </span>
                  {isActive && <span className="sr-only">({t("nav.currentPage")})</span>}
                </>
              )}
            </NavLink>

            <div className={classNames("px-1", collapsed && "lg:hidden")}>
              <LanguageSelector className="mb-2 hidden lg:block" />
              {isConfigured && (
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => void createNewWorkspace()}
                    className="min-h-[44px] rounded-lg border border-slate-300 bg-white px-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 lg:min-h-10"
                    title={`${t("nav.newWorkspace")} (${credentials.userId})`}
                  >
                    {t("nav.newWorkspace")}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      clearCredentials();
                      navigate("/");
                    }}
                    className="min-h-[44px] rounded-lg border border-red-200 bg-white px-1.5 text-xs font-semibold text-red-700 transition hover:border-red-300 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 lg:min-h-10"
                  >
                    {t("nav.resetData")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </aside>

      {sidebarOpen && !desktop && (
        <button
          type="button"
          className="fixed inset-0 z-20 cursor-default bg-slate-950/50"
          onClick={() => {
            closeSidebar();
            menuButtonRef.current?.focus();
          }}
          aria-label={t("nav.close")}
          tabIndex={-1}
        />
      )}

      {/* overflow-x-clip (not hidden): `hidden` would create a scroll
          container and silently break the About page's sticky section bar
          and any other sticky element inside the content column. `clip`
          guards against horizontal overflow without a scrollport. */}
      <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 overflow-x-clip bg-slate-50">
        {/* The About page opts into a wider editorial grid (spec: up to
            1280px with 48px gutters); every other page keeps the standard
            72rem content column. */}
        <div
          className={classNames(
            "app-content mx-auto min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8",
            location.pathname.startsWith("/about") ? "max-w-[1280px] lg:px-12" : "max-w-6xl"
          )}
        >
          <Outlet />
        </div>
      </main>

      {tooltip && createPortal(
        <div
          id={tooltip.id}
          role="tooltip"
          style={{ left: 82, top: tooltip.top }}
          className="sidebar-tooltip pointer-events-none fixed z-[100] w-[280px] -translate-y-1/2 rounded-xl border border-slate-200/90 bg-white px-4 py-3 text-left shadow-[0_16px_40px_-12px_rgba(15,23,42,0.28)]"
        >
          <span className="absolute -left-1.5 top-1/2 h-3 w-3 -translate-y-1/2 rotate-45 border-b border-l border-slate-200 bg-white" aria-hidden="true" />
          <span className="block text-sm font-semibold text-slate-900">{tooltip.title}</span>
          <span className="mt-0.5 block text-xs leading-relaxed text-slate-600">{tooltip.description}</span>
        </div>,
        document.body
      )}
    </div>
  );
}

function Logo({ small }: { small?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={classNames(
        "flex shrink-0 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-brand-100",
        small ? "h-8 w-8" : "h-10 w-10"
      )}
    >
      <img
        src="/favicon.svg"
        alt=""
        className={classNames("block rounded-[9px]", small ? "h-7 w-7" : "h-9 w-9")}
      />
    </span>
  );
}

function InfoIcon({ className }: { className?: string }) {
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
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}
