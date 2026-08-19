import { useEffect, useRef, useState } from "react";
import { ApiError, api, type PatientProfileInput } from "../api/client";
import { Alert } from "../components/Alert";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { toastMessage, useToast } from "../components/Toast";
import { DownloadIcon, SettingsIcon, ShieldIcon } from "../components/icons";
import { downloadJsonFile, todayStamp } from "../utils/download";
import type { FhirValidationReport } from "../types/api";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { LanguageSelector } from "../components/LanguageSelector";

export function SettingsPage() {
  const {
    credentials,
    isConfigured,
    isInitializing,
    initError,
    createNewWorkspace,
    clearCredentials,
  } = useAuth();
  const { t } = useI18n();
  const { toastSuccess, toastError, toastInfo } = useToast();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletingWorkspace, setDeletingWorkspace] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [profile, setProfile] = useState<PatientProfileInput>({});
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileNotice, setProfileNotice] = useState<string | null>(null);
  const deleteTriggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!isConfigured) return;
    let cancelled = false;
    setProfileLoading(true);
    api
      .getProfile(credentials)
      .then((value) => {
        if (!cancelled) setProfile(value);
      })
      .catch((error) => {
        if (!cancelled) setProfileNotice(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (!cancelled) setProfileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [credentials, isConfigured]);

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
      } catch (err) {
        const error = err as { status?: number; message?: string };
        if (error?.status === 404) {
          setTestResult({
            ok: true,
            message: t("settings.connectedEmpty"),
          });
        } else {
          throw err;
        }
      }
      void health;
    } catch (err) {
      const error = err as { status?: number; message?: string };
      setTestResult({ ok: false, message: error?.message || t("errors.server") });
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

      <section
        aria-labelledby="language-settings-title"
        className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h2 id="language-settings-title" className="card-title">
          {t("common.language")}
        </h2>
        <div className="mt-3 max-w-sm">
          <LanguageSelector />
        </div>
      </section>

      <section
        aria-labelledby="profile-settings-title"
        className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <h2 id="profile-settings-title" className="card-title">
          Patient profile
        </h2>
        <p className="secondary-text mt-1 max-w-2xl">
          Optional identity and contact details. Profile identity is used only as an additional
          mismatch signal and never silently overrides uploaded records.
        </p>
        {profileLoading ? (
          <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
            <Spinner className="h-4 w-4" /> Loading profile…
          </div>
        ) : (
          <form
            className="mt-4 grid gap-4 sm:grid-cols-2"
            onSubmit={async (event) => {
              event.preventDefault();
              setProfileSaving(true);
              setProfileNotice(null);
              try {
                const saved = await api.updateProfile(credentials, profile);
                setProfile(saved);
                setProfileNotice("Profile saved securely.");
                toastSuccess("Profile saved", "Your details are stored with your private records.");
              } catch (error) {
                setProfileNotice(error instanceof Error ? error.message : String(error));
                toastError("Profile not saved", toastMessage(error));
              } finally {
                setProfileSaving(false);
              }
            }}
          >
            <label className="text-sm font-medium text-slate-700">
              Legal name
              <input
                className="input mt-1 w-full"
                value={profile.legal_name || ""}
                onChange={(e) => setProfile({ ...profile, legal_name: e.target.value })}
                autoComplete="name"
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Preferred name
              <input
                className="input mt-1 w-full"
                value={profile.preferred_name || ""}
                onChange={(e) => setProfile({ ...profile, preferred_name: e.target.value })}
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Date of birth
              <input
                type="date"
                className="input mt-1 w-full"
                value={profile.date_of_birth || ""}
                max={new Date().toISOString().slice(0, 10)}
                onChange={(e) => setProfile({ ...profile, date_of_birth: e.target.value })}
              />
            </label>
            <label className="text-sm font-medium text-slate-700">
              Phone
              <input
                type="tel"
                className="input mt-1 w-full"
                value={profile.phone || ""}
                onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
                autoComplete="tel"
              />
            </label>
            <label className="text-sm font-medium text-slate-700 sm:col-span-2">
              Emergency contact
              <input
                className="input mt-1 w-full"
                value={profile.emergency_contact || ""}
                onChange={(e) => setProfile({ ...profile, emergency_contact: e.target.value })}
                placeholder="Name and contact details"
              />
            </label>
            <div className="flex items-center gap-3 sm:col-span-2">
              <button
                type="submit"
                disabled={profileSaving || !isConfigured}
                className="btn-primary"
              >
                {profileSaving ? "Saving…" : "Save patient profile"}
              </button>
              {profileNotice && (
                <p role="status" className="text-sm text-slate-600">
                  {profileNotice}
                </p>
              )}
            </div>
          </form>
        )}
      </section>

      <RecordExportSection
        onSuccess={toastSuccess}
        onError={toastError}
        onInfo={toastInfo}
        disabled={!isConfigured}
        credentials={credentials}
      />

      <section
        aria-labelledby="workspace-settings-title"
        className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
            <SettingsIcon className="h-6 w-6" />
          </div>
          <div>
            <h2 id="workspace-settings-title" className="card-title">
              {t("settings.workspace")}
            </h2>
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
                <p className="text-base font-semibold text-brand-900">🔒 {t("settings.ready")}</p>
                <p className="mt-1 text-sm leading-relaxed text-brand-800/80">
                  MediMind works without an account. This browser stores the anonymous key used to
                  access records held by MediMind's connected storage services. See About MediMind
                  for the full data model.
                </p>
              </div>

              {testResult && (
                <Alert variant={testResult.ok ? "success" : "danger"}>
                  <p className="text-sm">{testResult.message}</p>
                </Alert>
              )}

              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => void handleTest()}
                  disabled={testing}
                  className="btn-secondary"
                >
                  {testing && <Spinner className="h-4 w-4" />}{" "}
                  {testing ? t("settings.checking") : t("settings.check")}
                </button>
                <button
                  onClick={() => {
                    if (
                      window.confirm(
                        "Start a new workspace? This browser will lose access to the current workspace unless you saved its code. Stored data is not deleted.",
                      )
                    ) {
                      void createNewWorkspace();
                    }
                  }}
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

              <section
                aria-labelledby="delete-workspace-title"
                className="rounded-xl border border-red-200 bg-red-50/60 p-4"
              >
                <h3 id="delete-workspace-title" className="text-sm font-bold text-red-900">
                  {t("settings.dangerZone")}
                </h3>
                <p className="mt-1 text-sm leading-relaxed text-red-800">
                  {t("settings.deleteDataBody")}
                </p>
                <button
                  ref={deleteTriggerRef}
                  type="button"
                  onClick={() => {
                    setDeleteError(null);
                    setDeleteConfirmation("");
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
        <div
          className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/55 p-4"
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-workspace-dialog-title"
            aria-describedby="delete-workspace-dialog-description"
            className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-2xl"
          >
            <div
              className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-50 text-xl font-bold text-red-700"
              aria-hidden="true"
            >
              !
            </div>
            <h2
              id="delete-workspace-dialog-title"
              className="mt-4 text-lg font-bold text-slate-900"
            >
              {t("settings.deleteConfirmTitle")}
            </h2>
            <p
              id="delete-workspace-dialog-description"
              className="mt-2 text-sm leading-relaxed text-slate-600"
            >
              {t("settings.deleteConfirmBody")}
            </p>
            <label className="mt-4 block text-sm font-semibold text-slate-800">
              Type <span className="font-mono text-red-700">RESET</span> to confirm
              <input
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                autoFocus
                autoComplete="off"
                spellCheck={false}
                className="input mt-2 w-full font-mono"
                aria-describedby="delete-workspace-dialog-description"
              />
            </label>
            {deleteError && (
              <p role="alert" className="mt-3 text-sm text-red-700">
                {deleteError}
              </p>
            )}
            <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
              <button
                type="button"
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
                disabled={deletingWorkspace || deleteConfirmation !== "RESET"}
                onClick={async () => {
                  if (deleteConfirmation !== "RESET") return;
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
                className="btn min-w-[170px] bg-red-600 text-white hover:bg-red-700 focus-visible:ring-red-500 disabled:cursor-not-allowed disabled:opacity-50"
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

/**
 * "Take a copy of your records with you."
 *
 * Exposes the export endpoints the backend already serves
 * (GET /api/v1/export and /api/v1/export/validation). Both formats are
 * described by what the user would do with them rather than by their
 * technical name, and the FHIR file can be checked before it is handed to
 * a clinic so nobody discovers a broken file at the reception desk.
 */
function RecordExportSection({
  credentials,
  disabled,
  onSuccess,
  onError,
  onInfo,
}: {
  credentials: Parameters<typeof api.exportRecord>[0];
  disabled: boolean;
  onSuccess: (title: string, description?: string) => void;
  onError: (title: string, description?: string) => void;
  onInfo: (title: string, description?: string) => void;
}) {
  const [busy, setBusy] = useState<"json" | "fhir" | "check" | null>(null);
  const [validation, setValidation] = useState<FhirValidationReport | null>(null);

  const noRecordsYet = (error: unknown) => error instanceof ApiError && error.status === 404;

  async function handleDownload(format: "json" | "fhir") {
    setBusy(format);
    try {
      const data = await api.exportRecord(credentials, format);
      const filename =
        format === "fhir"
          ? `medimind-records-for-clinic-${todayStamp()}.json`
          : `medimind-records-${todayStamp()}.json`;
      if (downloadJsonFile(filename, data)) {
        onSuccess(
          "Download started",
          `Saved as ${filename}. Check your browser's Downloads folder.`,
        );
      } else {
        onError(
          "Download blocked",
          "Your browser stopped the download. Allow downloads and retry.",
        );
      }
    } catch (error) {
      if (noRecordsYet(error)) {
        onInfo("Nothing to download yet", "Upload a document first, then try again.");
      } else {
        onError("Download failed", toastMessage(error));
      }
    } finally {
      setBusy(null);
    }
  }

  async function handleValidate() {
    setBusy("check");
    setValidation(null);
    try {
      const report = await api.validateRecordExport(credentials);
      setValidation(report);
      if (report.valid) {
        onSuccess("The clinic file is ready", "It passed the structure check.");
      } else {
        onError(
          "The clinic file has problems",
          `${report.errors?.length || 0} issue(s) were found. See the details below.`,
        );
      }
    } catch (error) {
      if (noRecordsYet(error)) {
        onInfo("Nothing to check yet", "Upload a document first, then try again.");
      } else {
        onError("Check failed", toastMessage(error));
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <section
      aria-labelledby="record-export-title"
      className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
          <DownloadIcon className="h-6 w-6" aria-hidden="true" />
        </div>
        <div>
          <h2 id="record-export-title" className="card-title">
            Take a copy of your records
          </h2>
          <p className="secondary-text">
            Download everything MediMind has read from your documents. Nothing is deleted by
            downloading.
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col justify-between rounded-xl border border-slate-200 p-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">A copy for yourself</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              Your timeline, medicine checks and lab trends in one file you can keep or email to
              family.
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary mt-4 w-full"
            disabled={disabled || busy !== null}
            onClick={() => void handleDownload("json")}
          >
            {busy === "json" ? (
              <Spinner className="h-5 w-5" />
            ) : (
              <DownloadIcon className="h-5 w-5" />
            )}
            {busy === "json" ? "Preparing your file…" : "Download my copy"}
          </button>
        </div>

        <div className="flex flex-col justify-between rounded-xl border border-slate-200 p-4">
          <div>
            <h3 className="text-base font-semibold text-slate-900">A copy for a clinic</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-600">
              The same record in the standard format (FHIR) hospitals and clinics can import into
              their own system.
            </p>
          </div>
          <div className="mt-4 space-y-2">
            <button
              type="button"
              className="btn-secondary w-full"
              disabled={disabled || busy !== null}
              onClick={() => void handleDownload("fhir")}
            >
              {busy === "fhir" ? (
                <Spinner className="h-5 w-5" />
              ) : (
                <DownloadIcon className="h-5 w-5" />
              )}
              {busy === "fhir" ? "Preparing your file…" : "Download clinic copy"}
            </button>
            <button
              type="button"
              className="btn-ghost w-full"
              disabled={disabled || busy !== null}
              onClick={() => void handleValidate()}
              title="Checks that the clinic file has the right structure before you send it."
            >
              {busy === "check" ? (
                <Spinner className="h-5 w-5" />
              ) : (
                <ShieldIcon className="h-5 w-5" />
              )}
              {busy === "check" ? "Checking…" : "Check the clinic copy first"}
            </button>
          </div>
        </div>
      </div>

      {validation && (
        <div className="mt-4">
          <Alert
            variant={validation.valid ? "success" : "danger"}
            title={
              validation.valid
                ? "This file is ready to share with a clinic"
                : "This file needs attention before sharing"
            }
          >
            <div className="space-y-2 text-sm">
              <div className="flex flex-wrap gap-2">
                <StatusBadge tone={validation.valid ? "success" : "danger"}>
                  {validation.valid ? "✓ Structure check passed" : "✗ Structure check failed"}
                </StatusBadge>
                {validation.resource_counts &&
                  Object.entries(validation.resource_counts).map(([kind, count]) => (
                    <StatusBadge key={kind} tone="neutral">
                      {kind}: {count}
                    </StatusBadge>
                  ))}
              </div>
              {validation.errors && validation.errors.length > 0 && (
                <ul className="list-disc space-y-1 pl-5">
                  {validation.errors.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              )}
              {validation.warnings && validation.warnings.length > 0 && (
                <details>
                  <summary className="cursor-pointer font-semibold">
                    Notes ({validation.warnings.length})
                  </summary>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {validation.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          </Alert>
        </div>
      )}
    </section>
  );
}
