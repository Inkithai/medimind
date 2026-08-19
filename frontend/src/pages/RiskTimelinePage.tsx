import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { LoadingState } from "../components/Spinner";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { RiskTimelineView } from "../components/RiskTimelineView";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { RiskTimelineReport } from "../types/api";
import type { EmbeddedPageProps } from "../components/TabBar";

export function RiskTimelinePage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const [report, setReport] = useState<RiskTimelineReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getRiskTimeline(credentials);
      setReport(data);
    } catch (err) {
      setReport(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load, reloadKey]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        {embedded ? (
          <div />
        ) : (
          <div>
            <h1 className="page-title">Risk Timeline</h1>
            <p className="secondary-text mt-2 max-w-2xl">
              When was each safety finding actually live? Two medicines only interact if they were
              taken at the same time — findings whose courses never overlapped are shown as history,
              not current risk.
            </p>
          </div>
        )}
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshIcon className="h-4 w-4" />
          Refresh
        </button>
      </div>

      {loading && <LoadingState label="Placing your safety findings in time" />}

      {!loading && error !== null && (
        <NotFoundOrError error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && report && (
        <>
          <RiskTimelineView report={report} />
          <MedicalDisclaimer />
        </>
      )}
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
            <p className="text-sm text-slate-600">
              No records yet — upload a document and MediMind will place every safety finding on a
              timeline.
            </p>
            <Link
              to="/upload"
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            >
              <UploadIcon className="h-4 w-4" />
              Upload documents
            </Link>
          </div>
        </CardBody>
      </Card>
    );
  }
  return (
    <Card>
      <CardBody>
        <div className="flex flex-col items-center gap-3 py-10 text-center">
          <p className="text-sm text-slate-600">The risk timeline could not be loaded right now.</p>
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <RefreshIcon className="h-4 w-4" />
            Try again
          </button>
        </div>
      </CardBody>
    </Card>
  );
}
