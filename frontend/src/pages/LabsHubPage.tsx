/**
 * Labs & vitals — measurements over time, from two sources:
 *
 *   /labs              → Lab trends   (values extracted from uploaded reports)
 *   /labs?tab=vitals   → Home vitals  (BP, weight, sugar the patient enters)
 *
 * /lab-trends and /vitals redirect here.
 */
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { BeakerIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { LabTrendsPage } from "./LabTrendsPage";
import { VitalsPage } from "./VitalsPage";

const GROUP = "labs";

export function LabsHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "trends", label: t("labsHub.tabTrends") },
    { id: "vitals", label: t("labsHub.tabVitals") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      <HubHeader
        eyebrow={t("labsHub.eyebrow")}
        icon={<BeakerIcon className="h-4 w-4" />}
        title={t("labsHub.title")}
        description={t("labsHub.subtitle")}
      />

      <TabBar
        tabs={tabs}
        active={active}
        onSelect={setActive}
        group={GROUP}
        label={t("labsHub.tabsLabel")}
      />

      <TabPanel group={GROUP} id="trends" active={active}>
        <LabTrendsPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="vitals" active={active}>
        <VitalsPage embedded />
      </TabPanel>
    </div>
  );
}
