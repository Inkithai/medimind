import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { classNames } from "../utils/format";
import {
  BeakerIcon,
  ChatIcon,
  FileIcon,
  PillIcon,
  LocationIcon,
  SettingsIcon,
  ShieldIcon,
  TimelineIcon,
  UploadIcon,
} from "./icons";
import { LanguageSelector } from "./LanguageSelector";

interface NavItem {
  to: string;
  labelKey: string;
  icon: (props: { className?: string }) => ReactNode;
  chip: string;
}

const NAV: NavItem[] = [
  { to: "/dashboard", labelKey: "nav.dashboard", icon: TimelineIcon, chip: "bg-brand-50 text-brand-700" },
  { to: "/documents", labelKey: "nav.records", icon: FileIcon, chip: "bg-sky-50 text-sky-700" },
  { to: "/medicines", labelKey: "nav.medications", icon: PillIcon, chip: "bg-emerald-50 text-emerald-700" },
  { to: "/labs", labelKey: "nav.labs", icon: BeakerIcon, chip: "bg-violet-50 text-violet-700" },
  { to: "/history", labelKey: "nav.timeline", icon: TimelineIcon, chip: "bg-sky-50 text-sky-700" },
  { to: "/safety", labelKey: "nav.safety", icon: ShieldIcon, chip: "bg-amber-50 text-amber-800" },
  { to: "/ask", labelKey: "nav.ask", icon: ChatIcon, chip: "bg-brand-50 text-brand-700" },
  { to: "/find-care", labelKey: "nav.care", icon: LocationIcon, chip: "bg-rose-50 text-rose-700" },
  { to: "/settings", labelKey: "nav.settings", icon: SettingsIcon, chip: "bg-slate-100 text-slate-700" },
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Desktop-only: collapse the sidebar to an icon rail (persisted).
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const desktop = useDesktopLayout();

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

      {/* Mobile drawer; desktop sticky sidebar remains visible on long pages. */}
      <aside
        ref={sidebarRef}
        id="primary-sidebar"
        className={classNames(
          "fixed bottom-0 left-0 top-0 z-30 w-72 transform border-r border-slate-200 bg-white transition-all duration-200",
          // `self-start` stops the flex row from stretching the sidebar to the
          // full content height, which would defeat sticky positioning.
          "lg:sticky lg:bottom-auto lg:top-0 lg:h-screen lg:shrink-0 lg:self-start lg:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
          collapsed ? "lg:w-[84px]" : "lg:w-72"
        )}
        aria-label={t("nav.main")}
        aria-modal={!desktop && sidebarOpen ? true : undefined}
        role={!desktop && sidebarOpen ? "dialog" : undefined}
      >
        <div className="flex h-full flex-col">
          <div
            className={classNames(
              "flex items-center gap-3 pb-5 pt-6",
              collapsed ? "px-6 lg:justify-center lg:px-0" : "px-6"
            )}
          >
            <Logo />
            <div className={classNames("min-w-0 flex-1", collapsed && "lg:hidden")}>
              <p className="text-lg font-bold leading-tight text-slate-900">MediMind</p>
              <p className="truncate text-sm text-slate-600">{t("common.tagline")}</p>
            </div>
            {!desktop && (
              <button type="button" onClick={closeSidebar} className="btn-ghost !min-h-[44px] !px-3" aria-label={t("nav.close")}>
                <span aria-hidden="true">✕</span>
              </button>
            )}
          </div>

          {/* Desktop collapse toggle */}
          {desktop && (
            <div className="hidden px-4 pb-2 lg:block">
              <button
                type="button"
                onClick={() => setCollapsed((value) => !value)}
                className="flex min-h-[40px] w-full items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-700"
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
                  className={classNames("h-4 w-4 shrink-0 transition-transform", collapsed && "rotate-180")}
                  aria-hidden="true"
                >
                  <polyline points="11 17 6 12 11 7" />
                  <polyline points="18 17 13 12 18 7" />
                </svg>
                {!collapsed && <span>{t("nav.collapseSidebar")}</span>}
              </button>
            </div>
          )}

          {isConfigured && (
            <div className="px-4 pb-3">
              <NavLink
                to="/upload"
                onClick={closeSidebar}
                tabIndex={navInteractive ? undefined : -1}
                className={classNames("btn-primary w-full", collapsed && "lg:min-w-0 lg:px-0")}
                title={collapsed ? t("nav.upload") : undefined}
              >
                <UploadIcon className="h-5 w-5 shrink-0" />
                <span className={classNames(collapsed && "lg:hidden")}>{t("nav.upload")}</span>
              </NavLink>
            </div>
          )}

          <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2 scroll-thin" aria-label={t("nav.main")}>
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
                  aria-disabled={disabled}
                  title={collapsed ? t(item.labelKey) : undefined}
                  className={({ isActive }) =>
                    classNames(
                      "group flex min-h-[48px] items-center gap-3 rounded-xl px-3 py-2.5 text-base transition",
                      collapsed && "lg:justify-center lg:px-0",
                      disabled
                        ? "cursor-not-allowed text-slate-400"
                        : isActive
                        ? "bg-brand-50 font-semibold text-brand-800"
                        : "text-slate-700 hover:bg-slate-50 hover:text-slate-950"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span className={classNames("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", item.chip, !isActive && "opacity-90")}>
                        <Icon className="h-[18px] w-[18px]" />
                      </span>
                      <span className={classNames("min-w-0 flex-1 break-words", collapsed && "lg:hidden")}>{t(item.labelKey)}</span>
                      {isActive && <span className="sr-only">({t("nav.currentPage")})</span>}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          <div className={classNames("border-t border-slate-100 p-4", collapsed && "lg:hidden")}>
            <LanguageSelector className="mb-3 hidden lg:block" />
            {isConfigured && (
              <>
                <div className="rounded-xl bg-brand-50 p-4 ring-1 ring-brand-200">
                  <p className="text-sm font-semibold text-brand-900">{t("nav.privateTitle")}</p>
                  <p className="mt-1 text-xs leading-relaxed text-brand-900">{t("nav.privateBody")}</p>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => void createNewWorkspace()}
                    className="min-h-[44px] rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
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
                    className="min-h-[44px] rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    {t("nav.resetData")}
                  </button>
                </div>
              </>
            )}
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

      <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 bg-slate-50">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Logo({ small }: { small?: boolean }) {
  return (
    <div aria-hidden="true" className={classNames("flex shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm", small ? "h-8 w-8" : "h-10 w-10")}>
      <span className={classNames("font-black tracking-tight", small ? "text-sm" : "text-[18px]")}>M</span>
    </div>
  );
}
