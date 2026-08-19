import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ClinicalFindingCard } from "../components/ClinicalFindingCard";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { EmptyState } from "../components/EmptyState";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import { StatusBadge } from "../components/StatusBadge";
import type { EmbeddedPageProps } from "../components/TabBar";
import type {
  FindingFeedbackEntry,
  ManagedAlertsReport,
  FeedbackMetrics,
  FindingLifecycleOverview,
  FindingLifecycleState,
} from "../types/api";

export function ClinicalSafetyPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [alerts, setAlerts] = useState<ManagedAlertsReport | null>(null);
  const [metrics, setMetrics] = useState<FeedbackMetrics | null>(null);
  // finding_key -> lifecycle state, so each card knows what has already
  // been reviewed, dismissed or resolved (GET /api/v1/findings/lifecycle).
  const [lifecycle, setLifecycle] = useState<Record<string, FindingLifecycleState>>({});
  const [lifecycleSummary, setLifecycleSummary] = useState<FindingLifecycleOverview | null>(null);
  const [pastFeedback, setPastFeedback] = useState<FindingFeedbackEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [a, m, lc, fb] = await Promise.all([
        api.getManagedAlerts(credentials),
        api.getFeedbackMetrics(credentials).catch(() => null),
        api.getFindingLifecycle(credentials).catch(() => null),
        // Your own past answers — the other half of the feedback loop.
        api.listFindingFeedback(credentials).catch(() => ({ feedback: [] })),
      ]);
      setAlerts(a);
      setMetrics(m);
      setLifecycleSummary(lc);
      setPastFeedback(fb?.feedback || []);
      const states: Record<string, FindingLifecycleState> = {};
      for (const finding of lc?.findings || []) {
        if (finding.finding_key) states[finding.finding_key] = finding.lifecycle_state;
      }
      setLifecycle(states);
    } catch (err) {
      setAlerts(null);
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
      <div className="flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row">
        {embedded ? (
          <div className="min-w-0" />
        ) : (
          <div className="min-w-0">
            <h1 className="page-title">{t("clinicalSafety.title")}</h1>
            <p className="secondary-text mt-2 max-w-2xl">{t("clinicalSafety.subtitle")}</p>
          </div>
        )}
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshIcon className="h-4 w-4" />
          {t("common.refresh")}
        </button>
      </div>

      {loading && <LoadingState label={t("common.loading")} />}

      {!loading && error !== null && (
        <ErrorOrEmpty error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && alerts && (
        <>
          {alerts.active_count === 0 && alerts.suppressed_count === 0 && (
            <Card>
              <CardBody>
                <EmptyState
                  title="No active safety alerts"
                  description="Once documents are uploaded, drug–lab, renal/hepatic, condition-contraindication and interaction findings appear here, with reviewer actions."
                />
              </CardBody>
            </Card>
          )}

          {lifecycleSummary && lifecycleSummary.open_count + lifecycleSummary.closed_count > 0 && (
            <Card>
              <CardHeader
                title="Your progress on these warnings"
                description="Marking a warning as read, sorted out or not relevant keeps this list manageable. Nothing is deleted."
              />
              <CardBody>
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <ProgressTile
                    label="Still open"
                    value={lifecycleSummary.open_count}
                    tone="warning"
                  />
                  <ProgressTile
                    label="Dealt with"
                    value={lifecycleSummary.closed_count}
                    tone="success"
                  />
                  <ProgressTile
                    label="You have read"
                    value={lifecycleSummary.by_state?.reviewed || 0}
                    tone="info"
                  />
                  <ProgressTile
                    label="Not relevant to you"
                    value={lifecycleSummary.by_state?.dismissed || 0}
                    tone="neutral"
                  />
                </dl>
              </CardBody>
            </Card>
          )}

          {alerts.active_count > 0 && (
            <div>
              <h2 className="section-title">Active findings ({alerts.active_count})</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {alerts.active_findings.map((f, i) => (
                  <ClinicalFindingCard
                    key={f.finding_key || i}
                    finding={f}
                    lifecycleState={f.finding_key ? lifecycle[f.finding_key] : undefined}
                    onLifecycleChange={(key, state) =>
                      setLifecycle((current) => ({ ...current, [key]: state }))
                    }
                  />
                ))}
              </div>
              {alerts.collapsed_duplicates > 0 && (
                <p className="mt-2 text-xs text-slate-400">
                  {alerts.collapsed_duplicates} near-duplicate alert(s) collapsed.
                </p>
              )}
            </div>
          )}

          {alerts.suppressed_count > 0 && (
            <div>
              <h2 className="section-title">Overridden / suppressed ({alerts.suppressed_count})</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {alerts.suppressed_findings.map((f, i) => (
                  <ClinicalFindingCard
                    key={f.finding_key || i}
                    finding={f}
                    lifecycleState={f.finding_key ? lifecycle[f.finding_key] : undefined}
                    onLifecycleChange={(key, state) =>
                      setLifecycle((current) => ({ ...current, [key]: state }))
                    }
                  />
                ))}
              </div>
            </div>
          )}

          {pastFeedback.length > 0 && <PastFeedbackSection entries={pastFeedback} />}

          {metrics && metrics.total > 0 && (
            <Card>
              <CardHeader title="Reviewer metrics" />
              <CardBody>
                <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <Metric label="Total reviews" value={metrics.total} />
                  <Metric label="Confirmation rate" value={metrics.confirmation_rate ?? "—"} />
                  <Metric label="False-positive rate" value={metrics.false_positive_rate ?? "—"} />
                  <Metric label="Override rate" value={metrics.override_rate ?? "—"} />
                </dl>
              </CardBody>
            </Card>
          )}

          <MedicalDisclaimer />
        </>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-800">{value}</dd>
    </div>
  );
}

function ErrorOrEmpty({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status =
    error && typeof error === "object" && "status" in error
      ? (error as { status?: number }).status
      : undefined;
  if (status === 404) {
    return (
      <Card>
        <CardBody>
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="text-sm font-semibold text-slate-700">No records yet</p>
            <Link
              to="/upload"
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            >
              <UploadIcon className="h-4 w-4" /> Upload documents
            </Link>
          </div>
        </CardBody>
      </Card>
    );
  }
  return <ErrorState error={error} onRetry={onRetry} />;
}

/** One counter in the review-progress summary (label + number, no colour-only meaning). */
function ProgressTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "warning" | "success" | "info" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <dt className="text-sm font-medium text-slate-600">{label}</dt>
      <dd className="mt-1 flex items-center gap-2">
        <span className="text-2xl font-bold text-slate-900">{value}</span>
        <StatusBadge tone={tone}>{label}</StatusBadge>
      </dd>
    </div>
  );
}

/**
 * Your past answers (GET /api/v1/findings/feedback).
 *
 * The app asks "was this warning helpful?" on every finding, but until
 * now there was nowhere to see what you had already answered. Without
 * that, the same question feels like it is being asked again and again.
 */
function PastFeedbackSection({ entries }: { entries: FindingFeedbackEntry[] }) {
  const VERDICT_TEXT: Record<string, string> = {
    confirmed: "You said this looks right",
    false_positive: "You said this is wrong",
    needs_change: "You said this is partly right",
    overridden: "You asked to hide this warning",
  };
  const ordered = [...entries].sort((a, b) =>
    String(b.created_at || "").localeCompare(String(a.created_at || "")),
  );
  return (
    <Card>
      <CardHeader
        title="Your past answers"
        description="What you told MediMind about earlier warnings. Nothing here changes your medical record."
      />
      <CardBody>
        <ul className="divide-y divide-slate-100">
          {ordered.slice(0, 8).map((entry, index) => (
            <li
              key={`${entry.finding_key}-${entry.created_at}-${index}`}
              className="flex flex-wrap items-center justify-between gap-2 py-3"
            >
              <div className="min-w-0">
                <p className="text-base font-medium text-slate-800">
                  {VERDICT_TEXT[entry.verdict] || entry.verdict}
                </p>
                <p className="text-sm text-slate-600">
                  {entry.rule ? entry.rule.replace(/_/g, " ") : entry.finding_key}
                  {entry.reason ? ` — “${entry.reason}”` : ""}
                </p>
              </div>
              <span className="text-sm text-slate-500">
                {entry.created_at ? entry.created_at.slice(0, 10) : ""}
              </span>
            </li>
          ))}
        </ul>
        {ordered.length > 8 && (
          <p className="mt-2 text-sm text-slate-600">
            Showing the 8 most recent of {ordered.length} answers.
          </p>
        )}
      </CardBody>
    </Card>
  );
}
