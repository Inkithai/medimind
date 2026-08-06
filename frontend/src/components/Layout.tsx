import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { classNames } from "../utils/format";
import {
  ChartIcon,
  ChatIcon,
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
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: TimelineIcon, description: "Patient record" },
  { to: "/upload", label: "Upload & Extract", icon: UploadIcon, description: "ML extraction" },
  { to: "/cross-check", label: "Safety Cross-Check", icon: ShieldIcon, description: "Interactions" },
  { to: "/lab-trends", label: "Lab Trends", icon: ChartIcon, description: "Trend tracking" },
  { to: "/qa", label: "Ask (single Q&A)", icon: ChatIcon, description: "One-off RAG" },
  { to: "/sessions", label: "Conversations", icon: SparkleIcon, description: "Multi-turn" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, description: "API connection" },
];

export function Layout() {
  const { isConfigured, credentials, clearCredentials } = useAuth();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleSignOut = () => {
    clearCredentials();
    navigate("/settings");
  };

  return (
    <div className="min-h-full lg:flex">
      {/* Mobile header */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
        <div className="flex items-center gap-2">
          <Logo />
          <span className="font-semibold text-slate-900">Nalam</span>
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
            <div>
              <p className="text-lg font-bold leading-tight text-slate-900">Nalam</p>
              <p className="text-xs text-slate-500">Medical Records Intelligence</p>
            </div>
          </div>

          <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4 scroll-thin">
            {NAV.map((item) => {
              const Icon = item.icon;
              const disabled = item.to !== "/settings" && !isConfigured;
              return (
                <NavLink
                  key={item.to}
                  to={disabled ? "#" : item.to}
                  onClick={() => setSidebarOpen(false)}
                  className={({ isActive }) =>
                    classNames(
                      "group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition",
                      disabled
                        ? "cursor-not-allowed text-slate-300"
                        : isActive
                        ? "bg-brand-50 font-semibold text-brand-700"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                    )
                  }
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <div className="min-w-0">
                    <p className="truncate">{item.label}</p>
                    <p className="truncate text-xs text-slate-400 group-hover:text-slate-500">
                      {item.description}
                    </p>
                  </div>
                </NavLink>
              );
            })}
          </nav>

          {isConfigured && (
            <div className="border-t border-slate-100 p-4">
              <div className="rounded-lg bg-slate-50 px-3 py-2.5">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  Connected as
                </p>
                <p className="mt-0.5 truncate text-sm font-medium text-slate-700" title={credentials.userId}>
                  {credentials.userId}
                </p>
                <button
                  onClick={handleSignOut}
                  className="mt-2 text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline"
                >
                  Clear credentials
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
        />
      )}

      {/* Main content */}
      <main className="min-w-0 flex-1 bg-slate-50">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8 lg:py-10">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Logo() {
  return (
    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} className="h-6 w-6">
        <path d="M12 2v20M2 12h20" strokeLinecap="round" />
      </svg>
    </div>
  );
}
