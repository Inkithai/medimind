/**
 * Safety — the parent for the three checks that used to be three sidebar
 * entries answering the same patient question ("is anything on my record
 * dangerous?"):
 *
 *   /safety                  → Alerts       (interactions, duplicates, dosage, allergy)
 *   /safety?tab=clinical     → Clinical     (drug–lab, organ function, contraindications)
 *   /safety?tab=timeline     → Over time    (were those courses actually overlapping?)
 *
 * Nothing was rewritten: each tab renders the original page component with
 * its own data loading, disclaimers and actions intact. The old paths
 * (/cross-check, /clinical-safety, /risk-timeline) redirect onto these tabs
 * so existing links and bookmarks keep working.
 */
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { ShieldIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import { collectSafetyAlerts } from "../utils/safety";
import { ClinicalSafetyPage } from "./ClinicalSafetyPage";
import { CrossCheckPage } from "./CrossCheckPage";
import { RiskTimelinePage } from "./RiskTimelinePage";

const GROUP = "safety";

export function SafetyHubPage() {
  const { t } = useI18n();
  const { credentials, isConfigured } = useAuth();
  const [alertCount, setAlertCount] = useState<number | null>(null);

  const tabs: TabSpec[] = [
    { id: "alerts", label: t("safetyHub.tabAlerts"), badge: alertCount || undefined },
    { id: "clinical", label: t("safetyHub.tabClinical") },
    { id: "timeline", label: t("safetyHub.tabTimeline") },
  ];
  const [active, setActive] = useTabParam(tabs);

  // The alert count on the first tab is the same number the sidebar badge
  // shows; re-running the analysis on the Alerts tab broadcasts an update.
  useEffect(() => {
    if (!isConfigured) return;
    let cancelled = false;
    api
      .getPatientSnapshot(credentials)
      .then((snapshot) => {
        if (cancelled) return;
        setAlertCount(
          collectSafetyAlerts(snapshot.cross_check_report, snapshot.dosage_report).length,
        );
      })
      .catch(() => {
        if (!cancelled) setAlertCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [credentials, isConfigured]);

  useEffect(() => {
    const onUpdated = (event: Event) => {
      const count = Number((event as CustomEvent<{ count?: number }>).detail?.count);
      if (Number.isFinite(count)) setAlertCount(count);
    };
    window.addEventListener("medimind:safety-updated", onUpdated);
    return () => window.removeEventListener("medimind:safety-updated", onUpdated);
  }, []);

  return (
    <div className="space-y-6">
      <HubHeader
        eyebrow={t("safetyHub.eyebrow")}
        icon={<ShieldIcon className="h-4 w-4" />}
        title={t("safetyHub.title")}
        description={t("safetyHub.subtitle")}
      />

      <TabBar
        tabs={tabs}
        active={active}
        onSelect={setActive}
        group={GROUP}
        label={t("safetyHub.tabsLabel")}
      />

      <TabPanel group={GROUP} id="alerts" active={active}>
        <CrossCheckPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="clinical" active={active}>
        <ClinicalSafetyPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="timeline" active={active}>
        <RiskTimelinePage embedded />
      </TabPanel>
    </div>
  );
}
