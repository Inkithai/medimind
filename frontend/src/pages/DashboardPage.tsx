import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import {
  BeakerIcon,
  PillIcon,
  ShieldIcon,
  UploadIcon,
  FileIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type { CrossCheckReport, LabTrendsReport, Timeline } from "../types/api";
import { formatDate } from "../utils/format";

interface RecordState {
  timeline: Timeline;
  crossCheck: CrossCheckReport;
  labTrends: LabTrendsReport;
}

export function DashboardPage() {
  const { credentials } = useAuth();
  const [record, setRecord] = useState<RecordState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [timeline, crossCheck, labTrends] = await Promise.all([
        api.getTimeline(credentials),
        api.getCrossCheck(credentials),
        api.getLabTrends(credentials),
      ]);
      setRecord({ timeline, crossCheck, labTrends });
    } catch (err) {
      setRecord(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader onReload={() => setReloadKey((k) => k + 1)} reloading />
        <LoadingState
          label="Loading patient workspace"
          description="Fetching timeline, safety report, and lab trends from MediMind backend."
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
          <Card>
            <CardBody>
              <div className="flex flex-col items-center gap-4 py-12 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
                  <UploadIcon className="h-7 w-7" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">No medical record yet</h2>
                  <p className="mt-1 max-w-md text-sm text-slate-500">
                    Upload your first prescription, lab report, or discharge summary. MediMind extracts structured
                    data, builds a timeline, runs safety cross-checking, and indexes for grounded Q&A.
                  </p>
                </div>
                <div className="flex flex-wrap justify-center gap-3">
                  <Link
                    to="/upload"
                    className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-700"
                  >
                    <UploadIcon className="h-4 w-4" /> Upload documents
                  </Link>
                  <Link
                    to="/"
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    How it works
                  </Link>
                </div>

                <div className="mt-6 grid w-full max-w-2xl gap-3 rounded-xl bg-slate-50 p-4 text-left sm:grid-cols-3">
                  <FlowStep
                    title="Anonymous session"
                    desc="session_id in localStorage, JWT from /anonymous/session"
                  />
                  <FlowStep title="Upload → Pipeline" desc="OCR, extraction, Supabase + Cloudinary, Chroma" />
                  <FlowStep title="Ask & Verify" desc="RAG answers with source file • page citations" />
                </div>
              </div>
            </CardBody>
          </Card>
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
  const docCount = record.timeline.visits.length;

  const recentVisits = [...record.timeline.visits]
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
    .slice(0, 5);

  return (
    <div className="space-y-6">
      <PageHeader onReload={() => setReloadKey((k) => k + 1)} />

      {/* Overview stats per spec */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<FileIcon className="h-5 w-5" />}
          label="Documents"
          value={docCount}
          to="/documents"
          tone="brand"
          sub="Supabase + Cloudinary + Chroma"
        />
        <StatCard
          icon={<PillIcon className="h-5 w-5" />}
          label="Medicines"
          value={medCount}
          to="/medicines"
          tone="brand"
          sub="Traceable to source file"
        />
        <StatCard
          icon={<BeakerIcon className="h-5 w-5" />}
          label="Test Results"
          value={labCount}
          to="/labs"
          tone="info"
          sub={`${trendsCount} trends`}
        />
        <StatCard
          icon={<ShieldIcon className="h-5 w-5" />}
          label="Safety"
          value={issueCount}
          to="/safety"
          tone={issueCount > 0 ? "danger" : "success"}
          sub={issueCount > 0 ? "Needs attention" : "No issues flagged"}
        />
      </div>

      {allergyCount > 0 && (
        <Card>
          <CardBody>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Known allergies</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {record.timeline.known_allergies.map((a) => (
                <StatusBadge key={a} tone="danger">
                  {a}
                </StatusBadge>
              ))}
            </div>
          </CardBody>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardBody>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">Latest Safety Warnings</h3>
              <Link to="/safety" className="text-xs font-medium text-brand-600 hover:text-brand-700">
                View all →
              </Link>
            </div>
            {issueCount === 0 ? (
              <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                No safety issues flagged by cross-check.
              </div>
            ) : (
              <div className="mt-3 space-y-2">
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
                    <div key={idx} className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <StatusBadge tone={item.severity === "high" ? "danger" : item.severity === "moderate" ? "warning" : "info"}>
                          {item.severity}
                        </StatusBadge>
                        <p className="text-sm font-medium text-slate-800">{item.title}</p>
                      </div>
                      <p className="mt-1 line-clamp-2 text-xs text-slate-600">{item.desc}</p>
                    </div>
                  ))}
                {issueCount > 3 && (
                  <p className="text-xs text-slate-500">+ {issueCount - 3} more — view safety page for details.</p>
                )}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">Recent Medical History</h3>
              <Link to="/history" className="text-xs font-medium text-brand-600 hover:text-brand-700">
                View timeline →
              </Link>
            </div>
            <div className="mt-3 space-y-2">
              {recentVisits.length === 0 ? (
                <p className="text-xs text-slate-500">No visits yet.</p>
              ) : (
                recentVisits.map((v, i) => (
                  <Link
                    key={i}
                    to="/documents"
                    className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-3 py-2 hover:bg-slate-50"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm">
                        {v.document_type === "lab_report" ? "🧪" : v.document_type === "prescription" ? "💊" : "🏥"}
                      </span>
                      <div>
                        <p className="text-sm font-medium text-slate-800">
                          {formatDate(v.date)} — {v.document_type.replace("_", " ")}
                        </p>
                        <p className="text-xs text-slate-500">{v._source.file}</p>
                      </div>
                    </div>
                    <span className="text-xs text-slate-400">View →</span>
                  </Link>
                ))
              )}
            </div>

            <div className="mt-5 rounded-lg bg-slate-50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Ask MediMind</p>
              <p className="mt-1 text-xs text-slate-600">
                Grounded Q&A over your indexed timeline. Sources cited with file • page.
              </p>
              <Link
                to="/ask"
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
              >
                Try: “What medications am I currently taking?” →
              </Link>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Processing pipeline</p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <code className="rounded bg-slate-100 px-2 py-1">Upload → /api/v1/documents</code>
          <code className="rounded bg-slate-100 px-2 py-1">OCR / text_layer</code>
          <code className="rounded bg-slate-100 px-2 py-1">Clinical extraction (Groq)</code>
          <code className="rounded bg-slate-100 px-2 py-1">Supabase + Cloudinary</code>
          <code className="rounded bg-slate-100 px-2 py-1">Safety + Lab trends</code>
          <code className="rounded bg-slate-100 px-2 py-1">Chroma RAG chunks</code>
          <code className="rounded bg-slate-100 px-2 py-1">Patient Record</code>
        </div>
      </div>
    </div>
  );
}

function PageHeader({ onReload, reloading }: { onReload: () => void; reloading?: boolean }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
          Patient workspace
          <span className="rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-200">
            Anonymous • MediMind
          </span>
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Your merged medical timeline, safety report, lab trends, and grounded Q&A — derived from every document
          uploaded in this anonymous workspace. Session ID stored only in this browser's localStorage.
        </p>
      </div>
      <div className="flex gap-2">
        <Link
          to="/upload"
          className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
        >
          <UploadIcon className="h-4 w-4" /> Add documents
        </Link>
        <button
          onClick={onReload}
          disabled={reloading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
        >
          ↻ Refresh
        </button>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
  to,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: "brand" | "info" | "success" | "warning" | "danger" | "neutral";
  to: string;
  sub?: string;
}) {
  const tones: Record<string, string> = {
    brand: "bg-brand-50 text-brand-600",
    info: "bg-sky-50 text-sky-600",
    success: "bg-emerald-50 text-emerald-600",
    warning: "bg-amber-50 text-amber-600",
    danger: "bg-red-50 text-red-600",
    neutral: "bg-slate-100 text-slate-600",
  };
  return (
    <Link to={to}>
      <Card className="transition hover:shadow-md">
        <CardBody className="flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${tones[tone]}`}>{icon}</div>
          <div className="min-w-0 flex-1">
            <p className="text-2xl font-bold leading-tight text-slate-900">{value}</p>
            <p className="text-xs font-medium text-slate-700">{label}</p>
            {sub && <p className="truncate text-[11px] text-slate-500">{sub}</p>}
          </div>
        </CardBody>
      </Card>
    </Link>
  );
}

function FlowStep({ title, desc }: { title: string; desc: string }) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-800">{title}</p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{desc}</p>
    </div>
  );
}
