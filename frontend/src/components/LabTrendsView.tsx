import type { LabTrend, LabTrendsReport } from "../types/api";
import { classNames, flagTone, formatConfidence } from "../utils/format";
import { Alert } from "./Alert";
import { Card, CardBody, CardHeader } from "./Card";
import { EmptyState } from "./EmptyState";
import { ChartIcon } from "./icons";
import { StatusBadge } from "./StatusBadge";

export function LabTrendsView({ report }: { report: LabTrendsReport }) {
  const hasTrends = report.trends.length > 0;
  const hasInsufficient = report.insufficient_data.length > 0;

  return (
    <Card>
      <CardHeader
        title="Lab result trends"
        description="Deterministic trend tracking across visits — direction of drift, reference-range crossings, and boundary approach."
        icon={<ChartIcon className="h-5 w-5" />}
      />
      <CardBody className="space-y-5">
        {report.note && (
          <Alert variant="info" title="Not a diagnosis">
            {report.note}
          </Alert>
        )}

        {!hasTrends && !hasInsufficient && (
          <EmptyState
            title="No lab results to trend"
            description="Upload lab reports to track how values move across visits."
          />
        )}

        {hasTrends && (
          <div className="space-y-3">
            {report.trends.map((trend, idx) => (
              <TrendCard key={idx} trend={trend} />
            ))}
          </div>
        )}

        {hasInsufficient && (
          <div>
            <h3 className="mb-2 text-sm font-semibold text-slate-700">
              Tests with insufficient data ({report.insufficient_data.length})
            </h3>
            <div className="space-y-2">
              {report.insufficient_data.map((item, idx) => (
                <div key={idx} className="rounded-md border border-slate-200 bg-slate-50/60 px-3 py-2 text-sm">
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

function TrendCard({ trend }: { trend: LabTrend }) {
  const crossed = trend.crossed_into_abnormal_at;
  const approaching = trend.approaching_threshold;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-base font-semibold text-slate-900">{trend.test_name}</h4>
            <StatusBadge tone={directionBadgeTone(trend.direction)}>{trend.direction}</StatusBadge>
            {crossed && (
              <StatusBadge tone="danger">
                crossed to {crossed.flag} on {crossed.date || "unknown date"}
              </StatusBadge>
            )}
            {approaching && !crossed && <StatusBadge tone="warning">approaching threshold</StatusBadge>}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {trend.unit && <span>unit: {trend.unit} · </span>}
            {trend.reference_range ? (
              <span>reference range: {trend.reference_range}</span>
            ) : (
              <span>no reference range provided</span>
            )}{" "}
            · confidence {formatConfidence(trend.confidence)}
          </p>
        </div>
        <Sparkline trend={trend} />
      </div>

      <p className="mt-3 text-sm text-slate-600">{trend.explanation}</p>

      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="text-left text-slate-400">
              <th className="py-1 pr-4 font-medium">Date</th>
              <th className="py-1 pr-4 font-medium">Value</th>
              <th className="py-1 pr-4 font-medium">Flag</th>
              <th className="py-1 font-medium">Source</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {trend.data_points.map((p, i) => (
              <tr key={i}>
                <td className="py-1 pr-4 text-slate-600">{p.date || "—"}</td>
                <td className="py-1 pr-4 font-medium text-slate-700">{p.value}</td>
                <td className="py-1 pr-4">
                  <span className={classNames("inline-flex rounded-full px-2 py-0.5 ring-1 ring-inset", flagTone(p.flag))}>
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
  if (direction.startsWith("increasing")) return "danger";
  if (direction.startsWith("decreasing")) return "info";
  if (direction === "stable") return "success";
  return "warning";
}

function Sparkline({ trend }: { trend: LabTrend }) {
  const W = 160;
  const H = 48;
  const PAD = 4;

  const numericPoints = trend.data_points
    .map((p) => {
      const m = /-?\d+(?:\.\d+)?/.exec(p.value);
      return m ? parseFloat(m[0]) : NaN;
    })
    .filter((v) => !Number.isNaN(v));

  if (numericPoints.length < 2) {
    return <div className="h-12 w-40 text-xs text-slate-400">Not enough numeric values to plot</div>;
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
      let low = parseFloat(m[1]);
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

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");

  return (
    <svg width={W} height={H} className="shrink-0" role="img" aria-label="Lab trend sparkline">
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
      <path d={path} fill="none" stroke="#26685b" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
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
