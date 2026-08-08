import { useState } from "react";
import type { Visit } from "../types/api";
import { documentTypeLabel, formatConfidence, formatDate } from "../utils/format";
import { StatusBadge } from "./StatusBadge";
import { BeakerIcon, FileIcon, LinkIcon, PillIcon } from "./icons";

export function DocumentViewer({ visit, onClose }: { visit: Visit; onClose?: () => void }) {
  const [tab, setTab] = useState<"original" | "structured">("structured");

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
      <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <StatusBadge tone="brand">{documentTypeLabel(visit.document_type)}</StatusBadge>
            <span className="text-sm font-semibold text-slate-800">{visit._source.file}</span>
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
              <LinkIcon className="h-3.5 w-3.5" /> Open original
            </a>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <div className="border-b border-slate-100 bg-slate-50 px-2">
        <div className="flex gap-1 p-1">
          <TabButton active={tab === "original"} onClick={() => setTab("original")}>
            Original
          </TabButton>
          <TabButton active={tab === "structured"} onClick={() => setTab("structured")}>
            What We Found
          </TabButton>
        </div>
      </div>

      {tab === "original" ? (
        <div className="p-4">
          {visit.document_url ? (
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
              {visit._source.method === "text_layer" || visit.document_url.toLowerCase().split("?")[0].endsWith(".pdf") ? (
                <iframe src={visit.document_url} title="Original document" className="h-[600px] w-full bg-white" />
              ) : (
                <img src={visit.document_url} alt="Original document" className="max-h-[600px] w-full object-contain bg-white" />
              )}
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
              The original file isn't available for this record, but everything we found in it is still
              here — switch to the extraction view.
            </p>
          )}
          <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
            <FileIcon className="h-4 w-4" />
            {visit._source.file} • {visit._source.method === "text_layer" ? "Digital PDF" : "Scanned or photo"}
            {visit._source.page ? ` • page ${visit._source.page}` : ""}
          </div>
        </div>
      ) : (
        <div className="space-y-5 p-5">
          {visit.patient_name && (
            <Section title="Patient">
              <p className="text-sm text-slate-700">{visit.patient_name}</p>
            </Section>
          )}

          {visit.medications.length > 0 && (
            <Section title={`Medications (${visit.medications.length})`} icon={<PillIcon className="h-4 w-4" />}>
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
                        normalized:{" "}
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
            <Section title={`Lab Results (${visit.lab_results.length})`} icon={<BeakerIcon className="h-4 w-4" />}>
              <div className="overflow-x-auto rounded-lg border border-slate-200">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-2 font-medium">Test</th>
                      <th className="px-3 py-2 font-medium">Value</th>
                      <th className="px-3 py-2 font-medium">Range</th>
                      <th className="px-3 py-2 font-medium">Flag</th>
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
            <Section title="Allergies noted">
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
            <Section title="Clinical notes">
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{visit.clinical_notes}</p>
            </Section>
          )}

          {visit.illegible_or_low_confidence_fields.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
              <span className="font-semibold">Low-confidence fields:</span> {visit.illegible_or_low_confidence_fields.join("; ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
        active ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:bg-white hover:text-slate-900"
      }`}
    >
      {children}
    </button>
  );
}

function Section({ title, children, icon }: { title: string; children: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div>
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {icon}
        {title}
      </p>
      <div className="mt-2">{children}</div>
    </div>
  );
}
