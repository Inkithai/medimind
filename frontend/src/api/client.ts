import type {
  CrossCheckReport,
  HealthResponse,
  LabTrendsReport,
  PatientSnapshot,
  QAResponse,
  SessionHistory,
  SessionInfo,
  Timeline,
  UploadResponse,
} from "../types/api";

export interface Job {
  job_id: string;
  user_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  progress?: { step: string; message: string; file_names?: string[] };
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

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
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
    throw new ApiError(response.status, message, data);
  }

  return data as T;
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
    throw new ApiError(response.status, message, data);
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
  uploadDocumentsAsync(credentials: Credentials, files: File[]): Promise<{ job_id: string; status: string }> {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    // Prefer header and query param both trigger background on server
    return request<{ job_id: string; status: string }>(credentials, "/api/v1/documents?async=true", {
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
  async pollJobUntilDone(
    credentials: Credentials,
    jobId: string,
    onProgress?: (job: Job) => void,
    intervalMs = 1500,
    timeoutMs = 120000
  ): Promise<Job> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const job = await api.getJob(credentials, jobId);
      if (onProgress) onProgress(job);
      if (job.status === "completed" || job.status === "failed") return job;
      await new Promise((r) => setTimeout(r, intervalMs));
    }
    throw new ApiError(408, "Upload timed out — still processing, check back shortly");
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

  ask(credentials: Credentials, question: string, topK = 8): Promise<QAResponse> {
    return request<QAResponse>(credentials, "/api/v1/qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, top_k: topK }),
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
};
