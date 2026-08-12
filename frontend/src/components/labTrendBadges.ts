import type { LabTrend } from "../types/api";

export type TrendAlertBadge = {
  tone: "danger" | "success" | "warning";
  label: string;
};

type BadgeSource = Pick<
  LabTrend,
  "crossed_into_abnormal_at" | "approaching_threshold" | "returned_to_normal" | "data_points"
>;

/**
 * A recovery is the most reassuring pattern in the data (abnormal, then
 * back to normal). The API now ships `returned_to_normal`, but snapshots
 * saved before that field existed still populate `crossed_into_abnormal_at`
 * and the UI used to render that as an unconditional red alarm sitting
 * above a paragraph that said the patient had recovered.
 *
 * Gate on the explicit flag when present; otherwise fall back to the
 * latest reading's flag so old payloads don't keep showing a red badge.
 */
export function isRecoveredTrend(trend: BadgeSource): boolean {
  if (trend.returned_to_normal === true) return true;
  if (trend.returned_to_normal === false) return false;
  const last = trend.data_points[trend.data_points.length - 1];
  return Boolean(trend.crossed_into_abnormal_at && last && last.flag === "normal");
}

export function trendAlertBadges(trend: BadgeSource): TrendAlertBadge[] {
  const badges: TrendAlertBadge[] = [];
  const crossed = trend.crossed_into_abnormal_at;
  const recovered = isRecoveredTrend(trend);

  if (recovered) {
    if (crossed) {
      badges.push({
        tone: "success",
        label: `returned to normal (was ${crossed.flag} on ${crossed.date || "unknown date"})`,
      });
    } else {
      badges.push({ tone: "success", label: "returned to normal" });
    }
  } else if (crossed) {
    badges.push({
      tone: "danger",
      label: `crossed to ${crossed.flag} on ${crossed.date || "unknown date"}`,
    });
  }

  if (trend.approaching_threshold && !crossed && !recovered) {
    badges.push({ tone: "warning", label: "approaching threshold" });
  }

  return badges;
}
