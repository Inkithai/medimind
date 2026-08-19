import { useState } from "react";
import { Card, CardBody } from "./Card";
import { Spinner } from "./Spinner";
import { StatusBadge } from "./StatusBadge";
import { toastMessage, useToast } from "./Toast";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import type { ClinicalFinding, FeedbackVerdict, FindingLifecycleState } from "../types/api";

const SEVERITY_TONE: Record<string, "danger" | "warning" | "neutral"> = {
  high: "danger",
  moderate: "warning",
  low: "neutral",
};

/**
 * Reviewer verdicts in plain language. The backend vocabulary
 * (confirmed / false_positive / needs_change / overridden) is unchanged —
 * only the wording shown to a non-clinical user is friendlier, with the
 * technical term kept in the tooltip so a clinician still recognises it.
 */
const VERDICT_LABEL: Record<FeedbackVerdict, { label: string; hint: string }> = {
  confirmed: { label: "This looks right", hint: "Recorded as: confirmed" },
  false_positive: { label: "This is wrong", hint: "Recorded as: false positive" },
  needs_change: { label: "Partly right", hint: "Recorded as: needs change" },
  overridden: { label: "Hide this warning", hint: "Recorded as: overridden" },
};

/**
 * Lifecycle states (GET/POST /api/v1/findings/lifecycle) told as a status
 * a patient can act on. Only transitions the backend allows are offered,
 * so an illegal move is never presented as a button.
 */
const LIFECYCLE_LABEL: Record<
  string,
  { label: string; tone: "neutral" | "info" | "success" | "warning" }
> = {
  new: { label: "Not looked at yet", tone: "warning" },
  active: { label: "Still open", tone: "warning" },
  reviewed: { label: "You have read it", tone: "info" },
  confirmed: { label: "Confirmed with a clinician", tone: "info" },
  dismissed: { label: "Not relevant to you", tone: "neutral" },
  resolved: { label: "Sorted out", tone: "success" },
  reopened: { label: "Open again", tone: "warning" },
};

const NEXT_STEPS: Record<
  string,
  Array<{ to: FindingLifecycleState; label: string; hint: string }>
> = {
  new: [
    { to: "reviewed", label: "I have read this", hint: "Marks the warning as read." },
    {
      to: "dismissed",
      label: "Not relevant to me",
      hint: "Keeps it on record but out of the way.",
    },
  ],
  active: [
    { to: "reviewed", label: "I have read this", hint: "Marks the warning as read." },
    {
      to: "resolved",
      label: "This is sorted out",
      hint: "Use after a clinician has dealt with it.",
    },
    {
      to: "dismissed",
      label: "Not relevant to me",
      hint: "Keeps it on record but out of the way.",
    },
  ],
  reviewed: [
    {
      to: "confirmed",
      label: "A clinician confirmed it",
      hint: "Records that it was checked with a professional.",
    },
    { to: "resolved", label: "This is sorted out", hint: "Use after it has been dealt with." },
    {
      to: "dismissed",
      label: "Not relevant to me",
      hint: "Keeps it on record but out of the way.",
    },
  ],
  confirmed: [
    { to: "resolved", label: "This is sorted out", hint: "Use after it has been dealt with." },
    { to: "reopened", label: "It came back", hint: "Puts the warning back on the open list." },
  ],
  dismissed: [{ to: "reopened", label: "Put it back", hint: "Shows this warning as open again." }],
  resolved: [{ to: "reopened", label: "It came back", hint: "Shows this warning as open again." }],
  reopened: [
    { to: "reviewed", label: "I have read this", hint: "Marks the warning as read." },
    { to: "resolved", label: "This is sorted out", hint: "Use after it has been dealt with." },
  ],
};

const FINDING_KIND_LABEL: Record<string, string> = {
  drug_lab: "Drug × Lab",
  renal_hepatic: "Organ-function dose",
  condition_contraindication: "Drug × Condition",
  ddi: "Drug interaction",
};

function labPhrase(f: ClinicalFinding): string | null {
  if (f.lab && f.lab.test) {
    return `${f.lab.test} ${f.lab.value ?? ""} ${f.lab.unit ?? ""}`.trim();
  }
  if (f.lab_markers && f.lab_markers.length) {
    return f.lab_markers.map((m) => `${m.test} ${m.value ?? ""} ${m.unit ?? ""}`.trim()).join(", ");
  }
  return null;
}

/**
 * Displays one clinical finding (drug-lab / renal-hepatic / condition) with its
 * severity, the evidence (medications + lab/condition), and inline reviewer
 * feedback actions (clinician feedback loop + alert-fatigue override).
 */
export function ClinicalFindingCard({
  finding,
  lifecycleState,
  onLifecycleChange,
}: {
  finding: ClinicalFinding;
  /** Current lifecycle state from GET /api/v1/findings/lifecycle, if loaded. */
  lifecycleState?: FindingLifecycleState;
  onLifecycleChange?: (findingKey: string, state: FindingLifecycleState) => void;
}) {
  const { credentials } = useAuth();
  const { toastSuccess, toastError } = useToast();
  const [verdict, setVerdict] = useState<string | null>(finding.feedback_verdict ?? null);
  const [saving, setSaving] = useState<FeedbackVerdict | null>(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState<FindingLifecycleState | null>(lifecycleState ?? null);
  const [movingTo, setMovingTo] = useState<FindingLifecycleState | null>(null);

  const labs = labPhrase(finding);
  const meds = finding.medications_involved?.length
    ? finding.medications_involved.join(", ")
    : null;
  const currentState = state ?? lifecycleState ?? "new";
  const stateView = LIFECYCLE_LABEL[currentState] || {
    label: currentState,
    tone: "neutral" as const,
  };
  const nextSteps = NEXT_STEPS[currentState] || [];

  async function submit(v: FeedbackVerdict) {
    setSaving(v);
    try {
      const entry = await api.recordFindingFeedback(credentials, {
        finding_kind: finding.finding_kind,
        rule: finding.rule,
        medications_involved: finding.medications_involved,
        condition: finding.condition,
        organ: finding.organ,
        verdict: v,
        reason: reason.trim() || undefined,
      });
      setVerdict(entry.verdict);
      toastSuccess(
        "Thank you — your answer was saved",
        v === "overridden"
          ? "This warning will be shown lower down from now on."
          : "It helps MediMind show fewer unhelpful warnings.",
      );
    } catch (err) {
      toastError("Your answer was not saved", toastMessage(err));
    } finally {
      setSaving(null);
    }
  }

  /**
   * Move the finding through its lifecycle. The backend validates the
   * transition, so a rejected move is reported instead of being applied
   * optimistically in the interface.
   */
  async function moveTo(to: FindingLifecycleState, label: string) {
    setMovingTo(to);
    try {
      const result = await api.setFindingLifecycle(credentials, {
        finding_kind: finding.finding_kind,
        rule: finding.rule,
        medications_involved: finding.medications_involved,
        condition: finding.condition,
        organ: finding.organ,
        to_state: to,
        reason: reason.trim() || undefined,
      });
      const nextState = (result.state || to) as FindingLifecycleState;
      setState(nextState);
      if (result.finding_key) onLifecycleChange?.(result.finding_key, nextState);
      toastSuccess(`Marked: ${label}`, "You can change this again at any time.");
    } catch (err) {
      toastError("Could not update this warning", toastMessage(err));
    } finally {
      setMovingTo(null);
    }
  }

  const overridden = verdict === "overridden";

  return (
    <Card className={overridden ? "opacity-60" : undefined}>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={SEVERITY_TONE[finding.severity] ?? "neutral"}>
            {finding.severity}
          </StatusBadge>
          {finding.finding_kind && (
            <StatusBadge tone="info">
              {FINDING_KIND_LABEL[finding.finding_kind] ?? finding.finding_kind}
            </StatusBadge>
          )}
          {finding.source === "curated_knowledge_base" && (
            <StatusBadge tone="success">deterministic</StatusBadge>
          )}
          {overridden && <StatusBadge tone="neutral">overridden</StatusBadge>}
        </div>

        <p className="text-sm leading-relaxed text-slate-700">{finding.explanation}</p>

        <div className="space-y-1 text-xs text-slate-500">
          {meds && (
            <div>
              <span className="font-medium text-slate-600">Medications:</span> {meds}
            </div>
          )}
          {labs && (
            <div>
              <span className="font-medium text-slate-600">Lab evidence:</span> {labs}
            </div>
          )}
          {finding.condition && (
            <div>
              <span className="font-medium text-slate-600">Condition:</span>{" "}
              {finding.condition.replace(/_/g, " ")}
            </div>
          )}
          {finding.organ && (
            <div>
              <span className="font-medium text-slate-600">Organ:</span> {finding.organ}
            </div>
          )}
          {finding.rule && (
            <div>
              <span className="font-medium text-slate-600">Rule:</span>{" "}
              <code className="rounded bg-slate-100 px-1">{finding.rule}</code>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-700">Where this stands:</span>
            <StatusBadge tone={stateView.tone}>{stateView.label}</StatusBadge>
          </div>
          {nextSteps.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {nextSteps.map((step) => (
                <button
                  key={step.to}
                  type="button"
                  disabled={movingTo !== null}
                  onClick={() => void moveTo(step.to, step.label)}
                  title={step.hint}
                  className="inline-flex min-h-[44px] items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {movingTo === step.to && <Spinner className="h-4 w-4" />}
                  {step.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <details className="pt-1">
          <summary className="cursor-pointer text-sm font-semibold text-brand-700 hover:underline">
            Was this warning helpful?
            {verdict
              ? ` · you said: ${VERDICT_LABEL[verdict as FeedbackVerdict]?.label ?? verdict}`
              : ""}
          </summary>
          <div className="mt-2 space-y-2">
            <label className="block text-sm font-medium text-slate-700">
              Add a note (optional)
              <input
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="For example: my doctor already changed this"
                className="input mt-1 w-full"
              />
            </label>
            <div className="flex flex-wrap gap-2">
              {(
                ["confirmed", "false_positive", "needs_change", "overridden"] as FeedbackVerdict[]
              ).map((v) => (
                <button
                  key={v}
                  type="button"
                  disabled={saving !== null}
                  onClick={() => submit(v)}
                  title={VERDICT_LABEL[v].hint}
                  aria-pressed={verdict === v}
                  className={`inline-flex min-h-[44px] items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                    verdict === v
                      ? "border-brand-500 bg-brand-50 text-brand-800"
                      : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
                  } disabled:cursor-not-allowed disabled:opacity-50`}
                >
                  {saving === v && <Spinner className="h-4 w-4" />}
                  {verdict === v && saving !== v && <span aria-hidden="true">✓</span>}
                  {VERDICT_LABEL[v].label}
                </button>
              ))}
            </div>
            <p className="text-sm text-slate-500">
              Your answer stays in this workspace. It is used to show fewer unhelpful warnings — it
              never changes your medical record.
            </p>
          </div>
        </details>
      </CardBody>
    </Card>
  );
}
