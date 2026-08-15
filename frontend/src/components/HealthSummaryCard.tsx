import { Link } from "react-router-dom";
import type { Timeline } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
import { BeakerIcon, ChatIcon, FileIcon, PillIcon, ShieldIcon, TimelineIcon } from "./icons";
import { classNames } from "../utils/format";

/**
 * "Health Summary" stat grid — Documents / Medicines / Lab Tests / Allergies /
 * Doctors, derived from the merged timeline. Used on Dashboard and Upload so
 * neither page ever shows empty white space.
 */
export function HealthSummaryCard({ timeline }: { timeline: Timeline }) {
  const { t, formatNumber } = useI18n();
  const doctors = new Set(
    timeline.visits
      .map((v) => (v.provider_or_doctor || "").trim().toLowerCase())
      .filter(Boolean)
  ).size;

  const stats = [
    {
      label: t("common.documents"),
      value: timeline.visits.length,
      to: "/documents",
      icon: FileIcon,
      chip: "bg-sky-50 text-sky-600",
    },
    {
      label: t("common.medications"),
      value: timeline.medications_timeline.length,
      to: "/medicines",
      icon: PillIcon,
      chip: "bg-emerald-50 text-emerald-600",
    },
    {
      label: t("common.labResults"),
      value: timeline.lab_results_timeline.length,
      to: "/labs",
      icon: BeakerIcon,
      chip: "bg-violet-50 text-violet-600",
    },
    {
      label: t("common.allergies"),
      value: timeline.known_allergies.length,
      to: "/history",
      icon: ShieldIcon,
      chip:
        timeline.known_allergies.length > 0
          ? "bg-red-50 text-red-600"
          : "bg-slate-100 text-slate-500",
    },
    {
      label: t("care.doctors"),
      value: doctors,
      to: "/history",
      icon: TimelineIcon,
      chip: "bg-brand-50 text-brand-600",
    },
  ];

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="card-title">{t("dashboard.healthSummary")}</h2>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {stats.map((s) => {
          const Icon = s.icon;
          return (
            <Link
              key={s.label}
              to={s.to}
              className="group rounded-xl border border-slate-100 bg-slate-50/60 p-4 transition hover:border-brand-200 hover:bg-white hover:shadow-sm"
            >
              <span
                className={classNames(
                  "flex h-9 w-9 items-center justify-center rounded-lg transition group-hover:scale-105",
                  s.chip
                )}
              >
                <Icon className="h-5 w-5" />
              </span>
              <p className="mt-3 text-2xl font-bold leading-none text-slate-900">{formatNumber(s.value)}</p>
              <p className="mt-1 text-sm font-medium text-slate-600">{s.label}</p>
            </Link>
          );
        })}
        {/* Ask AI tile fills the 6th grid slot with a gentle nudge */}
        <Link
          to="/ask"
          className="group rounded-xl border border-brand-100 bg-brand-50 p-4 transition hover:shadow-sm"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white text-brand-600 ring-1 ring-brand-100 transition group-hover:scale-105">
            <ChatIcon className="h-5 w-5" />
          </span>
          <p className="mt-3 text-sm font-semibold text-brand-900">{t("ask.title")}</p>
          <p className="mt-1 text-xs leading-relaxed text-brand-800/80">
            {t("ask.question")}
          </p>
        </Link>
      </div>
    </div>
  );
}
