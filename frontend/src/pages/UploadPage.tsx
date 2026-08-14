import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  ApiError,
  type JobFileProgress,
  type JobProgress,
} from "../api/client";
import { Alert } from "../components/Alert";
import { ErrorState } from "../components/ErrorState";
import { HealthSummaryCard } from "../components/HealthSummaryCard";
import { ProcessingStatus, type ProcessingStepId } from "../components/ProcessingStatus";
import { Spinner } from "../components/Spinner";
import { TimelineView } from "../components/TimelineView";
import { FileIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
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

function initialFileProgress(files: PendingFile[]): JobFileProgress[] {
  return files.map((pendingFile, index) => ({
    id: `file-${index + 1}`,
    index: index + 1,
    name: pendingFile.file.name,
    status: "queued",
    step: "upload",
    message: "Uploaded and waiting for a processing slot",
  }));
}

function filesAfterResult(files: PendingFile[], response: UploadResponse): PendingFile[] {
  const retryableFailures = (response.failed_files || []).filter(
    (failure) => failure.retryable !== false && failure.kind !== "not_medical"
  );
  if (retryableFailures.length === 0) return [];

  const failedIndices = new Set(
    retryableFailures
      .map((failure) => failure.file_index)
      .filter((index): index is number => typeof index === "number")
  );
  if (failedIndices.size > 0) {
    return files.filter((_, index) => failedIndices.has(index + 1));
  }

  // Compatibility with an older backend that returned only filenames.
  const failedNames = new Set(retryableFailures.map((failure) => failure.file));
  return files.filter((pendingFile) => failedNames.has(pendingFile.file.name));
}

function completedFallbackProgress(
  initialFiles: JobFileProgress[],
  response: UploadResponse
): JobProgress {
  const failuresByIndex = new Map(
    (response.failed_files || [])
      .filter((failure) => typeof failure.file_index === "number")
      .map((failure) => [failure.file_index as number, failure])
  );
  const failuresByName = new Map((response.failed_files || []).map((failure) => [failure.file, failure]));
  const files = initialFiles.map((file) => {
    const failure = failuresByIndex.get(file.index) || failuresByName.get(file.name);
    if (!failure) {
      return {
        ...file,
        status: "completed" as const,
        step: "ready",
        message: "Details extracted and saved",
      };
    }
    return {
      ...file,
      status: "failed" as const,
      step: "failed",
      message: failure.error,
      error: failure.error,
      error_code: failure.code,
      retryable: failure.retryable,
      retry_after_seconds: failure.retry_after_seconds,
    };
  });
  const successful = files.filter((file) => file.status === "completed").length;
  return {
    step: "ready",
    message: "Your health record is up to date",
    total_files: files.length,
    processed_files: files.length,
    successful_files: successful,
    failed_files: files.length - successful,
    files,
  };
}

export function UploadPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);

  const [pending, setPending] = useState<PendingFile[]>([]);
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [processingStep, setProcessingStep] = useState<ProcessingStepId>("upload");
  const [jobProgress, setJobProgress] = useState<JobProgress | null>(null);

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
    setError(null);
    setResult(null);
    setJobProgress(null);
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
      if (phase === "uploading") return;
      if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
    },
    [addFiles, phase]
  );

  const validate = (): Error | null => {
    if (pending.length === 0) return new Error(t("upload.selectRequired"));
    for (const { file } of pending) {
      const lower = file.name.toLowerCase();
      if (!ACCEPTED.some((ext) => lower.endsWith(ext))) {
        return new Error(t("upload.invalidType", { file: `“${file.name}”` }));
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        return new Error(t("upload.tooLarge", { file: `“${file.name}”`, size: MAX_MB }));
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

    const filesForRun = [...pending];
    const initialFiles = initialFileProgress(filesForRun);
    setError(null);
    setResult(null);
    setPhase("uploading");
    setProcessingStep("upload");
    setJobProgress({
      step: "upload",
      message: "Sending files securely",
      total_files: initialFiles.length,
      processed_files: 0,
      successful_files: 0,
      failed_files: 0,
      files: initialFiles,
    });

    const toStep = (step: string): ProcessingStepId => {
      if (step === "failed") return "failed";
      if (step === "reading") return "reading";
      if (step === "extracting" || step === "upload") return "extracting";
      if (step === "organizing") return "organizing";
      if (step === "safety") return "safety";
      if (step === "indexing") return "indexing";
      if (step === "ready" || step === "completed") return "ready";
      return "upload";
    };

    try {
      // Every upload uses the parent job endpoint. It is the only path that
      // can report independent per-file phases and it avoids tying a browser
      // request to several minutes of OCR/model work.
      try {
        const queued = await api.uploadDocumentsAsync(
          credentials,
          filesForRun.map((pendingFile) => pendingFile.file)
        );
        if (!queued.job_id) {
          throw new ApiError(500, "The server did not return a processing job.");
        }
        if (queued.worker_limit) {
          setJobProgress((current) =>
            current ? { ...current, worker_limit: queued.worker_limit } : current
          );
        }

        const final = await api.pollJobUntilDone(credentials, queued.job_id, (job) => {
          if (job.progress) {
            setJobProgress(job.progress);
            setProcessingStep(toStep(job.progress.step));
          }
        });

        if (final.status === "failed") {
          const progress = final.progress;
          throw new ApiError(
            progress?.http_status || 502,
            final.error || progress?.message || "Document processing could not finish.",
            final,
            {
              code: progress?.error_code,
              retryable: progress?.retryable,
              retryAfterSeconds: progress?.retry_after_seconds,
            }
          );
        }

        const response = final.result as UploadResponse | undefined;
        if (!response) {
          throw new ApiError(500, "Processing finished, but the server returned no result.");
        }
        setResult(response);
        setPending(filesAfterResult(filesForRun, response));
        setProcessingStep("ready");
        if (final.progress) setJobProgress(final.progress);
        return;
      } catch (asyncError) {
        // Only an explicitly old server without job routes may use the legacy
        // synchronous endpoint. Never fall back after a network ambiguity or
        // a terminal job failure: that would upload and charge every file a
        // second time.
        const jobsUnsupported =
          asyncError instanceof ApiError &&
          (asyncError.status === 404 || asyncError.status === 405);
        if (!jobsUnsupported) throw asyncError;
      }

      const response = await api.uploadDocuments(
        credentials,
        filesForRun.map((pendingFile) => pendingFile.file)
      );
      setResult(response);
      setPending(filesAfterResult(filesForRun, response));
      setJobProgress(completedFallbackProgress(initialFiles, response));
      setProcessingStep("ready");
    } catch (uploadError) {
      setError(uploadError);
      setProcessingStep("failed");
    } finally {
      setPhase("idle");
    }
  }

  const uploadFailed = phase === "idle" && error !== null;
  const busy = phase === "uploading";
  const retryBlocked =
    uploadFailed &&
    typeof error === "object" &&
    error !== null &&
    "retryable" in error &&
    (error as { retryable?: boolean }).retryable === false;
  const recent = timeline ? [...timeline.visits].slice(-5).reverse() : [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">{t("upload.title")}</h1>
        <p className="secondary-text mt-2">{t("upload.subtitle")}</p>
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
            aria-label={t("upload.area")}
          >
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
              <UploadIcon className="h-8 w-8" />
            </div>
            <p className="mt-4 text-lg font-semibold text-slate-900">{t("upload.drag")}</p>
            <p className="secondary-text mt-1">{t("upload.or")}</p>
            <button
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              className="btn-primary mt-3"
            >
              {t("upload.browse")}
            </button>
            <p className="secondary-text mt-4">
              {t("upload.supported", { size: MAX_MB })}
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
              aria-label={t("upload.browse")}
              multiple
              accept={ACCEPTED.join(",")}
              className="hidden"
              disabled={busy}
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
              aria-label={t("upload.ready")}
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
                            {t("upload.preview")}<span className="sr-only"> ({t("common.opensNewWindow")})</span>
                          </a>
                        )}
                        <button
                          type="button"
                          aria-label={t("upload.removeFile", { file: p.file.name })}
                          onClick={() => {
                            setPending((prev) => prev.filter((x) => x.id !== p.id));
                            setError(null);
                            setResult(null);
                            setJobProgress(null);
                          }}
                          disabled={busy}
                          className="flex min-h-[44px] items-center rounded-lg px-3 text-sm font-medium text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          {t("common.remove")}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-5 py-4">
                <button
                  onClick={() => {
                    setPending([]);
                    setError(null);
                    setResult(null);
                    setJobProgress(null);
                  }}
                  disabled={busy}
                  className="btn-ghost"
                >
                  {t("upload.clearAll")}
                </button>
                <button
                  onClick={handleUpload}
                  disabled={busy || retryBlocked}
                  className="btn-primary"
                >
                  {retryBlocked ? (
                    t("upload.retryLater")
                  ) : busy ? (
                    <>
                      <Spinner className="h-5 w-5" />
                      {t("upload.processing")}
                    </>
                  ) : (
                    <>
                      <UploadIcon className="h-5 w-5" />
                      {t("upload.upload")}
                    </>
                  )}
                </button>
              </div>
            </section>
          )}

          {busy && (
            <Alert variant="info" title={t("upload.readingTitle")}>
              <p className="text-sm">{t("upload.readingBody")}</p>
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
          {(busy || result || uploadFailed) && (
            <ProcessingStatus
              current={busy ? processingStep : uploadFailed ? "failed" : "ready"}
              files={jobProgress?.files || []}
              workerLimit={jobProgress?.worker_limit}
              error={null}
            />
          )}

          {result && (
            <>
              <Alert
                variant={result.failed_files?.length ? "warning" : "success"}
                title={
                  result.failed_files?.length
                    ? t("upload.partial")
                    : t("upload.success")
                }
              >
                <p className="text-sm">
                  Added <strong>{result.files_added ?? result.documents_added}</strong>{" "}
                  {(result.files_added ?? result.documents_added) === 1 ? "file" : "files"}. Your record now
                  contains <strong>{result.documents_total}</strong>{" "}
                  {result.documents_total === 1 ? "document page" : "document pages"} in total.
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
                          <strong>{f.file}</strong> — {f.error}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Alert>

              <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
                <h2 className="card-title">{t("upload.next")}</h2>
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
          aria-label={t("upload.recent")}
        >
          <div className="flex items-center justify-between">
            <h2 className="card-title">{t("upload.recent")}</h2>
            {recent.length > 0 && (
              <Link to="/documents" className="text-sm font-medium text-brand-600 hover:text-brand-700">
                View all →
              </Link>
            )}
          </div>
          {recent.length === 0 ? (
            <p className="secondary-text mt-3">
              {t("upload.none")}
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
