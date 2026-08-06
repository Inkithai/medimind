import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Spinner } from "../components/Spinner";
import { SettingsIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";

interface FormState {
  apiBase: string;
  token: string;
  userId: string;
}

export function SettingsPage() {
  const { credentials, isConfigured, saveCredentials, clearCredentials } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState<FormState>({
    apiBase: credentials.apiBase,
    token: credentials.token,
    userId: credentials.userId,
  });
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<
    | { ok: true; message: string }
    | { ok: false; message: string }
    | null
  >(null);

  useEffect(() => {
    setForm({
      apiBase: credentials.apiBase,
      token: credentials.token,
      userId: credentials.userId,
    });
  }, [credentials]);

  const update = (field: keyof FormState, value: string) =>
    setForm((f) => ({ ...f, [field]: value }));

  const canTest = form.token.trim().length > 0 && form.userId.trim().length > 0;

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    const creds = {
      apiBase: form.apiBase.trim(),
      token: form.token.trim(),
      userId: form.userId.trim(),
    };
    try {
      // 1) Unauthenticated health check proves the API is reachable.
      const health = await api.health(creds);
      // 2) Authenticated call proves the JWT + X-User-Id are accepted.
      // /timeline returns 404 for a user with no documents, which is still
      // a successful auth result (the request was authorized; there's
      // simply nothing stored yet). Treat 404 as auth-success.
      try {
        await api.getTimeline(creds);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          // expected for a brand-new user
        } else {
          throw err;
        }
      }
      setTestResult({
        ok: true,
        message: `Connected successfully. API health: "${health.status}". Credentials accepted for user ${creds.userId}.`,
      });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `[${err.status || "network"}] ${err.message}`
          : err instanceof Error
          ? err.message
          : "Connection failed.";
      setTestResult({ ok: false, message });
    } finally {
      setTesting(false);
    }
  }

  function handleSave() {
    saveCredentials({
      apiBase: form.apiBase,
      token: form.token,
      userId: form.userId,
    });
    navigate("/dashboard");
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">API connection</h1>
        <p className="mt-1 text-sm text-slate-500">
          Connect this console to your Nalam backend. The backend verifies a JWT
          bearer token locally (HS256) and requires the <code className="rounded bg-slate-100 px-1">X-User-Id</code> header
          to match the user-id claim inside that token. These credentials are
          stored only in this browser's local storage.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Backend credentials"
          description="All API calls are scoped to this authenticated user."
          icon={<SettingsIcon className="h-5 w-5" />}
        />
        <CardBody className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-700">
              API base URL
            </label>
            <input
              type="text"
              value={form.apiBase}
              onChange={(e) => update("apiBase", e.target.value)}
              placeholder="Leave empty for same-origin (recommended with the Vite proxy), e.g. http://127.0.0.1:8000"
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <p className="mt-1 text-xs text-slate-500">
              All routes are under <code className="rounded bg-slate-100 px-1">/api/v1/</code>.
              In local dev the Vite server proxies <code className="rounded bg-slate-100 px-1">/api</code> to the backend, so you can leave this blank.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">
              User ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={form.userId}
              onChange={(e) => update("userId", e.target.value)}
              placeholder="e.g. 6620a1f2..."
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <p className="mt-1 text-xs text-slate-500">
              Sent as the <code className="rounded bg-slate-100 px-1">X-User-Id</code> header. Must match the user id claim in the JWT.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">
              JWT access token <span className="text-red-500">*</span>
            </label>
            <textarea
              value={form.token}
              onChange={(e) => update("token", e.target.value)}
              rows={4}
              placeholder="Paste a Bearer JWT (without the 'Bearer ' prefix)"
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-xs shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <p className="mt-1 text-xs text-slate-500">
              Sent as <code className="rounded bg-slate-100 px-1">Authorization: Bearer &lt;token&gt;</code>.
              The token must be signed with the backend's <code className="rounded bg-slate-100 px-1">JWT_SECRET</code>.
            </p>
          </div>

          {testResult && (
            <Alert variant={testResult.ok ? "success" : "danger"}>
              <p className="break-all text-sm">{testResult.message}</p>
            </Alert>
          )}

          <div className="flex flex-wrap gap-3">
            <button
              onClick={handleTest}
              disabled={!canTest || testing}
              className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {testing && <Spinner className="h-4 w-4" />}
              Test connection
            </button>
            <button
              onClick={handleSave}
              disabled={!canTest}
              className="inline-flex items-center rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Save & continue
            </button>
            {isConfigured && (
              <button
                onClick={() => {
                  clearCredentials();
                  setForm({ apiBase: "", token: "", userId: "" });
                  setTestResult(null);
                }}
                className="inline-flex items-center rounded-md px-4 py-2 text-sm font-medium text-slate-500 hover:text-slate-700"
              >
                Clear stored credentials
              </button>
            )}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="What credentials do I need?" />
        <CardBody className="space-y-2 text-sm text-slate-600">
          <p>
            This backend has no signup/login endpoint — it relies on a JWT issued
            by your own authentication system. The token's payload must include a
            user id claim under one of: <code className="rounded bg-slate-100 px-1">user_id</code>,{" "}
            <code className="rounded bg-slate-100 px-1">userId</code>,{" "}
            <code className="rounded bg-slate-100 px-1">id</code>,{" "}
            <code className="rounded bg-slate-100 px-1">_id</code>, or{" "}
            <code className="rounded bg-slate-100 px-1">sub</code>, and the value must match
            the User ID field above.
          </p>
          <p>
            For local development you can mint a token with the same{" "}
            <code className="rounded bg-slate-100 px-1">JWT_SECRET</code> the backend uses, for
            example at <a className="text-brand-600 underline" href="https://jwt.io" target="_blank" rel="noreferrer">jwt.io</a>.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
