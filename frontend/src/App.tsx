import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./context/AuthContext";
import { AboutPage } from "./pages/AboutPage";
import { CrossCheckPage } from "./pages/CrossCheckPage";
import { CareRecommendationsPage } from "./pages/CareRecommendationsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LabTrendsPage } from "./pages/LabTrendsPage";
import { LandingPage } from "./pages/LandingPage";
import { QAPage } from "./pages/QAPage";
import { SessionPage } from "./pages/SessionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UploadPage } from "./pages/UploadPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { MedicinesPage } from "./pages/MedicinesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { RiskTimelinePage } from "./pages/RiskTimelinePage";
import { ClinicalSafetyPage } from "./pages/ClinicalSafetyPage";
import { VitalsPage } from "./pages/VitalsPage";
import { PreventiveCarePage } from "./pages/PreventiveCarePage";
import { SymptomCheckerPage } from "./pages/SymptomCheckerPage";
import { GuidelinesPage } from "./pages/GuidelinesPage";
import { MessagesPage } from "./pages/MessagesPage";
import { FhirImportPage } from "./pages/FhirImportPage";
import { ChangesPage } from "./pages/ChangesPage";
import { AppointmentPrepPage } from "./pages/AppointmentPrepPage";
import { RecordIntegrityPage } from "./pages/RecordIntegrityPage";
import { FollowUpPage } from "./pages/FollowUpPage";
import { ReviewPage } from "./pages/ReviewPage";
import { Spinner } from "./components/Spinner";
import { useI18n } from "./i18n/I18nContext";

const FindCarePage = lazy(() =>
  import("./pages/FindCarePage").then((module) => ({ default: module.FindCarePage }))
);

function FindCareLoading() {
  const { t } = useI18n();
  return (
    <div role="status" aria-live="polite" className="flex min-h-[50vh] items-center justify-center gap-3 text-sm font-medium text-slate-700">
      <Spinner className="h-5 w-5 text-brand-600" /> {t("care.finding")}
    </div>
  );
}

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
        <p className="mt-3 text-sm text-slate-600">
          {t("auth.checkConnection")}
        </p>
      </div>
    );
  }
  if (!isConfigured) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
        {/* Informational, like /settings: readable without a workspace. */}
        <Route path="/about" element={<AboutPage />} />
        <Route
          path="/find-care"
          element={
            <RequireAuth>
              <Suspense fallback={<FindCareLoading />}>
                <FindCarePage />
              </Suspense>
            </RequireAuth>
          }
        />
        <Route path="/location-picker" element={<Navigate to="/find-care" replace />} />
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <DashboardPage />
            </RequireAuth>
          }
        />
        <Route
          path="/upload"
          element={
            <RequireAuth>
              <UploadPage />
            </RequireAuth>
          }
        />
        <Route
          path="/documents"
          element={
            <RequireAuth>
              <DocumentsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/history"
          element={
            <RequireAuth>
              <HistoryPage />
            </RequireAuth>
          }
        />
        <Route
          path="/review"
          element={
            <RequireAuth>
              <ReviewPage />
            </RequireAuth>
          }
        />
        <Route
          path="/medicines"
          element={
            <RequireAuth>
              <MedicinesPage />
            </RequireAuth>
          }
        />
        {/* Legacy timeline path */}
        <Route
          path="/timeline"
          element={
            <RequireAuth>
              <HistoryPage />
            </RequireAuth>
          }
        />
        <Route
          path="/changes"
          element={
            <RequireAuth>
              <ChangesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/follow-up"
          element={
            <RequireAuth>
              <FollowUpPage />
            </RequireAuth>
          }
        />
        <Route
          path="/record-integrity"
          element={
            <RequireAuth>
              <RecordIntegrityPage />
            </RequireAuth>
          }
        />
        <Route
          path="/appointment-prep"
          element={
            <RequireAuth>
              <AppointmentPrepPage />
            </RequireAuth>
          }
        />
        <Route
          path="/cross-check"
          element={
            <RequireAuth>
              <CrossCheckPage />
            </RequireAuth>
          }
        />
        <Route
          path="/safety"
          element={
            <RequireAuth>
              <CrossCheckPage />
            </RequireAuth>
          }
        />
        <Route
          path="/lab-trends"
          element={
            <RequireAuth>
              <LabTrendsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/labs"
          element={
            <RequireAuth>
              <LabTrendsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/risk-timeline"
          element={
            <RequireAuth>
              <RiskTimelinePage />
            </RequireAuth>
          }
        />
        <Route
          path="/clinical-safety"
          element={
            <RequireAuth>
              <ClinicalSafetyPage />
            </RequireAuth>
          }
        />
        <Route
          path="/vitals"
          element={
            <RequireAuth>
              <VitalsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/preventive-care"
          element={
            <RequireAuth>
              <PreventiveCarePage />
            </RequireAuth>
          }
        />
        <Route
          path="/symptoms"
          element={
            <RequireAuth>
              <SymptomCheckerPage />
            </RequireAuth>
          }
        />
        <Route
          path="/guidelines"
          element={
            <RequireAuth>
              <GuidelinesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/messages"
          element={
            <RequireAuth>
              <MessagesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/import"
          element={
            <RequireAuth>
              <FhirImportPage />
            </RequireAuth>
          }
        />
        <Route
          path="/care"
          element={
            <RequireAuth>
              <CareRecommendationsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/qa"
          element={
            <RequireAuth>
              <QAPage />
            </RequireAuth>
          }
        />
        <Route
          path="/ask"
          element={
            <RequireAuth>
              <QAPage />
            </RequireAuth>
          }
        />
        <Route
          path="/sessions"
          element={
            <RequireAuth>
              <SessionPage />
            </RequireAuth>
          }
        />
        <Route
          path="/conversations"
          element={
            <RequireAuth>
              <SessionPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
