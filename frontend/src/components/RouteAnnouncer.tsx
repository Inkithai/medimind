import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";

const routeKeys: Record<string, string> = {
  "/dashboard": "nav.dashboard",
  "/documents": "nav.records",
  "/medicines": "nav.medications",
  "/labs": "nav.labs",
  "/lab-trends": "nav.labs",
  "/history": "nav.timeline",
  "/timeline": "nav.timeline",
  "/safety": "nav.safety",
  "/cross-check": "nav.safety",
  "/ask": "nav.ask",
  "/qa": "nav.ask",
  "/conversations": "nav.ask",
  "/sessions": "nav.ask",
  "/find-care": "nav.care",
  "/care": "nav.care",
  "/settings": "nav.settings",
  "/upload": "nav.upload",
};

export function RouteAnnouncer() {
  const location = useLocation();
  const { t, language } = useI18n();
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (location.pathname === "/ygc-prep") {
      document.title = "Judge Q&A prep · MediMind";
      setMessage("Judge Q&A prep");
      return;
    }
    const title = t(routeKeys[location.pathname] || "common.appName");
    document.title = `${title} · MediMind`;
    setMessage(t("a11y.routeChanged", { title }));
    window.requestAnimationFrame(() => {
      document.getElementById("main-content")?.focus({ preventScroll: true });
    });
  }, [language, location.pathname, t]);

  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {message}
    </div>
  );
}
