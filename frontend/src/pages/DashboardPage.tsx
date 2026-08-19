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
  TimelineIcon,
  ChangesIcon,
  ReminderIcon,
  StethoscopeIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type {
  CrossCheckReport,
  DosageReport,
  LabTrendsReport,
  PatientProfileSummary,
  Timeline,
} from "../types/api";
import { formatDate, documentTypeLabel, relativeTime } from "../utils/format";
import { collectSafetyAlerts } from "../utils/safety";

interface RecordState {
  timeline: Timeline;
  crossCheck: CrossCheckReport;
  labTrends: LabTrendsReport;
  dosageReport: DosageReport | null;
  profile: PatientProfileSummary | null;
  updatedAt: string | null;
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
        dosageReport: snapshot.dosage_report || null,
        profile: snapshot.patient_profile || null,
        updatedAt: snapshot.updated_at,
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
        <LoadingState
          label={t("dashboard.loading")}
          description={t("dashboard.loadingDescription")}
        />
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
            <p className="secondary-text">
              {t("common.prescription")} • {t("common.labReport")} • {t("common.dischargeSummary")}
            </p>
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
  const clinicalEventCount =
    (record.timeline.diagnoses_timeline?.length || 0) +
    (record.timeline.symptoms_timeline?.length || 0) +
    (record.timeline.procedures_timeline?.length || 0) +
    (record.timeline.vital_signs_timeline?.length || 0) +
    (record.timeline.imaging_results_timeline?.length || 0);
  const deduplicatedAllergies = deduplicateAllergies(record.timeline.known_allergies);
  const allergyCount = deduplicatedAllergies.length;
  const safetyAlerts = collectSafetyAlerts(record.crossCheck, record.dosageReport);
  const issueCount = safetyAlerts.length;
  const trendsCount = record.labTrends.trends.length;
  const docCount = (record.timeline.documents || record.timeline.visits).length;
  const doctorCount = new Set(
    record.timeline.visits
      .map((v) => (v.provider_or_doctor || "").trim().toLowerCase())
      .filter(Boolean),
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
      <PageHeader
        onReload={() => setReloadKey((k) => k + 1)}
        patientName={
          record.profile?.preferred_name ||
          record.profile?.legal_name ||
          firstPatientName(record.timeline)
        }
        lastVisit={lastVisit}
        doctorCount={doctorCount}
        docCount={docCount}
        updatedAt={record.updatedAt}
      />

      {allergyCount > 0 && (
        <section
          aria-labelledby="dashboard-allergies"
          className="rounded-2xl border border-red-200 bg-red-50 p-5 shadow-sm"
        >
          <h2 id="dashboard-allergies" className="text-sm font-bold text-red-950">
            <span aria-hidden="true">⚠️</span> {t("dashboard.knownAllergies")}
          </h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {deduplicatedAllergies.map((allergy) => (
              <StatusBadge key={allergy.key} tone="danger">
                {allergy.label}
                {allergy.merged > 1 ? ` · ${allergy.merged} similar entries merged` : ""}
              </StatusBadge>
            ))}
          </div>
          <p className="mt-3 text-xs text-red-800">
            Taken from uploaded records. Confirm the exact allergen and reaction with a healthcare
            professional.
          </p>
        </section>
      )}

      {record.rebuiltFromDocuments && (
        <Alert variant="info" title="Restored from your saved records">
          <p className="text-sm">
            Your record views were rebuilt from stored documents. Medication safety analysis may
            still be pending; open Safety Alerts and run the full safety check before relying on the
            alert count.
          </p>
        </Alert>
      )}

      {((record.timeline.trust_summary?.unresolved_conflicts || 0) > 0 ||
        (record.timeline.trust_summary?.quarantined_documents || 0) > 0 ||
        (record.timeline.trust_summary?.quarantined_facts || 0) > 0) && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-900">
          <div>
            <p className="font-semibold">
              {record.timeline.trust_summary?.unresolved_conflicts
                ? "Conflicting evidence needs review"
                : "Non-authoritative evidence is excluded"}
            </p>
            <p className="mt-1 text-sm">
              {record.timeline.trust_summary?.unresolved_conflicts || 0} unresolved conflict(s),{" "}
              {record.timeline.trust_summary?.quarantined_documents || 0} source(s), and{" "}
              {record.timeline.trust_summary?.quarantined_facts || 0} fact(s) are excluded from
              derived views.
            </p>
          </div>
          <Link to="/record-integrity?tab=conflicts" className="btn-secondary">
            Review sources
          </Link>
        </div>
      )}

      <section aria-labelledby="records-glance-title" className="space-y-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-brand-700">
              Your records
            </p>
            <h2 id="records-glance-title" className="section-title">
              At a glance
            </h2>
          </div>
          <span className="text-xs text-slate-500">Select a card to open its detailed view</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <StatCard
            icon={<FileIcon className="h-6 w-6" />}
            label={t("common.documents")}
            value={docCount}
            to="/documents"
            chip="bg-sky-50 text-sky-600"
            sub="Reports, scans & summaries"
          />
          <StatCard
            icon={<TimelineIcon className="h-6 w-6" />}
            label="Clinical Events"
            value={clinicalEventCount}
            to="/history"
            chip="bg-indigo-50 text-indigo-600"
            sub="Diagnoses, symptoms & more"
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
            sub={
              record.rebuiltFromDocuments
                ? "Safety analysis pending"
                : issueCount > 0
                  ? `${issueCount} active finding${issueCount === 1 ? "" : "s"} to review`
                  : "No active findings detected"
            }
          />
        </div>
      </section>

      {docCount >= 2 && (
        <section aria-labelledby="dashboard-insights-title" className="space-y-3">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.12em] text-indigo-700">
              Insights & analysis
            </p>
            <h2 id="dashboard-insights-title" className="section-title">
              What MediMind found
            </h2>
          </div>
          <Link
            to="/changes"
            className="group flex flex-col gap-4 overflow-hidden rounded-2xl border border-indigo-200 bg-gradient-to-r from-indigo-50 via-white to-sky-50 p-5 shadow-sm transition hover:border-indigo-300 hover:shadow-md sm:flex-row sm:items-center"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-sm">
              <ChangesIcon className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-[0.12em] text-indigo-700">
                  Longitudinal insight
                </span>
                <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-bold text-indigo-700">
                  NEW
                </span>
              </div>
              <h2 className="mt-1 text-lg font-bold text-slate-900">
                What changed between my records?
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                Compare labs, medication instructions, and allergies with before-and-after source
                evidence.
              </p>
            </div>
            <span className="shrink-0 text-sm font-semibold text-indigo-700 transition group-hover:translate-x-1">
              Review changes →
            </span>
          </Link>
        </section>
      )}

      <section aria-labelledby="dashboard-actions-title" className="space-y-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.12em] text-cyan-700">Take action</p>
          <h2 id="dashboard-actions-title" className="section-title">
            Useful next steps
          </h2>
        </div>
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
          <Link
            to="/who-to-see"
            className="group flex flex-col gap-4 rounded-2xl border border-amber-200 bg-white p-5 shadow-sm transition hover:border-amber-300 hover:shadow-md sm:flex-row sm:items-center lg:flex-col lg:items-start"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-amber-700 text-white shadow-sm">
              <StethoscopeIcon className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-amber-800">Decide</p>
              <h2 className="mt-1 text-lg font-bold text-slate-900">Who should I talk to?</h2>
              <p className="mt-1 text-sm text-slate-600">
                See whether a pharmacist or a doctor should look at what was found, and how soon.
              </p>
              <p className="mt-2 text-sm font-semibold text-amber-800 transition group-hover:translate-x-1">
                See the suggestion →
              </p>
            </div>
          </Link>
          <Link
            to="/appointment-prep"
            className="group flex flex-col gap-4 rounded-2xl border border-cyan-200 bg-white p-5 shadow-sm transition hover:border-cyan-300 hover:shadow-md sm:flex-row sm:items-center lg:flex-col lg:items-start"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-cyan-700 text-white shadow-sm">
              <AppointmentIcon className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-cyan-700">Prepare</p>
              <h2 className="mt-1 text-lg font-bold text-slate-900">
                Prepare for your appointment
              </h2>
              <p className="mt-1 text-sm text-slate-600">
                Create a printable handoff and evidence-backed questions.
              </p>
              <p className="mt-2 text-sm font-semibold text-cyan-800 transition group-hover:translate-x-1">
                Prepare visit →
              </p>
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
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-fuchsia-700">
                Track
              </p>
              <h2 className="mt-1 text-lg font-bold text-slate-900">Open your Action Center</h2>
              <p className="mt-1 text-sm text-slate-600">
                Prioritize findings, choose reminders, and track completion.
              </p>
              <p className="mt-2 text-sm font-semibold text-fuchsia-800 transition group-hover:translate-x-1">
                View actions →
              </p>
            </div>
          </Link>
          <Link
            to="/ask"
            className="group flex flex-col gap-4 rounded-2xl border border-brand-200 bg-white p-5 shadow-sm transition hover:border-brand-300 hover:shadow-md sm:flex-row sm:items-center lg:flex-col lg:items-start"
          >
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-700 text-white shadow-sm">
              <ChatIcon className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-bold uppercase tracking-[0.12em] text-brand-700">Ask</p>
              <h2 className="mt-1 text-lg font-bold text-slate-900">Ask about your records</h2>
              <p className="mt-1 text-sm text-slate-600">
                Get an evidence-linked answer grounded in uploaded documents.
              </p>
              <p className="mt-2 text-sm font-semibold text-brand-800 transition group-hover:translate-x-1">
                Ask AI →
              </p>
            </div>
          </Link>
        </div>
      </section>

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
                  to={`/documents?document=${encodeURIComponent(v._document_id)}`}
                  className="flex items-center justify-between gap-3 rounded-xl border border-slate-100 px-4 py-3 transition hover:border-brand-200 hover:bg-slate-50"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="text-xl" aria-hidden="true">
                      {v.document_type === "lab_report"
                        ? "🧪"
                        : v.document_type === "prescription"
                          ? "💊"
                          : "📄"}
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
              Last recorded visit:{" "}
              <strong className="text-slate-700">{relativeTime(lastVisit)}</strong>
              {doctorCount > 0 &&
                ` · ${doctorCount} ${doctorCount === 1 ? "doctor" : "doctors"} seen across your records`}
            </p>
          )}
        </section>

        {/* Safety + Ask AI */}
        <div className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <h2 className="card-title">{t("safety.title")}</h2>
              <Link
                to="/safety"
                className="text-sm font-medium text-brand-600 hover:text-brand-700"
              >
                View all →
              </Link>
            </div>
            {issueCount === 0 ? (
              record.rebuiltFromDocuments ? (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-base text-amber-900">
                  Safety analysis has not been rerun since the dashboard was reconstructed. Open
                  Safety Alerts and run the full safety check.
                </div>
              ) : (record.timeline.trust_summary?.unresolved_conflicts || 0) > 0 ? (
                <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-base text-amber-800">
                  Safety results are withheld until conflicting sources are reviewed.
                </div>
              ) : (
                <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-base text-emerald-800">
                  ✓ No active medication safety findings were detected in the uploaded records by
                  the checks currently available.
                </div>
              )
            ) : (
              <div className="mt-4 space-y-2">
                {safetyAlerts.slice(0, 3).map((item) => (
                  <div
                    key={item.key}
                    className="rounded-xl border border-amber-200 bg-amber-50/60 px-4 py-3"
                  >
                    <div className="flex items-center gap-2">
                      <StatusBadge
                        tone={
                          item.severity === "high"
                            ? "danger"
                            : item.severity === "moderate"
                              ? "warning"
                              : "info"
                        }
                      >
                        {item.severity}
                      </StatusBadge>
                      <p className="text-base font-medium text-slate-800">{item.title}</p>
                    </div>
                    <p className="secondary-text mt-1 line-clamp-2">{item.description}</p>
                  </div>
                ))}
                {issueCount > 3 && (
                  <p className="secondary-text">
                    + {issueCount - 3} more — see the full Safety Alerts page.
                  </p>
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
              “Has my glucose changed over time?” — MediMind routes the question to matching
              evidence, checks whether enough dated results exist, and cites each source.
            </p>
            <Link to="/ask" className="btn mt-4 bg-white text-brand-700 hover:bg-brand-50">
              Ask AI 🤖
            </Link>
          </section>
        </div>
      </div>
    </div>
  );
}

function firstPatientName(timeline: Timeline): string | null {
  const names = timeline.visits
    .map((visit) => visit.patient_name?.trim())
    .filter((name): name is string => Boolean(name));
  if (!names.length) return null;
  const counts = new Map<string, { label: string; count: number }>();
  for (const name of names) {
    const key = name.toLocaleLowerCase();
    const current = counts.get(key);
    counts.set(key, { label: current?.label || name, count: (current?.count || 0) + 1 });
  }
  return [...counts.values()].sort((a, b) => b.count - a.count)[0]?.label || null;
}

function deduplicateAllergies(
  allergies: string[],
): Array<{ key: string; label: string; merged: number }> {
  const groups = new Map<string, { values: string[] }>();
  for (const raw of allergies) {
    const label = raw.trim();
    if (!label) continue;
    const normalized = label
      .toLocaleLowerCase()
      .replace(/[^a-z0-9\s-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    // Most extracted allergy strings begin with the allergen, followed by
    // reaction prose. Group only on that leading allergen phrase; never merge
    // unrelated strings merely because they share reaction words.
    const key = normalized.split(/\s+(?:allergy|causing|caused|reaction|with)\b|\s*-\s*/)[0].trim();
    const safeKey = key || normalized;
    const group = groups.get(safeKey) || { values: [] };
    if (!group.values.some((value) => value.toLocaleLowerCase() === label.toLocaleLowerCase())) {
      group.values.push(label);
    }
    groups.set(safeKey, group);
  }
  return [...groups.entries()].map(([key, group]) => ({
    key,
    // Prefer the most informative source wording instead of fabricating a
    // merged clinical statement.
    label: [...group.values].sort((a, b) => b.length - a.length)[0],
    merged: group.values.length,
  }));
}

function PageHeader({
  onReload,
  reloading,
  patientName,
  lastVisit,
  doctorCount,
  docCount,
  updatedAt,
}: {
  onReload: () => void;
  reloading?: boolean;
  patientName?: string | null;
  lastVisit?: string | null;
  doctorCount?: number;
  docCount?: number;
  updatedAt?: string | null;
}) {
  const { t } = useI18n();
  const safeName = patientName?.trim();
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-brand-700">
          Patient record overview
        </p>
        <h1 className="page-title">
          {safeName ? `${safeName}'s Health Overview` : t("dashboard.title")}
        </h1>
        <p className="secondary-text mt-2 max-w-2xl">{t("dashboard.subtitle")}</p>
        {(lastVisit || docCount || updatedAt) && (
          <p className="mt-2 text-xs text-slate-500">
            {lastVisit
              ? `Last recorded visit: ${formatDate(lastVisit)}`
              : "No dated visit available"}
            {typeof doctorCount === "number" && doctorCount > 0
              ? ` · ${doctorCount} provider${doctorCount === 1 ? "" : "s"}`
              : ""}
            {typeof docCount === "number"
              ? ` · ${docCount} document${docCount === 1 ? "" : "s"}`
              : ""}
            {updatedAt ? ` · Overview refreshed ${relativeTime(updatedAt)}` : ""}
          </p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        <Link to="/upload" className="btn-secondary">
          <UploadIcon className="h-5 w-5" /> {t("nav.upload")}
        </Link>
        <button
          onClick={onReload}
          disabled={reloading}
          className="btn-secondary"
          aria-label="Refresh the dashboard overview from saved analysis"
          title="Fetch the latest saved records and analysis. This does not reprocess documents."
        >
          <span aria-hidden="true">↻</span> {reloading ? "Refreshing…" : "Refresh overview"}
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
      className="group relative rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md focus-visible:ring-2 focus-visible:ring-brand-400"
    >
      <span
        aria-hidden="true"
        className="absolute right-4 top-4 text-lg text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-brand-600"
      >
        →
      </span>
      <div
        className={`flex h-11 w-11 items-center justify-center rounded-xl transition group-hover:scale-105 ${chip}`}
      >
        {icon}
      </div>
      <p className="mt-3 text-3xl font-bold leading-tight text-slate-900">{formatNumber(value)}</p>
      <p className="mt-0.5 text-base font-semibold text-slate-700">{label}</p>
      {sub && <p className="secondary-text mt-0.5 truncate">{sub}</p>}
    </Link>
  );
}
