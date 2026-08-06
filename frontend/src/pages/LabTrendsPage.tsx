import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody } from "../components/Card";
import { LabTrendsView } from "../components/LabTrendsView";
import { LoadingState } from "../components/Spinner";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type { LabTrendsReport } from "../types/api";

export function LabTrendsPage() {
  const { credentials } = useAuth();
  const [report, setReport] = useState<LabTrendsReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getLabTrends(credentials);
      setReport(data);
    } catch (err) {
      setReport(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="page-title">Lab Results</h1>
          <p className="secondary-text mt-2 max-w-2xl">
            How each test result moves over time — and whether it's drifting toward, or past, its
            healthy range.
          </p>
        </div>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshIcon className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {loading && <LoadingState label="Analyzing lab trends" />}

      {!loading && error !== null && (
        <NotFoundOrError
          error={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      )}

      {!loading && report && <LabTrendsView report={report} />}
    </div>
  );
}

function NotFoundOrError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404) {
    return (
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="text-sm font-semibold text-slate-700">
              No lab trends available
            </p>
            <p className="max-w-md text-sm text-slate-500">
              Upload at least two lab reports with parseable values to track
              how results move across visits.
            </p>
            <Link
              to="/upload"
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            >
              <UploadIcon className="h-4 w-4" />
              Upload lab reports
            </Link>
          </div>
        </CardBody>
      </Card>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
