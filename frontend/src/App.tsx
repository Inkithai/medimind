import { Navigate, Route, Routes, useSearchParams } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./context/AuthContext";
import { AboutPage } from "./pages/AboutPage";
import { AnalysesPage } from "./pages/AnalysesPage";
import { AppointmentPrepPage } from "./pages/AppointmentPrepPage";
import { CareRecommendationsPage } from "./pages/CareRecommendationsPage";
import { ChangesPage } from "./pages/ChangesPage";
import { ClinicalSafetyPage } from "./pages/ClinicalSafetyPage";
import { CrossCheckPage } from "./pages/CrossCheckPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { FhirImportPage } from "./pages/FhirImportPage";
import { FollowUpPage } from "./pages/FollowUpPage";
import { GetCareHubPage } from "./pages/GetCareHubPage";
import { GuidelinesPage } from "./pages/GuidelinesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { JudgePrepPage } from "./pages/JudgePrepPage";
import { LabTrendsPage } from "./pages/LabTrendsPage";
import { LabsHubPage } from "./pages/LabsHubPage";
import { LandingPage } from "./pages/LandingPage";
import { MedicinesPage } from "./pages/MedicinesPage";
import { NextStepsHubPage } from "./pages/NextStepsHubPage";
import { PreventiveCarePage } from "./pages/PreventiveCarePage";
import { ProviderMessagesPage } from "./pages/ProviderMessagesPage";
import { QAPage } from "./pages/QAPage";
import { RecordCheckHubPage } from "./pages/RecordCheckHubPage";
import { RecordsHubPage } from "./pages/RecordsHubPage";
import { RiskTimelinePage } from "./pages/RiskTimelinePage";
import { SafetyHubPage } from "./pages/SafetyHubPage";
import { SessionPage } from "./pages/SessionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TrustHubPage } from "./pages/TrustHubPage";
import { UploadHubPage } from "./pages/UploadHubPage";
import { VitalsPage } from "./pages/VitalsPage";
import { WhoToSeePage } from "./pages/WhoToSeePage";
import { Spinner } from "./components/Spinner";
import { useI18n } from "./i18n/I18nContext";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isConfigured, isInitializing, initError } = useAuth();
  const { t } = useI18n();
  if (isInitializing) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
        <Spinner className="h-6 w-6 text-brand-600" />
        <p className="text-base font-medium text-slate-700">{t("auth.preparing")}</p>
        <p className="text-sm text-slate-600">{t("auth.oneMoment")}</p>
      </div>
    );
  }
  if (initError) {
    return (
      <div className="mx-auto max-w-md rounded-2xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-base font-semibold text-red-900">{t("auth.failedTitle")}</p>
        <p className="mt-1 text-sm text-red-700">{initError}</p>
        <p className="mt-3 text-sm text-slate-600">{t("auth.checkConnection")}</p>
      </div>
    );
  }
  if (!isConfigured) return <Navigate to="/" replace />;
  return children;
}

/** Shorthand: a workspace-scoped route. */
function Guarded({ children }: { children: JSX.Element }) {
  return <RequireAuth>{children}</RequireAuth>;
}

/**
 * /record-integrity was the same screen as the Record check tabs behind a
 * second door. It now redirects onto the hub, preserving its old
 * ?tab=conflicts contract (its default view maps to the Discrepancies tab).
 */
function RecordIntegrityRedirect() {
  const [params] = useSearchParams();
  const tab = params.get("tab") === "conflicts" ? "conflicts" : "discrepancies";
  return <Navigate to={`/record-check?tab=${tab}`} replace />;
}

/**
 * Route table.
 *
 * The sidebar shows eleven destinations, but the app still answers every URL
 * it ever answered. Routes fall into three kinds:
 *
 *   HUB      — a parent page with tabs (Safety, Record check, Ask, Find care,
 *              Next steps, My record, Labs, Upload, About & settings).
 *   TAB URL  — an old top-level path, redirected onto the hub tab that now
 *              holds that screen. Nothing 404s mid-demo.
 *   DEEP     — a real page kept out of the sidebar on purpose: the analysis
 *              audit log (/analyses) and the viva sheet (/ygc-prep).
 *
 * Several screens are also still mounted standalone (e.g. /settings,
 * /guidelines) because links, print views and tests point at them.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      {/* DEEP: speaker notes only — no nav, sidebar, or landing link. Type /ygc-prep. */}
      <Route path="/ygc-prep" element={<JudgePrepPage />} />
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />

        {/* ---------------- Start ---------------- */}
        <Route
          path="/dashboard"
          element={
            <Guarded>
              <DashboardPage />
            </Guarded>
          }
        />
        {/* HUB: Photos & PDFs | FHIR file */}
        <Route
          path="/upload"
          element={
            <Guarded>
              <UploadHubPage />
            </Guarded>
          }
        />
        {/* TAB URL: FHIR import is the second Upload tab. */}
        <Route path="/import" element={<Navigate to="/upload?tab=fhir" replace />} />
        <Route
          path="/upload/fhir"
          element={
            <Guarded>
              <FhirImportPage />
            </Guarded>
          }
        />

        {/* ---------------- My record ---------------- */}
        {/* HUB: Files | Timeline */}
        <Route
          path="/documents"
          element={
            <Guarded>
              <RecordsHubPage />
            </Guarded>
          }
        />
        {/* TAB URLs: the timeline is a view of the same documents. */}
        <Route path="/history" element={<Navigate to="/documents?tab=timeline" replace />} />
        <Route path="/timeline" element={<Navigate to="/documents?tab=timeline" replace />} />
        <Route
          path="/documents/files"
          element={
            <Guarded>
              <DocumentsPage />
            </Guarded>
          }
        />
        <Route
          path="/documents/timeline"
          element={
            <Guarded>
              <HistoryPage />
            </Guarded>
          }
        />
        <Route
          path="/medicines"
          element={
            <Guarded>
              <MedicinesPage />
            </Guarded>
          }
        />
        {/* HUB: Lab trends | Home vitals */}
        <Route
          path="/labs"
          element={
            <Guarded>
              <LabsHubPage />
            </Guarded>
          }
        />
        <Route path="/lab-trends" element={<Navigate to="/labs" replace />} />
        {/* TAB URL: home BP / weight / sugar live under Labs. */}
        <Route path="/vitals" element={<Navigate to="/labs?tab=vitals" replace />} />
        <Route
          path="/labs/trends"
          element={
            <Guarded>
              <LabTrendsPage />
            </Guarded>
          }
        />
        <Route
          path="/labs/vitals"
          element={
            <Guarded>
              <VitalsPage />
            </Guarded>
          }
        />

        {/* ---------------- Insights ---------------- */}
        {/* HUB: Alerts | Clinical | Over time */}
        <Route
          path="/safety"
          element={
            <Guarded>
              <SafetyHubPage />
            </Guarded>
          }
        />
        <Route path="/cross-check" element={<Navigate to="/safety" replace />} />
        {/* TAB URLs: the two other halves of the same safety question. */}
        <Route path="/clinical-safety" element={<Navigate to="/safety?tab=clinical" replace />} />
        <Route path="/risk-timeline" element={<Navigate to="/safety?tab=timeline" replace />} />
        <Route
          path="/safety/alerts"
          element={
            <Guarded>
              <CrossCheckPage />
            </Guarded>
          }
        />
        <Route
          path="/safety/clinical"
          element={
            <Guarded>
              <ClinicalSafetyPage />
            </Guarded>
          }
        />
        <Route
          path="/safety/timeline"
          element={
            <Guarded>
              <RiskTimelinePage />
            </Guarded>
          }
        />

        {/* HUB: What changed | Discrepancies | Conflicts */}
        <Route
          path="/record-check"
          element={
            <Guarded>
              <RecordCheckHubPage />
            </Guarded>
          }
        />
        {/* TAB URLs. /record-integrity was a second door to the same screen;
            it now redirects onto the hub with its ?tab=conflicts contract
            preserved. */}
        <Route path="/changes" element={<Navigate to="/record-check?tab=changes" replace />} />
        <Route path="/review" element={<Navigate to="/record-check?tab=conflicts" replace />} />
        <Route path="/record-integrity" element={<RecordIntegrityRedirect />} />
        <Route
          path="/record-check/changes"
          element={
            <Guarded>
              <ChangesPage />
            </Guarded>
          }
        />

        {/* HUB: Question | Symptom | Conversation */}
        <Route
          path="/ask"
          element={
            <Guarded>
              <QAPage />
            </Guarded>
          }
        />
        <Route path="/qa" element={<Navigate to="/ask" replace />} />
        {/* TAB URLs: symptom check and multi-turn chat are Ask AI tabs. */}
        <Route path="/symptoms" element={<Navigate to="/ask?tab=symptoms" replace />} />
        <Route path="/conversations" element={<Navigate to="/ask?tab=chat" replace />} />
        <Route path="/sessions" element={<Navigate to="/ask?tab=chat" replace />} />
        <Route
          path="/ask/chat"
          element={
            <Guarded>
              <SessionPage />
            </Guarded>
          }
        />

        {/* ---------------- Take action ---------------- */}
        {/* HUB: Browse nearby (default) | Find a local professional | Who to see.
            The map directory works with or without a safety flag, so it is
            the landing tab; the flag → specialty → live listing flow is one
            tab over. */}
        <Route
          path="/care"
          element={
            <Guarded>
              <GetCareHubPage />
            </Guarded>
          }
        />
        <Route
          path="/find-care"
          element={
            <Guarded>
              <GetCareHubPage />
            </Guarded>
          }
        />
        <Route path="/location-picker" element={<Navigate to="/care?tab=map" replace />} />
        {/* TAB URL: pharmacist-vs-doctor triage is the second Find care tab. */}
        <Route path="/who-to-see" element={<Navigate to="/care?tab=who" replace />} />
        <Route
          path="/care/who-to-see"
          element={
            <Guarded>
              <WhoToSeePage />
            </Guarded>
          }
        />
        <Route
          path="/care/local"
          element={
            <Guarded>
              <CareRecommendationsPage />
            </Guarded>
          }
        />

        {/* HUB: Appointment prep | Action Center | Preventive | Messages */}
        <Route
          path="/appointment-prep"
          element={
            <Guarded>
              <NextStepsHubPage />
            </Guarded>
          }
        />
        {/* TAB URLs. Preventive care and provider messages previously
            redirected to other screens, which made two shipped features look
            deleted; they are real tabs again. */}
        <Route path="/follow-up" element={<Navigate to="/appointment-prep?tab=queue" replace />} />
        <Route
          path="/preventive-care"
          element={<Navigate to="/appointment-prep?tab=preventive" replace />}
        />
        <Route
          path="/messages"
          element={<Navigate to="/appointment-prep?tab=messages" replace />}
        />
        <Route
          path="/next-steps/prep"
          element={
            <Guarded>
              <AppointmentPrepPage />
            </Guarded>
          }
        />
        <Route
          path="/next-steps/queue"
          element={
            <Guarded>
              <FollowUpPage />
            </Guarded>
          }
        />
        <Route
          path="/next-steps/preventive"
          element={
            <Guarded>
              <PreventiveCarePage />
            </Guarded>
          }
        />
        <Route
          path="/next-steps/messages"
          element={
            <Guarded>
              <ProviderMessagesPage />
            </Guarded>
          }
        />

        {/* ---------------- Trust ---------------- */}
        {/* HUB: How it works | Guidelines | Settings | Advanced.
            Informational, like /settings: readable without a workspace. */}
        <Route path="/about" element={<TrustHubPage />} />
        <Route path="/about/how-it-works" element={<AboutPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route
          path="/guidelines"
          element={
            <Guarded>
              <GuidelinesPage />
            </Guarded>
          }
        />
        {/* DEEP: audit log. Reachable from About → Advanced, never the sidebar. */}
        <Route
          path="/analyses"
          element={
            <Guarded>
              <AnalysesPage />
            </Guarded>
          }
        />

        {/* A typo mid-demo must not blank the screen. */}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
