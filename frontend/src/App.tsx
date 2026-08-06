import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./context/AuthContext";
import { CrossCheckPage } from "./pages/CrossCheckPage";
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
import { Spinner } from "./components/Spinner";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isConfigured, isInitializing, initError } = useAuth();
  if (isInitializing) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
        <Spinner className="h-6 w-6 text-brand-600" />
        <p className="text-sm font-medium text-slate-700">Creating your private MediMind workspace…</p>
        <p className="text-xs text-slate-500">Anonymous session • JWT issued via /api/v1/anonymous/session</p>
      </div>
    );
  }
  if (initError) {
    return (
      <div className="mx-auto max-w-md rounded-xl border border-red-200 bg-red-50 p-6 text-center">
        <p className="text-sm font-semibold text-red-800">Could not create workspace</p>
        <p className="mt-1 text-xs text-red-700">{initError}</p>
        <p className="mt-3 text-xs text-slate-600">
          Check that the backend is running and <code className="rounded bg-slate-100 px-1">/api</code> proxy is reachable.
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
