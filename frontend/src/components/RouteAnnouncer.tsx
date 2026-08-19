import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";

/* Every hub route, so a screen-reader announcement and the document title
   name the destination the sidebar names. Old paths redirect before this
   runs, so only the canonical ones need entries. */
const routeKeys: Record<string, string> = {
  "/dashboard": "nav.dashboard",
  "/upload": "nav.upload",
  "/documents": "nav.records",
  "/medicines": "nav.medications",
  "/labs": "nav.labs",
  "/safety": "nav.safety",
  "/record-check": "nav.recordCheck",
  "/ask": "nav.ask",
  "/care": "nav.care",
  "/find-care": "nav.care",
  "/appointment-prep": "nav.nextSteps",
  "/about": "about.nav",
  "/settings": "nav.settings",
  "/guidelines": "nav.guidelines",
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
