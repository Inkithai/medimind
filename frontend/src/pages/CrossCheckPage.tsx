import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { CrossCheckView } from "../components/CrossCheckView";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody } from "../components/Card";
import { LoadingState } from "../components/Spinner";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { CrossCheckReport } from "../types/api";

export function CrossCheckPage() {
  const { credentials } = useAuth();
  const [report, setReport] = useState<CrossCheckReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getCrossCheck(credentials);
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
        <div>
          <h1 className="page-title">Safety Alerts</h1>
          <p className="secondary-text mt-2 max-w-2xl">
            We check your medicines for interactions, duplicates, conflicting doses, and allergy
            conflicts — matched by active ingredient, not brand name.
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

      {loading && <LoadingState label="Loading safety report" />}

      {!loading && error !== null && (
        <NotFoundOrError
          error={error}
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      )}

      {!loading && report && (
        <>
          <CrossCheckView report={report} />
          <p className="text-sm text-slate-600">
            This is not a diagnosis. If you want a public listing of nearby clinics,{" "}
            <Link to="/find-care" className="font-medium text-brand-600 hover:text-brand-700">
              find facilities
            </Link>
            — MediMind will not pick one for you.
          </p>
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
            <p className="text-base font-semibold text-slate-700">
              No safety alerts yet
            </p>
            <p className="max-w-md text-sm text-slate-500">
              Upload at least one document and we'll check your medicines for you.
            </p>
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
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}
