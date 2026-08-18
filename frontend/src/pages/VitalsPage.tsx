import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { StatusBadge } from "../components/StatusBadge";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { RefreshIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type {
  VitalTrendsReport,
  EarlyWarningReport,
  AdherenceReport,
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

export function VitalsPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [trends, setTrends] = useState<VitalTrendsReport | null>(null);
  const [ews, setEws] = useState<EarlyWarningReport | null>(null);
  const [adh, setAdh] = useState<AdherenceReport | null>(null);
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

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tr, ew, ad, ms] = await Promise.all([
        api.getVitalTrends(credentials).catch(() => null),
        api.getEarlyWarning(credentials).catch(() => null),
        api.getAdherence(credentials).catch(() => null),
        api.listPatientMeasurements(credentials).catch(() => ({ measurements: [] })),
      ]);
      setTrends(tr);
      setEws(ew);
      setAdh(ad);
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
    if (!mName.trim() || !mValue.trim()) return;
    setSavingM(true);
    try {
      await api.recordPatientMeasurement(credentials, {
        name: mName.trim(),
        value: mValue.trim(),
        unit: mUnit.trim() || undefined,
        kind: mKind,
      });
      setMName("");
      setMValue("");
      setMUnit("");
      const ms = await api.listPatientMeasurements(credentials);
      setMeasurements(ms.measurements || []);
      // refresh trends so the new reading folds in
      setReloadKey((k) => k + 1);
    } finally {
      setSavingM(false);
    }
  }

  const noData = !trends && !ews;

  return (
    <div className="space-y-6">
      <div className="flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row">
        <div className="min-w-0">
          <h1 className="page-title">{t("vitals.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("vitals.subtitle")}</p>
        </div>
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
                  <div className="font-medium text-slate-600">
                    {c.signal.replace(/_/g, " ")}
                  </div>
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
          <CardHeader title="Possible adherence signals" />
          <CardBody className="space-y-2">
            {adh.signals.map((s, i) => (
              <div key={i} className="rounded-md border border-amber-200 bg-amber-50/50 p-2 text-xs">
                <div className="font-medium text-amber-800">
                  {s.ingredient} — {s.signal.replace(/_/g, " ")}
                </div>
                <div className="text-slate-600">{s.detail}</div>
              </div>
            ))}
            <p className="text-[11px] text-slate-400">{adh.note}</p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Record a home measurement" />
        <CardBody>
          <form onSubmit={saveMeasurement} className="flex flex-wrap items-end gap-2">
            <label className="text-xs text-slate-500">
              Name
              <input
                value={mName}
                onChange={(e) => setMName(e.target.value)}
                placeholder="Blood Pressure"
                className="mt-1 block rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-xs text-slate-500">
              Value
              <input
                value={mValue}
                onChange={(e) => setMValue(e.target.value)}
                placeholder="128/82"
                className="mt-1 block rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-xs text-slate-500">
              Unit
              <input
                value={mUnit}
                onChange={(e) => setMUnit(e.target.value)}
                placeholder="mmHg"
                className="mt-1 block rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-xs text-slate-500">
              Type
              <select
                value={mKind}
                onChange={(e) => setMKind(e.target.value)}
                className="mt-1 block rounded-md border border-slate-300 px-2 py-1 text-sm"
              >
                <option value="vital">vital</option>
                <option value="lab">lab</option>
              </select>
            </label>
            <button
              type="submit"
              disabled={savingM || !mName.trim() || !mValue.trim()}
              className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {savingM ? "Saving…" : "Save"}
            </button>
          </form>
          {measurements.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {measurements.slice(-8).map((m, i) => (
                <span
                  key={i}
                  className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
                  title={m.recorded_at}
                >
                  {m.name}: {m.value} {m.unit ?? ""}
                </span>
              ))}
            </div>
          )}
          <p className="mt-2 text-[11px] text-slate-400">
            Patient-reported measurements fold into the vital/lab analysis above.
          </p>
        </CardBody>
      </Card>

      <MedicalDisclaimer />
    </div>
  );
}
