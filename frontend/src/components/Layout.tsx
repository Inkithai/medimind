import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { classNames } from "../utils/format";
import {
  BeakerIcon,
  ChatIcon,
  FileIcon,
  PillIcon,
  SettingsIcon,
  ShieldIcon,
  SparkleIcon,
  TimelineIcon,
  UploadIcon,
} from "./icons";

interface NavItem {
  to: string;
  label: string;
  icon: (p: { className?: string }) => ReactNode;
  description: string;
  badge?: string;
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Overview", icon: TimelineIcon, description: "Patient workspace" },
  { to: "/upload", label: "Upload", icon: UploadIcon, description: "Add documents" },
  { to: "/documents", label: "My Documents", icon: FileIcon, description: "PDFs & images" },
  { to: "/history", label: "My History", icon: TimelineIcon, description: "Chronological" },
  { to: "/medicines", label: "My Medicines", icon: PillIcon, description: "Traceable meds" },
  { to: "/labs", label: "Test Results", icon: BeakerIcon, description: "Labs + trends" },
  { to: "/safety", label: "Safety", icon: ShieldIcon, description: "Warnings" },
  { to: "/ask", label: "Ask", icon: ChatIcon, description: "Grounded Q&A" },
  { to: "/conversations", label: "Conversations", icon: SparkleIcon, description: "Multi-turn" },
  { to: "/settings", label: "Workspace", icon: SettingsIcon, description: "Session & API" },
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
          <Logo />
          <span className="font-semibold text-slate-900">MediMind</span>
          <span className="ml-2 rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-medium text-brand-700 ring-1 ring-brand-200">
            anonymous
          </span>
        </div>
        <button
          onClick={() => setSidebarOpen((v) => !v)}
          className="rounded-md p-2 text-slate-600 hover:bg-slate-100"
          aria-label="Toggle navigation"
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
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center gap-3 border-b border-slate-100 px-6 py-5">
            <Logo />
            <div className="min-w-0 flex-1">
              <p className="flex items-center gap-2 text-lg font-bold leading-tight text-slate-900">
                MediMind
                <span className="rounded-full bg-slate-900 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-white">
                  beta
                </span>
              </p>
              <p className="truncate text-xs text-slate-500">Understand your medical docs</p>
            </div>
          </div>

          <div className="px-3 py-3">
            <div className="rounded-xl bg-gradient-to-br from-brand-600 to-brand-800 p-4 text-white shadow-sm">
              <p className="text-xs font-medium uppercase tracking-wide text-brand-100">Anonymous workspace</p>
              <p className="mt-1 text-sm font-semibold">No login required</p>
              <p className="mt-1 text-xs leading-relaxed text-brand-100/90">
                Session stored only in this browser. Clear anytime.
              </p>
            </div>
          </div>

          <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-1 scroll-thin">
            {NAV.map((item) => {
              const Icon = item.icon;
              const isSettings = item.to === "/settings";
              const disabled = !isSettings && !isConfigured;
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
                  className={({ isActive }) =>
                    classNames(
                      "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition",
                      disabled
                        ? "pointer-events-none cursor-not-allowed text-slate-300"
                        : isActive
                        ? "bg-brand-50 font-semibold text-brand-700 ring-1 ring-brand-100"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                    )
                  }
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{item.label}</p>
                    <p className="truncate text-xs text-slate-400 group-hover:text-slate-500">
                      {item.description}
                    </p>
                  </div>
                  {item.badge && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                      {item.badge}
                    </span>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {isConfigured && (
            <div className="border-t border-slate-100 p-4">
              <div className="rounded-xl bg-slate-50 px-3 py-3">
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">
                  Workspace ID
                </p>
                <p className="mt-1 truncate font-mono text-xs font-medium text-slate-700" title={credentials.userId}>
                  {credentials.userId}
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    onClick={() => void createNewWorkspace()}
                    className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-800"
                  >
                    New workspace
                  </button>
                  <button
                    onClick={() => {
                      clearCredentials();
                      navigate("/");
                    }}
                    className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                  >
                    Reset
                  </button>
                </div>
              </div>
              <button
                onClick={() => navigate("/")}
                className="mt-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
              >
                ← Landing page
              </button>
            </div>
          )}
        </div>
      </aside>

      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-slate-900/30 lg:hidden"
          onClick={() => setSidebarOpen(false)}
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

function Logo() {
  return (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
      <span className="text-[18px] font-black tracking-tight">M</span>
    </div>
  );
}
