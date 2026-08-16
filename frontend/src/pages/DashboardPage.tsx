import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import {
  AppointmentIcon,
  BeakerIcon,
  PillIcon,
  ShieldIcon,
  UploadIcon,
  FileIcon,
  ChatIcon,
  ChangesIcon,
  IntegrityIcon,
  ReminderIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { CrossCheckReport, LabTrendsReport, Timeline } from "../types/api";
import { formatDate, documentTypeLabel, relativeTime } from "../utils/format";

interface RecordState {
  timeline: Timeline;
  crossCheck: CrossCheckReport;
  labTrends: LabTrendsReport;
  rebuiltFromDocuments: boolean;
}

export function DashboardPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [record, setRecord] = useState<RecordState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Single snapshot request instead of three parallel calls to
      // /timeline + /cross-check + /lab-trends (they all live in one
      // patient_snapshots row anyway — one round-trip, one failure mode,
      // and no repeated 404s while the record is still being built).
      const snapshot = await api.getPatientSnapshot(credentials);
      setRecord({
        timeline: snapshot.patient_timeline,
        crossCheck: snapshot.cross_check_report,
        labTrends: snapshot.lab_trends,
        // The server rebuilds this from the saved documents when the cached
        // snapshot row is gone, so a backend restart never empties the
        // dashboard — it just means the safety check is pending.
        rebuiltFromDocuments: snapshot.rebuilt_from_documents === true,
      });
    } catch (err) {
      setRecord(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  // StrictMode-safe: runs once per mount even in React 18 dev StrictMode
  // (which would otherwise fire load() twice → duplicate GETs + Supabase queries).
  useStrictEffect(() => {
    void load();
  }, [load, reloadKey]);

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader onReload={() => setReloadKey((k) => k + 1)} reloading />
        <LoadingState label={t("dashboard.loading")} description={t("dashboard.loadingDescription")} />
      </div>
    );
  }

  if (error || !record) {
    const status =
      error && typeof error === "object" && "status" in error
        ? (error as { status?: number }).status
        : undefined;
    if (status === 404) {
      return (
        <div className="space-y-6">
          <PageHeader onReload={() => setReloadKey((k) => k + 1)} />
          {/* Welcoming first-run empty state */}
          <div className="flex flex-col items-center gap-5 rounded-2xl border border-slate-200 bg-white px-6 py-16 text-center shadow-sm">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
              <UploadIcon className="h-8 w-8" />
            </div>
            <div>
              <h2 className="section-title">{t("dashboard.welcome")}</h2>
              <p className="secondary-text mx-auto mt-2 max-w-md">{t("dashboard.firstUpload")}</p>
            </div>
            <Link to="/upload" className="btn-primary">
              <UploadIcon className="h-5 w-5" />
              Upload Document
            </Link>
            <p className="secondary-text">{t("common.prescription")} • {t("common.labReport")} • {t("common.dischargeSummary")}</p>
          </div>
        </div>
      );
    }
    return (
      <div className="space-y-6">
        <PageHeader onReload={() => setReloadKey((k) => k + 1)} />
        <ErrorState error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      </div>
    );
  }

  const medCount = record.timeline.medications_timeline.length;
  const labCount = record.timeline.lab_results_timeline.length;
  const allergyCount = record.timeline.known_allergies.length;
  const issueCount =
    record.crossCheck.potential_drug_interactions.length +
    record.crossCheck.duplicate_prescriptions.length +
    record.crossCheck.conflicting_dosage_instructions.length +
    record.crossCheck.allergy_conflicts.length;
  const trendsCount = record.labTrends.trends.length;
  const docCount = (record.timeline.documents || record.timeline.visits).length;
  const doctorCount = new Set(
    record.timeline.visits.map((v) => (v.provider_or_doctor || "").trim().toLowerCase()).filter(Boolean)
  ).size;

  // visits are already chronological (oldest first) from the backend.
  // Do not re-sort by raw string — "05 Jan 2026" vs "2024-03-15" is not
  // lexicographic.
  const recentVisits = [...record.timeline.visits].slice(-5).reverse();

  const lastVisit = [...record.timeline.visits]
    .map((v) => v.date)
    .filter((d): d is string => Boolean(d))
    .pop();

  return (
    <div className="space-y-6">
      <PageHeader onReload={() => setReloadKey((k) => k + 1)} />

      {record.rebuiltFromDocuments && (
        <Alert variant="info" title="Restored from your saved records">
          <p className="text-sm">
            Everything below was rebuilt from your stored documents, so nothing was lost. The
            medication safety check refreshes the next time you upload a document.
          </p>
        </Alert>
      )}

      {((record.timeline.trust_summary?.unresolved_conflicts || 0) > 0 ||
        (record.timeline.trust_summary?.quarantined_documents || 0) > 0 ||
        (record.timeline.trust_summary?.quarantined_facts || 0) > 0) && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-900">
          <div>
            <p className="font-semibold">
              {record.timeline.trust_summary?.unresolved_conflicts ? "Conflicting evidence needs review" : "Non-authoritative evidence is excluded"}
            </p>
            <p className="mt-1 text-sm">
              {record.timeline.trust_summary?.unresolved_conflicts || 0} unresolved conflict(s), {record.timeline.trust_summary?.quarantined_documents || 0} source(s), and {record.timeline.trust_summary?.quarantined_facts || 0} fact(s) are excluded from derived views.
            </p>
          </div>
          <Link to="/review" className="btn-secondary">Review sources</Link>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<FileIcon className="h-6 w-6" />}
          label={t("common.documents")}
          value={docCount}
          to="/documents"
          chip="bg-sky-50 text-sky-600"
          sub="Reports, scans & summaries"
        />
        <StatCard
          icon={<PillIcon className="h-6 w-6" />}
          label={t("common.medications")}
          value={medCount}
          to="/medicines"
          chip="bg-emerald-50 text-emerald-600"
          sub="Across all your records"
        />
        <StatCard
          icon={<BeakerIcon className="h-6 w-6" />}
          label={t("common.labResults")}
          value={labCount}
          to="/labs"
          chip="bg-violet-50 text-violet-600"
          sub={trendsCount > 0 ? `${trendsCount} trends spotted` : "Across all your reports"}
        />
        <StatCard
          icon={<ShieldIcon className="h-6 w-6" />}
          label={t("safety.title")}
          value={issueCount}
          to="/safety"
          chip={issueCount > 0 ? "bg-red-50 text-red-600" : "bg-emerald-50 text-emerald-600"}
          sub={issueCount > 0 ? "Worth a look" : "Nothing flagged 🎉"}
        />
      </div>

      {docCount >= 2 && (
        <Link
          to="/changes"
          className="group flex flex-col gap-4 overflow-hidden rounded-2xl border border-indigo-200 bg-gradient-to-r from-indigo-50 via-white to-sky-50 p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md sm:flex-row sm:items-center"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-sm">
            <ChangesIcon className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold uppercase tracking-[0.12em] text-indigo-700">Longitudinal insight</span>
              <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700">NEW</span>
            </div>
            <h2 className="mt-1 text-lg font-bold text-slate-900">What changed between my records?</h2>
            <p className="mt-1 text-sm text-slate-600">
              Compare labs, medication instructions, and allergies with before-and-after source evidence.
            </p>
          </div>
          <span className="shrink-0 text-sm font-semibold text-indigo-700 transition group-hover:translate-x-1">
            Review changes →
          </span>
        </Link>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Link
          to="/appointment-prep"
          className="group flex flex-col gap-4 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm transition hover:border-cyan-300 hover:shadow-md sm:flex-row sm:items-center lg:flex-col lg:items-start"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-cyan-700 text-white shadow-sm">
            <AppointmentIcon className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-cyan-700">Turn insight into action</p>
            <h2 className="mt-1 text-lg font-bold text-slate-900">Prepare for your appointment</h2>
            <p className="mt-1 text-sm text-slate-600">Create a printable handoff and evidence-backed questions.</p>
            <p className="mt-2 text-sm font-semibold text-cyan-800 transition group-hover:translate-x-1">Prepare visit →</p>
          </div>
        </Link>
        <Link
          to="/follow-up"
          className="group flex flex-col gap-4 rounded-2xl border border-fuchsia-200 bg-white p-5 shadow-sm transition hover:border-fuchsia-300 hover:shadow-md sm:flex-row sm:items-center lg:flex-col lg:items-start"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-fuchsia-700 text-white shadow-sm">
            <ReminderIcon className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-fuchsia-700">Keep track</p>
            <h2 className="mt-1 text-lg font-bold text-slate-900">Open your Action Center</h2>
            <p className="mt-1 text-sm text-slate-600">Prioritize findings, choose reminders, and track completion.</p>
            <p className="mt-2 text-sm font-semibold text-fuchsia-800 transition group-hover:translate-x-1">View actions →</p>
          </div>
        </Link>
        <Link
          to="/record-integrity"
          className="group flex flex-col gap-4 rounded-2xl border border-orange-200 bg-white p-5 shadow-sm transition hover:border-orange-300 hover:shadow-md sm:flex-row sm:items-center lg:flex-col lg:items-start"
        >
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-orange-600 text-white shadow-sm">
            <IntegrityIcon className="h-6 w-6" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-orange-700">Trust your clinical memory</p>
            <h2 className="mt-1 text-lg font-bold text-slate-900">Cross-check record integrity</h2>
            <p className="mt-1 text-sm text-slate-600">Find conflicting facts and compare both source documents.</p>
            <p className="mt-2 text-sm font-semibold text-orange-800 transition group-hover:translate-x-1">Run record checks →</p>
          </div>
        </Link>
      </div>

      {allergyCount > 0 && (
        <div className="rounded-2xl border border-red-100 bg-red-50/60 p-5">
          <h2 className="text-sm font-semibold text-red-950"><span aria-hidden="true">⚠️</span> {t("dashboard.knownAllergies")}</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {record.timeline.known_allergies.map((a) => (
              <StatusBadge key={a} tone="danger">
                {a}
              </StatusBadge>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        {/* Recent records */}
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="card-title">{t("dashboard.recent")}</h2>
            <Link to="/history" className="text-sm font-medium text-brand-600 hover:text-brand-700">
              {t("dashboard.viewTimeline")} →
            </Link>
          </div>
          <div className="mt-4 space-y-2">
            {recentVisits.length === 0 ? (
              <p className="secondary-text">{t("dashboard.noRecords")}</p>
            ) : (
              recentVisits.map((v, i) => (
                <Link
                  key={i}
                  to="/documents"
                  className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 px-4 py-3 transition hover:border-brand-200 hover:bg-slate-50"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="text-xl" aria-hidden="true">
                      {v.document_type === "lab_report" ? "🧪" : v.document_type === "prescription" ? "💊" : "📄"}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-base font-medium text-slate-800">
                        {documentTypeLabel(v.document_type)}
                        {v.provider_or_doctor ? ` · ${v.provider_or_doctor}` : ""}
                      </p>
                      <p className="secondary-text truncate">{v._source.file}</p>
                    </div>
                  </div>
                  <span className="secondary-text shrink-0">{formatDate(v.date)}</span>
                </Link>
              ))
            )}
          </div>

          {lastVisit && (
            <p className="secondary-text mt-4">
              Last recorded visit: <strong className="text-slate-700">{relativeTime(lastVisit)}</strong>
              {doctorCount > 0 && ` · ${doctorCount} ${doctorCount === 1 ? "doctor" : "doctors"} seen across your records`}
            </p>
          )}
        </section>

        {/* Safety + Ask AI */}
        <div className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="card-title">{t("safety.title")}</h2>
              <Link to="/safety" className="text-sm font-medium text-brand-600 hover:text-brand-700">
                View all →
              </Link>
            </div>
            {issueCount === 0 ? (
              (record.timeline.trust_summary?.unresolved_conflicts || 0) > 0 ? (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-base text-amber-800">
                  Safety results are withheld until conflicting sources are reviewed.
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-base text-emerald-800">
                  ✅ Nothing to worry about — no interactions, duplicates, or allergy conflicts found in your medicines.
                </div>
              )
            ) : (
              <div className="mt-4 space-y-2">
                {[
                  ...record.crossCheck.allergy_conflicts.map((i) => ({
                    severity: "high",
                    title: `Allergy: ${i.medication} ↔ ${i.allergy}`,
                    desc: i.explanation,
                  })),
                  ...record.crossCheck.potential_drug_interactions.map((i) => ({
                    severity: i.severity,
                    title: i.medications_involved.join(" + "),
                    desc: i.explanation,
                  })),
                  ...record.crossCheck.conflicting_dosage_instructions.map((i) => ({
                    severity: "moderate",
                    title: `Dosage conflict: ${i.medication}`,
                    desc: i.explanation,
                  })),
                  ...record.crossCheck.duplicate_prescriptions.map((i) => ({
                    severity: "low",
                    title: `Duplicate: ${i.medication}`,
                    desc: i.explanation,
                  })),
                ]
                  .slice(0, 3)
                  .map((item, idx) => (
                    <div key={idx} className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3">
                      <div className="flex items-center gap-2">
                        <StatusBadge
                          tone={item.severity === "high" ? "danger" : item.severity === "moderate" ? "warning" : "info"}
                        >
                          {item.severity}
                        </StatusBadge>
                        <p className="text-base font-medium text-slate-800">{item.title}</p>
                      </div>
                      <p className="secondary-text mt-1 line-clamp-2">{item.desc}</p>
                    </div>
                  ))}
                {issueCount > 3 && (
                  <p className="secondary-text">+ {issueCount - 3} more — see the full Safety Alerts page.</p>
                )}
              </div>
            )}
          </section>

          {/* Ask AI nudge */}
          <section className="rounded-2xl bg-gradient-to-br from-brand-600 to-brand-800 p-6 text-white shadow-sm">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/15">
                <ChatIcon className="h-6 w-6" />
              </div>
              <h2 className="card-title text-white">{t("ask.title")}</h2>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-brand-100">
              “Has my glucose changed over time?” — MediMind routes the question to matching evidence,
              checks whether enough dated results exist, and cites each source.
            </p>
            <Link
              to="/ask"
              className="btn mt-4 bg-white text-brand-700 hover:bg-brand-50"
            >
              Ask AI 🤖
            </Link>
          </section>
        </div>
      </div>
    </div>
  );
}

function PageHeader({ onReload, reloading }: { onReload: () => void; reloading?: boolean }) {
  const { t } = useI18n();
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="page-title">{t("dashboard.title")}</h1>
        <p className="secondary-text mt-2 max-w-2xl">{t("dashboard.subtitle")}</p>
      </div>
      <div className="flex gap-2">
        <Link to="/upload" className="btn-primary">
          <UploadIcon className="h-5 w-5" /> {t("nav.upload")}
        </Link>
        <button
          onClick={onReload}
          disabled={reloading}
          className="btn-secondary"
          aria-label={t("common.refresh")}
        >
          <span aria-hidden="true">↻</span> {t("common.refresh")}
        </button>
      </div>
    </header>
  );
}

function StatCard({
  icon,
  label,
  value,
  to,
  chip,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  to: string;
  chip: string;
  sub?: string;
}) {
  const { formatNumber } = useI18n();
  return (
    <Link
      to={to}
      aria-label={`${label}: ${formatNumber(value)}`}
      className="group rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className={`flex h-11 w-11 items-center justify-center rounded-xl transition group-hover:scale-105 ${chip}`}>
        {icon}
      </div>
      <p className="mt-3 text-3xl font-bold leading-tight text-slate-900">{formatNumber(value)}</p>
      <p className="mt-0.5 text-base font-semibold text-slate-700">{label}</p>
      {sub && <p className="secondary-text mt-0.5 truncate">{sub}</p>}
    </Link>
  );
}
