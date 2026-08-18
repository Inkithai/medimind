import { useState } from "react";
import { Card, CardBody } from "./Card";
import { StatusBadge } from "./StatusBadge";
import { useAuth } from "../context/AuthContext";
import { api } from "../api/client";
import type { ClinicalFinding, FeedbackVerdict } from "../types/api";

const SEVERITY_TONE: Record<string, "danger" | "warning" | "neutral"> = {
  high: "danger",
  moderate: "warning",
  low: "neutral",
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
    return f.lab_markers
      .map((m) => `${m.test} ${m.value ?? ""} ${m.unit ?? ""}`.trim())
      .join(", ");
  }
  return null;
}

/**
 * Displays one clinical finding (drug-lab / renal-hepatic / condition) with its
 * severity, the evidence (medications + lab/condition), and inline reviewer
 * feedback actions (clinician feedback loop + alert-fatigue override).
 */
export function ClinicalFindingCard({ finding }: { finding: ClinicalFinding }) {
  const { credentials } = useAuth();
  const [verdict, setVerdict] = useState<string | null>(
    finding.feedback_verdict ?? null
  );
  const [saving, setSaving] = useState<FeedbackVerdict | null>(null);
  const [reason, setReason] = useState("");

  const labs = labPhrase(finding);
  const meds = finding.medications_involved?.length
    ? finding.medications_involved.join(", ")
    : null;

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
    } finally {
      setSaving(null);
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

        <details className="pt-1">
          <summary className="cursor-pointer text-xs font-medium text-brand-700 hover:underline">
            Reviewer action{verdict ? ` · ${verdict}` : ""}
          </summary>
          <div className="mt-2 space-y-2">
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason / note (optional)"
              className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs"
            />
            <div className="flex flex-wrap gap-2">
              {(
                ["confirmed", "false_positive", "needs_change", "overridden"] as FeedbackVerdict[]
              ).map((v) => (
                <button
                  key={v}
                  type="button"
                  disabled={saving !== null}
                  onClick={() => submit(v)}
                  className={`rounded-md border px-2 py-1 text-xs font-medium ${
                    verdict === v
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                  } disabled:opacity-50`}
                >
                  {saving === v ? "…" : v.replace(/_/g, " ")}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-400">
              Captured for this workspace only. Used to tune alert priority and
              track false-positive / override rates.
            </p>
          </div>
        </details>
      </CardBody>
    </Card>
  );
}
