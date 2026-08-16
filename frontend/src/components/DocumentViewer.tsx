import { forwardRef, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useI18n } from "../i18n/I18nContext";
import type { EvidenceRegion, Visit } from "../types/api";
import { documentTypeLabel, formatConfidence, formatDate } from "../utils/format";
import { StatusBadge } from "./StatusBadge";
import { BeakerIcon, FileIcon, LinkIcon, PillIcon } from "./icons";
import { CorrectionEditor } from "./CorrectionEditor";
import { EvidenceViewer } from "./EvidenceViewer";

export function DocumentViewer({
  visit,
  onClose,
  onUpdated,
  initialEvidenceId,
}: {
  visit: Visit;
  onClose?: () => void;
  onUpdated?: () => void;
  initialEvidenceId?: string | null;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"original" | "structured" | "correct">("structured");
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRegion | null>(null);
  const titleId = useId();
  const originalTabId = useId();
  const structuredTabId = useId();
  const correctTabId = useId();
  const originalPanelId = useId();
  const structuredPanelId = useId();
  const correctPanelId = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const linkedEvidence = initialEvidenceId ? findEvidence(visit, initialEvidenceId) : null;
    setSelectedEvidence(linkedEvidence);
    setTab(linkedEvidence ? "original" : "structured");
  }, [visit, initialEvidenceId]);

  function showEvidence(evidence?: EvidenceRegion) {
    if (!evidence) return;
    setSelectedEvidence(evidence);
    setTab("original");
  }

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight" && event.key !== "Home" && event.key !== "End") return;
    event.preventDefault();
    const tabs = ["original", "structured", "correct"] as const;
    const current = tabs.indexOf(tab);
    const next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : event.key === "ArrowRight"
          ? (current + 1) % tabs.length
          : (current - 1 + tabs.length) % tabs.length;
    setTab(tabs[next]);
    tabRefs.current[next]?.focus();
  };

  return (
    <section role="region" aria-labelledby={titleId} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <StatusBadge tone="brand">{documentTypeLabel(visit.document_type)}</StatusBadge>
            {visit._trust?.quarantined ? (
              <StatusBadge tone="danger">Quarantined</StatusBadge>
            ) : visit._corrections?.paths.length ? (
              <StatusBadge tone="success">Corrected</StatusBadge>
            ) : null}
            <h2 id={titleId} className="text-sm font-semibold text-slate-900">{visit._source.file}</h2>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {formatDate(visit.date)} {visit.provider_or_doctor ? `• ${visit.provider_or_doctor}` : ""} • confidence{" "}
            {formatConfidence(visit.overall_confidence)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {visit.document_url && (
            <a
              href={visit.document_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              <LinkIcon className="h-3.5 w-3.5" /> {t("viewer.openOriginal")}
              <span className="sr-only"> ({t("common.opensNewWindow")})</span>
            </a>
          )}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label={t("a11y.closeDocument")}
              className="min-h-[44px] min-w-[44px] rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <span aria-hidden="true">✕</span>
            </button>
          )}
        </div>
      </div>

      <div className="border-b border-slate-100 bg-slate-50 px-2">
        <div role="tablist" aria-label={t("a11y.tabs")} onKeyDown={onTabKeyDown} className="flex gap-1 p-1">
          <TabButton ref={(node) => { tabRefs.current[0] = node; }} id={originalTabId} controls={originalPanelId} active={tab === "original"} onClick={() => setTab("original")}>
            {t("viewer.original")}
          </TabButton>
          <TabButton ref={(node) => { tabRefs.current[1] = node; }} id={structuredTabId} controls={structuredPanelId} active={tab === "structured"} onClick={() => setTab("structured")}>
            {t("viewer.structured")}
          </TabButton>
          <TabButton ref={(node) => { tabRefs.current[2] = node; }} id={correctTabId} controls={correctPanelId} active={tab === "correct"} onClick={() => setTab("correct")}>
            Correct & Audit
          </TabButton>
        </div>
      </div>

      {tab === "original" ? (
        <div id={originalPanelId} role="tabpanel" aria-labelledby={originalTabId} tabIndex={0} className="p-4">
          <EvidenceViewer visit={visit} evidence={selectedEvidence} />
          <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
            <FileIcon className="h-4 w-4" />
            {visit._source.file} • {visit._source.method === "text_layer" ? "Digital PDF" : "Scanned or photo"}
            {visit._source.page ? ` • page ${visit._source.page}` : ""}
          </div>
        </div>
      ) : tab === "correct" ? (
        <div id={correctPanelId} role="tabpanel" aria-labelledby={correctTabId} tabIndex={0} className="p-5">
          <CorrectionEditor visit={visit} onSaved={() => onUpdated?.()} />
        </div>
      ) : (
        <div id={structuredPanelId} role="tabpanel" aria-labelledby={structuredTabId} tabIndex={0} className="space-y-5 p-5">
          <Section title="Document facts">
            <div className="grid gap-2 sm:grid-cols-2">
              <FactRow
                label={t("common.date")}
                value={formatDate(visit.date)}
                evidence={visit.field_evidence?.date?.[0]}
                onEvidence={showEvidence}
              />
              {visit.patient_name && (
                <FactRow
                  label={t("viewer.patient")}
                  value={visit.patient_name}
                  evidence={visit.field_evidence?.patient_name?.[0]}
                  onEvidence={showEvidence}
                />
              )}
              {visit.provider_or_doctor && (
                <FactRow
                  label="Provider"
                  value={visit.provider_or_doctor}
                  evidence={visit.field_evidence?.provider_or_doctor?.[0]}
                  onEvidence={showEvidence}
                />
              )}
            </div>
          </Section>

          {visit.medications.length > 0 && (
            <Section title={`${t("common.medications")} (${visit.medications.length})`} icon={<PillIcon className="h-4 w-4" />}>
              <div className="grid gap-2 sm:grid-cols-2">
                {visit.medications.map((med, i) => (
                  <div key={i} className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium text-slate-800">{med.name}</p>
                      <span className="rounded-full bg-white px-2 py-0.5 text-xs ring-1 ring-slate-200">
                        {formatConfidence(med.confidence)}
                      </span>
                    </div>
                    {med.ingredients.length > 0 && (
                      <p className="mt-0.5 text-xs text-slate-500">{med.ingredients.join(", ")}</p>
                    )}
                    <p className="mt-1 text-xs text-slate-600">
                      {[med.dosage, med.frequency, med.duration].filter(Boolean).join(" • ") || "—"}
                    </p>
                    {(med.dosage_value != null || med.frequency_per_day != null) && (
                      <p className="mt-1 text-[11px] text-slate-500">
                        {t("viewer.normalized")}:{" "}
                        {med.dosage_value != null && med.dosage_unit ? `${med.dosage_value} ${med.dosage_unit}` : "—"}
                        {med.frequency_per_day != null ? ` • ${med.frequency_per_day}x/day` : ""}
                        {med.is_as_needed ? " • PRN" : ""}
                      </p>
                    )}
                    <EvidenceButton evidence={med.evidence?.[0]} onClick={showEvidence} />
                  </div>
                ))}
              </div>
            </Section>
          )}

          {visit.lab_results.length > 0 && (
            <Section title={`${t("common.labResults")} (${visit.lab_results.length})`} icon={<BeakerIcon className="h-4 w-4" />}>
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-full text-sm">
                  <caption className="sr-only">{t("common.labResults")} — {visit._source.file}</caption>
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-medium">{t("common.test")}</th>
                      <th scope="col" className="px-3 py-2 font-medium">{t("common.value")}</th>
                      <th scope="col" className="px-3 py-2 font-medium">{t("common.range")}</th>
                      <th scope="col" className="px-3 py-2 font-medium">{t("common.flag")}</th>
                      <th scope="col" className="px-3 py-2 font-medium">Evidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visit.lab_results.map((lab, i) => (
                      <tr key={i}>
                        <td className="px-3 py-2 font-medium text-slate-700">{lab.test_name}</td>
                        <td className="px-3 py-2 text-slate-600">
                          {lab.value}
                          {lab.unit ? ` ${lab.unit}` : ""}
                        </td>
                        <td className="px-3 py-2 text-slate-500">{lab.reference_range || "—"}</td>
                        <td className="px-3 py-2">
                          <StatusBadge
                            tone={
                              lab.flag === "normal" ? "success" : lab.flag === "high" ? "danger" : lab.flag === "low" ? "info" : "neutral"
                            }
                          >
                            {lab.flag}
                          </StatusBadge>
                        </td>
                        <td className="px-3 py-2">
                          <EvidenceButton evidence={lab.evidence?.[0]} onClick={showEvidence} compact />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {visit.allergies_noted.length > 0 && (
            <Section title={t("common.allergies")}>
              <div className="flex flex-wrap items-center gap-1.5">
                {visit.allergies_noted.map((a) => (
                  <StatusBadge key={a} tone="danger">
                    {a}
                  </StatusBadge>
                ))}
                <EvidenceButton evidence={visit.field_evidence?.allergies_noted?.[0]} onClick={showEvidence} compact />
              </div>
            </Section>
          )}

          {visit.clinical_notes && (
            <Section title={t("common.clinicalNotes")}>
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{visit.clinical_notes}</p>
              <EvidenceButton evidence={visit.field_evidence?.clinical_notes?.[0]} onClick={showEvidence} />
            </Section>
          )}

          {visit.illegible_or_low_confidence_fields.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              <span className="font-semibold">{t("viewer.lowConfidence")}:</span> {visit.illegible_or_low_confidence_fields.join("; ")}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function findEvidence(visit: Visit, evidenceId: string): EvidenceRegion | null {
  const regions: EvidenceRegion[] = [
    ...Object.values(visit.field_evidence || {}).flat(),
    ...visit.medications.flatMap((med) => med.evidence || []),
    ...visit.lab_results.flatMap((lab) => lab.evidence || []),
  ];
  return regions.find((region) => region.evidence_id === evidenceId) || null;
}

function FactRow({
  label,
  value,
  evidence,
  onEvidence,
}: {
  label: string;
  value: string;
  evidence?: EvidenceRegion;
  onEvidence: (evidence?: EvidenceRegion) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-sm text-slate-700">{value}</p>
      <EvidenceButton evidence={evidence} onClick={onEvidence} />
    </div>
  );
}

function EvidenceButton({
  evidence,
  onClick,
  compact = false,
}: {
  evidence?: EvidenceRegion;
  onClick: (evidence?: EvidenceRegion) => void;
  compact?: boolean;
}) {
  if (!evidence) return null;
  return (
    <button
      type="button"
      onClick={() => onClick(evidence)}
      className={`${compact ? "mt-0" : "mt-2"} inline-flex min-h-[36px] items-center gap-1 rounded-md bg-amber-50 px-2 py-1 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-300 hover:bg-amber-100`}
      title={evidence.quote || `Open page ${evidence.page}`}
    >
      <LinkIcon className="h-3 w-3" /> Page {evidence.page} · View evidence
    </button>
  );
}

const TabButton = forwardRef<HTMLButtonElement, {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  id: string;
  controls: string;
}>(function TabButton({ active, onClick, children, id, controls }, ref) {
  return (
    <button
      ref={ref}
      id={id}
      type="button"
      role="tab"
      aria-selected={active}
      aria-controls={controls}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={`min-h-[44px] rounded-lg px-3 py-1.5 text-sm font-medium transition ${
        active ? "bg-white text-slate-950 shadow-sm ring-1 ring-slate-300" : "text-slate-700 hover:bg-white hover:text-slate-950"
      }`}
    >
      {children}
    </button>
  );
});

function Section({ title, children, icon }: { title: string; children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div>
      <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-700">
        {icon}
        {title}
      </h3>
      <div className="mt-2">{children}</div>
    </div>
  );
}
