import { useEffect, useMemo, useState } from "react";
import type { EvidenceRegion, Visit } from "../types/api";
import { FileIcon } from "./icons";

function isPdf(url: string): boolean {
  return url.toLowerCase().split("?")[0].endsWith(".pdf");
}

function cloudinaryPageImage(url: string, page: number): string | null {
  if (!url.includes("res.cloudinary.com") || !url.includes("/upload/")) return null;
  return url.replace("/upload/", `/upload/f_jpg,pg_${Math.max(1, page)}/`);
}

export function EvidenceViewer({ visit, evidence }: { visit: Visit; evidence?: EvidenceRegion | null }) {
  const [previewFailed, setPreviewFailed] = useState(false);
  const url = visit.document_url || "";
  const pdf = isPdf(url) || visit._source.method === "text_layer";
  const page = evidence?.page || visit._source.page || 1;
  const previewUrl = useMemo(
    () => (pdf ? cloudinaryPageImage(url, page) : url || null),
    [pdf, url, page]
  );
  const bbox = evidence?.bbox;

  useEffect(() => {
    setPreviewFailed(false);
  }, [url, page]);

  if (!url) {
    return (
      <div className="space-y-3">
        <p className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
          The original file is unavailable. The saved page and evidence text are shown below when available.
        </p>
        {evidence && <EvidenceDetails evidence={evidence} page={page} />}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {previewUrl && !previewFailed ? (
        <div className="overflow-auto rounded-lg border border-slate-200 bg-slate-100 p-2 text-center">
          <div className="relative inline-block max-w-full leading-none">
            <img
              src={previewUrl}
              alt={`Original document, page ${page}`}
              className="max-h-[680px] max-w-full bg-white object-contain shadow-sm"
              onError={() => setPreviewFailed(true)}
            />
            {bbox && (
              <span
                className="pointer-events-none absolute border-2 border-amber-500 bg-amber-300/30 shadow-[0_0_0_2px_rgba(255,255,255,0.85)]"
                style={{
                  left: `${bbox[0] * 100}%`,
                  top: `${bbox[1] * 100}%`,
                  width: `${(bbox[2] - bbox[0]) * 100}%`,
                  height: `${(bbox[3] - bbox[1]) * 100}%`,
                }}
                aria-label="Highlighted evidence region"
              />
            )}
          </div>
        </div>
      ) : pdf ? (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
          <iframe
            src={`${url}${url.includes("#") ? "&" : "#"}page=${page}`}
            title={`Original document page ${page}`}
            className="h-[600px] w-full bg-white"
          />
        </div>
      ) : (
        <img src={url} alt="Original document" className="max-h-[680px] w-full object-contain bg-white" />
      )}

      {evidence ? (
        <EvidenceDetails evidence={evidence} page={page} />
      ) : (
        <p className="flex items-center gap-2 text-xs text-slate-500">
          <FileIcon className="h-4 w-4" /> Choose “View evidence” beside an extracted fact to highlight it.
        </p>
      )}
    </div>
  );
}

function EvidenceDetails({ evidence, page }: { evidence: EvidenceRegion; page: number }) {
  const hasQuote = Boolean(evidence.quote);
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-left">
      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-amber-800">
        <span>Page {page}</span>
        <span>·</span>
        <span>{evidence.bbox ? "Exact highlighted region" : hasQuote ? "Page-linked quote" : "Page-only source link"}</span>
        {evidence.verification_status && <span>· {evidence.verification_status.replace(/_/g, " ")}</span>}
      </div>
      <blockquote className="mt-1.5 border-l-2 border-amber-400 pl-2 text-sm leading-relaxed text-slate-700">
        {hasQuote ? evidence.quote : "No verbatim quote was established for this legacy extraction."}
      </blockquote>
      <p className="mt-1 text-[11px] text-amber-700/80">
        Locator: {evidence.locator.replace(/_/g, " ")} · evidence confidence {Math.round(evidence.confidence * 100)}%
      </p>
    </div>
  );
}
