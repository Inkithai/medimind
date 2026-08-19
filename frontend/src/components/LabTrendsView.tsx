import { useId } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";
import type { LabTrend, LabTrendsReport, SingleLabResult } from "../types/api";
import { classNames, flagTone, formatConfidence } from "../utils/format";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";
import { EmptyState } from "./EmptyState";
import { ChartIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";

export function LabTrendsView({ report }: { report: LabTrendsReport }) {
  const { t, formatNumber } = useI18n();
  const hasTrends = report.trends.length > 0;
  const singleResults = report.single_results || [];
  const hasSingles = singleResults.length > 0;
  const hasInsufficient = report.insufficient_data.length > 0;

  return (
    <Card>
      <CardHeader
        title={t("labs.trendsTitle")}
        description={t("labs.trendsDescription")}
        icon={<ChartIcon className="h-5 w-5" />}
      />
      <CardBody className="space-y-5">
        {report.note && (
          <Alert variant="info" title={t("common.notDiagnosis")}>
            {report.note}
          </Alert>
        )}

        {!hasTrends && !hasSingles && !hasInsufficient && (
          <EmptyState title={t("labs.noTrends")} description={t("labs.noTrendsBody")} />
        )}

        {hasTrends && (
          <div className="space-y-3">
            {report.trends.map((trend, idx) => (
              <TrendCard key={idx} trend={trend} />
            ))}
          </div>
        )}

        {hasSingles && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              Single lab results ({formatNumber(singleResults.length)})
            </h3>
            <p className="mb-3 text-xs text-slate-500">
              These have one usable reading, so no trend is calculated. When safe, the backend
              compares the value with the printed reference range or a conservative general
              interval.
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              {singleResults.map((item, idx) => (
                <SingleResultCard key={idx} item={item} />
              ))}
            </div>
          </div>
        )}

        {hasInsufficient && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              {t("labs.insufficient", { count: formatNumber(report.insufficient_data.length) })}
            </h3>
            <div className="space-y-2">
              {report.insufficient_data.map((item, idx) => (
                <div
                  key={idx}
                  className="rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2 text-sm"
                >
                  <p className="font-medium text-slate-700">{item.test_name}</p>
                  <p className="text-xs text-slate-500">{item.reason}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function lastFlag(trend: LabTrend): string {
  const points = trend.data_points || [];
  return points.length ? points[points.length - 1].flag : "";
}

function recovered(trend: LabTrend): boolean {
  if (typeof trend.returned_to_normal === "boolean") return trend.returned_to_normal;
  // Old snapshots omit the field — a last-reading "normal" after a recorded
  // crossing is a recovery, not an ongoing alarm.
  return Boolean(trend.crossed_into_abnormal_at) && lastFlag(trend) === "normal";
}

function SingleResultCard({ item }: { item: SingleLabResult }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-slate-900">{item.test_name}</p>
          <p className="mt-0.5 text-xs text-slate-500">
            {item.date || "unknown date"} · {item.source_file || "unknown source"}
            {item.range_source ? ` · range: ${item.range_source}` : ""}
          </p>
        </div>
        <StatusBadge
          tone={
            item.status === "normal"
              ? "success"
              : item.status === "high"
                ? "danger"
                : item.status === "low"
                  ? "info"
                  : "neutral"
          }
        >
          {item.status}
        </StatusBadge>
      </div>
      <p className="mt-2 text-sm text-slate-700">
        <span className="font-medium">Value:</span> {item.value ?? "—"}
        {item.unit ? ` ${item.unit}` : ""}
      </p>
      {item.reference_range && (
        <p className="mt-1 text-xs text-slate-500">Reference: {item.reference_range}</p>
      )}
      <p className="mt-2 text-xs leading-relaxed text-slate-600">{item.explanation}</p>
      {typeof item.confidence === "number" && (
        <p className="mt-2 text-[11px] text-slate-500">
          confidence {formatConfidence(item.confidence)}
        </p>
      )}
    </div>
  );
}

function TrendCard({ trend }: { trend: LabTrend }) {
  const { t } = useI18n();
  const crossed = trend.crossed_into_abnormal_at;
  const approaching = trend.approaching_threshold;
  const isRecovered = recovered(trend);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-base font-semibold text-slate-900">{trend.test_name}</h4>
            <StatusBadge tone={directionBadgeTone(trend.direction)}>{trend.direction}</StatusBadge>
            {crossed && isRecovered && (
              <StatusBadge tone="success">
                returned to normal (was {crossed.flag} on {crossed.date || "unknown date"})
              </StatusBadge>
            )}
            {crossed && !isRecovered && (
              <StatusBadge tone="danger">
                crossed to {crossed.flag} on {crossed.date || "unknown date"}
              </StatusBadge>
            )}
            {approaching && !crossed && (
              <StatusBadge tone="warning">{t("labs.approaching")}</StatusBadge>
            )}
            {trend.risk_level && trend.risk_level !== "none" && (
              <StatusBadge tone={trend.risk_level === "high" ? "danger" : "warning"}>
                {t("labs.risk", { level: trend.risk_level })}
              </StatusBadge>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {trend.unit && <span>unit: {trend.unit} · </span>}
            {trend.reference_range ? (
              <span>reference range: {trend.reference_range}</span>
            ) : (
              <span>{t("labs.noRange")}</span>
            )}{" "}
            · confidence {formatConfidence(trend.confidence)}
          </p>
        </div>
        <Sparkline trend={trend} />
      </div>

      <p className="mt-3 text-sm text-slate-600">{trend.explanation}</p>
      {trend.risk_reason && trend.risk_level !== "none" && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p>
            <span className="font-semibold">{t("labs.safetyObservation")}:</span>{" "}
            {trend.risk_reason}
          </p>
          {trend.professional_review_recommended && (
            <Link
              to="/find-care?from=lab-trend"
              className="mt-2 inline-flex font-semibold text-brand-700 hover:underline"
            >
              {t("safety.findCare")} →
            </Link>
          )}
        </div>
      )}
      {trend.confidence < 0.6 && (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p>
            <span className="font-semibold">{t("labs.lowConfidence")}:</span>{" "}
            {t("common.medicalDisclaimer")}
          </p>
          <Link
            to="/find-care?from=low-confidence-lab"
            className="mt-2 inline-flex font-semibold text-brand-700 hover:underline"
          >
            {t("labs.verify")} →
          </Link>
        </div>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full text-xs">
          <caption className="sr-only">{t("labs.tableCaption", { test: trend.test_name })}</caption>
          <thead>
            <tr className="text-left text-slate-400">
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("common.date")}
              </th>
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("common.value")}
              </th>
              <th scope="col" className="py-1 pr-4 font-medium">
                {t("common.flag")}
              </th>
              <th scope="col" className="py-1 font-medium">
                {t("common.source")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {trend.data_points.map((p, i) => (
              <tr key={i}>
                <td className="py-1 pr-4 text-slate-600">{p.date || "—"}</td>
                <td className="py-1 pr-4 font-medium text-slate-700">{p.value}</td>
                <td className="py-1 pr-4">
                  <span
                    className={classNames(
                      "inline-flex rounded-full px-2 py-0.5 ring-1 ring-inset",
                      flagTone(p.flag),
                    )}
                  >
                    {p.flag}
                  </span>
                </td>
                <td className="py-1 text-slate-500">{p.source_file || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function directionBadgeTone(direction: string): "danger" | "info" | "success" | "warning" {
  if (direction.includes("increasing")) return "danger";
  if (direction.includes("decreasing")) return "info";
  if (direction === "stable") return "success";
  return "warning";
}

function parseLabNumber(value: string): number | null {
  // Consume thousands separators so "150,000" is 150000, not 150.
  const match = /-?\d[\d,.]*/.exec(String(value ?? ""));
  if (!match) return null;
  let token = match[0].replace(/[.,]+$/, "");
  if (!token || token === "-") return null;
  const hasComma = token.includes(",");
  const hasDot = token.includes(".");
  if (hasComma && hasDot) {
    token =
      token.lastIndexOf(",") > token.lastIndexOf(".")
        ? token.replace(/\./g, "").replace(",", ".")
        : token.replace(/,/g, "");
  } else if (hasComma) {
    const parts = token.replace(/^-/, "").split(",");
    token =
      parts.length > 1 && parts.slice(1).every((p) => p.length === 3 && /^\d+$/.test(p))
        ? token.replace(/,/g, "")
        : token.replace(",", ".").replace(/,/g, "");
  }
  const n = Number(token);
  return Number.isFinite(n) ? n : null;
}

function Sparkline({ trend }: { trend: LabTrend }) {
  const { t, formatNumber } = useI18n();
  const titleId = useId();
  const descriptionId = useId();
  const W = 160;
  const H = 48;
  const PAD = 4;

  const numericPoints = trend.data_points
    .map((p) => parseLabNumber(p.value))
    .filter((v): v is number => v !== null);

  if (numericPoints.length < 2) {
    return <div className="h-12 w-40 text-xs text-slate-600">{t("labs.plotUnavailable")}</div>;
  }

  let min = Math.min(...numericPoints);
  let max = Math.max(...numericPoints);
  if (min === max) {
    min -= 1;
    max += 1;
  }

  // Robust range parsing: handles "70-99", "70 - 99 mg/dL", "Reference: 0.74-1.35 mg/dL"
  const rangeStr = trend.reference_range || "";
  let refLow = NaN;
  let refHigh = NaN;
  const strictMatch = /^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$/.exec(rangeStr);
  if (strictMatch) {
    refLow = parseFloat(strictMatch[1]);
    refHigh = parseFloat(strictMatch[2]);
  } else {
    const m = /(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)/.exec(rangeStr);
    if (m) {
      const low = parseFloat(m[1]);
      let high = parseFloat(m[2]);
      if (low >= 0 && high < 0) {
        const cleaned = rangeStr.replace(/\s/g, "");
        if (cleaned.includes(`${m[1]}-${Math.abs(high)}`)) {
          high = Math.abs(high);
        }
      }
      refLow = low;
      refHigh = high;
    }
  }

  if (!Number.isNaN(refLow) && !Number.isNaN(refHigh)) {
    min = Math.min(min, refLow);
    max = Math.max(max, refHigh);
  }

  const xStep = (W - PAD * 2) / (numericPoints.length - 1);
  const yFor = (v: number) => H - PAD - ((v - min) / (max - min || 1)) * (H - PAD * 2);

  const points = numericPoints.map((v, i) => ({
    x: PAD + i * xStep,
    y: yFor(v),
    flag: trend.data_points[i]?.flag || "unknown",
  }));

  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");

  return (
    <svg
      width={W}
      height={H}
      className="shrink-0"
      role="img"
      aria-labelledby={`${titleId} ${descriptionId}`}
    >
      <title id={titleId}>{t("labs.chartLabel", { test: trend.test_name })}</title>
      <desc id={descriptionId}>
        {t("labs.chartDescription", {
          count: formatNumber(numericPoints.length),
          direction: trend.direction,
          range: trend.reference_range || t("common.notAvailable"),
        })}
      </desc>
      {!Number.isNaN(refLow) && !Number.isNaN(refHigh) && (
        <rect
          x={PAD}
          y={yFor(refHigh)}
          width={W - PAD * 2}
          height={Math.max(0, yFor(refLow) - yFor(refHigh))}
          fill="#d1fae5"
          opacity={0.6}
        />
      )}
      <path
        d={path}
        fill="none"
        stroke="#26685b"
        strokeWidth={1.8}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={2.5}
          fill={p.flag === "high" ? "#dc2626" : p.flag === "low" ? "#2563eb" : "#26685b"}
        />
      ))}
    </svg>
  );
}
