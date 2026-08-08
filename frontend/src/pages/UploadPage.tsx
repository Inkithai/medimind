import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { Alert } from "../components/Alert";
import { ErrorState } from "../components/ErrorState";
import { HealthSummaryCard } from "../components/HealthSummaryCard";
import { ProcessingStatus, type ProcessingStepId } from "../components/ProcessingStatus";
import { Spinner } from "../components/Spinner";
import { TimelineView } from "../components/TimelineView";
import { FileIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { Timeline, UploadResponse } from "../types/api";
import { classNames, documentTypeLabel, fileSizeLabel, relativeTime } from "../utils/format";

const ACCEPTED = [".pdf", ".png", ".jpg", ".jpeg", ".webp"];
const MAX_MB = 25;

const SUPPORTED_TYPES = [
  "Prescriptions",
  "Lab Reports",
  "Discharge Summaries",
  "Medical Images",
  "Insurance Documents",
];

type Phase = "idle" | "uploading";

interface PendingFile {
  file: File;
  id: string; // dedup key: name-size-lastModified (no random)
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
  const [processingStep, setProcessingStep] = useState<ProcessingStepId>("upload");

  // Recent uploads + health summary fill the page's right column / bottom.
  const [timeline, setTimeline] = useState<Timeline | null>(null);

  useStrictEffect(() => {
    api
      .getTimeline(credentials)
      .then(setTimeline)
      .catch(() => setTimeline(null)); // 404 = no record yet — page still works
  }, [credentials, result]);

  // Object URLs for image previews — revoked when the pending list changes.
  const previewUrls = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of pending) {
      if (/\.(png|jpe?g|webp)$/i.test(p.file.name)) {
        map.set(p.id, URL.createObjectURL(p.file));
      }
    }
    return map;
  }, [pending]);
  useEffect(() => {
    return () => previewUrls.forEach((url) => URL.revokeObjectURL(url));
  }, [previewUrls]);

  const addFiles = useCallback((fileList: FileList | File[]) => {
    const incoming = Array.from(fileList).map((file) => ({
      file,
      id: `${file.name}-${file.size}-${file.lastModified}`,
    }));
    setPending((prev) => {
      const seen = new Set(prev.map((p) => p.id));
      const toAdd = incoming.filter((f) => !seen.has(f.id));
      return [...prev, ...toAdd];
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
    if (pending.length === 0) return new Error("Select at least one file first.");
    for (const { file } of pending) {
      const lower = file.name.toLowerCase();
      if (!ACCEPTED.some((ext) => lower.endsWith(ext))) {
        return new Error(`"${file.name}" isn't a file type we can read.`);
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        return new Error(`"${file.name}" is larger than ${MAX_MB} MB.`);
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
    setProcessingStep("upload");

    // Map job progress step -> ProcessingStepId (real progress from server)
    const toStep = (s: string): ProcessingStepId => {
      if (s === "reading" || s === "upload") return "reading";
      if (s === "extracting") return "extracting";
      if (s === "organizing") return "organizing";
      if (s === "safety") return "safety";
      if (s === "indexing") return "indexing";
      if (s === "ready" || s === "completed") return "ready";
      return "upload";
    };

    // Try async (202 + poll) first — avoids free-tier 429 timeouts and shows real progress.
    // Falls back to sync if server doesn't support jobs (old deployment).
    try {
      // Heuristic: use async for >1 file or any file >2MB (likely scan) or if USE_BACKGROUND_JOBS set
      const shouldUseAsync = pending.length > 1 || pending.some((p) => p.file.size > 2 * 1024 * 1024);
      if (shouldUseAsync) {
        try {
          const { job_id } = await api.uploadDocumentsAsync(
            credentials,
            pending.map((p) => p.file)
          );
          // Poll until done, updating step from server progress
          const final = await api.pollJobUntilDone(credentials, job_id, (job) => {
            if (job.progress?.step) setProcessingStep(toStep(job.progress.step));
          });
          if (final.status === "failed") {
            // The job ran and REPORTED failure — this is terminal. The old
            // code let this fall through to the sync fallback below, which
            // silently re-uploaded every file and paid the provider cost
            // twice for the same rejection (seen as two full processing
            // runs in the server logs).
            const jobError = new Error(final.error || "Processing failed") as Error & {
              __jobTerminal?: boolean;
            };
            jobError.__jobTerminal = true;
            throw jobError;
          }
          const res = final.result as UploadResponse;
          if (!res) throw new Error("Job completed but no result");
          setResult(res);
          setPending([]);
          setProcessingStep("ready");
          return;
        } catch (e: any) {
          // Sync fallback ONLY when the async path itself couldn't be used:
          // old server without jobs (404/405) or a network-level failure
          // (ApiError status 0). Any real HTTP rejection, timeout, or job
          // failure is rethrown — a sync retry would fail identically and
          // double the upload cost.
          if (e?.__jobTerminal) {
            throw e;
          }
          if (e?.message?.includes("timed out")) {
            throw e;
          }
          if (e instanceof ApiError && e.status >= 400 && e.status !== 404 && e.status !== 405) {
            throw e;
          }
          // else: 404/405 (jobs unsupported) or network error — try sync below
        }
      }
      // Sync fallback (used by tests and small uploads)
      const res = await api.uploadDocuments(
        credentials,
        pending.map((p) => p.file)
      );
      setResult(res);
      setPending([]);
      setProcessingStep("ready");
    } catch (err) {
      setError(err);
      setProcessingStep("reading");
    } finally {
      setPhase("idle");
    }
  }

  const uploadFailed = phase === "idle" && error !== null;
  const busy = phase === "uploading";
  const recent = timeline ? [...timeline.visits].slice(-5).reverse() : [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Upload Medical Documents</h1>
        <p className="secondary-text mt-2">
          We'll read them, find the important details, and add them to your health record.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-4">
          {/* Drop zone */}
          <section
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={classNames(
              "rounded-2xl border-2 border-dashed bg-white p-8 text-center transition sm:p-10",
              dragging ? "border-brand-500 bg-brand-50/40" : "border-slate-300"
            )}
            aria-label="Document upload area"
          >
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
              <UploadIcon className="h-8 w-8" />
            </div>
            <p className="mt-4 text-lg font-semibold text-slate-800">Drag files here</p>
            <p className="secondary-text mt-1">or</p>
            <button onClick={() => inputRef.current?.click()} className="btn-primary mt-3">
              Browse Files
            </button>
            <p className="secondary-text mt-4">
              Supported: PDF • JPG • PNG • WEBP &nbsp;·&nbsp; Max {MAX_MB} MB each
            </p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {SUPPORTED_TYPES.map((t) => (
                <span
                  key={t}
                  className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600"
                >
                  {t}
                </span>
              ))}
            </div>
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
          </section>

          {/* Pending files — with previews, not a disappearing list */}
          {pending.length > 0 && (
            <section
              className="rounded-2xl border border-slate-200 bg-white shadow-sm"
              aria-label="Files ready to upload"
            >
              <div className="border-b border-slate-100 px-5 py-4">
                <h2 className="card-title">{pending.length} {pending.length === 1 ? "file" : "files"} ready</h2>
              </div>
              <ul className="divide-y divide-slate-100">
                {pending.map((p) => {
                  const preview = previewUrls.get(p.id);
                  return (
                    <li key={p.id} className="flex items-center gap-4 px-5 py-3">
                      {preview ? (
                        <img
                          src={preview}
                          alt={`Preview of ${p.file.name}`}
                          className="h-14 w-14 shrink-0 rounded-lg border border-slate-200 object-cover"
                        />
                      ) : (
                        <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg bg-slate-50 text-slate-400">
                          <FileIcon className="h-7 w-7" />
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-base font-medium text-slate-800">{p.file.name}</p>
                        <p className="secondary-text">{fileSizeLabel(p.file.size)}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        {preview && (
                          <a
                            href={preview}
                            target="_blank"
                            rel="noreferrer"
                            className="flex min-h-[44px] items-center rounded-lg px-3 text-sm font-medium text-brand-600 hover:bg-brand-50"
                          >
                            Preview
                          </a>
                        )}
                        <button
                          onClick={() => setPending((prev) => prev.filter((x) => x.id !== p.id))}
                          className="flex min-h-[44px] items-center rounded-lg px-3 text-sm font-medium text-slate-400 hover:bg-red-50 hover:text-red-600"
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-5 py-4">
                <button onClick={() => setPending([])} className="btn-ghost">
                  Clear all
                </button>
                <button onClick={handleUpload} disabled={busy} className="btn-primary">
                  {busy ? (
                    <>
                      <Spinner className="h-5 w-5" />
                      Processing…
                    </>
                  ) : (
                    <>
                      <UploadIcon className="h-5 w-5" />
                      Upload
                    </>
                  )}
                </button>
              </div>
            </section>
          )}

          {busy && (
            <Alert variant="info" title="Hang tight — we're reading your documents">
              <p className="text-sm">
                Scanned pages and photos take a little longer than digital PDFs. You can leave this
                page; everything is saved automatically.
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
        </div>

        {/* Right column: live status while processing, success + next steps after */}
        <div className="space-y-4">
          {(busy || result) && (
            <ProcessingStatus current={busy ? processingStep : "ready"} error={null} />
          )}

          {result && (
            <>
              <Alert variant="success" title="All done — your record is up to date">
                <p className="text-sm">
                  Added <strong>{result.documents_added}</strong>{" "}
                  {result.documents_added === 1 ? "document" : "documents"}. Your record now holds{" "}
                  <strong>{result.documents_total}</strong> in total.
                </p>
                {!result.indexed && result.index_error && (
                  <p className="mt-2 rounded-lg bg-red-100/60 px-3 py-2 text-sm text-red-800">
                    Your documents were saved, but question-answering couldn't be set up this time.
                    It will retry on your next upload.
                  </p>
                )}
                {result.failed_files && result.failed_files.length > 0 && (
                  <div className="mt-2 rounded-lg bg-amber-100/70 px-3 py-2 text-sm text-amber-900">
                    <p className="font-medium">
                      {result.failed_files.length === 1
                        ? "1 file couldn't be processed (the rest went through fine):"
                        : `${result.failed_files.length} files couldn't be processed (the rest went through fine):`}
                    </p>
                    <ul className="mt-1 list-disc space-y-1 pl-5">
                      {result.failed_files.map((f, i) => (
                        <li key={`${f.file}-${i}`}>
                          <strong>{f.file}</strong>
                          {f.kind === "not_medical"
                            ? " — doesn't look like a medical document."
                            : " — processing failed; try uploading just this file again."}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Alert>

              <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="card-title">What would you like to do next?</h2>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <button onClick={() => navigate("/medicines")} className="btn-secondary text-sm">
                    💊 Medications
                  </button>
                  <button onClick={() => navigate("/labs")} className="btn-secondary text-sm">
                    🧪 Lab Results
                  </button>
                  <button onClick={() => navigate("/safety")} className="btn-secondary text-sm">
                    ⚠️ Safety Alerts
                  </button>
                  <button onClick={() => navigate("/ask")} className="btn-primary text-sm">
                    🤖 Ask AI
                  </button>
                </div>
              </section>

              <details className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <summary className="cursor-pointer text-base font-semibold text-slate-800">
                  See everything we found in these documents
                </summary>
                <div className="mt-4">
                  <TimelineView timeline={result.timeline} />
                </div>
              </details>
            </>
          )}
        </div>
      </div>

      {/* Below the fold: status already shown above on mobile; this fills the
          page so it never feels empty — recent uploads + health summary */}
      <div className="grid gap-6 lg:grid-cols-2">
        <section
          className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
          aria-label="Recent uploads"
        >
          <div className="flex items-center justify-between">
            <h2 className="card-title">Recent Uploads</h2>
            {recent.length > 0 && (
              <Link to="/documents" className="text-sm font-medium text-brand-600 hover:text-brand-700">
                View all →
              </Link>
            )}
          </div>
          {recent.length === 0 ? (
            <p className="secondary-text mt-3">
              Nothing here yet — your uploaded reports will show up in this list.
            </p>
          ) : (
            <ul className="mt-4 space-y-2">
              {recent.map((v, i) => (
                <li key={`${v._source.file}-${i}`}>
                  <Link
                    to="/documents"
                    className="flex items-center gap-3 rounded-xl border border-slate-100 px-4 py-3 transition hover:border-brand-200 hover:bg-slate-50"
                  >
                    <span className="text-xl" aria-hidden="true">
                      {v.document_type === "lab_report" ? "🧪" : v.document_type === "prescription" ? "💊" : "📄"}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-800">{v._source.file}</p>
                      <p className="secondary-text">{documentTypeLabel(v.document_type)}</p>
                    </div>
                    <span className="secondary-text shrink-0">{relativeTime(v.date)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {timeline && <HealthSummaryCard timeline={timeline} />}
      </div>
    </div>
  );
}
