/**
 * About & settings — the "can I trust this, and can I get my data out?"
 * corner of the app. One sidebar entry, four tabs:
 *
 *   /about                    → How it works  (architecture, privacy, API)
 *   /about?tab=guidelines     → Guidelines    (WHO/FDA sources and review status)
 *   /about?tab=settings       → Settings      (language, profile, export, passport, delete)
 *   /about?tab=advanced       → Advanced      (AI analysis audit log)
 *
 * /settings and /guidelines remain real routes, so nothing that links to
 * them breaks; they simply no longer need their own sidebar rows.
 *
 * The analysis log is deliberately behind the Advanced tab rather than the
 * sidebar: it is an audit dump for a judge who asks, not a patient task.
 */
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { InfoIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { AboutPage } from "./AboutPage";
import { AnalysesPage } from "./AnalysesPage";
import { GuidelinesPage } from "./GuidelinesPage";
import { SettingsPage } from "./SettingsPage";

const GROUP = "trust";

export function TrustHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "how", label: t("trustHub.tabHow") },
    { id: "guidelines", label: t("trustHub.tabGuidelines") },
    { id: "settings", label: t("trustHub.tabSettings") },
    { id: "advanced", label: t("trustHub.tabAdvanced") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      {/* The How-it-works tab carries the full editorial About page, which
          brings its own title block and section bar, so the hub header is
          only shown on the other three tabs. */}
      {active !== "how" && (
        <HubHeader
          eyebrow={t("trustHub.eyebrow")}
          icon={<InfoIcon className="h-4 w-4" />}
          title={t("trustHub.title")}
          description={t("trustHub.subtitle")}
        />
      )}

      <TabBar
        tabs={tabs}
        active={active}
        onSelect={setActive}
        group={GROUP}
        label={t("trustHub.tabsLabel")}
      />

      <TabPanel group={GROUP} id="how" active={active}>
        <AboutPage />
      </TabPanel>
      <TabPanel group={GROUP} id="guidelines" active={active}>
        <GuidelinesPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="settings" active={active}>
        <SettingsPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="advanced" active={active}>
        <div className="space-y-4">
          <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5 text-sm leading-relaxed text-slate-700">
            <p className="font-semibold text-slate-900">{t("trustHub.advancedTitle")}</p>
            <p className="mt-1">{t("trustHub.advancedBody")}</p>
          </div>
          <AnalysesPage embedded />
        </div>
      </TabPanel>
    </div>
  );
}
