import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { CrossCheckView } from "../components/CrossCheckView";
import { ErrorState } from "../components/ErrorState";
import { LabTrendsView } from "../components/LabTrendsView";
import { Spinner } from "../components/Spinner";
import { TimelineView } from "../components/TimelineView";
import { FileIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import type { UploadResponse } from "../types/api";
import { classNames } from "../utils/format";

const ACCEPTED = [".pdf", ".png", ".jpg", ".jpeg", ".webp"];
const MAX_MB = 25;

type Phase = "idle" | "uploading";

interface PendingFile {
  file: File;
  id: string;
}

export function UploadPage() {
  const { credentials } = useAuth();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [pending, setPending] = useState<PendingFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  const addFiles = useCallback((fileList: FileList | File[]) => {
    const incoming = Array.from(fileList).map((file) => ({
      file,
      id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
    }));
    setPending((prev) => {
      const seen = new Set(prev.map((p) => p.id));
      return [...prev, ...incoming.filter((f) => !seen.has(f.id))];
    });
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
    [addFiles]
  );

  const validate = (): Error | null => {
    if (pending.length === 0) return new Error("Select at least one file.");
    for (const { file } of pending) {
      const lower = file.name.toLowerCase();
      if (!ACCEPTED.some((ext) => lower.endsWith(ext))) {
        return new Error(
          `Unsupported file: ${file.name}. Supported: ${ACCEPTED.join(", ")}`
        );
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        return new Error(`${file.name} exceeds ${MAX_MB} MB.`);
      }
    }
    return null;
  };

  async function handleUpload() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setResult(null);
    setPhase("uploading");
    try {
      const res = await api.uploadDocuments(
        credentials,
        pending.map((p) => p.file)
      );
      setResult(res);
      setPending([]);
    } catch (err) {
      setError(err);
    } finally {
      setPhase("idle");
    }
  }

  const uploadFailed = phase === "idle" && error !== null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Upload &amp; extract</h1>
        <p className="mt-1 text-sm text-slate-500">
          Upload prescriptions, lab reports, or discharge summaries. The backend
          runs vision OCR / text extraction, merges the results with prior
          uploads, rebuilds the timeline, re-runs safety cross-checking and lab
          trend tracking, and re-indexes the record for Q&amp;A.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={classNames(
          "rounded-xl border-2 border-dashed bg-white p-8 text-center transition",
          dragging ? "border-brand-500 bg-brand-50/40" : "border-slate-300"
        )}
      >
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600">
          <UploadIcon className="h-6 w-6" />
        </div>
        <p className="mt-3 text-sm font-medium text-slate-700">
          Drag &amp; drop medical documents here
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Supported: {ACCEPTED.join(" ")} — up to {MAX_MB} MB each
        </p>
        <button
          onClick={() => inputRef.current?.click()}
          className="mt-4 inline-flex items-center rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          Browse files
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED.join(",")}
          className="hidden"
          onChange={(e) => {
            if (e.target.files) addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {pending.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-5 py-3">
            <h2 className="text-sm font-semibold text-slate-800">
              {pending.length} file(s) ready to upload
            </h2>
          </div>
          <ul className="divide-y divide-slate-100">
            {pending.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-3 px-5 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  <FileIcon className="h-5 w-5 shrink-0 text-slate-400" />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">{p.file.name}</p>
                    <p className="text-xs text-slate-400">
                      {(p.file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setPending((prev) => prev.filter((x) => x.id !== p.id))}
                  className="text-xs font-medium text-slate-400 hover:text-red-600"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-5 py-3">
            <button
              onClick={() => setPending([])}
              className="rounded-md px-3 py-2 text-sm font-medium text-slate-500 hover:text-slate-700"
            >
              Clear all
            </button>
            <button
              onClick={handleUpload}
              disabled={phase === "uploading"}
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
            >
              {phase === "uploading" ? (
                <>
                  <Spinner className="h-4 w-4" />
                  Processing…
                </>
              ) : (
                <>
                  <UploadIcon className="h-4 w-4" />
                  Upload &amp; extract
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {phase === "uploading" && (
        <Alert variant="info" title="ML pipeline running">
          <p>
            Each file is being extracted (vision OCR for scans/images, text
            extraction for digital PDFs), validated as a genuine medical
            document, then merged with your existing record. Large batches and
            scanned PDFs take longer because every page runs through the vision
            model.
          </p>
        </Alert>
      )}

      {uploadFailed && (
        <ErrorState
          error={error}
          onRetry={() => {
            setError(null);
            if (pending.length > 0) void handleUpload();
          }}
        />
      )}

      {result && (
        <div className="space-y-6">
          <Alert variant="success" title="Processing complete">
            <p>
              Added <strong>{result.documents_added}</strong> document(s). You now
              have <strong>{result.documents_total}</strong> in your record.
            </p>
            {!result.indexed && result.index_error && (
              <p className="mt-2 rounded bg-red-100/60 px-2 py-1 text-red-800">
                Q&amp;A indexing failed: {result.index_error}. The timeline and
                cross-check were still saved, but question answering may be
                unavailable until re-indexed.
              </p>
            )}
            {result.indexed && (
              <p className="mt-1 text-xs text-emerald-700/80">
                Record re-indexed for Q&amp;A.
              </p>
            )}
          </Alert>

          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => navigate("/cross-check")}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              View safety cross-check
            </button>
            <button
              onClick={() => navigate("/lab-trends")}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              View lab trends
            </button>
            <button
              onClick={() => navigate("/qa")}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
            >
              Ask a question
            </button>
          </div>

          <TimelineView timeline={result.timeline} />
          <CrossCheckView report={result.cross_check_report} />
          <LabTrendsView report={result.lab_trends} />
        </div>
      )}
    </div>
  );
}
