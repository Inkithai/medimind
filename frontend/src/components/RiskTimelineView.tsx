import type { RiskTimelineReport } from "../types/api";
import { classNames } from "../utils/format";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";

// Presentation for the chronological risk view: when was each safety finding
// actually live? Findings whose courses never overlapped are shown as
// history, not current risk — and every finding shows what evidence backs it.

const STATUS_STYLES: Record<string, string> = {
  concurrent: "bg-red-50 text-red-700",
  possible: "bg-amber-50 text-amber-700",
  not_concurrent: "bg-slate-100 text-slate-500",
  unknown: "bg-slate-100 text-slate-500",
};

const STATUS_LABELS: Record<string, string> = {
  concurrent: "Taken together",
  possible: "May have overlapped",
  not_concurrent: "Never taken together",
  unknown: "Dates unreadable",
};

const KIND_LABELS: Record<string, string> = {
  drug_interaction: "Interaction",
  duplicate_prescription: "Duplicate",
  dosage_conflict: "Dosage conflict",
};

function EvidenceBadge({ source }: { source?: string | null }) {
  if (!source) return null;
  const verified = source === "deterministic" || source === "reference_graph";
  return (
    <span
      className={classNames(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
        verified ? "bg-emerald-50 text-emerald-700" : "bg-violet-50 text-violet-600"
      )}
      title={
        verified
          ? "Computed from your own records or backed by a reference document"
          : "From the AI model's general knowledge — not verified against a drug-interaction database"
      }
    >
      {verified ? "Verified in your records" : "Unverified model knowledge"}
    </span>
  );
}

export function RiskTimelineView({ report }: { report: RiskTimelineReport }) {
  const calendar = report.calendar ?? [];
  const exposures = report.concurrent_exposure ?? [];
  const timing = report.timing_summary;
  const evidence = report.evidence_summary;

  if (calendar.length === 0 && exposures.length === 0) {
    return (
      <Card>
        <CardBody>
          <p className="py-6 text-center text-sm text-slate-500">
            No safety findings to place in time. This is not a clean bill of health —
            it only means the automated checks found nothing in the documents provided.
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {evidence && (
        <Alert variant="info" title="How findings are graded">
          {evidence.note}
        </Alert>
      )}

      {timing && timing.note && (
        <p className="text-sm text-slate-600">{timing.note}</p>
      )}

      {exposures.length > 0 && (
        <Card>
          <CardHeader
            title="Double-dosing periods"
            description="Times when two separate prescriptions supplied the same ingredient at once"
          />
          <CardBody className="space-y-3">
            {exposures.map((exposure, i) => (
              <div key={i} className="rounded-lg border border-red-100 bg-red-50/50 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold capitalize text-slate-800">
                    {exposure.ingredient}
                  </span>
                  <span
                    className={classNames(
                      "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
                      STATUS_STYLES[exposure.status] ?? STATUS_STYLES.unknown
                    )}
                  >
                    {STATUS_LABELS[exposure.status] ?? exposure.status}
                  </span>
                  {exposure.cumulative_daily_dose != null && exposure.dosage_unit && (
                    <span className="text-xs font-medium text-red-700">
                      {exposure.cumulative_daily_dose} {exposure.dosage_unit}/day combined
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-600">{exposure.note}</p>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <div className="space-y-4">
        {calendar.map((period, i) => (
          <Card key={i}>
            <CardHeader
              title={period.label}
              description={
                period.window_start
                  ? `${period.risks.length} finding(s) live in this period`
                  : "Findings kept for the record"
              }
            />
            <CardBody className="space-y-3">
              {period.risks.map((risk, j) => (
                <div key={j} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      {KIND_LABELS[risk.kind] ?? risk.kind}
                    </span>
                    <span className="text-sm font-medium text-slate-800">
                      {risk.subjects.join(" + ") || "Unnamed"}
                    </span>
                    <span
                      className={classNames(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium",
                        STATUS_STYLES[risk.status] ?? STATUS_STYLES.unknown
                      )}
                    >
                      {STATUS_LABELS[risk.status] ?? risk.status}
                    </span>
                    {risk.severity && (
                      <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium capitalize text-slate-600">
                        {risk.severity}
                      </span>
                    )}
                    <EvidenceBadge source={risk.evidence_source} />
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>
        ))}
      </div>

      {report.treatment_windows.length > 0 && (
        <Card>
          <CardHeader
            title="Treatment windows"
            description="Each course on file, with its start date and duration where printed"
          />
          <CardBody>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                    <th className="py-2 pr-3 font-medium">Medication</th>
                    <th className="py-2 pr-3 font-medium">Started</th>
                    <th className="py-2 pr-3 font-medium">Ended</th>
                    <th className="py-2 pr-3 font-medium">Daily dose</th>
                    <th className="py-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {report.treatment_windows.map((window, i) => (
                    <tr key={i} className="border-b border-slate-100 last:border-0">
                      <td className="py-2 pr-3 font-medium text-slate-700">
                        {window.name ?? window.ingredients.join(", ") ?? "Unknown"}
                      </td>
                      <td className="py-2 pr-3 text-slate-600">{window.start ?? "Unknown"}</td>
                      <td className="py-2 pr-3 text-slate-600">
                        {window.end ?? (window.duration_known ? "—" : "Open-ended")}
                      </td>
                      <td className="py-2 pr-3 text-slate-600">
                        {window.daily_dose != null && window.dosage_unit
                          ? `${window.daily_dose} ${window.dosage_unit}`
                          : "—"}
                      </td>
                      <td className="py-2 text-xs text-slate-500">{window.source_file ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}
