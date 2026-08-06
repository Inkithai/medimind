import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CrossCheckView } from "../components/CrossCheckView";
import { ErrorState } from "../components/ErrorState";
import { LabTrendsView } from "../components/LabTrendsView";
import { Card, CardBody } from "../components/Card";
import { LoadingState } from "../components/Spinner";
import { TimelineView } from "../components/TimelineView";
import { StatusBadge } from "../components/StatusBadge";
import {
  BeakerIcon,
  ChartIcon,
  PillIcon,
  RefreshIcon,
  ShieldIcon,
  UploadIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type {
  CrossCheckReport,
  LabTrendsReport,
  Timeline,
} from "../types/api";

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
      // These three endpoints share the same 404 semantics (no record for
      // this user yet). Fire them in parallel; if timeline 404s, there's
      // no record at all.
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
          label="Loading patient record"
          description="Fetching timeline, safety report, and lab trends from the backend."
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
              <div className="flex flex-col items-center gap-4 py-10 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
                  <UploadIcon className="h-7 w-7" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">
                    No medical record yet
                  </h2>
                  <p className="mt-1 max-w-md text-sm text-slate-500">
                    Upload your first prescription, lab report, or discharge
                    summary. The backend extracts structured data, builds a
                    timeline, runs safety cross-checking, and indexes the
                    record for Q&amp;A.
                  </p>
                </div>
                <Link
                  to="/upload"
                  className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
                >
                  <UploadIcon className="h-4 w-4" />
                  Upload a document
                </Link>
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

  return (
    <div className="space-y-6">
      <PageHeader onReload={() => setReloadKey((k) => k + 1)} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={<PillIcon className="h-5 w-5" />}
          label="Medications"
          value={medCount}
          tone="brand"
        />
        <StatCard
          icon={<BeakerIcon className="h-5 w-5" />}
          label="Lab results"
          value={labCount}
          tone="info"
        />
        <StatCard
          icon={<ShieldIcon className="h-5 w-5" />}
          label="Safety issues"
          value={issueCount}
          tone={issueCount > 0 ? "danger" : "success"}
        />
        <StatCard
          icon={<ChartIcon className="h-5 w-5" />}
          label="Lab trends"
          value={trendsCount}
          tone={trendsCount > 0 ? "warning" : "neutral"}
        />
      </div>

      {allergyCount > 0 && (
        <Card>
          <CardBody>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Known allergies
            </p>
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

      <TimelineView timeline={record.timeline} />
      <CrossCheckView report={record.crossCheck} />
      <LabTrendsView report={record.labTrends} />
    </div>
  );
}

function PageHeader({ onReload, reloading }: { onReload: () => void; reloading?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Patient record</h1>
        <p className="mt-1 text-sm text-slate-500">
          Your merged medical timeline, safety report, and lab trends — derived
          from every document you've uploaded.
        </p>
      </div>
      <button
        onClick={onReload}
        disabled={reloading}
        className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50"
      >
        <RefreshIcon className={reloading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        Refresh
      </button>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: "brand" | "info" | "success" | "warning" | "danger" | "neutral";
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
    <Card>
      <CardBody className="flex items-center gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${tones[tone]}`}>
          {icon}
        </div>
        <div>
          <p className="text-2xl font-bold leading-tight text-slate-900">{value}</p>
          <p className="text-xs text-slate-500">{label}</p>
        </div>
      </CardBody>
    </Card>
  );
}
