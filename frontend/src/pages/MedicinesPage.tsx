import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody } from "../components/Card";
import { MedicationReconciliationView } from "../components/MedicationReconciliationView";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { PillIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { MedicationReconciliationReport, Timeline } from "../types/api";
import { compareDates, formatDate } from "../utils/format";

export function MedicinesPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [reconciliation, setReconciliation] = useState<MedicationReconciliationReport | null>(null);
  const [reconciliationError, setReconciliationError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setReconciliationError(null);
    // The reconciled list is an extra view of the same record: if it is
    // unavailable the raw medicine history must still render.
    void api
      .getMedicationReconciliation(credentials)
      .then((report) => {
        setReconciliation(report);
        setReconciliationError(null);
      })
      .catch((err) => {
        setReconciliation(null);
        setReconciliationError(
          err instanceof ApiError && err.status === 404
            ? null
            : "The checked medicine list could not be loaded just now. The full history below is still accurate.",
        );
      });
    try {
      const data = await api.getTimeline(credentials);
      setTimeline(data);
    } catch (err) {
      // 404 = no record yet (fresh workspace or snapshot still building) — the
      // API's documented first-run contract. Show the page's normal empty
      // state instead of a hard error, exactly like the Dashboard and Labs
      // pages do for the same response.
      if (err instanceof ApiError && err.status === 404) {
        setTimeline({
          visits: [],
          medications_timeline: [],
          lab_results_timeline: [],
          known_allergies: [],
        });
      } else {
        setTimeline(null);
        setError(err);
      }
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="space-y-6">
        <Header count={null} />
        <LoadingState label={t("medicines.loading")} />
      </div>
    );
  }

  if (error || !timeline) {
    return (
      <div className="space-y-6">
        <Header count={null} />
        <ErrorState error={error} onRetry={() => void load()} />
      </div>
    );
  }

  const filtered = timeline.medications_timeline.filter((m) => {
    if (!filter.trim()) return true;
    const q = filter.toLowerCase();
    return (
      m.name.toLowerCase().includes(q) ||
      m.ingredients.some((ing) => ing.toLowerCase().includes(q)) ||
      (m.source_file || "").toLowerCase().includes(q)
    );
  });

  // Group by ingredient for "current" view: most recent occurrence per ingredient
  const byIngredient = new Map<string, (typeof filtered)[0][]>();
  for (const med of filtered) {
    const key = (med.ingredients[0] || med.name).toLowerCase();
    if (!byIngredient.has(key)) byIngredient.set(key, []);
    byIngredient.get(key)!.push(med);
  }

  const mostRecentOf = (entries: (typeof filtered)[0][]) =>
    entries.reduce(
      (latest, cur) => (compareDates(cur.date, latest.date) > 0 ? cur : latest),
      entries[0],
    );

  const sortedIngredients = Array.from(byIngredient.entries()).sort((a, b) => {
    return compareDates(mostRecentOf(b[1]).date, mostRecentOf(a[1]).date);
  });

  return (
    <div className="space-y-6">
      <Header count={timeline.medications_timeline.length} />

      <Card>
        <CardBody className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
              <PillIcon className="h-5 w-5" />
            </div>
            <label htmlFor="medicine-search" className="sr-only">
              {t("medicines.searchLabel")}
            </label>
            <input
              id="medicine-search"
              type="search"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("medicines.searchPlaceholder")}
              className="min-w-0 flex-1 rounded-xl border border-slate-200 px-3 py-2 text-sm shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 sm:max-w-xs"
            />
          </div>
          <p className="text-xs text-slate-500">
            {filter.trim() ? t("medicines.searchHelp") : t("medicines.description")}
          </p>
        </CardBody>
      </Card>

      {filtered.length === 0 ? (
        <Card>
          <CardBody className="py-12 text-center">
            <p className="text-sm font-semibold text-slate-700">
              {timeline.medications_timeline.length === 0
                ? t("medicines.noMedicines")
                : t("medicines.noMatches")}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {timeline.medications_timeline.length === 0
                ? "Upload prescriptions or discharge summaries to populate this list."
                : `No medicines match “${filter}”.`}
            </p>
            {timeline.medications_timeline.length === 0 && (
              <Link
                to="/upload"
                className="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              >
                <UploadIcon className="h-4 w-4" /> Upload documents
              </Link>
            )}
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-6">
          {reconciliation && (
            <Section title="Checked medicine list">
              <MedicationReconciliationView report={reconciliation} />
            </Section>
          )}
          {reconciliationError && (
            <Alert variant="info" title="Checked list unavailable">
              {reconciliationError}
            </Alert>
          )}

          <Section title={t("medicines.current")}>
            <div className="grid gap-3 sm:grid-cols-2">
              {sortedIngredients.map(([ingredient, entries]) => {
                const mostRecent = mostRecentOf(entries);
                const historyCount = entries.length;
                return (
                  <div
                    key={ingredient}
                    className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{mostRecent.name}</p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {mostRecent.ingredients.join(", ")}
                        </p>
                      </div>
                      <StatusBadge tone="brand">{historyCount} ×</StatusBadge>
                    </div>
                    {mostRecent.cross_check_eligible === false && (
                      <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-2 text-xs leading-relaxed text-amber-900">
                        <span className="font-semibold">Not safety-checked: </span>
                        {mostRecent.unmatched_reason ||
                          "This drug name could not be converted to its standard English name, so it cannot be compared against your other records."}
                      </p>
                    )}
                    <div className="mt-2 space-y-1 text-xs text-slate-600">
                      <p>
                        {[mostRecent.dosage, mostRecent.frequency, mostRecent.duration]
                          .filter(Boolean)
                          .join(" • ") || "—"}
                      </p>
                      <p className="text-slate-500">
                        Source:{" "}
                        {mostRecent.document_id ? (
                          <Link
                            to={`/documents?document=${encodeURIComponent(mostRecent.document_id)}`}
                            className="font-medium text-brand-700 underline decoration-brand-300 underline-offset-2 hover:text-brand-900"
                          >
                            {mostRecent.source_file || "unknown"}
                          </Link>
                        ) : (
                          mostRecent.source_file || "unknown"
                        )}{" "}
                        • {formatDate(mostRecent.date)}
                      </p>
                      {(mostRecent.dosage_value != null ||
                        mostRecent.frequency_per_day != null) && (
                        <p className="text-[11px] text-slate-400">
                          Standard dose:{" "}
                          {mostRecent.dosage_value != null && mostRecent.dosage_unit
                            ? `${mostRecent.dosage_value} ${mostRecent.dosage_unit}`
                            : "—"}
                          {mostRecent.frequency_per_day != null
                            ? ` • ${mostRecent.frequency_per_day}×/day`
                            : ""}
                          {mostRecent.is_as_needed ? " • PRN" : ""}
                        </p>
                      )}
                    </div>

                    {historyCount > 1 && (
                      <details className="mt-3">
                        <summary className="cursor-pointer text-xs font-medium text-brand-600 hover:text-brand-700">
                          View history ({historyCount})
                        </summary>
                        <ul className="mt-2 space-y-1">
                          {entries
                            .slice()
                            .sort((a, b) => compareDates(a.date, b.date))
                            .map((e, i) => (
                              <li
                                key={i}
                                className="flex items-center gap-2 text-xs text-slate-500"
                              >
                                <span className="h-1 w-1 rounded-full bg-slate-400" />
                                {formatDate(e.date)} • {e.source_file || "unknown"} • {e.dosage}{" "}
                                {e.frequency}
                              </li>
                            ))}
                        </ul>
                      </details>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>

          <Section title={t("medicines.fullHistory")}>
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full text-sm">
                <caption className="sr-only">{t("medicines.fullHistory")}</caption>
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      {t("common.date")}
                    </th>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      {t("medicines.medicine")}
                    </th>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      {t("medicines.dose")}
                    </th>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      {t("common.source")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filtered
                    .slice()
                    .sort((a, b) => compareDates(a.date, b.date))
                    .map((med, idx) => (
                      <tr key={idx}>
                        <td className="px-4 py-2 text-xs text-slate-500">{formatDate(med.date)}</td>
                        <td className="px-4 py-2">
                          <p className="font-medium text-slate-800">{med.name}</p>
                          <p className="text-xs text-slate-500">{med.ingredients.join(", ")}</p>
                        </td>
                        <td className="px-4 py-2 text-xs text-slate-600">
                          {[med.dosage, med.frequency].filter(Boolean).join(" • ")}
                        </td>
                        <td className="px-4 py-2 text-xs text-slate-500">
                          {med.document_id ? (
                            <Link
                              to={`/documents?document=${encodeURIComponent(med.document_id)}`}
                              className="font-medium text-brand-700 underline decoration-brand-300 underline-offset-2 hover:text-brand-900"
                            >
                              {med.source_file || "—"}
                            </Link>
                          ) : (
                            med.source_file || "—"
                          )}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Section>
        </div>
      )}
    </div>
  );
}

function Header({ count }: { count: number | null }) {
  const { t, formatNumber } = useI18n();
  return (
    <header>
      <h1 className="page-title">{t("medicines.title")}</h1>
      <p className="secondary-text mt-2">
        {count != null
          ? t("medicines.subtitle", { count: formatNumber(count) })
          : t("medicines.loading")}
      </p>
    </header>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="section-title mb-3">{title}</h2>
      {children}
    </div>
  );
}
