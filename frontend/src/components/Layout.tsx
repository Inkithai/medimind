import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { classNames } from "../utils/format";
import {
  AppointmentIcon,
  BeakerIcon,
  ChangesIcon,
  ChatIcon,
  FileIcon,
  PillIcon,
  LocationIcon,
  SettingsIcon,
  ShieldIcon,
  TimelineIcon,
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
  { to: "/changes", label: "What Changed?", icon: ChangesIcon, chip: "bg-indigo-50 text-indigo-600" },
  { to: "/appointment-prep", label: "Appointment Prep", icon: AppointmentIcon, chip: "bg-cyan-50 text-cyan-700" },
  { to: "/safety", label: "Safety Alerts", icon: ShieldIcon, chip: "bg-amber-50 text-amber-600" },
  { to: "/ask", label: "Ask AI", icon: ChatIcon, chip: "bg-brand-50 text-brand-600" },
  { to: "/find-care", label: "Find Care", icon: LocationIcon, chip: "bg-rose-50 text-rose-600" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, chip: "bg-slate-100 text-slate-500" },
];

export function Layout() {
  const { isConfigured, credentials, createNewWorkspace, clearCredentials } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-full lg:flex">
      {/* Mobile header */}
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
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-6 w-6">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </div>

      {/* Sidebar */}
      <aside
        className={classNames(
          "fixed inset-y-0 left-0 z-30 w-72 transform border-r border-slate-200 bg-white transition-transform lg:static lg:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        )}
        aria-label="Main navigation"
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center gap-3 px-6 pb-5 pt-6">
            <Logo />
            <div className="min-w-0 flex-1">
              <p className="text-lg font-bold leading-tight text-slate-900">MediMind</p>
              <p className="truncate text-sm text-slate-500">Your health, in one place</p>
            </div>
          </div>

          {isConfigured && (
            <div className="px-4 pb-3">
              <NavLink
                to="/upload"
                onClick={() => setSidebarOpen(false)}
                className="btn-primary w-full"
              >
                <UploadIcon className="h-5 w-5" />
                Upload Document
              </NavLink>
            </div>
          )}

          <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2 scroll-thin">
            {NAV.map((item) => {
              const Icon = item.icon;
              const worksWithoutWorkspace = item.to === "/settings";
              const disabled = !worksWithoutWorkspace && !isConfigured;
              return (
                <NavLink
                  key={item.to}
                  to={disabled ? "#" : item.to}
                  onClick={(e) => {
                    if (disabled) {
                      e.preventDefault();
                      return;
                    }
                    setSidebarOpen(false);
                  }}
                  aria-disabled={disabled}
                  className={({ isActive }) =>
                    classNames(
                      "group flex min-h-[48px] items-center gap-3 rounded-xl px-3 py-2.5 text-base transition",
                      disabled
                        ? "pointer-events-none cursor-not-allowed text-slate-300"
                        : isActive
                        ? "bg-brand-50 font-semibold text-brand-700"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span
                        className={classNames(
                          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition",
                          item.chip,
                          !isActive && "opacity-80 group-hover:opacity-100"
                        )}
                      >
                        <Icon className="h-[18px] w-[18px]" />
                      </span>
                      <span className="truncate">{item.label}</span>
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {isConfigured && (
            <div className="border-t border-slate-100 p-4">
              <div className="rounded-xl bg-brand-50 p-4 ring-1 ring-brand-100">
                <p className="text-sm font-semibold text-brand-900">Private — no account needed</p>
                <p className="mt-1 text-xs leading-relaxed text-brand-800/80">
                  Your records are tied to this browser only. Nothing to sign up for.
                </p>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  onClick={() => void createNewWorkspace()}
                  className="flex min-h-[44px] items-center justify-center rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
                  title={`Start a fresh workspace (current: ${credentials.userId})`}
                >
                  New workspace
                </button>
                <button
                  onClick={() => {
                    clearCredentials();
                    navigate("/");
                  }}
                  className="flex min-h-[44px] items-center justify-center rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
                >
                  Reset data
                </button>
              </div>
            </div>
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

      {/* Main content */}
      <main className="min-w-0 flex-1 bg-slate-50">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Logo({ small }: { small?: boolean }) {
  return (
    <div
      className={classNames(
        "flex items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm",
        small ? "h-8 w-8" : "h-10 w-10"
      )}
    >
      <span className={classNames("font-black tracking-tight", small ? "text-sm" : "text-[18px]")}>M</span>
    </div>
  );
}
