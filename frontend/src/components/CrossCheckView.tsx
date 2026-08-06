import type { CrossCheckReport } from "../types/api";
import { formatConfidence, severityTone } from "../utils/format";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";
import { EmptyState } from "./EmptyState";
import { ShieldIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";

interface Section {
  key: keyof Pick<
    CrossCheckReport,
    | "potential_drug_interactions"
    | "duplicate_prescriptions"
    | "conflicting_dosage_instructions"
    | "allergy_conflicts"
  >;
  title: string;
  tone: "danger" | "warning" | "info";
}

const SECTIONS: Section[] = [
  { key: "allergy_conflicts", title: "Allergy conflicts", tone: "danger" },
  { key: "potential_drug_interactions", title: "Potential drug interactions", tone: "warning" },
  { key: "conflicting_dosage_instructions", title: "Conflicting dosage instructions", tone: "warning" },
  { key: "duplicate_prescriptions", title: "Duplicate prescriptions", tone: "info" },
];

export function CrossCheckView({ report }: { report: CrossCheckReport }) {
  const totalIssues = SECTIONS.reduce(
    (sum, s) => sum + (report[s.key]?.length || 0),
    0
  );

  return (
    <Card>
      <CardHeader
        title="Safety cross-check"
        description={
          totalIssues === 0
            ? "No issues detected by the cross-check."
            : `${totalIssues} issue(s) flagged across medications and allergies.`
        }
        icon={<ShieldIcon className="h-5 w-5" />}
      />
      <CardBody className="space-y-5">
        {report.overall_recommendation && (
          <Alert variant="warning" title="Professional recommendation">
            {report.overall_recommendation}
          </Alert>
        )}

        {totalIssues === 0 ? (
          <EmptyState
            title="No safety issues flagged"
            description="The cross-check found no interactions, duplicates, dosage conflicts, or allergy conflicts."
          />
        ) : (
          SECTIONS.map((section) => (
            <IssueSection key={section.key} report={report} section={section} />
          ))
        )}
      </CardBody>
    </Card>
  );
}

function IssueSection({ report, section }: { report: CrossCheckReport; section: Section }) {
  const items = report[section.key] || [];
  if (items.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-800">{section.title}</h3>
        <StatusBadge tone={section.tone}>{items.length}</StatusBadge>
      </div>
      <div className="space-y-2">
        {items.map((item, idx) => (
          <div
            key={idx}
            className="rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3"
          >
            {"severity" in item && (
              <div className="mb-1.5">
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${severityTone(
                    item.severity
                  )}`}
                >
                  {item.severity} severity
                </span>
              </div>
            )}

            {"medications_involved" in item && (
              <p className="text-sm font-medium text-slate-800">
                {item.medications_involved.join(" + ")}
              </p>
            )}
            {"medication" in item && !("allergy" in item) && (
              <p className="text-sm font-medium text-slate-800">{item.medication}</p>
            )}
            {"allergy" in item && (
              <p className="text-sm font-medium text-slate-800">
                {item.medication}{" "}
                <span className="text-slate-400">↔</span>{" "}
                <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-700 ring-1 ring-inset ring-red-200">
                  allergy: {item.allergy}
                </span>
              </p>
            )}

            <p className="mt-1 text-sm text-slate-600">
              {"explanation" in item ? item.explanation : ""}
            </p>

            {"occurrences" in item && item.occurrences.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-slate-500">
                {item.occurrences.map((o, i) => (
                  <li key={i}>
                    · {o.date || "undated"} — {o.source_file || "unknown file"}
                    {o.dosage ? ` — ${o.dosage}` : ""}
                  </li>
                ))}
              </ul>
            )}

            {"conflicting_instructions" in item && item.conflicting_instructions.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-slate-500">
                {item.conflicting_instructions.map((o, i) => (
                  <li key={i}>
                    · {o.date || "undated"} — {o.source_file || "unknown file"} —{" "}
                    {[o.dosage, o.frequency].filter(Boolean).join(", ")}
                  </li>
                ))}
              </ul>
            )}

            <p className="mt-2 text-xs text-slate-400">
              confidence {formatConfidence((item as { confidence?: number }).confidence)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
