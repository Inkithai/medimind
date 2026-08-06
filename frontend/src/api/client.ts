import type {
  CrossCheckReport,
  HealthResponse,
  LabTrendsReport,
  QAResponse,
  SessionHistory,
  SessionInfo,
  Timeline,
  UploadResponse,
} from "../types/api";

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
