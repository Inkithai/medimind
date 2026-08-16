import type {
  CareAvailability,
  CareFacility,
  CareFacilityResponse,
  CareRecommendation,
  FacilityKind as DirectoryFacilityKind,
} from "../types/facility";
import type {
  CareFacilitiesResponse,
  CareRecommendationContext,
  CareProviderSearchResponse,
  CrossCheckReport,
  FacilityKind,
  HealthResponse,
  LabTrendsReport,
  PatientSnapshot,
  QAResponse,
  SessionHistory,
  SessionInfo,
  Timeline,
  UploadResponse,
  CareSuggestion,
  CareSearchResponse,
  CareDay,
  CareTimeOfDay,
} from "../types/api";
import type { ScoredCareRecommendationsResponse } from "../types/recommendations";

export interface DocumentsResponse {
  user_id: string;
  count: number;
  documents: Record<string, unknown>[];
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
    metadata?: { code?: string; retryable?: boolean; retryAfterSeconds?: number | null }
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
  options: RequestOptions = {}
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
      err
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
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.toString() : undefined;
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
  options: RequestOptions = {}
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
      err
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
    files: File[]
  ): Promise<{ job_id: string; status: string; file_count?: number; worker_limit?: number }> {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    // Prefer header and query param both trigger background on server
    return request<{ job_id: string; status: string; file_count?: number; worker_limit?: number }>(credentials, "/api/v1/documents?async=true", {
      method: "POST",
      headers: { Prefer: "respond-async" },
      body: form,
    });
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
    } = {}
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
            { code: "job_status_unavailable", retryable: true }
          );
        }
      }
      await new Promise((r) => setTimeout(r, pollInterval));
    }
    throw new ApiError(
      408,
      "The browser stopped waiting, but the server may still be processing this upload. Do not upload the same files again yet; check back shortly.",
      undefined,
      { code: "job_poll_timeout", retryable: false }
    );
  },

  // Every document page persisted in Supabase for this user. Authoritative
  // across restarts — used to verify/reconstruct the record independently
  // of any in-process state.
  listDocuments(credentials: Credentials): Promise<DocumentsResponse> {
    return request<DocumentsResponse>(credentials, "/api/v1/documents");
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

  getCrossCheck(credentials: Credentials): Promise<CrossCheckReport> {
    return request<CrossCheckReport>(credentials, "/api/v1/cross-check");
  },

  getLabTrends(credentials: Credentials): Promise<LabTrendsReport> {
    return request<LabTrendsReport>(credentials, "/api/v1/lab-trends");
  },

  getCareRecommendation(credentials: Credentials): Promise<CareRecommendation> {
    return request<CareRecommendation>(credentials, "/api/v1/care/recommendation");
  },

  getCareRecommendationContext(credentials: Credentials): Promise<CareRecommendationContext> {
    return request<CareRecommendationContext>(credentials, "/api/v1/care-recommendations");
  },

  searchCareProviders(
    credentials: Credentials,
    body: { flag_id: string; location: string; availability: "any" | "today" | "this_week" | "evenings" | "weekends" }
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
    }
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
      { signal: options.signal }
    );
    return facilities.map(normalizeCareFacility);
  },

  ask(
    credentials: Credentials,
    question: string,
    topK = 8,
    signal?: AbortSignal
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
    topK = 8
  ): Promise<QAResponse> {
    return request<QAResponse>(
      credentials,
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, top_k: topK }),
      }
    );
  },

  getSession(credentials: Credentials, sessionId: string): Promise<SessionHistory> {
    return request<SessionHistory>(
      credentials,
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`
    );
  },

  deleteSession(credentials: Credentials, sessionId: string): Promise<void> {
    return request<void>(
      credentials,
      `/api/v1/sessions/${encodeURIComponent(sessionId)}`,
      { method: "DELETE" }
    );
  },

  searchFacilities(
    credentials: Credentials,
    location: string,
    kind: FacilityKind = "any",
    radiusKm = 8
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
    signal?: AbortSignal
  ): Promise<ScoredCareRecommendationsResponse> {
    return request<ScoredCareRecommendationsResponse>(
      credentials,
      "/api/v1/care/recommendations",
      { signal }
    );
  },

  searchCare(
    credentials: Credentials,
    body: {
      city: string;
      specialty?: string;
      days?: CareDay[];
      time_of_day?: CareTimeOfDay;
      radius_km?: number;
    }
  ): Promise<CareSearchResponse> {
    return request<CareSearchResponse>(credentials, "/api/v1/care/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
};
