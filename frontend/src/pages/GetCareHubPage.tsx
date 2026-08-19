/**
 * Find care — the "I have a flag, now what?" hub, and the fix for the single
 * biggest navigation problem in the app: the flag → specialty → live listing
 * flow lived at /care and was not in the sidebar at all. It is now the
 * default tab of this hub, so it is the first thing anyone sees here.
 *
 *   /care  (or /find-care)      → Find local care  (pick a safety flag → live doctors nearby)
 *   /find-care?tab=who          → Who to see       (pharmacist vs doctor triage)
 *   /find-care?tab=map          → Browse nearby    (Leaflet directory of facilities)
 *
 * The map tab stays lazy-loaded: the Leaflet bundle must not be downloaded
 * by someone who only wanted the triage answer.
 */
import { Suspense, lazy } from "react";
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { Spinner } from "../components/Spinner";
import { StethoscopeIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { CareRecommendationsPage } from "./CareRecommendationsPage";
import { WhoToSeePage } from "./WhoToSeePage";

const GROUP = "care";

const FindCarePage = lazy(() =>
  import("./FindCarePage").then((module) => ({ default: module.FindCarePage })),
);

function MapLoading() {
  const { t } = useI18n();
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-[40vh] items-center justify-center gap-3 text-sm font-medium text-slate-700"
    >
      <Spinner className="h-5 w-5 text-brand-600" /> {t("care.finding")}
    </div>
  );
}

export function GetCareHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "local", label: t("careHub.tabLocal") },
    { id: "who", label: t("careHub.tabWho") },
    { id: "map", label: t("careHub.tabMap") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      {/* print:hidden — the Who to see tab offers "Print this page" as a
          handoff, and the hub chrome must not appear on that sheet. */}
      <div className="space-y-6 print:hidden">
        <HubHeader
          eyebrow={t("careHub.eyebrow")}
          icon={<StethoscopeIcon className="h-4 w-4" />}
          title={t("careHub.title")}
          description={t("careHub.subtitle")}
        />

        <TabBar
          tabs={tabs}
          active={active}
          onSelect={setActive}
          group={GROUP}
          label={t("careHub.tabsLabel")}
        />
      </div>

      <TabPanel group={GROUP} id="local" active={active}>
        <CareRecommendationsPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="who" active={active}>
        <WhoToSeePage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="map" active={active}>
        <Suspense fallback={<MapLoading />}>
          <FindCarePage embedded />
        </Suspense>
      </TabPanel>
    </div>
  );
}
