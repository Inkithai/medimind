import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { classNames } from "../utils/format";
import {
  BeakerIcon,
  ChatIcon,
  FileIcon,
  PillIcon,
  LocationIcon,
  PlusIcon,
  SettingsIcon,
  ShieldIcon,
  TimelineIcon,
  TrashIcon,
  UploadIcon,
} from "./icons";

interface NavItem {
  to: string;
  label: string;
  icon: (p: { className?: string }) => ReactNode;
  // Soft background tint for the icon chip — keeps the nav calm but alive.
  chip: string;
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: TimelineIcon, chip: "bg-brand-50 text-brand-600" },
  { to: "/documents", label: "Medical Records", icon: FileIcon, chip: "bg-sky-50 text-sky-600" },
  { to: "/medicines", label: "Medications", icon: PillIcon, chip: "bg-emerald-50 text-emerald-600" },
  { to: "/labs", label: "Lab Results", icon: BeakerIcon, chip: "bg-violet-50 text-violet-600" },
  { to: "/history", label: "Timeline", icon: TimelineIcon, chip: "bg-sky-50 text-sky-600" },
  { to: "/safety", label: "Safety Alerts", icon: ShieldIcon, chip: "bg-amber-50 text-amber-600" },
  { to: "/ask", label: "Ask AI", icon: ChatIcon, chip: "bg-brand-50 text-brand-600" },
  { to: "/find-care", label: "Find Care", icon: LocationIcon, chip: "bg-rose-50 text-rose-600" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, chip: "bg-slate-100 text-slate-500" },
];

export function Layout() {
  const { isConfigured, credentials, createNewWorkspace, clearCredentials } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [language, setLanguage] = useState(() => localStorage.getItem("medimind-language") || "en");

  useEffect(() => {
    document.documentElement.lang = language;
    localStorage.setItem("medimind-language", language);
  }, [language]);

  useEffect(() => {
    if (!aboutOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAboutOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [aboutOpen]);

  const desktopLabel = sidebarCollapsed ? "lg:sr-only" : "";

  return (
    <div className="min-h-full lg:flex">
      {/* Mobile header remains independent of the desktop sidebar treatment. */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
        <div className="flex items-center gap-2">
          <Logo small />
          <span className="text-lg font-bold text-slate-900">MediMind</span>
        </div>
        <button
          onClick={() => setSidebarOpen((v) => !v)}
          className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100"
          aria-label="Toggle navigation menu"
          aria-expanded={sidebarOpen}
        >
          <MenuIcon className="h-6 w-6" />
        </button>
      </div>

      {/* One compact, viewport-height desktop sidebar; no internal scrollbar. */}
      <aside
        className={classNames(
          "fixed inset-y-0 left-0 z-30 h-dvh w-72 transform border-r border-slate-200 bg-white transition-[transform,width] duration-200 lg:sticky lg:top-0 lg:translate-x-0",
          sidebarCollapsed ? "lg:w-[76px]" : "lg:w-64",
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Main navigation"
      >
        <div className="flex h-full min-h-0 flex-col">
          <header className={classNames("flex h-14 shrink-0 items-center gap-3 px-4", sidebarCollapsed && "lg:justify-center lg:px-2")}>
            <Logo />
            <div className={classNames("min-w-0 flex-1", desktopLabel)}>
              <p className="text-base font-bold leading-tight text-slate-900">MediMind</p>
              <p className="truncate text-xs text-slate-500">Your health, in one place</p>
            </div>
          </header>

          <div className={classNames("shrink-0 px-3 pb-1", sidebarCollapsed && "lg:px-2")}>
            <button
              type="button"
              onClick={() => setSidebarCollapsed((value) => !value)}
              className={classNames(
                "group flex h-8 w-full items-center gap-2 rounded-lg px-2 text-xs font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-800",
                sidebarCollapsed && "lg:justify-center lg:px-0"
              )}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!sidebarCollapsed}
              title={sidebarCollapsed ? "Expand sidebar" : undefined}
            >
              <CollapseIcon className={classNames("h-4 w-4 shrink-0 transition-transform", sidebarCollapsed && "lg:rotate-180")} />
              <span className={desktopLabel}>Collapse sidebar</span>
            </button>
          </div>

          {isConfigured && (
            <div className={classNames("shrink-0 px-3 pb-2", sidebarCollapsed && "lg:px-2")}>
              <NavLink
                to="/upload"
                onClick={() => setSidebarOpen(false)}
                className={classNames(
                  "flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-brand-600 px-3 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
                  sidebarCollapsed && "lg:px-0"
                )}
                title={sidebarCollapsed ? "Upload Document" : undefined}
              >
                <UploadIcon className="h-[18px] w-[18px] shrink-0" />
                <span className={desktopLabel}>Upload Document</span>
              </NavLink>
            </div>
          )}

          <nav className={classNames("min-h-0 flex-1 space-y-0.5 px-3 py-1", sidebarCollapsed && "lg:px-2")} aria-label="Health workspace">
            {NAV.map((item) => {
              const Icon = item.icon;
              const worksWithoutWorkspace = item.to === "/settings";
              const disabled = !worksWithoutWorkspace && !isConfigured;
              return (
                <NavLink
                  key={item.to}
                  to={disabled ? "#" : item.to}
                  onClick={(event) => {
                    if (disabled) {
                      event.preventDefault();
                      return;
                    }
                    setSidebarOpen(false);
                  }}
                  aria-disabled={disabled}
                  title={sidebarCollapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    classNames(
                      "group flex h-9 items-center gap-2.5 rounded-lg px-2 text-sm transition",
                      sidebarCollapsed && "lg:justify-center lg:px-0",
                      disabled
                        ? "pointer-events-none cursor-not-allowed text-slate-300"
                        : isActive
                        ? "bg-brand-50 font-semibold text-brand-700 ring-1 ring-inset ring-brand-100"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span
                        className={classNames(
                          "flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition",
                          item.chip,
                          !isActive && "opacity-80 group-hover:opacity-100"
                        )}
                      >
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className={classNames("truncate", desktopLabel)}>{item.label}</span>
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          <div className={classNames("shrink-0 border-t border-slate-100 px-3 py-1", sidebarCollapsed && "lg:px-2")}>
            <button
              type="button"
              onClick={() => setAboutOpen(true)}
              className={classNames(
                "flex h-9 w-full items-center gap-2.5 rounded-lg px-2 text-sm font-medium text-slate-500 transition hover:bg-slate-50 hover:text-slate-800",
                sidebarCollapsed && "lg:justify-center lg:px-0"
              )}
              title={sidebarCollapsed ? "About MediMind" : undefined}
            >
              <InfoIcon className="h-4 w-4 shrink-0" />
              <span className={desktopLabel}>About MediMind</span>
            </button>
          </div>

          {isConfigured && (
            <section
              className={classNames("shrink-0 border-t border-slate-100 px-3 py-2", sidebarCollapsed && "lg:px-2")}
              aria-label="Language, privacy and workspace controls"
            >
              <div className={classNames("flex items-center gap-2", sidebarCollapsed && "lg:justify-center")}>
                <label htmlFor="sidebar-language" className={classNames("shrink-0 text-xs font-semibold text-slate-600", desktopLabel)}>
                  Language
                </label>
                <select
                  id="sidebar-language"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                  className={classNames(
                    "h-9 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-700 outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100",
                    sidebarCollapsed && "lg:w-11 lg:flex-none lg:px-1 lg:text-[10px]"
                  )}
                  aria-label="Language"
                  title={sidebarCollapsed ? "Language: English" : undefined}
                >
                  <option value="en">English</option>
                </select>
              </div>

              <div
                className={classNames(
                  "mt-1.5 rounded-lg bg-brand-50 px-2.5 py-2 ring-1 ring-inset ring-brand-100",
                  sidebarCollapsed && "lg:flex lg:h-9 lg:items-center lg:justify-center lg:p-0"
                )}
                title={sidebarCollapsed ? "Private — no account needed. Your records are tied to this browser only. Nothing to sign up for." : undefined}
              >
                <ShieldIcon className={classNames("hidden h-4 w-4 text-brand-700", sidebarCollapsed && "lg:block")} />
                <div className={desktopLabel}>
                  <p className="text-xs font-semibold leading-4 text-brand-900">Private — no account needed</p>
                  <p className="text-[11px] leading-4 text-brand-800/80">
                    Your records are tied to this browser only. Nothing to sign up for.
                  </p>
                </div>
              </div>

              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                <button
                  type="button"
                  onClick={() => void createNewWorkspace()}
                  className="flex h-9 items-center justify-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                  title={`Start a fresh workspace (current: ${credentials.userId})`}
                >
                  <PlusIcon className={classNames("hidden h-4 w-4 shrink-0", sidebarCollapsed && "lg:block")} />
                  <span className={desktopLabel}>New workspace</span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    clearCredentials();
                    navigate("/");
                  }}
                  className="flex h-9 items-center justify-center gap-1 rounded-lg border border-slate-200 bg-white px-1.5 text-xs font-medium text-slate-600 transition hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                  title={sidebarCollapsed ? "Reset data" : undefined}
                >
                  <TrashIcon className={classNames("hidden h-4 w-4 shrink-0", sidebarCollapsed && "lg:block")} />
                  <span className={desktopLabel}>Reset data</span>
                </button>
              </div>
            </section>
          )}
        </div>
      </aside>

      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-slate-900/30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      <main className="min-w-0 flex-1 overflow-x-hidden bg-slate-50">
        <div className="app-content mx-auto min-w-0 max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </div>
      </main>

      {aboutOpen && (
        <div
          className="fixed inset-0 z-50 flex overflow-y-auto overscroll-contain bg-slate-900/30 p-4 sm:items-center sm:justify-center"
          role="presentation"
          onMouseDown={() => setAboutOpen(false)}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="about-title"
            className="my-auto max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto overscroll-contain rounded-2xl border border-slate-200 bg-white p-5 shadow-xl sm:p-6"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start gap-3">
              <Logo />
              <div className="min-w-0 flex-1">
                <h2 id="about-title" className="text-lg font-bold text-slate-900">About MediMind</h2>
                <p className="mt-1 text-sm leading-6 text-slate-600">
                  MediMind helps you organize medical documents, understand health records, and find information from your private workspace.
                </p>
              </div>
              <button type="button" autoFocus onClick={() => setAboutOpen(false)} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100" aria-label="Close About MediMind">
                <span aria-hidden="true" className="text-xl leading-none">×</span>
              </button>
            </div>
            <p className="mt-4 rounded-lg bg-brand-50 px-3 py-2 text-xs leading-5 text-brand-900">
              Your records are tied to this browser only. MediMind is an informational tool and does not replace professional medical advice.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}

function Logo({ small }: { small?: boolean }) {
  return (
    <div
      className={classNames(
        "flex shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm",
        small ? "h-8 w-8" : "h-9 w-9"
      )}
      aria-hidden="true"
    >
      <span className={classNames("font-black tracking-tight", small ? "text-sm" : "text-base")}>M</span>
    </div>
  );
}

function MenuIcon({ className }: { className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={className} aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>;
}

function CollapseIcon({ className }: { className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className={className} aria-hidden="true"><path d="M9 4 4 9l5 5M4 9h10a6 6 0 0 1 6 6v5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function InfoIcon({ className }: { className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className={className} aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5h.01" strokeLinecap="round" /></svg>;
}
