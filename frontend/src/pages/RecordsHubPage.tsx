/**
 * My record — the parent for the two ways of looking at the same set of
 * uploaded documents:
 *
 *   /documents                → Files     (every document + extraction)
 *   /documents?tab=timeline   → Timeline  (the same documents in date order)
 *
 * /history and /timeline redirect here so older links keep working.
 */
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { FileIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { DocumentsPage } from "./DocumentsPage";
import { HistoryPage } from "./HistoryPage";

const GROUP = "records";

export function RecordsHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "files", label: t("recordsHub.tabFiles") },
    { id: "timeline", label: t("recordsHub.tabTimeline") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      <HubHeader
        eyebrow={t("recordsHub.eyebrow")}
        icon={<FileIcon className="h-4 w-4" />}
        title={t("recordsHub.title")}
        description={t("recordsHub.subtitle")}
      />

      <TabBar
        tabs={tabs}
        active={active}
        onSelect={setActive}
        group={GROUP}
        label={t("recordsHub.tabsLabel")}
      />

      <TabPanel group={GROUP} id="files" active={active}>
        <DocumentsPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="timeline" active={active}>
        <HistoryPage embedded />
      </TabPanel>
    </div>
  );
}
