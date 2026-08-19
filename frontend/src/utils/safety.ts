import type { CrossCheckReport, DosageReport } from "../types/api";

export type SafetyAlertKind =
  "allergy" | "interaction" | "duplicate" | "dosage" | "concurrent_duplicate" | "age_restriction";

export interface SafetyAlertSummary {
  key: string;
  kind: SafetyAlertKind;
  severity: "high" | "moderate" | "low";
  title: string;
  description: string;
  confidence?: number;
  evidenceSource?: string;
}

function normalized(value: unknown): string {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function pairKey(values: unknown[]): string {
  return values.map(normalized).filter(Boolean).sort().join("+");
}

function isLive(item: { timing?: { status?: string } }): boolean {
  return item.timing?.status !== "not_concurrent";
}

/**
 * One canonical source of truth for the dashboard, sidebar and Safety page.
 * Medication changes are deliberately excluded: a changed prescription is a
 * record insight, not automatically a safety alert.
 */
export function collectSafetyAlerts(
  report: CrossCheckReport,
  dosageReport?: DosageReport | null,
): SafetyAlertSummary[] {
  const alerts: SafetyAlertSummary[] = [];
  const guidelinePairs = new Set(
    (report.guideline_flagged_combinations || []).map((item) =>
      pairKey([item.opioid, item.depressant]),
    ),
  );

  for (const item of report.allergy_conflicts || []) {
    if (!isLive(item)) continue;
    alerts.push({
      key: `allergy:${normalized(item.medication)}:${normalized(item.allergy)}`,
      kind: "allergy",
      severity: "high",
      title: `${item.medication} conflicts with recorded allergy: ${item.allergy}`,
      description: item.explanation,
      confidence: item.confidence,
      evidenceSource: item.evidence_source,
    });
  }

  for (const item of report.guideline_flagged_combinations || []) {
    const pair = [item.opioid, item.depressant].filter(Boolean).join(" + ");
    alerts.push({
      key: `interaction:${pairKey([item.opioid, item.depressant])}`,
      kind: "interaction",
      severity: "high",
      title: pair || "Published medication-combination warning",
      description: `${item.plain || item.quote || "Published guidance flags this combination for professional review."}${item.citation?.source ? ` Source: ${item.citation.source}${item.citation.page ? `, page ${item.citation.page}` : ""}.` : ""}`,
      confidence: 0.9,
      evidenceSource: "published_reference",
    });
  }

  for (const item of report.potential_drug_interactions || []) {
    if (!isLive(item)) continue;
    const pair = pairKey(item.medications_involved || []);
    // Prefer the page-cited version when the same medication pair was also
    // emitted by the published-guidance matcher.
    if (guidelinePairs.has(pair)) continue;
    alerts.push({
      key: `interaction:${pair}`,
      kind: "interaction",
      severity: item.severity,
      title: item.medications_involved.join(" + "),
      description: item.explanation,
      confidence: item.confidence,
      evidenceSource: item.evidence_source,
    });
  }

  for (const item of report.concurrent_exposure || []) {
    const ingredient = item.ingredient || "same ingredient";
    alerts.push({
      key: `concurrent:${normalized(ingredient)}:${item.window_start || ""}:${item.window_end || ""}`,
      kind: "concurrent_duplicate",
      severity: "high",
      title: `Overlapping prescriptions: ${ingredient}`,
      description:
        item.note ||
        "Two active prescriptions supplied the same ingredient during an overlapping period.",
    });
  }

  for (const item of report.conflicting_dosage_instructions || []) {
    if (!isLive(item)) continue;
    alerts.push({
      key: `dosage:${normalized(item.medication)}`,
      kind: "dosage",
      severity: "moderate",
      title: `Conflicting instructions: ${item.medication}`,
      description: item.explanation,
      confidence: item.confidence,
      evidenceSource: item.evidence_source,
    });
  }

  for (const item of report.duplicate_prescriptions || []) {
    if (!isLive(item)) continue;
    alerts.push({
      key: `duplicate:${normalized(item.medication)}`,
      kind: "duplicate",
      severity: "moderate",
      title: `Possible duplicate prescription: ${item.medication}`,
      description: item.explanation,
      confidence: item.confidence,
      evidenceSource: item.evidence_source,
    });
  }

  for (const item of report.eml_age_conflicts || []) {
    alerts.push({
      key: `age:${normalized(item.medication)}:${normalized(item.restriction)}`,
      kind: "age_restriction",
      severity: "high",
      title: `Published age restriction: ${item.medication || "medication"}`,
      description:
        item.explanation ||
        item.restriction ||
        "A published age restriction needs professional review.",
      confidence: item.confidence,
      evidenceSource: item.evidence_source,
    });
  }

  // Only above-ceiling findings are alerts. A below-minimum rule is a
  // transcription/data-quality prompt and should not inflate Safety Alerts.
  for (const item of dosageReport?.findings || []) {
    if (!item.kind.startsWith("above_max_")) continue;
    const subject = item.medication || item.ingredient || "medication";
    alerts.push({
      key: `dosage-rule:${item.kind}:${normalized(subject)}`,
      kind: "dosage",
      severity: "high",
      title: `Dose needs review: ${subject}`,
      description:
        item.explanation ||
        "The extracted dose is above a configured adult ceiling and needs professional confirmation.",
      confidence: item.confidence,
      evidenceSource: item.source,
    });
  }

  const rank = { high: 0, moderate: 1, low: 2 };
  return [...new Map(alerts.map((item) => [item.key, item])).values()].sort(
    (a, b) => rank[a.severity] - rank[b.severity] || a.title.localeCompare(b.title),
  );
}
