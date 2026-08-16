import { useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
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
      try {
        await api.getTimeline(credentials);
        setTestResult({ ok: true, message: "Everything is connected and working." });
      } catch (err: any) {
        if (err?.status === 404) {
          setTestResult({
            ok: true,
            message: "Connected — you just haven't uploaded any documents yet.",
          });
        } else {
          throw err;
        }
      }
      void health;
    } catch (err: any) {
      setTestResult({ ok: false, message: err?.message || "Couldn't connect. Please try again." });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">Settings</h1>
        <p className="secondary-text mt-2 max-w-2xl">
          Manage your private workspace and check that everything is working.
        </p>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
            <SettingsIcon className="h-6 w-6" />
          </div>
          <div>
            <h2 className="card-title">Your private workspace</h2>
            <p className="secondary-text">No email, no password — created automatically.</p>
          </div>
        </div>

        <div className="mt-5 space-y-4">
          {isInitializing ? (
            <div className="flex items-center gap-2 text-base text-slate-600">
              <Spinner className="h-5 w-5" /> Setting up your workspace…
            </div>
          ) : initError ? (
            <Alert variant="danger" title="We couldn't set up your workspace">
              {initError}
            </Alert>
          ) : isConfigured ? (
            <>
              <div className="rounded-xl bg-brand-50 p-5 ring-1 ring-brand-100">
                <p className="text-base font-semibold text-brand-900">
                  🔒 Your workspace access key lives in this browser
                </p>
                <p className="mt-1 text-sm leading-relaxed text-brand-800/80">
                  MediMind works without an account. This browser stores the anonymous key used to access
                  records held by MediMind's connected storage services. See About MediMind for the full data model.
                </p>
              </div>

              {testResult && (
                <Alert variant={testResult.ok ? "success" : "danger"}>
                  <p className="text-sm">{testResult.message}</p>
                </Alert>
              )}

              <div className="flex flex-wrap gap-3">
                <button onClick={() => void handleTest()} disabled={testing} className="btn-secondary">
                  {testing && <Spinner className="h-4 w-4" />} Check connection
                </button>
                <button
                  onClick={() => void createNewWorkspace()}
                  className="btn-secondary"
                >
                  Start a new workspace
                </button>
                <button
                  onClick={() => {
                    clearCredentials();
                    window.location.href = "/";
                  }}
                  className="btn-ghost text-red-600 hover:bg-red-50 hover:text-red-700"
                >
                  Erase this workspace
                </button>
              </div>

              <details className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <summary className="cursor-pointer text-sm font-medium text-slate-600">
                  Advanced · workspace details
                </summary>
                <div className="mt-3 space-y-1 text-sm text-slate-600">
                  <p>
                    <span className="font-medium text-slate-700">Workspace code:</span>{" "}
                    <code className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">
                      {credentials.userId}
                    </code>
                  </p>
                  <p className="text-xs text-slate-500">
                    Starting a new workspace abandons this code (and the records tied to it).
                    Erasing removes it from this browser.
                  </p>
                </div>
              </details>
            </>
          ) : (
            <Alert variant="info" title="No workspace yet">
              A private workspace is created automatically the first time you open the app.
            </Alert>
          )}
        </div>
      </section>
    </div>
  );
}
