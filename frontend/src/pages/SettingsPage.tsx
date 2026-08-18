import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { Spinner } from "../components/Spinner";
import { SettingsIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { LanguageSelector } from "../components/LanguageSelector";

export function SettingsPage() {
  const { credentials, isConfigured, isInitializing, initError, createNewWorkspace, clearCredentials } = useAuth();
  const { t } = useI18n();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingWorkspace, setDeletingWorkspace] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!deleteOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deletingWorkspace) {
        setDeleteOpen(false);
        window.setTimeout(() => deleteTriggerRef.current?.focus(), 0);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [deleteOpen, deletingWorkspace]);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const health = await api.healthUnauthenticated(credentials.apiBase);
      try {
        await api.getTimeline(credentials);
        setTestResult({ ok: true, message: t("settings.connected") });
      } catch (err: any) {
        if (err?.status === 404) {
          setTestResult({
            ok: true,
            message: t("settings.connectedEmpty"),
          });
        } else {
          throw err;
        }
      }
      void health;
    } catch (err: any) {
      setTestResult({ ok: false, message: err?.message || t("errors.server") });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">{t("settings.title")}</h1>
        <p className="secondary-text mt-2 max-w-2xl">{t("settings.subtitle")}</p>
      </header>

      <section aria-labelledby="language-settings-title" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 id="language-settings-title" className="card-title">{t("common.language")}</h2>
        <div className="mt-3 max-w-sm"><LanguageSelector /></div>
      </section>

      <section aria-labelledby="workspace-settings-title" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
            <SettingsIcon className="h-6 w-6" />
          </div>
          <div>
            <h2 id="workspace-settings-title" className="card-title">{t("settings.workspace")}</h2>
            <p className="secondary-text">{t("settings.workspaceBody")}</p>
          </div>
        </div>

        <div className="mt-5 space-y-4">
          {isInitializing ? (
            <div className="flex items-center gap-2 text-base text-slate-600">
              <Spinner className="h-5 w-5" /> Setting up your workspace…
            </div>
          ) : initError ? (
            <Alert variant="danger" title={t("auth.failedTitle")}>
              {initError}
            </Alert>
          ) : isConfigured ? (
            <>
              <div className="rounded-xl bg-brand-50 p-5 ring-1 ring-brand-100">
                <p className="text-base font-semibold text-brand-900">
                  🔒 {t("settings.ready")}
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
                  {testing && <Spinner className="h-4 w-4" />} {testing ? t("settings.checking") : t("settings.check")}
                </button>
                <button
                  onClick={() => void createNewWorkspace()}
                  className="btn-secondary"
                >
                  {t("settings.new")}
                </button>
                <button
                  onClick={() => {
                    clearCredentials();
                    window.location.href = "/";
                  }}
                  className="btn-ghost text-red-600 hover:bg-red-50 hover:text-red-700"
                >
                  {t("settings.removeBrowser")}
                </button>
              </div>

              <section aria-labelledby="delete-workspace-title" className="rounded-xl border border-red-200 bg-red-50/60 p-4">
                <h3 id="delete-workspace-title" className="text-sm font-bold text-red-900">{t("settings.dangerZone")}</h3>
                <p className="mt-1 text-sm leading-relaxed text-red-800">{t("settings.deleteDataBody")}</p>
                <button
                  ref={deleteTriggerRef}
                  type="button"
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteOpen(true);
                  }}
                  className="mt-3 inline-flex min-h-[44px] items-center rounded-xl border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-700 transition hover:bg-red-100 focus-visible:ring-red-500"
                >
                  {t("settings.deleteData")}
                </button>
              </section>

              <details className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                <summary className="cursor-pointer text-sm font-medium text-slate-600">
                  {t("settings.details")}
                </summary>
                <div className="mt-3 space-y-1 text-sm text-slate-600">
                  <p>
                    <span className="font-medium text-slate-700">{t("settings.code")}:</span>{" "}
                    <code className="break-words rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">
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
            <Alert variant="info" title={t("errors.notFound")}>
              A private workspace is created automatically the first time you open the app.
            </Alert>
          )}
        </div>
      </section>

      {deleteOpen && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/55 p-4" role="presentation">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-workspace-dialog-title"
            aria-describedby="delete-workspace-dialog-description"
            className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
          >
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-50 text-xl font-bold text-red-700" aria-hidden="true">!</div>
            <h2 id="delete-workspace-dialog-title" className="mt-4 text-lg font-bold text-slate-900">{t("settings.deleteConfirmTitle")}</h2>
            <p id="delete-workspace-dialog-description" className="mt-2 text-sm leading-relaxed text-slate-600">
              {t("settings.deleteConfirmBody")}
            </p>
            {deleteError && <p role="alert" className="mt-3 text-sm text-red-700">{deleteError}</p>}
            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
                autoFocus
                disabled={deletingWorkspace}
                onClick={() => {
                  setDeleteOpen(false);
                  window.setTimeout(() => deleteTriggerRef.current?.focus(), 0);
                }}
                className="btn-secondary"
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                disabled={deletingWorkspace}
                onClick={async () => {
                  setDeletingWorkspace(true);
                  setDeleteError(null);
                  try {
                    await api.deleteWorkspace(credentials);
                    clearCredentials();
                    window.location.href = "/";
                  } catch (err) {
                    setDeleteError(err instanceof Error ? err.message : String(err));
                    setDeletingWorkspace(false);
                  }
                }}
                className="btn min-w-[170px] bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-500 disabled:cursor-not-allowed"
              >
                {deletingWorkspace ? t("settings.deletingData") : t("settings.deleteConfirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
