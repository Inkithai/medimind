import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { Spinner } from "../components/Spinner";
import { toastMessage, useToast } from "../components/Toast";
import { PlusIcon, RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import { formatDate } from "../utils/format";
import type { EmbeddedPageProps } from "../components/TabBar";
import type {
  VitalTrendsReport,
  EarlyWarningReport,
  AdherenceReport,
  AdherenceSignal,
  DeteriorationReport,
  PatientMeasurement,
} from "../types/api";

const FLAG_TONE: Record<string, "danger" | "warning" | "success" | "neutral"> = {
  high: "danger",
  low: "danger",
  borderline: "warning",
};

const RISK_BAND_TONE: Record<string, "danger" | "warning" | "success" | "neutral"> = {
  high: "danger",
  medium: "warning",
  low: "neutral",
  none: "success",
};

const ADHERENCE_SIGNAL_LABEL: Record<string, string> = {
  refill_gap: "Possible gap in refills",
  late_refill: "Possible late refill",
  apparent_stop: "May have stopped",
};

// The backend emits one signal per gap plus one "may have stopped" per
// medicine, so a medicine can legitimately appear more than once. This
// collapses only EXACT repeats (same medicine, signal and dates) that a
// re-upload can introduce, so the list never shows the same line twice.
function dedupeAdherenceSignals(signals: AdherenceSignal[]): AdherenceSignal[] {
  const seen = new Set<string>();
  return signals.filter((signal) => {
    const key = [
      signal.ingredient,
      signal.signal,
      signal.gap_days ?? "",
      (signal.between || []).join("|"),
      signal.last_supply ?? "",
    ].join("::");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function VitalsPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const { toastSuccess, toastError } = useToast();
  const [trends, setTrends] = useState<VitalTrendsReport | null>(null);
  const [ews, setEws] = useState<EarlyWarningReport | null>(null);
  const [adh, setAdh] = useState<AdherenceReport | null>(null);
  const [deterioration, setDeterioration] = useState<DeteriorationReport | null>(null);
  const [measurements, setMeasurements] = useState<PatientMeasurement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // PGHD entry form
  const [mName, setMName] = useState("");
  const [mValue, setMValue] = useState("");
  const [mUnit, setMUnit] = useState("");
  const [mKind, setMKind] = useState("vital");
  const [savingM, setSavingM] = useState(false);
  const [measurementError, setMeasurementError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tr, ew, ad, det, ms] = await Promise.all([
        api.getVitalTrends(credentials).catch(() => null),
        api.getEarlyWarning(credentials).catch(() => null),
        api.getAdherence(credentials).catch(() => null),
        // Longitudinal early-warning trajectory across every dated reading.
        api.getDeterioration(credentials).catch(() => null),
        api.listPatientMeasurements(credentials).catch(() => ({ measurements: [] })),
      ]);
      setTrends(tr);
      setEws(ew);
      setAdh(ad);
      setDeterioration(det);
      setMeasurements(ms.measurements || []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load, reloadKey]);

  async function saveMeasurement(e: React.FormEvent) {
    e.preventDefault();
    if (!mName.trim() || !mValue.trim()) {
      setMeasurementError("Please fill in both the measurement name and the reading.");
      return;
    }
    setSavingM(true);
    setMeasurementError(null);
    try {
      await api.recordPatientMeasurement(credentials, {
        name: mName.trim(),
        value: mValue.trim(),
        unit: mUnit.trim() || undefined,
        kind: mKind,
      });
      toastSuccess(
        "Reading saved",
        `${mName.trim()} ${mValue.trim()}${mUnit.trim() ? ` ${mUnit.trim()}` : ""} was added to your record.`,
      );
      setMName("");
      setMValue("");
      setMUnit("");
      const ms = await api.listPatientMeasurements(credentials);
      setMeasurements(ms.measurements || []);
      // refresh trends so the new reading folds in
      setReloadKey((k) => k + 1);
    } catch (err) {
      setMeasurementError(toastMessage(err));
      toastError("Reading not saved", toastMessage(err));
    } finally {
      setSavingM(false);
    }
  }

  const noData = !trends && !ews;

  return (
    <div className="space-y-6">
      <div className="flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row">
        {embedded ? (
          <div className="min-w-0" />
        ) : (
          <div className="min-w-0">
            <h1 className="page-title">{t("vitals.title")}</h1>
            <p className="secondary-text mt-2 max-w-2xl">{t("vitals.subtitle")}</p>
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
        <ErrorState error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && noData && (
        <Card>
          <CardBody>
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <p className="text-sm font-semibold text-slate-700">No vitals on record yet</p>
              <Link
                to="/upload"
                className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              >
                <UploadIcon className="h-4 w-4" /> Upload a report
              </Link>
            </div>
          </CardBody>
        </Card>
      )}

      {!loading && deterioration && deterioration.point_count > 0 && (
        <DeteriorationCard report={deterioration} />
      )}

      {!loading && ews && (
        <Card>
          <CardHeader title="Early-warning screen" />
          <CardBody className="space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-3xl font-bold text-slate-800">{ews.score}</span>
              <span className="text-sm text-slate-400">/ {ews.max_possible}</span>
              <StatusBadge tone={RISK_BAND_TONE[ews.risk_band] ?? "neutral"}>
                {ews.risk_band} risk
              </StatusBadge>
            </div>
            <p className="text-sm text-slate-600">{ews.advice}</p>
            <div className="grid gap-2 sm:grid-cols-3">
              {ews.components.map((c) => (
                <div key={c.signal} className="rounded-md border border-slate-200 p-2 text-xs">
                  <div className="font-medium text-slate-600">{c.signal.replace(/_/g, " ")}</div>
                  <div className="text-slate-500">
                    {c.value ?? "—"} · {c.points}/{c.max_points} pts
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-slate-400">{ews.note}</p>
          </CardBody>
        </Card>
      )}

      {!loading && trends && trends.trends.length > 0 && (
        <Card>
          <CardHeader title="Vital-sign trends" />
          <CardBody className="space-y-3">
            {trends.trends.map((tr) => (
              <div key={tr.vital} className="rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-slate-700">{tr.display_name}</div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-slate-500">
                      latest {tr.latest} {tr.unit ?? ""}
                    </span>
                    {tr.latest_flag && (
                      <StatusBadge tone={FLAG_TONE[tr.latest_flag] ?? "neutral"}>
                        {tr.latest_flag}
                      </StatusBadge>
                    )}
                    <StatusBadge tone="neutral">{tr.direction.replace(/_/g, " ")}</StatusBadge>
                  </div>
                </div>
                <p className="mt-1 text-xs text-slate-500">{tr.explanation}</p>
                <div className="mt-1 flex flex-wrap gap-1 text-[11px] text-slate-400">
                  {tr.data_points.map((p, i) => (
                    <span key={i} className="rounded bg-slate-50 px-1.5 py-0.5">
                      {p.date ? p.date.slice(0, 10) : "?"}: {p.value}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      {!loading && adh && adh.signals.length > 0 && (
        <Card>
          <CardHeader
            title="Possible adherence signals"
            description="Patterns in how a medicine was supplied that may be worth asking about. They do not say whether you took the medicine or not."
          />
          <CardBody className="space-y-2">
            {dedupeAdherenceSignals(adh.signals).map((s, i) => (
              <div
                key={`${s.ingredient}-${s.signal}-${i}`}
                className="rounded-md border border-amber-200 bg-amber-50/50 p-2 text-xs"
              >
                <div className="font-medium text-amber-800">
                  {s.ingredient} — {ADHERENCE_SIGNAL_LABEL[s.signal] || s.signal.replace(/_/g, " ")}
                </div>
                <div className="text-slate-600">{s.detail}</div>
              </div>
            ))}
            <p className="text-[11px] text-slate-400">{adh.note}</p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Record a reading you took at home"
          description="Blood pressure, weight, blood sugar — anything you measure yourself. Saved readings are included in the trends above."
        />
        <CardBody>
          <form onSubmit={saveMeasurement} className="space-y-4" noValidate>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <label className="block text-base font-semibold text-slate-800">
                What did you measure? <span className="text-red-600">*</span>
                <input
                  value={mName}
                  onChange={(e) => setMName(e.target.value)}
                  placeholder="Blood pressure"
                  required
                  aria-describedby="measurement-name-help"
                  className="input mt-1 text-base"
                />
                <span
                  id="measurement-name-help"
                  className="mt-1 block text-sm font-normal text-slate-600"
                >
                  For example: Blood pressure, Weight
                </span>
              </label>
              <label className="block text-base font-semibold text-slate-800">
                The reading <span className="text-red-600">*</span>
                <input
                  value={mValue}
                  onChange={(e) => setMValue(e.target.value)}
                  placeholder="128/82"
                  required
                  aria-describedby="measurement-value-help"
                  className="input mt-1 text-base"
                />
                <span
                  id="measurement-value-help"
                  className="mt-1 block text-sm font-normal text-slate-600"
                >
                  Exactly as it appears on your device
                </span>
              </label>
              <label className="block text-base font-semibold text-slate-800">
                Unit (optional)
                <input
                  value={mUnit}
                  onChange={(e) => setMUnit(e.target.value)}
                  placeholder="mmHg"
                  className="input mt-1 text-base"
                />
                <span className="mt-1 block text-sm font-normal text-slate-600">
                  mmHg, kg, mg/dL…
                </span>
              </label>
              <label className="block text-base font-semibold text-slate-800">
                Kind of reading
                <select
                  value={mKind}
                  onChange={(e) => setMKind(e.target.value)}
                  className="input mt-1 text-base"
                >
                  <option value="vital">Vital sign (blood pressure, pulse…)</option>
                  <option value="lab">Lab value (sugar, cholesterol…)</option>
                </select>
                <span className="mt-1 block text-sm font-normal text-slate-600">
                  Helps MediMind chart it correctly
                </span>
              </label>
            </div>

            {measurementError && (
              <p
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-base font-medium text-red-800"
              >
                {measurementError}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={savingM || !mName.trim() || !mValue.trim()}
                className="btn-primary disabled:cursor-not-allowed"
                title={
                  !mName.trim() || !mValue.trim()
                    ? "Fill in what you measured and the reading first"
                    : "Save this reading to your record"
                }
              >
                {savingM ? (
                  <Spinner className="h-5 w-5" />
                ) : (
                  <PlusIcon className="h-5 w-5" aria-hidden="true" />
                )}
                {savingM ? "Saving your reading…" : "Save this reading"}
              </button>
              {(!mName.trim() || !mValue.trim()) && (
                <p className="text-sm text-slate-600">
                  Fill in the two boxes marked <span className="font-semibold text-red-600">*</span>{" "}
                  to save.
                </p>
              )}
            </div>
          </form>

          {measurements.length > 0 ? (
            <div className="mt-6">
              <h3 className="text-base font-semibold text-slate-900">Your recent readings</h3>
              <div className="mt-2 overflow-x-auto rounded-xl border border-slate-200">
                <table className="min-w-full text-left text-base">
                  <caption className="sr-only">Home readings you have saved</caption>
                  <thead className="bg-slate-50 text-sm uppercase tracking-wide text-slate-600">
                    <tr>
                      <th scope="col" className="px-4 py-3 font-semibold">
                        Measurement
                      </th>
                      <th scope="col" className="px-4 py-3 font-semibold">
                        Reading
                      </th>
                      <th scope="col" className="px-4 py-3 font-semibold">
                        Saved on
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {measurements
                      .slice(-8)
                      .reverse()
                      .map((m, i) => (
                        <tr key={`${m.name}-${m.recorded_at}-${i}`} className="hover:bg-slate-50">
                          <th
                            scope="row"
                            className="px-4 py-3 text-left font-medium text-slate-800"
                          >
                            {m.name}
                          </th>
                          <td className="px-4 py-3 text-slate-700">
                            {m.value} {m.unit ?? ""}
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {m.recorded_at ? formatDate(m.recorded_at) : "—"}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="mt-4 text-base text-slate-600">
              You have not saved any home readings yet. Anything you add here is kept with your
              private records.
            </p>
          )}
        </CardBody>
      </Card>

      <MedicalDisclaimer />
    </div>
  );
}

/**
 * "Is this getting better or worse?" — the deterioration trajectory
 * (GET /api/v1/deterioration), which had no screen before.
 *
 * The backend scores every dated set of readings and reports the trend,
 * whether the score stayed high across consecutive readings, and which
 * signals worsened. The direction is stated in words and with an arrow
 * symbol, never by colour alone.
 */
function DeteriorationCard({ report }: { report: DeteriorationReport }) {
  const TREND_VIEW: Record<
    string,
    { label: string; tone: "danger" | "warning" | "success" | "neutral"; symbol: string }
  > = {
    worsening: { label: "Getting worse", tone: "danger", symbol: "▲" },
    improving: { label: "Getting better", tone: "success", symbol: "▼" },
    stable: { label: "Staying about the same", tone: "neutral", symbol: "▬" },
    insufficient_data: {
      label: "Not enough dated readings yet",
      tone: "neutral",
      symbol: "•",
    },
  };
  const trend = TREND_VIEW[report.trend] || {
    label: report.trend.replace(/_/g, " "),
    tone: "neutral" as const,
    symbol: "•",
  };
  const recent = report.trajectory.slice(-6);

  return (
    <Card className={report.deteriorating ? "border-2 border-red-300" : undefined}>
      <CardHeader
        title="Is this getting better or worse?"
        description="Compares your dated readings over time, not just the latest one."
        action={
          <StatusBadge tone={trend.tone}>
            <span aria-hidden="true" className="font-bold">
              {trend.symbol}
            </span>
            {trend.label}
          </StatusBadge>
        }
      />
      <CardBody className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-medium text-slate-600">Latest score</p>
            <p className="text-2xl font-bold text-slate-900">{report.latest_score}</p>
            <p className="text-sm text-slate-600">{report.latest_band} concern level</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-medium text-slate-600">Previous score</p>
            <p className="text-2xl font-bold text-slate-900">{report.previous_score ?? "—"}</p>
            <p className="text-sm text-slate-600">{report.point_count} readings compared</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
            <p className="text-sm font-medium text-slate-600">Highest so far</p>
            <p className="text-2xl font-bold text-slate-900">{report.peak_score}</p>
            <p className="text-sm text-slate-600">
              {report.sustained_high ? "Stayed high more than once" : "No sustained high period"}
            </p>
          </div>
        </div>

        {report.worsening_signals.length > 0 && (
          <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-4">
            <p className="text-base font-semibold text-amber-900">What got worse</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-base text-amber-900">
              {report.worsening_signals.map((signal) => (
                <li key={signal}>{signal.replace(/_/g, " ")}</li>
              ))}
            </ul>
          </div>
        )}

        {recent.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="min-w-full text-left text-base">
              <caption className="sr-only">Recent early-warning scores by date</caption>
              <thead className="bg-slate-50 text-sm uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Date
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Score
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Concern level
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recent.map((point, index) => (
                  <tr key={`${point.date}-${index}`} className="hover:bg-slate-50">
                    <th scope="row" className="px-4 py-3 text-left font-medium text-slate-800">
                      {point.date ? formatDate(point.date) : "Undated"}
                    </th>
                    <td className="px-4 py-3 text-slate-700">{point.score}</td>
                    <td className="px-4 py-3">
                      <StatusBadge tone={RISK_BAND_TONE[point.risk_band] ?? "neutral"}>
                        {point.risk_band}
                      </StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-sm leading-relaxed text-slate-600">{report.note}</p>
      </CardBody>
    </Card>
  );
}
