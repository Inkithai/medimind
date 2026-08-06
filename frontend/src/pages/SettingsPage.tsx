import { useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody, CardHeader } from "../components/Card";
import { Spinner } from "../components/Spinner";
import { SettingsIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";

export function SettingsPage() {
  const { credentials, isConfigured, isInitializing, initError, createNewWorkspace, clearCredentials } = useAuth();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const health = await api.healthUnauthenticated(credentials.apiBase);
      // Try timeline as auth test
      try {
        await api.getTimeline(credentials);
        setTestResult({ ok: true, message: `API ${health.status} • Auth OK for ${credentials.userId}` });
      } catch (err: any) {
        if (err?.status === 404) {
          setTestResult({ ok: true, message: `API ${health.status} • Auth OK for ${credentials.userId} (no docs yet)` });
        } else {
          throw err;
        }
      }
    } catch (err: any) {
      setTestResult({ ok: false, message: err?.message || "Connection failed" });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Workspace • MediMind</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">
          MediMind uses an <strong>anonymous workspace</strong> per browser. No email, no password. Backend issues a signed
          JWT via <code className="rounded bg-slate-100 px-1">POST /api/v1/anonymous/session</code> using{" "}
          <code className="rounded bg-slate-100 px-1">JWT_SECRET</code> from <code className="rounded bg-slate-100 px-1">.env</code>. The
          workspace ID (<code className="rounded bg-slate-100 px-1">anon_*</code>) is stored in{" "}
          <code className="rounded bg-slate-100 px-1">localStorage.medimind.session.v1</code> only in this browser.
          Clearing it resets your isolated patient record.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Anonymous session"
          description="Auto-provisioned on first visit. No manual credentials needed."
          icon={<SettingsIcon className="h-5 w-5" />}
        />
        <CardBody className="space-y-4">
          {isInitializing ? (
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Spinner className="h-4 w-4" /> Creating workspace…
            </div>
          ) : initError ? (
            <Alert variant="danger" title="Workspace creation failed">
              {initError}
            </Alert>
          ) : isConfigured ? (
            <div className="space-y-3">
              <div className="rounded-xl bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Workspace ID (user_id)</p>
                <p className="mt-1 break-all font-mono text-sm font-medium text-slate-800">{credentials.userId}</p>
                <p className="mt-2 text-xs text-slate-500">
                  API base: {credentials.apiBase || "(same origin via Vite proxy)"} • token: {credentials.token.slice(0, 18)}…{" "}
                  (hidden)
                </p>
                <p className="mt-2 text-xs text-slate-500">
                  Data isolation: <code className="rounded bg-white px-1">Supabase documents.user_id</code>,{" "}
                  <code className="rounded bg-white px-1">patient_snapshots.user_id</code>,{" "}
                  <code className="rounded bg-white px-1">Chroma collection</code>,{" "}
                  <code className="rounded bg-white px-1">Cloudinary mediscan/{credentials.userId}/</code>
                </p>
              </div>

              {testResult && (
                <Alert variant={testResult.ok ? "success" : "danger"}>
                  <p className="break-all text-xs">{testResult.message}</p>
                </Alert>
              )}

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => void handleTest()}
                  disabled={testing}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  {testing && <Spinner className="h-4 w-4" />} Test connection
                </button>
                <button
                  onClick={() => void createNewWorkspace()}
                  className="inline-flex items-center rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
                >
                  Create new workspace
                </button>
                <button
                  onClick={() => {
                    clearCredentials();
                    window.location.href = "/";
                  }}
                  className="inline-flex items-center rounded-xl px-4 py-2 text-sm font-medium text-slate-500 hover:text-slate-700"
                >
                  Clear & go to landing
                </button>
              </div>
            </div>
          ) : (
            <Alert variant="info" title="No workspace yet">
              Visit the landing page to create an anonymous MediMind workspace automatically.
            </Alert>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Architecture for anonymous isolation" />
        <CardBody className="space-y-3 text-sm text-slate-600">
          <p className="font-mono text-xs leading-relaxed">
            Open App → POST /api/v1/anonymous/session → {`{user_id, token, session_id}`} → localStorage.medimind.session.v1
            → Dashboard → Upload Documents → POST /api/v1/documents (with Authorization + X-User-Id) → FastAPI → Clinical
            Pipeline (OCR, Extract via Groq Llama 4 Scout, Safety checks) → Supabase + Cloudinary + Chroma → Patient Record
            → History • Medicine • Labs • Safety • Ask
          </p>
          <p>
            The backend <code className="rounded bg-slate-100 px-1">.env</code> already contains{" "}
            <code className="rounded bg-slate-100 px-1">JWT_SECRET, GROQ_API_KEY, SUPABASE_URL, etc.</code>. The frontend never
            asks for them — it just calls the anonymous session endpoint which signs a JWT server-side. This gives you
            isolated workspaces without login, while keeping all routes still verified via{" "}
            <code className="rounded bg-slate-100 px-1">auth.py:get_current_user</code>.
          </p>
          <div className="rounded-xl bg-brand-50 p-3 text-xs text-brand-800 ring-1 ring-brand-200">
            <p className="font-semibold text-brand-900">Why not ask for credentials in UI?</p>
            <p className="mt-1">
              Because they are already in <code className="rounded bg-brand-100 px-1">.env</code> on the server. Asking the
              user for JWT + User ID duplicates config and leaks implementation detail. The anonymous flow hides that
              and feels like a real consumer health app.
            </p>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
