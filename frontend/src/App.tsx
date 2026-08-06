import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { useAuth } from "./context/AuthContext";
import { CrossCheckPage } from "./pages/CrossCheckPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LabTrendsPage } from "./pages/LabTrendsPage";
import { QAPage } from "./pages/QAPage";
import { SessionPage } from "./pages/SessionPage";
import { SettingsPage } from "./pages/SettingsPage";
import { UploadPage } from "./pages/UploadPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { isConfigured } = useAuth();
  if (!isConfigured) return <Navigate to="/settings" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
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
          path="/timeline"
          element={
            <RequireAuth>
              <TimelineRedirect />
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
          path="/lab-trends"
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
          path="/sessions"
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

// The timeline view is surfaced as part of the dashboard (patient record
// panel) — redirect /timeline there so old links still work.
function TimelineRedirect() {
  return <Navigate to="/dashboard" replace />;
}
