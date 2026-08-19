import type {
  CareAvailability,
  CareFacility,
  CareFacilityResponse,
  CareRecommendation,
  FacilityKind as DirectoryFacilityKind,
} from "../types/facility";
import type {
  AppointmentPrepReport,
  CareFacilitiesResponse,
  CareRecommendationContext,
  CareProviderSearchResponse,
  CrossCheckReport,
  DosageReport,
  ConflictsResponse,
  DocumentCorrectionsResponse,
  DeleteDocumentResponse,
  DeleteWorkspaceResponse,
  FollowUpPlan,
  FacilityKind,
  HealthResponse,
  LabTrendsReport,
  PatientSnapshot,
  QAResponse,
  RiskTimelineReport,
  RecordChangesReport,
  RecordIntegrityReport,
  RecordRebuildResponse,
  SessionHistory,
  SessionInfo,
  Timeline,
  UploadResponse,
  CareSuggestion,
  CareSearchResponse,
  CareDay,
  CareTimeOfDay,
  VitalTrendsReport,
  EarlyWarningReport,
  AdherenceReport,
  SymptomAnalysis,
  PreventiveCareReport,
  ManagedAlertsReport,
  FindingFeedbackInput,
  FindingFeedbackEntry,
  FeedbackMetrics,
  FindingLifecycleInput,
  FindingLifecycleResult,
  FindingLifecycleOverview,
  FhirImportResult,
  PatientMeasurementInput,
  PatientMeasurement,
  ProviderMessageInput,
  ProviderMessage,
  ProviderThread,
  GuidelinesStatus,
  GuidelinesRefreshResult,
  AnalysisLogsResponse,
  ConsultTriageReport,
  MedicationReconciliationReport,
  DeteriorationReport,
  FhirValidationReport,
  CorrectionEvent,
  FindingChangeLog,
} from "../types/api";
import type { ScoredCareRecommendationsResponse } from "../types/recommendations";

export interface PatientProfileInput {
  legal_name?: string | null;
  preferred_name?: string | null;
  date_of_birth?: string | null;
  phone?: string | null;
  emergency_contact?: string | null;
  preferred_language?: string | null;
}

export interface PatientProfile extends PatientProfileInput {
  user_id: string;
  updated_at?: string | null;
}

export interface DocumentsResponse {
  user_id: string;
  count: number;
  documents: Record<string, unknown>[];
  document_types?: {
    counts: Record<string, number>;
    types: string[];
    dominant: string;
    total: number;
  };
}

/** Response of POST /api/v1/documents/{id}/reprocess (mirrors the upload
 *  response's derived-record subset). */
export interface ReprocessDocumentResponse {
  document_id: string;
  documents_reprocessed: number;
  timeline: Record<string, unknown>;
  cross_check_report: Record<string, unknown>;
  lab_trends: Record<string, unknown>;
  dosage_report: Record<string, unknown>;
  consult_triage: Record<string, unknown>;
  document_types?: DocumentsResponse["document_types"];
  indexed: boolean;
  index_error?: string;
}

export interface DocumentSignedUrlResponse {
  document_id: string;
  url: string;
  expires_in_seconds: number;
  mode: "private_storage_signed_url" | "medimind_expiring_proxy" | string;
}

export interface ProcessTextResponse {
  document_id: string;
  raw_text_processing: Record<string, unknown>;
  rows_updated: number;
}

export type JobFileStatus = "queued" | "processing" | "completed" | "failed";

export interface JobFileProgress {
  id: string;
  index: number;
  name: string;
  status: JobFileStatus;
  step: "upload" | "reading" | "extracting" | "saving" | "ready" | "failed" | string;
  message: string;
  error?: string | null;
  error_code?: string | null;
  retryable?: boolean | null;
  retry_after_seconds?: number | null;
  updated_at?: string;
}

export interface JobProgress {
  step: string;
  message: string;
  file_names?: string[];
  total_files?: number;
  processed_files?: number;
  successful_files?: number;
  failed_files?: number;
  worker_limit?: number;
  files?: JobFileProgress[];
  error_code?: string;
  retryable?: boolean;
  retry_after_seconds?: number | null;
  http_status?: number;
  // Failure-aware indexing metadata. `records_saved` is the important one:
  // it tells the UI the medical record is durable in Supabase even when
  // the derived search index did not finish.
  stage?: string;
  error?: string;
  error_detail?: string;
  records_saved?: boolean;
  indexing_completed?: boolean;
  files_completed?: number;
}

export interface Job {
  job_id: string;
  user_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress?: JobProgress;
  result?: UploadResponse;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

// MediMind anonymous workspace: the backend issues a signed JWT for a
// random anon_* user_id via POST /api/v1/anonymous/session. The frontend
// stores {userId, token, apiBase} in localStorage (medimind.session.v1)
// and uses it for all subsequent calls. User never sees credentials.
export interface Credentials {
  apiBase: string;
  token: string;
  userId: string;
}

export interface AnonymousSession {
  user_id: string;
  token: string;
  session_id: string;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  code?: string;
  retryable?: boolean;
  retryAfterSeconds?: number | null;

  constructor(
    status: number,
    message: string,
    detail?: unknown,
    metadata?: { code?: string; retryable?: boolean; retryAfterSeconds?: number | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = metadata?.code;
    this.retryable = metadata?.retryable;
    this.retryAfterSeconds = metadata?.retryAfterSeconds;
  }
}

function buildUrl(apiBase: string, path: string): string {
  const base = apiBase.trim().replace(/\/+$/, "");
  if (!base) return path;
  return `${base}${path}`;
}

interface RequestOptions {
  method?: string;
  body?: BodyInit | null;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function apiErrorMetadata(data: unknown) {
  if (typeof data !== "object" || data === null) return undefined;
  const payload = data as {
    code?: unknown;
    retryable?: unknown;
    retry_after_seconds?: unknown;
  };
  return {
    code: typeof payload.code === "string" ? payload.code : undefined,
    retryable: typeof payload.retryable === "boolean" ? payload.retryable : undefined,
    retryAfterSeconds:
      typeof payload.retry_after_seconds === "number" ? payload.retry_after_seconds : undefined,
  };
}

async function publicRequest<T>(
  apiBase: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(apiBase, path), {
      method: options.method || "GET",
      headers: options.headers || {},
      body: options.body ?? undefined,
      signal: options.signal,
    });
  } catch (err) {
    throw new ApiError(
      0,
      `Could not reach the API at ${apiBase || "(same origin)"}. Check that the backend is running.`,
      err,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const message =
      (typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : null) ||
      (typeof data === "string" ? data : null) ||
      `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, data, apiErrorMetadata(data));
  }

  return data as T;
}

function safeExternalUrl(value: string | null): string | undefined {
  if (!value) return undefined;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function normalizeCareFacility(facility: CareFacilityResponse): CareFacility {
  return {
    id: facility.id,
    // The provider name is the facility's identity: never substitute a
    // category label such as "Clinic" for a missing name.
    name: facility.name?.trim() || "Unnamed listing",
    kind: facility.kind,
    latitude: facility.latitude,
    longitude: facility.longitude,
    distanceKm: facility.distance_km,
    address: facility.address || undefined,
    rating: facility.rating ?? undefined,
    userRatingCount: facility.user_rating_count ?? undefined,
    phone: facility.phone || undefined,
    // URLs originate in an external directory. Never pass non-web schemes
    // (for example javascript:) through to rendered links.
    website: safeExternalUrl(facility.website),
    mapsUrl: safeExternalUrl(facility.maps_url),
    openingHours: facility.opening_hours || undefined,
    openNow: facility.open_now ?? undefined,
    specialty: facility.specialty || undefined,
    specialtyMatch: facility.specialty_match ?? undefined,
    availabilityMatch: facility.availability_match ?? undefined,
    rankingScore: facility.ranking_score ?? undefined,
    rankingReason: facility.ranking_reason || undefined,
    source: facility.source || "Public listing",
  };
}

async function request<T>(
  credentials: Credentials,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${credentials.token}`,
    "X-User-Id": credentials.userId,
    ...(options.headers || {}),
  };

  let response: Response;
  try {
    response = await fetch(buildUrl(credentials.apiBase, path), {
      method: options.method || "GET",
      headers,
      body: options.body ?? undefined,
      signal: options.signal,
    });
  } catch (err) {
    throw new ApiError(
      0,
      `Could not reach the API at ${credentials.apiBase || "(same origin)"}. Check that the backend is running.`,
      err,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const message =
      (typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : null) ||
      (typeof data === "string" ? data : null) ||
      `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, data, apiErrorMetadata(data));
  }

  return data as T;
}

export const api = {
  // Public, no auth needed
  healthUnauthenticated(apiBase = ""): Promise<HealthResponse> {
    return publicRequest<HealthResponse>(apiBase, "/api/v1/health");
  },

  // Creates anonymous workspace — no auth needed. Returns user_id + token
  createAnonymousSession(apiBase = ""): Promise<AnonymousSession> {
    return publicRequest<AnonymousSession>(apiBase, "/api/v1/anonymous/session", {
      method: "POST",
    });
  },

  // Backward compat: health used to require credentials arg
  health(credentials: Credentials): Promise<HealthResponse> {
    // Use public path — works even without credentials
    return publicRequest<HealthResponse>(credentials.apiBase, "/api/v1/health");
  },

  uploadDocuments(credentials: Credentials, files: File[]): Promise<UploadResponse> {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    return request<UploadResponse>(credentials, "/api/v1/documents", {
      method: "POST",
      body: form,
    });
  },

  // Async upload — returns 202 + job polling (avoids free-tier 429 timeouts)
  // Use when USE_BACKGROUND_JOBS=true or for large scans
  uploadDocumentsAsync(
    credentials: Credentials,
    files: File[],
  ): Promise<{ job_id: string; status: string; file_count?: number; worker_limit?: number }> {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    // Prefer header and query param both trigger background on server
    return request<{ job_id: string; status: string; file_count?: number; worker_limit?: number }>(
      credentials,
      "/api/v1/documents?async=true",
      {
        method: "POST",
        headers: { Prefer: "respond-async" },
        body: form,
      },
    );
  },

  getJob(credentials: Credentials, jobId: string): Promise<Job> {
    return request<Job>(credentials, `/api/v1/jobs/${encodeURIComponent(jobId)}`);
  },

  listJobs(credentials: Credentials): Promise<{ jobs: Job[] }> {
    return request<{ jobs: Job[] }>(credentials, "/api/v1/jobs");
  },

  // Helper: poll job until completed/failed (used by UploadPage for real progress)
  //
  // Server restarts are expected (a redeploy, or the platform recycling the
  // container after a memory spike). A single failed poll therefore must NOT
  // fail the upload: the work continues server-side and the job row is the
  // source of truth. Transient errors are tolerated for a grace window and
  // reported through onUnreachable so the UI can say "still processing,
  // reconnecting" instead of the misleading "Can't reach the server".
  async pollJobUntilDone(
    credentials: Credentials,
    jobId: string,
    onProgress?: (job: Job) => void,
    intervalMs = 4000,
    timeoutMs = 10 * 60 * 1000,
    options: {
      onUnreachable?: (info: { consecutiveFailures: number; error: ApiError }) => void;
      onReconnected?: () => void;
      unreachableGraceMs?: number;
    } = {},
  ): Promise<Job> {
    const start = Date.now();
    const graceMs = options.unreachableGraceMs ?? 90 * 1000;
    let firstFailureAt: number | null = null;
    let consecutiveFailures = 0;
    // Exponential backoff on transient failures (4s -> 8s -> 16s -> ...
    // capped at 30s) so a redeploy or a slow server doesn't get hammered
    // with hundreds of /api/v1/jobs/{id} requests in a few seconds. Reset
    // to the base interval after any successful poll.
    let pollInterval = intervalMs;

    while (Date.now() - start < timeoutMs) {
      try {
        const job = await api.getJob(credentials, jobId);
        pollInterval = intervalMs; // backoff reset after a successful poll
        if (firstFailureAt !== null) {
          firstFailureAt = null;
          consecutiveFailures = 0;
          options.onReconnected?.();
        }
        if (onProgress) onProgress(job);
        if (job.status === "completed" || job.status === "failed") return job;
      } catch (err) {
        const apiError =
          err instanceof ApiError
            ? err
            : new ApiError(0, err instanceof Error ? err.message : "Polling failed");

        // A 401 means the session is invalid — retrying cannot help.
        // A 404 after the job existed means the server lost it (restart with
        // in-memory jobs); that is still worth waiting out briefly, because
        // the record may already be saved and reload will show it.
        if (apiError.status === 401) throw apiError;

        consecutiveFailures += 1;
        if (firstFailureAt === null) firstFailureAt = Date.now();
        options.onUnreachable?.({ consecutiveFailures, error: apiError });

        // Back off harder as failures pile up so a sustained outage isn't
        // turned into a request flood.
        pollInterval = Math.min(pollInterval * 2, 30000);

        if (Date.now() - firstFailureAt > graceMs) {
          throw new ApiError(
            apiError.status,
            "Your files finished uploading, but the server stopped responding while we were tracking progress. Your records are saved — reopen this page in a moment to see them.",
            apiError.detail,
            { code: "job_status_unavailable", retryable: true },
          );
        }
      }
      await new Promise((r) => setTimeout(r, pollInterval));
    }
    throw new ApiError(
      408,
      "The browser stopped waiting, but the server may still be processing this upload. Do not upload the same files again yet; check back shortly.",
      undefined,
      { code: "job_poll_timeout", retryable: false },
    );
  },

  // Every document page persisted in Supabase for this user. Authoritative
  // across restarts — used to verify/reconstruct the record independently
  // of any in-process state.
  listDocuments(credentials: Credentials): Promise<DocumentsResponse> {
    return request<DocumentsResponse>(credentials, "/api/v1/documents");
  },

  deleteDocument(credentials: Credentials, documentId: string): Promise<DeleteDocumentResponse> {
    return request<DeleteDocumentResponse>(
      credentials,
      `/api/v1/documents/${encodeURIComponent(documentId)}`,
      { method: "DELETE" },
    );
  },

  deleteWorkspace(credentials: Credentials): Promise<DeleteWorkspaceResponse> {
    return request<DeleteWorkspaceResponse>(credentials, "/api/v1/workspace", {
      method: "DELETE",
    });
  },

  getProfile(credentials: Credentials): Promise<PatientProfile> {
    return request<PatientProfile>(credentials, "/api/v1/profile");
  },

  updateProfile(credentials: Credentials, profile: PatientProfileInput): Promise<PatientProfile> {
    return request<PatientProfile>(credentials, "/api/v1/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
  },

  // Re-runs the full per-document pipeline for one stored document (fetches
  // the original from storage, re-extracts, rebuilds timeline/safety/index).
  reprocessDocument(
    credentials: Credentials,
    documentId: string,
  ): Promise<ReprocessDocumentResponse> {
    return request<ReprocessDocumentResponse>(
      credentials,
      `/api/v1/documents/${encodeURIComponent(documentId)}/reprocess`,
      { method: "POST" },
    );
  },

  getDocumentSignedUrl(
    credentials: Credentials,
    documentId: string,
    expiresInSeconds = 900,
  ): Promise<DocumentSignedUrlResponse> {
    return request<DocumentSignedUrlResponse>(
      credentials,
      `/api/v1/documents/${encodeURIComponent(documentId)}/signed-url?expires_in_seconds=${encodeURIComponent(String(expiresInSeconds))}`,
      { method: "POST" },
    );
  },

  processDocumentText(credentials: Credentials, documentId: string): Promise<ProcessTextResponse> {
    return request<ProcessTextResponse>(
      credentials,
      `/api/v1/documents/${encodeURIComponent(documentId)}/process-text`,
      { method: "POST" },
    );
  },

  // One request returns timeline + cross-check + lab trends together (the
  // dashboard's whole record). Individual getters below remain for pages
  // that need just one slice, and for backward compatibility.
  getPatientSnapshot(credentials: Credentials): Promise<PatientSnapshot> {
    return request<PatientSnapshot>(credentials, "/api/v1/patient-snapshot");
  },

  getTimeline(credentials: Credentials): Promise<Timeline> {
    return request<Timeline>(credentials, "/api/v1/timeline");
  },

  getDocumentCorrections(
    credentials: Credentials,
    documentId: string,
  ): Promise<DocumentCorrectionsResponse> {
    return request<DocumentCorrectionsResponse>(
      credentials,
      `/api/v1/documents/${encodeURIComponent(documentId)}/corrections`,
    );
  },

  correctDocument(
    credentials: Credentials,
    documentId: string,
    changes: Array<{
      field_path: string;
      corrected_value: unknown;
      expected_previous_value?: unknown;
    }>,
    reason: string,
  ): Promise<RecordRebuildResponse> {
    return request<RecordRebuildResponse>(
      credentials,
      `/api/v1/documents/${encodeURIComponent(documentId)}/corrections`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changes, reason }),
      },
    );
  },

  getConflicts(credentials: Credentials, includeInactive = false): Promise<ConflictsResponse> {
    return request<ConflictsResponse>(
      credentials,
      `/api/v1/conflicts?include_inactive=${includeInactive ? "true" : "false"}`,
    );
  },

  resolveConflict(
    credentials: Credentials,
    conflictId: string,
    authoritativeDocumentId: string,
    note?: string,
  ): Promise<RecordRebuildResponse> {
    return request<RecordRebuildResponse>(
      credentials,
      `/api/v1/conflicts/${encodeURIComponent(conflictId)}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          authoritative_document_id: authoritativeDocumentId,
          note: note || null,
        }),
      },
    );
  },

  reopenConflict(
    credentials: Credentials,
    conflictId: string,
    note?: string,
  ): Promise<RecordRebuildResponse> {
    return request<RecordRebuildResponse>(
      credentials,
      `/api/v1/conflicts/${encodeURIComponent(conflictId)}/reopen`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: note || null }),
      },
    );
  },

  getCrossCheck(credentials: Credentials): Promise<CrossCheckReport> {
    return request<CrossCheckReport>(credentials, "/api/v1/cross-check");
  },

  getMedicationSafety(
    credentials: Credentials,
  ): Promise<CrossCheckReport & { dosage_report?: DosageReport }> {
    return request<CrossCheckReport & { dosage_report?: DosageReport }>(
      credentials,
      "/api/v1/medication-safety",
    );
  },

  getDosageReport(credentials: Credentials): Promise<DosageReport> {
    return request<DosageReport>(credentials, "/api/v1/dosage-report");
  },

  reanalyzeMedicationSafety(credentials: Credentials): Promise<{
    reanalyzed: boolean;
    findings_before: number;
    findings_after: number;
    net_change: number;
    resolved_count: number;
    cross_check_report: CrossCheckReport;
    dosage_report: DosageReport;
  }> {
    return request(credentials, "/api/v1/medication-safety/reanalyze", { method: "POST" });
  },

  getLabTrends(credentials: Credentials): Promise<LabTrendsReport> {
    return request<LabTrendsReport>(credentials, "/api/v1/lab-trends");
  },

  listAnalyses(credentials: Credentials): Promise<AnalysisLogsResponse> {
    return request<AnalysisLogsResponse>(credentials, "/api/v1/analyses");
  },

  getRiskTimeline(credentials: Credentials): Promise<RiskTimelineReport> {
    return request<RiskTimelineReport>(credentials, "/api/v1/risk-timeline");
  },

  getRecordChanges(credentials: Credentials): Promise<RecordChangesReport> {
    return request<RecordChangesReport>(credentials, "/api/v1/changes");
  },

  getFollowUpPlan(credentials: Credentials): Promise<FollowUpPlan> {
    return request<FollowUpPlan>(credentials, "/api/v1/follow-up");
  },

  getRecordIntegrity(credentials: Credentials): Promise<RecordIntegrityReport> {
    return request<RecordIntegrityReport>(credentials, "/api/v1/record-integrity");
  },

  getAppointmentPrep(credentials: Credentials): Promise<AppointmentPrepReport> {
    return request<AppointmentPrepReport>(credentials, "/api/v1/appointment-prep");
  },

  getCareRecommendation(credentials: Credentials): Promise<CareRecommendation> {
    return request<CareRecommendation>(credentials, "/api/v1/care/recommendation");
  },

  getCareRecommendationContext(credentials: Credentials): Promise<CareRecommendationContext> {
    return request<CareRecommendationContext>(credentials, "/api/v1/care-recommendations");
  },

  searchCareProviders(
    credentials: Credentials,
    body: {
      flag_id: string;
      location: string;
      availability: "any" | "today" | "this_week" | "evenings" | "weekends";
    },
  ): Promise<CareProviderSearchResponse> {
    return request<CareProviderSearchResponse>(credentials, "/api/v1/care-recommendations/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  async getCareFacilities(
    credentials: Credentials,
    options: {
      location: string;
      kind?: "any" | DirectoryFacilityKind;
      radiusKm?: number;
      latitude?: number;
      longitude?: number;
      specialty?: string;
      availability?: CareAvailability;
      signal?: AbortSignal;
    },
  ): Promise<CareFacility[]> {
    const params = new URLSearchParams({
      location: options.location,
      kind: options.kind || "any",
      radius_km: String(options.radiusKm || 5),
    });
    if (options.latitude !== undefined) params.set("latitude", String(options.latitude));
    if (options.longitude !== undefined) params.set("longitude", String(options.longitude));
    if (options.specialty?.trim()) params.set("specialty", options.specialty.trim());
    if (options.availability && options.availability !== "any") {
      params.set("availability", options.availability);
    }
    const facilities = await request<CareFacilityResponse[]>(
      credentials,
      `/api/v1/care/facilities?${params.toString()}`,
      { signal: options.signal },
    );
    return facilities.map(normalizeCareFacility);
  },

  ask(
    credentials: Credentials,
    question: string,
    topK = 8,
    signal?: AbortSignal,
  ): Promise<QAResponse> {
    return request<QAResponse>(credentials, "/api/v1/qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: topK }),
      signal,
    });
  },

  createSession(credentials: Credentials): Promise<SessionInfo> {
    return request<SessionInfo>(credentials, "/api/v1/sessions", { method: "POST" });
  },

  postMessage(
    credentials: Credentials,
    sessionId: string,
    question: string,
    topK = 8,
  ): Promise<QAResponse> {
    return request<QAResponse>(
      credentials,
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, top_k: topK }),
      },
    );
  },

  getSession(credentials: Credentials, sessionId: string): Promise<SessionHistory> {
    return request<SessionHistory>(
      credentials,
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
    );
  },

  deleteSession(credentials: Credentials, sessionId: string): Promise<void> {
    return request<void>(credentials, `/api/v1/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
  },

  searchFacilities(
    credentials: Credentials,
    location: string,
    kind: FacilityKind = "any",
    radiusKm = 8,
  ): Promise<CareFacilitiesResponse> {
    const params = new URLSearchParams({
      location,
      kind,
      radius_km: String(radiusKm),
    });
    return request<CareFacilitiesResponse>(credentials, `/api/v1/care/facilities?${params}`);
  },

  getCareSuggestion(credentials: Credentials): Promise<CareSuggestion> {
    return request<CareSuggestion>(credentials, "/api/v1/care/suggestion");
  },

  getScoredCareRecommendations(
    credentials: Credentials,
    signal?: AbortSignal,
  ): Promise<ScoredCareRecommendationsResponse> {
    return request<ScoredCareRecommendationsResponse>(credentials, "/api/v1/care/recommendations", {
      signal,
    });
  },

  searchCare(
    credentials: Credentials,
    body: {
      city: string;
      specialty?: string;
      days?: CareDay[];
      time_of_day?: CareTimeOfDay;
      radius_km?: number;
    },
  ): Promise<CareSearchResponse> {
    return request<CareSearchResponse>(credentials, "/api/v1/care/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },

  // ---- Clinical-safety & longitudinal CDS (P0/P1/P2) --------------------- //
  getVitalTrends(credentials: Credentials): Promise<VitalTrendsReport> {
    return request<VitalTrendsReport>(credentials, "/api/v1/vital-trends");
  },
  getEarlyWarning(credentials: Credentials): Promise<EarlyWarningReport> {
    return request<EarlyWarningReport>(credentials, "/api/v1/early-warning");
  },
  getAdherence(credentials: Credentials): Promise<AdherenceReport> {
    return request<AdherenceReport>(credentials, "/api/v1/adherence");
  },
  analyseSymptom(
    credentials: Credentials,
    symptom: string,
    duration?: string,
  ): Promise<SymptomAnalysis> {
    return request<SymptomAnalysis>(credentials, "/api/v1/symptoms/analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symptom, duration }),
    });
  },
  getPreventiveCare(credentials: Credentials): Promise<PreventiveCareReport> {
    return request<PreventiveCareReport>(credentials, "/api/v1/preventive-care");
  },
  getManagedAlerts(credentials: Credentials): Promise<ManagedAlertsReport> {
    return request<ManagedAlertsReport>(credentials, "/api/v1/findings/alerts");
  },
  recordFindingFeedback(
    credentials: Credentials,
    body: FindingFeedbackInput,
  ): Promise<FindingFeedbackEntry> {
    return request<FindingFeedbackEntry>(credentials, "/api/v1/findings/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  listFindingFeedback(credentials: Credentials): Promise<{ feedback: FindingFeedbackEntry[] }> {
    return request<{ feedback: FindingFeedbackEntry[] }>(credentials, "/api/v1/findings/feedback");
  },
  getFeedbackMetrics(credentials: Credentials): Promise<FeedbackMetrics> {
    return request<FeedbackMetrics>(credentials, "/api/v1/findings/feedback/metrics");
  },
  setFindingLifecycle(
    credentials: Credentials,
    body: FindingLifecycleInput,
  ): Promise<FindingLifecycleResult> {
    return request<FindingLifecycleResult>(credentials, "/api/v1/findings/lifecycle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  getFindingLifecycle(credentials: Credentials): Promise<FindingLifecycleOverview> {
    return request<FindingLifecycleOverview>(credentials, "/api/v1/findings/lifecycle");
  },
  importFhir(credentials: Credentials, bundle: unknown): Promise<FhirImportResult> {
    return request<FhirImportResult>(credentials, "/api/v1/import/fhir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bundle }),
    });
  },
  recordPatientMeasurement(
    credentials: Credentials,
    body: PatientMeasurementInput,
  ): Promise<PatientMeasurement> {
    return request<PatientMeasurement>(credentials, "/api/v1/patient-data/measurements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  listPatientMeasurements(
    credentials: Credentials,
    kind?: string,
  ): Promise<{ measurements: PatientMeasurement[] }> {
    const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
    return request<{ measurements: PatientMeasurement[] }>(
      credentials,
      `/api/v1/patient-data/measurements${qs}`,
    );
  },
  sendProviderMessage(
    credentials: Credentials,
    body: ProviderMessageInput,
  ): Promise<ProviderMessage> {
    return request<ProviderMessage>(credentials, "/api/v1/provider-messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  listProviderThreads(credentials: Credentials): Promise<{ threads: ProviderThread[] }> {
    return request<{ threads: ProviderThread[] }>(credentials, "/api/v1/provider-messages");
  },
  listProviderMessages(
    credentials: Credentials,
    threadId: string,
  ): Promise<{ thread_id: string; messages: ProviderMessage[] }> {
    return request<{ thread_id: string; messages: ProviderMessage[] }>(
      credentials,
      `/api/v1/provider-messages?thread_id=${encodeURIComponent(threadId)}`,
    );
  },
  getGuidelinesStatus(credentials: Credentials): Promise<GuidelinesStatus> {
    return request<GuidelinesStatus>(credentials, "/api/v1/guidelines/status");
  },

  /** Check the curated guideline sources for newer published versions. */
  refreshGuidelines(credentials: Credentials): Promise<GuidelinesRefreshResult> {
    return request<GuidelinesRefreshResult>(credentials, "/api/v1/guidelines/refresh", {
      method: "POST",
    });
  },

  /** Who to talk to (pharmacist / doctor), how soon, and why. */
  getConsultTriage(credentials: Credentials): Promise<ConsultTriageReport> {
    return request<ConsultTriageReport>(credentials, "/api/v1/consult-triage");
  },

  /** Reconciled current medicine list: active / duplicate / conflict / stopped. */
  getMedicationReconciliation(credentials: Credentials): Promise<MedicationReconciliationReport> {
    return request<MedicationReconciliationReport>(
      credentials,
      "/api/v1/medications/reconciliation",
    );
  },

  /** Early-warning trajectory across every dated reading. */
  getDeterioration(credentials: Credentials): Promise<DeteriorationReport> {
    return request<DeteriorationReport>(credentials, "/api/v1/deterioration");
  },

  /**
   * Full record export. `json` is the complete MediMind copy; `fhir` is the
   * standard FHIR R4 bundle other health systems can import.
   */
  exportRecord(
    credentials: Credentials,
    format: "json" | "fhir" = "json",
  ): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>(
      credentials,
      `/api/v1/export?format=${encodeURIComponent(format)}`,
    );
  },

  /** Structural check of the FHIR export before it is handed to a clinic. */
  validateRecordExport(credentials: Credentials): Promise<FhirValidationReport> {
    return request<FhirValidationReport>(credentials, "/api/v1/export/validation?format=fhir");
  },

  /** Every field correction saved in this workspace (append-only audit). */
  listCorrections(credentials: Credentials): Promise<{ corrections: CorrectionEvent[] }> {
    return request<{ corrections: CorrectionEvent[] }>(credentials, "/api/v1/corrections");
  },

  /** Per-finding change log: first seen, last seen, whether it came back. */
  getFindingChangeLog(credentials: Credentials): Promise<FindingChangeLog> {
    return request<FindingChangeLog>(credentials, "/api/v1/findings/history/change-log");
  },

  /** Record the current safety findings as a point-in-time snapshot. */
  captureFindingSnapshot(credentials: Credentials): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>(credentials, "/api/v1/findings/history/snapshot", {
      method: "POST",
    });
  },
};
