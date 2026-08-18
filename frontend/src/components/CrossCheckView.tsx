import { Link } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";
import type { CrossCheckReport, DosageReport, MedicationTransition, SourceReference } from "../types/api";
import { formatConfidence, severityTone } from "../utils/format";
import { collectSafetyAlerts } from "../utils/safety";
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
  titleKey: string;
  tone: "danger" | "warning" | "info";
}

const SECTIONS: Section[] = [
  { key: "allergy_conflicts", titleKey: "safety.allergy", tone: "danger" },
  { key: "potential_drug_interactions", titleKey: "safety.interactions", tone: "warning" },
  { key: "conflicting_dosage_instructions", titleKey: "safety.dosage", tone: "warning" },
  { key: "duplicate_prescriptions", titleKey: "safety.duplicates", tone: "info" },
];

export function CrossCheckView({ report, dosageReport }: { report: CrossCheckReport; dosageReport?: DosageReport | null }) {
  const { t, formatNumber } = useI18n();
  const canonicalAlerts = collectSafetyAlerts(report, dosageReport);
  const totalIssues = canonicalAlerts.length;
  const continuations = report.medication_continuations || [];
  const supplementalKinds = new Set(["concurrent_duplicate", "age_restriction"]);
  const supplementalAlerts = canonicalAlerts.filter((item) =>
    supplementalKinds.has(item.kind) || item.evidenceSource === "published_reference" ||
    (item.kind === "dosage" && item.key.startsWith("dosage-rule:"))
  );
  const guidelinePairs = new Set(
    (report.guideline_flagged_combinations || []).map((item) =>
      [item.opioid, item.depressant].map((value) => String(value || "").trim().toLowerCase()).sort().join("+")
    )
  );
  const displayReport: CrossCheckReport = {
    ...report,
    potential_drug_interactions: report.potential_drug_interactions.filter((item) =>
      item.timing?.status !== "not_concurrent" && !guidelinePairs.has(
        item.medications_involved.map((value) => value.trim().toLowerCase()).sort().join("+")
      )
    ),
    duplicate_prescriptions: report.duplicate_prescriptions.filter((item) => item.timing?.status !== "not_concurrent"),
    conflicting_dosage_instructions: report.conflicting_dosage_instructions.filter((item) => item.timing?.status !== "not_concurrent"),
    allergy_conflicts: report.allergy_conflicts.filter((item) => item.timing?.status !== "not_concurrent"),
  };
  const hasLowConfidence = canonicalAlerts.some(
    (item) => typeof item.confidence === "number" && item.confidence < 0.6
  );
  const hasHighRisk = canonicalAlerts.some((item) => item.severity === "high");

  return (
    <Card>
      <CardHeader
        title={t("safety.title")}
        description={totalIssues === 0 ? t("safety.noIssuesBody") : `${formatNumber(totalIssues)} · ${t("safety.subtitle")}`}
        icon={<ShieldIcon className="h-5 w-5" />}
      />
      <CardBody className="space-y-5">
        {totalIssues > 0 && report.overall_recommendation && (
          <Alert variant="warning" title={t("safety.recommendation")}>
            {report.overall_recommendation}
          </Alert>
        )}

        {hasHighRisk && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
            <p className="font-semibold">{t("safety.highRisk")}</p>
            <p className="mt-1">{t("safety.highRiskBody")}</p>
            <Link to="/find-care?from=safety" className="mt-2 inline-flex font-semibold text-brand-700 hover:underline">
              {t("safety.findCare")} →
            </Link>
          </div>
        )}

        {hasLowConfidence && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <p className="font-semibold">{t("safety.lowConfidence")}</p>
            <p className="mt-1">{t("safety.lowConfidenceBody")}</p>
            <Link to="/find-care?from=low-confidence-safety" className="mt-2 inline-flex font-semibold text-brand-700 hover:underline">
              {t("safety.verify")} →
            </Link>
          </div>
        )}

        {totalIssues === 0 ? (
          <EmptyState
            title={t("safety.noIssues")}
            description="No active medication interactions, duplicate prescriptions, above-ceiling doses, allergy conflicts, or applicable age restrictions were detected. This screening is limited to the uploaded records and configured rules."
          />
        ) : (
          <>
            {SECTIONS.map((section) => (
              <IssueSection key={section.key} report={displayReport} section={section} />
            ))}
            {supplementalAlerts.length > 0 && <CanonicalAlertSection items={supplementalAlerts} />}
          </>
        )}

        {(report.medication_changes?.length || 0) > 0 && (
          <TransitionSection
            title="Medication record changes (not automatically safety alerts)"
            items={report.medication_changes || []}
            tone="warning"
          />
        )}

        {continuations.length > 0 && (
          <TransitionSection
            title={t("safety.continuations")}
            items={continuations}
            tone="info"
          />
        )}
      </CardBody>
    </Card>
  );
}

function IssueSection({ report, section }: { report: CrossCheckReport; section: Section }) {
  const { t, formatNumber } = useI18n();
  const items = report[section.key] || [];
  if (items.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{t(section.titleKey)}</h3>
        <StatusBadge tone={section.tone}>{formatNumber(items.length)}</StatusBadge>
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
                  {t("safety.severity", { level: item.severity })}
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
                    {o.page ? `, page ${o.page}` : ""}
                    {o.dosage ? ` — ${o.dosage}` : ""}
                  </li>
                ))}
              </ul>
            )}

            {"conflicting_instructions" in item && item.conflicting_instructions.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-slate-500">
                {item.conflicting_instructions.map((o, i) => (
                  <li key={i}>
                    · {o.date || "undated"} — {o.source_file || "unknown file"}
                    {o.page ? `, page ${o.page}` : ""} —{" "}
                    {[o.dosage, o.frequency].filter(Boolean).join(", ")}
                  </li>
                ))}
              </ul>
            )}

            {"sources" in item && Boolean(item.sources?.length) && (
              <SourceList sources={item.sources || []} />
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

function CanonicalAlertSection({ items }: { items: ReturnType<typeof collectSafetyAlerts> }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Additional deterministic safety checks</h3>
        <StatusBadge tone="warning">{items.length}</StatusBadge>
      </div>
      <div className="space-y-2">
        {items.map((item) => (
          <div key={item.key} className="rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={item.severity === "high" ? "danger" : item.severity === "moderate" ? "warning" : "info"}>
                {item.severity}
              </StatusBadge>
              <p className="text-sm font-semibold text-slate-800">{item.title}</p>
            </div>
            <p className="mt-1 text-sm text-slate-600">{item.description}</p>
            {item.evidenceSource && <p className="mt-2 text-xs text-slate-500">Evidence: {item.evidenceSource.replace(/_/g, " ")}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

function TransitionSection({
  title,
  items,
  tone,
}: {
  title: string;
  items: MedicationTransition[];
  tone: "warning" | "info";
}) {
  const { t, formatNumber } = useI18n();
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        <StatusBadge tone={tone}>{formatNumber(items.length)}</StatusBadge>
      </div>
      <div className="space-y-2">
        {items.map((item, index) => (
          <div key={`${item.medication}-${index}`} className="rounded-lg border border-slate-200 bg-slate-50/60 px-4 py-3">
            <p className="text-sm font-semibold text-slate-800">{item.medication}</p>
            {item.changed_fields?.length ? (
              <p className="mt-1 text-xs font-medium text-amber-700">
                {t("safety.changed", { fields: item.changed_fields.join(", ") })}
              </p>
            ) : (
              <p className="mt-1 text-xs font-medium text-sky-800">{t("safety.same")}</p>
            )}
            <div className="mt-2 grid gap-2 text-xs text-slate-600 sm:grid-cols-2">
              <p><span className="font-semibold">{t("safety.earlier")}:</span> {[item.previous.dosage, item.previous.frequency].filter(Boolean).join(" · ") || "not specified"}</p>
              <p><span className="font-semibold">{t("safety.later")}:</span> {[item.current.dosage, item.current.frequency].filter(Boolean).join(" · ") || "not specified"}</p>
            </div>
            <p className="mt-2 text-sm text-slate-600">{item.explanation}</p>
            <SourceList sources={item.sources} />
            <p className="mt-2 text-xs text-slate-400">confidence {formatConfidence(item.confidence)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SourceList({ sources }: { sources: SourceReference[] }) {
  const { t } = useI18n();
  if (!sources.length) return null;
  return (
    <ul className="mt-2 space-y-1 text-xs text-slate-600" aria-label={t("common.sources")}>
      {sources.map((source, index) => (
        <li key={`${source.source_file}-${source.page || 0}-${index}`}>
          · {source.date || "undated"} — {source.source_file || "unknown file"}
          {source.page ? `, page ${source.page}` : ""}
        </li>
      ))}
    </ul>
  );
}
