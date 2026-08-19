import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { classNames } from "../utils/format";
import { collectSafetyAlerts } from "../utils/safety";
import {
  AlertIcon,
  AppointmentIcon,
  BeakerIcon,
  ChartIcon,
  ChangesIcon,
  ChatIcon,
  FileIcon,
  PillIcon,
  LocationIcon,
  IntegrityIcon,
  ReminderIcon,
  SettingsIcon,
  ShieldIcon,
  SparkleIcon,
  StethoscopeIcon,
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
  group: "home" | "records" | "insights" | "actions" | "utility";
}

interface SidebarTooltipState {
  id: string;
  title: string;
  description: string;
  top: number;
}

const NAV: NavItem[] = [
  {
    group: "home",
    to: "/dashboard",
    labelKey: "nav.dashboard",
    descriptionKey: "nav.descriptions.dashboard",
    icon: SparkleIcon,
    chip: "bg-brand-50 text-brand-700",
  },
  {
    group: "records",
    to: "/documents",
    labelKey: "nav.records",
    descriptionKey: "nav.descriptions.records",
    icon: FileIcon,
    chip: "bg-cyan-50 text-cyan-800",
  },
  {
    group: "records",
    to: "/medicines",
    labelKey: "nav.medications",
    descriptionKey: "nav.descriptions.medications",
    icon: PillIcon,
    chip: "bg-emerald-50 text-emerald-800",
  },
  {
    group: "records",
    to: "/labs",
    labelKey: "nav.labs",
    descriptionKey: "nav.descriptions.labs",
    icon: BeakerIcon,
    chip: "bg-violet-50 text-violet-800",
  },
  {
    group: "records",
    to: "/history",
    labelKey: "nav.timeline",
    descriptionKey: "nav.descriptions.timeline",
    icon: TimelineIcon,
    chip: "bg-sky-50 text-sky-800",
  },
  {
    group: "records",
    to: "/import",
    labelKey: "nav.fhir",
    descriptionKey: "nav.descriptions.fhir",
    icon: UploadIcon,
    chip: "bg-indigo-50 text-indigo-800",
  },
  {
    group: "insights",
    to: "/changes",
    labelKey: "nav.changes",
    descriptionKey: "nav.descriptions.changes",
    icon: ChangesIcon,
    chip: "bg-indigo-50 text-indigo-800",
  },
  {
    group: "insights",
    to: "/safety",
    labelKey: "nav.safety",
    descriptionKey: "nav.descriptions.safety",
    icon: AlertIcon,
    chip: "bg-red-50 text-red-800",
  },
  {
    group: "insights",
    to: "/risk-timeline",
    labelKey: "nav.riskTimeline",
    descriptionKey: "nav.descriptions.riskTimeline",
    icon: ChartIcon,
    chip: "bg-rose-50 text-rose-800",
  },
  {
    group: "insights",
    to: "/clinical-safety",
    labelKey: "nav.clinicalSafety",
    descriptionKey: "nav.descriptions.clinicalSafety",
    icon: ShieldIcon,
    chip: "bg-red-50 text-red-800",
  },
  {
    group: "insights",
    to: "/vitals",
    labelKey: "nav.vitals",
    descriptionKey: "nav.descriptions.vitals",
    icon: ChartIcon,
    chip: "bg-teal-50 text-teal-800",
  },
  {
    group: "insights",
    to: "/preventive-care",
    labelKey: "nav.preventive",
    descriptionKey: "nav.descriptions.preventive",
    icon: SparkleIcon,
    chip: "bg-emerald-50 text-emerald-800",
  },
  {
    group: "insights",
    to: "/symptoms",
    labelKey: "nav.symptoms",
    descriptionKey: "nav.descriptions.symptoms",
    icon: ChatIcon,
    chip: "bg-sky-50 text-sky-800",
  },
  {
    group: "insights",
    to: "/review",
    labelKey: "nav.trustReview",
    descriptionKey: "nav.descriptions.trustReview",
    icon: ShieldIcon,
    chip: "bg-amber-50 text-amber-800",
  },
  {
    group: "insights",
    to: "/record-integrity",
    labelKey: "nav.recordCheck",
    descriptionKey: "nav.descriptions.recordCheck",
    icon: IntegrityIcon,
    chip: "bg-orange-50 text-orange-800",
  },
  {
    group: "actions",
    to: "/who-to-see",
    labelKey: "nav.whoToSee",
    descriptionKey: "nav.descriptions.whoToSee",
    icon: StethoscopeIcon,
    chip: "bg-amber-50 text-amber-800",
  },
  {
    group: "actions",
    to: "/appointment-prep",
    labelKey: "nav.appointmentPrep",
    descriptionKey: "nav.descriptions.appointmentPrep",
    icon: AppointmentIcon,
    chip: "bg-teal-50 text-teal-800",
  },
  {
    group: "actions",
    to: "/follow-up",
    labelKey: "nav.actionCenter",
    descriptionKey: "nav.descriptions.actionCenter",
    icon: ReminderIcon,
    chip: "bg-fuchsia-50 text-fuchsia-800",
  },
  {
    group: "actions",
    to: "/messages",
    labelKey: "nav.messages",
    descriptionKey: "nav.descriptions.messages",
    icon: ChatIcon,
    chip: "bg-cyan-50 text-cyan-800",
  },
  {
    group: "actions",
    to: "/guidelines",
    labelKey: "nav.guidelines",
    descriptionKey: "nav.descriptions.guidelines",
    icon: InfoIcon,
    chip: "bg-slate-100 text-slate-700",
  },
  {
    group: "actions",
    to: "/ask",
    labelKey: "nav.ask",
    descriptionKey: "nav.descriptions.ask",
    icon: ChatIcon,
    chip: "bg-brand-50 text-brand-700",
  },
  {
    group: "actions",
    to: "/find-care",
    labelKey: "nav.care",
    descriptionKey: "nav.descriptions.care",
    icon: LocationIcon,
    chip: "bg-cyan-50 text-cyan-800",
  },
  {
    group: "utility",
    to: "/settings",
    labelKey: "nav.settings",
    descriptionKey: "nav.descriptions.settings",
    icon: SettingsIcon,
    chip: "bg-slate-100 text-slate-700",
  },
];

const NAV_GROUPS: Array<{ key: NavItem["group"]; labelKey?: string }> = [
  { key: "home" },
  { key: "records", labelKey: "nav.groupRecords" },
  { key: "insights", labelKey: "nav.groupInsights" },
  { key: "actions", labelKey: "nav.groupActions" },
  { key: "utility" },
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
    typeof window !== "undefined" ? window.matchMedia("(min-width: 1024px)").matches : false,
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
  const { isConfigured, credentials, createNewWorkspace } = useAuth();
  const { t } = useI18n();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Desktop-only: collapse the sidebar to an icon rail (persisted).
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [tooltip, setTooltip] = useState<SidebarTooltipState | null>(null);
  const [navSignals, setNavSignals] = useState({
    safety: 0,
    safetyAvailable: false,
    safetyPending: false,
    hasChanges: false,
  });
  const desktop = useDesktopLayout();

  useEffect(() => {
    if (!isConfigured) {
      setNavSignals({ safety: 0, safetyAvailable: false, safetyPending: false, hasChanges: false });
      return;
    }
    let cancelled = false;
    api
      .getPatientSnapshot(credentials)
      .then((snapshot) => {
        if (cancelled) return;
        setNavSignals({
          safety: collectSafetyAlerts(snapshot.cross_check_report, snapshot.dosage_report).length,
          safetyAvailable: true,
          safetyPending: snapshot.rebuilt_from_documents === true,
          hasChanges:
            (snapshot.patient_timeline.documents || snapshot.patient_timeline.visits).length >= 2,
        });
      })
      .catch(() => {
        if (!cancelled)
          setNavSignals({
            safety: 0,
            safetyAvailable: false,
            safetyPending: false,
            hasChanges: false,
          });
      });
    return () => {
      cancelled = true;
    };
  }, [credentials, isConfigured, location.pathname]);

  useEffect(() => {
    const onSafetyUpdated = (event: Event) => {
      const count = Number((event as CustomEvent<{ count?: number }>).detail?.count);
      if (Number.isFinite(count)) {
        setNavSignals((current) => ({
          ...current,
          safety: count,
          safetyAvailable: true,
          safetyPending: false,
        }));
      }
    };
    window.addEventListener("medimind:safety-updated", onSafetyUpdated);
    return () => window.removeEventListener("medimind:safety-updated", onSafetyUpdated);
  }, []);

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
            'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"]), select:not([disabled]), input:not([disabled])',
          ),
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
    description: string,
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
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              className="h-6 w-6"
              aria-hidden="true"
            >
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
          collapsed ? "lg:w-[72px]" : "lg:w-[280px]",
        )}
        aria-label={t("nav.main")}
        aria-modal={!desktop && sidebarOpen ? true : undefined}
        role={!desktop && sidebarOpen ? "dialog" : undefined}
      >
        <div className="flex h-full min-h-0 flex-col overflow-hidden">
          <div
            className={classNames(
              "flex min-h-16 shrink-0 items-center gap-3 px-4 py-3",
              collapsed && "lg:justify-center lg:px-2",
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
              <button
                type="button"
                onClick={closeSidebar}
                className="btn-ghost !min-h-[44px] !px-3"
                aria-label={t("nav.close")}
              >
                <span aria-hidden="true">✕</span>
              </button>
            )}
          </div>

          {isConfigured && (
            <div className="shrink-0 px-3 pb-3">
              <NavLink
                to="/upload"
                onClick={closeSidebar}
                onMouseEnter={(event) =>
                  showCollapsedTooltip(
                    event.currentTarget,
                    "sidebar-tooltip-upload",
                    t("nav.upload"),
                    t("nav.descriptions.upload"),
                  )
                }
                onMouseLeave={() => setTooltip(null)}
                onFocus={(event) =>
                  showCollapsedTooltip(
                    event.currentTarget,
                    "sidebar-tooltip-upload",
                    t("nav.upload"),
                    t("nav.descriptions.upload"),
                  )
                }
                onBlur={() => setTooltip(null)}
                tabIndex={navInteractive ? undefined : -1}
                aria-describedby={desktop && collapsed ? "sidebar-tooltip-upload" : undefined}
                className={classNames(
                  "flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-brand-600 px-3 text-[15px] font-semibold text-white shadow-sm transition hover:bg-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-300 focus-visible:ring-offset-2",
                  collapsed && "lg:px-0",
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
            {NAV_GROUPS.map((group) => {
              const items = NAV.filter((item) => item.group === group.key);
              return (
                <div
                  key={group.key}
                  role="group"
                  aria-labelledby={group.labelKey ? `nav-group-${group.key}` : undefined}
                  className={classNames(
                    group.key !== "home" && "mt-2 border-t border-slate-200/80 pt-2",
                  )}
                >
                  {group.labelKey && (
                    <p
                      id={`nav-group-${group.key}`}
                      className={classNames(
                        "px-2.5 pb-1 pt-1 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400",
                        collapsed && "lg:sr-only",
                      )}
                    >
                      {t(group.labelKey)}
                    </p>
                  )}
                  {items.map((item) => {
                    const index = NAV.indexOf(item);
                    const Icon = item.icon;
                    const worksWithoutWorkspace = item.to === "/settings";
                    const disabled = !worksWithoutWorkspace && !isConfigured;
                    const safetyCount = item.to === "/safety" ? navSignals.safety : 0;
                    const showNew = item.to === "/changes" && navSignals.hasChanges;
                    return (
                      <NavLink
                        ref={
                          index === (isConfigured ? 0 : NAV.length - 1) ? firstNavRef : undefined
                        }
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
                        onMouseEnter={(event) =>
                          showCollapsedTooltip(
                            event.currentTarget,
                            `sidebar-tooltip-${index}`,
                            t(item.labelKey),
                            t(item.descriptionKey),
                          )
                        }
                        onMouseLeave={() => setTooltip(null)}
                        onFocus={(event) =>
                          showCollapsedTooltip(
                            event.currentTarget,
                            `sidebar-tooltip-${index}`,
                            t(item.labelKey),
                            t(item.descriptionKey),
                          )
                        }
                        onBlur={() => setTooltip(null)}
                        aria-disabled={disabled}
                        aria-label={
                          collapsed
                            ? `${t(item.labelKey)}${navSignals.safetyPending && item.to === "/safety" ? ", analysis pending" : safetyCount ? `, ${safetyCount} alerts` : ""}`
                            : undefined
                        }
                        aria-describedby={
                          desktop && collapsed ? `sidebar-tooltip-${index}` : undefined
                        }
                        className={({ isActive }) =>
                          classNames(
                            "group relative flex min-h-[44px] items-center gap-2.5 rounded-[9px] px-2.5 text-[15px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-1 lg:min-h-[42px]",
                            collapsed && "lg:justify-center lg:px-0",
                            disabled
                              ? "cursor-not-allowed text-slate-400"
                              : isActive
                                ? "bg-[#eaf6f4] font-semibold text-[#123c3a] shadow-[inset_3px_0_0_#0F766E]"
                                : "text-slate-600 hover:bg-[#f3f7f6] hover:text-slate-900",
                          )
                        }
                      >
                        {({ isActive }) => (
                          <>
                            <span
                              className={classNames(
                                "relative flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px]",
                                item.chip,
                              )}
                            >
                              <Icon className="h-4 w-4" />
                              {(safetyCount > 0 ||
                                showNew ||
                                (item.to === "/safety" && navSignals.safetyPending)) && (
                                <span
                                  className={classNames(
                                    "absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-white",
                                    item.to === "/safety" && navSignals.safetyPending
                                      ? "bg-amber-500"
                                      : "bg-red-500",
                                  )}
                                  aria-hidden="true"
                                />
                              )}
                            </span>
                            <span
                              className={classNames(
                                "min-w-0 flex-1 break-words",
                                collapsed && "lg:hidden",
                              )}
                            >
                              {t(item.labelKey)}
                            </span>
                            {safetyCount > 0 && (
                              <span
                                className={classNames(
                                  "rounded-full bg-red-100 px-2 py-0.5 text-xs font-bold text-red-700",
                                  collapsed && "lg:hidden",
                                )}
                              >
                                {safetyCount}
                              </span>
                            )}
                            {safetyCount === 0 &&
                              item.to === "/safety" &&
                              navSignals.safetyAvailable &&
                              !navSignals.safetyPending && (
                                <span
                                  className={classNames(
                                    "text-emerald-600",
                                    collapsed && "lg:hidden",
                                  )}
                                  aria-label="No active safety alerts"
                                >
                                  ✓
                                </span>
                              )}
                            {item.to === "/safety" && navSignals.safetyPending && (
                              <span
                                className={classNames(
                                  "text-[10px] font-bold text-amber-700",
                                  collapsed && "lg:hidden",
                                )}
                              >
                                PENDING
                              </span>
                            )}
                            {showNew && (
                              <span
                                className={classNames(
                                  "rounded-full bg-indigo-100 px-1.5 py-0.5 text-[9px] font-bold text-indigo-700",
                                  collapsed && "lg:hidden",
                                )}
                              >
                                NEW
                              </span>
                            )}
                            {isActive && <span className="sr-only">({t("nav.currentPage")})</span>}
                          </>
                        )}
                      </NavLink>
                    );
                  })}
                </div>
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
              onMouseEnter={(event) =>
                showCollapsedTooltip(
                  event.currentTarget,
                  "sidebar-tooltip-about",
                  t("about.nav"),
                  t("nav.descriptions.about"),
                )
              }
              onMouseLeave={() => setTooltip(null)}
              onFocus={(event) =>
                showCollapsedTooltip(
                  event.currentTarget,
                  "sidebar-tooltip-about",
                  t("about.nav"),
                  t("nav.descriptions.about"),
                )
              }
              onBlur={() => setTooltip(null)}
              aria-label={collapsed ? t("about.nav") : undefined}
              aria-describedby={desktop && collapsed ? "sidebar-tooltip-about" : undefined}
              className={({ isActive }) =>
                classNames(
                  "flex min-h-[44px] items-center gap-2.5 rounded-[9px] px-2.5 text-[15px] font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-1",
                  collapsed && "lg:justify-center lg:px-0",
                  isActive
                    ? "bg-[#eaf6f4] font-semibold text-[#123c3a] shadow-[inset_3px_0_0_#0F766E]"
                    : "text-slate-600 hover:bg-[#f3f7f6] hover:text-slate-900",
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
                <div className="pt-1">
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        window.confirm(
                          "Start a new workspace? This browser will lose access to the current workspace unless you saved its code. Stored data is not deleted.",
                        )
                      ) {
                        void createNewWorkspace();
                      }
                    }}
                    className="flex min-h-[44px] w-full items-center rounded-lg px-2 text-left text-xs font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 lg:min-h-10"
                    title={`${t("nav.newWorkspace")} (${credentials.userId})`}
                  >
                    <span aria-hidden="true" className="mr-2 text-base">
                      ＋
                    </span>{" "}
                    {t("nav.newWorkspace")}
                  </button>
                  <p className="px-2 pb-1 text-[10px] leading-relaxed text-slate-400">
                    Permanent deletion is available in Settings.
                  </p>
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
            "app-content mx-auto min-w-0 px-4 pb-24 pt-6 sm:px-6 md:pb-6 lg:px-8 lg:py-8",
            location.pathname.startsWith("/about") ? "max-w-[1280px] lg:px-12" : "max-w-6xl",
          )}
        >
          <Outlet />
        </div>
      </main>

      {isConfigured && (
        <nav
          aria-label="Mobile primary navigation"
          className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-slate-200 bg-white/95 px-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] pt-2 shadow-[0_-8px_24px_-16px_rgba(15,23,42,0.4)] backdrop-blur md:hidden"
        >
          {[
            { to: "/dashboard", label: "Home", icon: SparkleIcon },
            { to: "/documents", label: "Records", icon: FileIcon },
            { to: "/upload", label: "Upload", icon: UploadIcon, primary: true },
            { to: "/safety", label: "Insights", icon: AlertIcon },
            { to: "/settings", label: "More", icon: SettingsIcon },
          ].map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  classNames(
                    "relative flex min-h-[48px] flex-col items-center justify-center gap-0.5 rounded-xl text-[10px] font-semibold",
                    item.primary
                      ? "-mt-5 bg-brand-700 text-white shadow-lg"
                      : isActive
                        ? "text-brand-700"
                        : "text-slate-500",
                  )
                }
              >
                <Icon className="h-5 w-5" />
                <span>{item.label}</span>
                {item.to === "/safety" && navSignals.safety > 0 && (
                  <span className="absolute right-[22%] top-0.5 min-w-4 rounded-full bg-red-600 px-1 text-center text-[9px] text-white">
                    {navSignals.safety}
                  </span>
                )}
                {item.to === "/safety" && navSignals.safetyPending && (
                  <span
                    className="absolute right-[25%] top-1 h-2.5 w-2.5 rounded-full border border-white bg-amber-500"
                    aria-label="Safety analysis pending"
                  />
                )}
              </NavLink>
            );
          })}
        </nav>
      )}

      {isConfigured && !location.pathname.startsWith("/ask") && (
        <NavLink
          to="/ask"
          aria-label="Ask AI about your uploaded medical records"
          title="Ask AI about your records"
          className="fixed bottom-5 right-5 z-20 hidden min-h-[52px] items-center md:flex gap-2 rounded-full bg-brand-700 px-4 py-3 text-sm font-bold text-white shadow-lg transition hover:-translate-y-0.5 hover:bg-brand-800 focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2"
        >
          <ChatIcon className="h-5 w-5" />
          <span className="hidden sm:inline">Ask AI</span>
        </NavLink>
      )}

      {tooltip &&
        createPortal(
          <div
            id={tooltip.id}
            role="tooltip"
            style={{ left: 82, top: tooltip.top }}
            className="sidebar-tooltip pointer-events-none fixed z-[100] w-[280px] -translate-y-1/2 rounded-xl border border-slate-200/90 bg-white px-4 py-3 text-left shadow-[0_16px_40px_-12px_rgba(15,23,42,0.28)]"
          >
            <span
              className="absolute -left-1.5 top-1/2 h-3 w-3 -translate-y-1/2 rotate-45 border-b border-l border-slate-200 bg-white"
              aria-hidden="true"
            />
            <span className="block text-sm font-semibold text-slate-900">{tooltip.title}</span>
            <span className="mt-0.5 block text-xs leading-relaxed text-slate-600">
              {tooltip.description}
            </span>
          </div>,
          document.body,
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
        small ? "h-8 w-8" : "h-10 w-10",
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
