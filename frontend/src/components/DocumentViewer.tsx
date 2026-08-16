import { forwardRef, useId, useRef, useState, type KeyboardEvent } from "react";
import { useI18n } from "../i18n/I18nContext";
import type { Visit } from "../types/api";
import { documentTypeLabel, formatConfidence, formatDate } from "../utils/format";
import { StatusBadge } from "./StatusBadge";
import { BeakerIcon, FileIcon, LinkIcon, PillIcon } from "./icons";
import { CorrectionEditor } from "./CorrectionEditor";

export function DocumentViewer({
  visit,
  onClose,
  onUpdated,
}: {
  visit: Visit;
  onClose?: () => void;
  onUpdated?: () => void;
}) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"original" | "structured" | "correct">("structured");
  const titleId = useId();
  const originalTabId = useId();
  const structuredTabId = useId();
  const correctTabId = useId();
  const originalPanelId = useId();
  const structuredPanelId = useId();
  const correctPanelId = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

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
          {visit.document_url ? (
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
              {visit._source.method === "text_layer" || visit.document_url.toLowerCase().split("?")[0].endsWith(".pdf") ? (
                <iframe src={visit.document_url} title={t("viewer.originalDocument")} className="h-[600px] w-full bg-white" />
              ) : (
                <img src={visit.document_url} alt={t("viewer.originalDocument")} className="max-h-[600px] w-full object-contain bg-white" />
              )}
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
              {t("viewer.unavailable")}
            </p>
          )}
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
          {visit.patient_name && (
            <Section title={t("viewer.patient")}>
              <p className="text-sm text-slate-700">{visit.patient_name}</p>
            </Section>
          )}

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
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {visit.allergies_noted.length > 0 && (
            <Section title={t("common.allergies")}>
              <div className="flex flex-wrap gap-1.5">
                {visit.allergies_noted.map((a) => (
                  <StatusBadge key={a} tone="danger">
                    {a}
                  </StatusBadge>
                ))}
              </div>
            </Section>
          )}

          {visit.clinical_notes && (
            <Section title={t("common.clinicalNotes")}>
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{visit.clinical_notes}</p>
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
