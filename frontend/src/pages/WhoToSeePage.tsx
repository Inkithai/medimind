/**
 * "Who should I talk to?" — the consult triage the backend already
 * computes (GET /api/v1/consult-triage) but that had no screen.
 *
 * The report routes every safety finding to a pharmacist or a doctor with
 * an urgency, a specialty and a plain-language reason. That is the single
 * most actionable thing MediMind knows, so this page states the answer in
 * one large sentence first and only then shows the detail behind it.
 *
 * Safety wording follows the backend contract exactly: "no trigger found"
 * is never rendered as "you are fine", and the urgency word is always
 * shown next to its meaning so it can be read without knowing the scale.
 */
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import {
  AlertIcon,
  LocationIcon,
  PillIcon,
  PrintIcon,
  ShieldIcon,
  UploadIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { ConsultTriageReport, TriageAction } from "../types/api";
import { formatConfidence } from "../utils/format";

/** Urgency → the words, tone and symbol shown to the user (never colour alone). */
const URGENCY_LABELS: Record<
  string,
  { label: string; tone: "danger" | "warning" | "info"; symbol: string }
> = {
  emergency: { label: "Emergency — get help now", tone: "danger", symbol: "!!!" },
  urgent: { label: "Urgent — within 24 hours", tone: "danger", symbol: "!!" },
  soon: { label: "Soon — within a few days", tone: "warning", symbol: "!" },
  routine: { label: "Routine — at your next visit", tone: "info", symbol: "•" },
};

function urgencyView(urgency?: string | null) {
  const key = String(urgency || "").toLowerCase();
  return (
    URGENCY_LABELS[key] || { label: key ? key : "Not urgent", tone: "info" as const, symbol: "•" }
  );
}

function UrgencyBadge({ urgency }: { urgency?: string | null }) {
  const view = urgencyView(urgency);
  return (
    <StatusBadge tone={view.tone}>
      <span aria-hidden="true" className="font-bold">
        {view.symbol}
      </span>
      {view.label}
    </StatusBadge>
  );
}

export function WhoToSeePage() {
  const { credentials } = useAuth();
  const [report, setReport] = useState<ConsultTriageReport | null>(null);
  const [noRecords, setNoRecords] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNoRecords(false);
    try {
      setReport(await api.getConsultTriage(credentials));
    } catch (err) {
      // 404 is the documented "nothing uploaded yet" answer, not a failure.
      if (err instanceof ApiError && err.status === 404) {
        setReport(null);
        setNoRecords(true);
      } else {
        setError(err);
      }
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="max-w-2xl">
          <h1 className="page-title">Who should I talk to?</h1>
          <p className="secondary-text mt-2 text-base">
            MediMind looks at what it found in your uploaded records and suggests whether a
            pharmacist or a doctor should look at it, and how soon. This is a suggestion about who
            to ask — it is not a diagnosis.
          </p>
        </div>
        {report && (
          <button type="button" onClick={() => window.print()} className="btn-secondary shrink-0">
            <PrintIcon className="h-5 w-5" aria-hidden="true" />
            Print this page
          </button>
        )}
      </header>

      {loading && <LoadingState label="Checking your records…" />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && noRecords && (
        <Card>
          <CardBody className="space-y-4 py-10 text-center">
            <p className="text-lg font-semibold text-slate-900">
              There are no records to check yet
            </p>
            <p className="mx-auto max-w-md text-base text-slate-600">
              Upload a prescription, lab report or clinic note first. MediMind can then tell you
              whether anything in it is worth asking a pharmacist or doctor about.
            </p>
            <Link to="/upload" className="btn-primary inline-flex">
              <UploadIcon className="h-5 w-5" aria-hidden="true" />
              Upload a document
            </Link>
          </CardBody>
        </Card>
      )}

      {!loading && report && (
        <>
          <AnswerCard report={report} />

          <Alert variant="warning" title="If this is an emergency">
            <p className="text-base leading-relaxed">{report.emergency_advice}</p>
          </Alert>

          <div className="grid gap-6 lg:grid-cols-2">
            <ActionList
              title="Ask a pharmacist about"
              description="A pharmacist can usually help with these without an appointment."
              icon={<PillIcon className="h-5 w-5" aria-hidden="true" />}
              actions={report.pharmacist_actions}
              emptyText="Nothing was routed to a pharmacist."
            />
            <ActionList
              title="Ask a doctor about"
              description="These need a clinician to look at your record."
              icon={<ShieldIcon className="h-5 w-5" aria-hidden="true" />}
              actions={report.doctor_actions}
              emptyText="Nothing was routed to a doctor."
            />
          </div>

          {report.recommended_specialties.length > 0 && (
            <Card>
              <CardHeader
                title="Which kind of doctor"
                description="Based on what was found. Tap Find care to see clinics near you."
                icon={<LocationIcon className="h-5 w-5" aria-hidden="true" />}
              />
              <CardBody>
                <ul className="space-y-3">
                  {report.recommended_specialties.map((specialty) => (
                    <li
                      key={specialty.key}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 p-4"
                    >
                      <div className="min-w-0">
                        <p className="text-base font-semibold text-slate-900">{specialty.label}</p>
                        {specialty.triggered_by && specialty.triggered_by.length > 0 && (
                          <p className="mt-1 text-sm text-slate-600">
                            Because of: {specialty.triggered_by.join(", ")}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-3">
                        <UrgencyBadge urgency={specialty.urgency} />
                        <Link to="/find-care" className="btn-secondary">
                          Find care
                        </Link>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}

          {report.document_quality_note && (
            <Alert variant="info" title="Check these documents against the originals">
              <p className="text-base leading-relaxed">{report.document_quality_note}</p>
              <Link
                to="/record-integrity"
                className="mt-2 inline-block text-base font-semibold underline"
              >
                Review document quality
              </Link>
            </Alert>
          )}

          <Card>
            <CardBody>
              <p className="text-sm leading-relaxed text-slate-600">{report.note}</p>
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}

function AnswerCard({ report }: { report: ConsultTriageReport }) {
  const consultType = (report.consult_type || "").replace(/_/g, " ");
  const headline = report.consult_needed
    ? `Talk to a ${consultType || "clinician"}`
    : "No reason to book an appointment was found";
  return (
    <Card
      className={report.consult_needed ? "border-2 border-amber-300" : "border-2 border-slate-200"}
    >
      <CardBody className="space-y-4">
        <div className="flex items-start gap-4">
          <div
            className={
              report.consult_needed
                ? "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-amber-100 text-amber-800"
                : "flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700"
            }
            aria-hidden="true"
          >
            <AlertIcon className="h-7 w-7" />
          </div>
          <div className="min-w-0 space-y-2">
            <h2 className="text-2xl font-bold leading-tight text-slate-900">{headline}</h2>
            {report.consult_needed && (
              <div className="flex flex-wrap items-center gap-2">
                <UrgencyBadge urgency={report.urgency} />
                {typeof report.confidence === "number" && (
                  <StatusBadge tone="neutral">
                    Confidence {formatConfidence(report.confidence)}
                  </StatusBadge>
                )}
              </div>
            )}
            {report.urgency_meaning && (
              <p className="text-base leading-relaxed text-slate-700">{report.urgency_meaning}</p>
            )}
            <p className="text-base leading-relaxed text-slate-700">{report.summary}</p>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function ActionList({
  title,
  description,
  icon,
  actions,
  emptyText,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
  actions: TriageAction[];
  emptyText: string;
}) {
  return (
    <Card>
      <CardHeader
        title={title}
        description={description}
        icon={icon}
        action={<StatusBadge tone="neutral">{actions.length}</StatusBadge>}
      />
      <CardBody>
        {actions.length === 0 ? (
          <p className="py-4 text-base text-slate-600">{emptyText}</p>
        ) : (
          <ul className="space-y-3">
            {actions.map((action, index) => (
              <li
                key={`${action.subject}-${index}`}
                className="rounded-xl border border-slate-200 p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="text-base font-semibold text-slate-900">{action.subject}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    {action.is_historical && <StatusBadge tone="neutral">Past record</StatusBadge>}
                    <UrgencyBadge urgency={action.urgency} />
                  </div>
                </div>
                <p className="mt-2 text-base leading-relaxed text-slate-700">{action.detail}</p>
                {action.why_this_route && (
                  <p className="mt-1 text-sm leading-relaxed text-slate-600">
                    {action.why_this_route}
                  </p>
                )}
                {action.confidence_caveat && (
                  <p className="mt-1 text-sm leading-relaxed text-amber-800">
                    {action.confidence_caveat}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-500">
                  {action.specialty?.label && <span>Specialty: {action.specialty.label}</span>}
                  {typeof action.confidence === "number" && (
                    <span>Confidence: {formatConfidence(action.confidence)}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
