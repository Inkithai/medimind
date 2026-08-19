/**
 * Reconciled medicine list (GET /api/v1/medications/reconciliation).
 *
 * The backend already works out, per active ingredient, whether it is
 * currently supplied, supplied twice, supplied at two different doses, or
 * stopped. That answer is what a patient actually needs before a visit —
 * "which of these am I still taking?" — so it is shown as one plain table
 * with a written status, not only a colour.
 *
 * Nothing is computed here: every state, count and note comes from the
 * backend response.
 */
import type { MedicationReconciliationReport, ReconciledMedication } from "../types/api";
import { Card, CardBody, CardHeader } from "./Card";
import { StatusBadge } from "./StatusBadge";
import { PillIcon } from "./icons";

interface StateView {
  label: string;
  tone: "success" | "warning" | "danger" | "neutral" | "info";
  symbol: string;
  meaning: string;
}

const STATE_VIEWS: Record<string, StateView> = {
  active: {
    label: "Taking now",
    tone: "success",
    symbol: "✓",
    meaning: "There is a current supply of this medicine on your record.",
  },
  duplicate: {
    label: "Possible duplicate",
    tone: "warning",
    symbol: "!",
    meaning: "More than one current supply of the same ingredient was found.",
  },
  dose_conflict: {
    label: "Different doses",
    tone: "danger",
    symbol: "!!",
    meaning: "Two different doses of the same ingredient are recorded at the same time.",
  },
  discontinued: {
    label: "Stopped",
    tone: "neutral",
    symbol: "–",
    meaning: "It was supplied before, but there is no current supply.",
  },
  single_supply: {
    label: "One supply only",
    tone: "info",
    symbol: "?",
    meaning: "Only one dated supply was found, so it is unclear whether it is current.",
  },
};

function stateView(state: string): StateView {
  return (
    STATE_VIEWS[state] || {
      label: state.replace(/_/g, " "),
      tone: "neutral",
      symbol: "•",
      meaning: "",
    }
  );
}

function doseText(medicine: ReconciledMedication): string {
  const doses = (medicine.doses || []).filter((dose) => dose && dose !== "unknown_dose");
  if (doses.length === 0) return "Dose not recorded";
  return doses.map((dose) => dose.replace(/\|/g, " · ")).join("  /  ");
}

export function MedicationReconciliationView({
  report,
}: {
  report: MedicationReconciliationReport;
}) {
  const medicines = report.reconciled_medications || [];
  const summary = report.summary;
  const needsAttention = medicines.filter(
    (medicine) => medicine.state === "dose_conflict" || medicine.state === "duplicate",
  );

  return (
    <Card>
      <CardHeader
        title="Your current medicine list"
        description={`Checked on ${report.reference_date}. Grouped by active ingredient, so the same medicine under two brand names is only listed once.`}
        icon={<PillIcon className="h-5 w-5" aria-hidden="true" />}
      />
      <CardBody className="space-y-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <SummaryTile label="Taking now" value={summary.active} />
          <SummaryTile label="Stopped" value={summary.discontinued} />
          <SummaryTile label="Possible duplicates" value={summary.duplicates} />
          <SummaryTile label="Different doses" value={summary.dose_conflicts} />
        </dl>

        {needsAttention.length > 0 && (
          <p className="rounded-xl border-2 border-amber-300 bg-amber-50 p-4 text-base leading-relaxed text-amber-900">
            <span className="font-semibold">Worth asking about: </span>
            {needsAttention.map((medicine) => medicine.display_name).join(", ")}. Take this list to
            your pharmacist or doctor and confirm what you should be taking.
          </p>
        )}

        {medicines.length === 0 ? (
          <p className="py-6 text-center text-base text-slate-600">
            No medicines have been found in your uploaded records yet.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-left text-base">
              <caption className="sr-only">
                Medicines grouped by ingredient with their current status
              </caption>
              <thead className="bg-slate-50 text-sm uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Medicine
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Dose on record
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    What this means
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {medicines.map((medicine) => {
                  const view = stateView(medicine.state);
                  return (
                    <tr key={medicine.ingredient} className="align-top hover:bg-slate-50">
                      <th scope="row" className="px-4 py-4 text-left font-semibold text-slate-900">
                        {medicine.display_name}
                        <span className="mt-1 block text-sm font-normal text-slate-600">
                          {medicine.supply_count} record
                          {medicine.supply_count === 1 ? "" : "s"} found
                        </span>
                      </th>
                      <td className="px-4 py-4">
                        <StatusBadge tone={view.tone}>
                          <span aria-hidden="true" className="font-bold">
                            {view.symbol}
                          </span>
                          {view.label}
                        </StatusBadge>
                      </td>
                      <td className="px-4 py-4 text-slate-700">{doseText(medicine)}</td>
                      <td className="px-4 py-4 text-slate-700">
                        <p>{view.meaning}</p>
                        {medicine.notes.map((note) => (
                          <p key={note} className="mt-1 text-sm text-slate-600">
                            {note}
                          </p>
                        ))}
                        {medicine.sources.length > 0 && (
                          <details className="mt-2">
                            <summary className="cursor-pointer text-sm font-semibold text-brand-700 hover:underline">
                              Where this came from ({medicine.sources.length})
                            </summary>
                            <ul className="mt-1 space-y-1 text-sm text-slate-600">
                              {medicine.sources.map((source, index) => (
                                <li key={`${source.source_file}-${index}`}>
                                  {source.date || "undated"} ·{" "}
                                  {source.source_file || "unknown file"}
                                </li>
                              ))}
                            </ul>
                          </details>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-sm leading-relaxed text-slate-600">{report.note}</p>
      </CardBody>
    </Card>
  );
}

function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-center">
      <dt className="text-sm font-medium text-slate-600">{label}</dt>
      <dd className="text-2xl font-bold text-slate-900">{value}</dd>
    </div>
  );
}
