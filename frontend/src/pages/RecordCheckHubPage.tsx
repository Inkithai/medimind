/**
 * Record check — "can I trust what was read out of my documents?"
 *
 *   /record-integrity                 → Discrepancies  (facts that disagree across documents)
 *   /record-integrity?tab=conflicts   → Conflicts      (identity / allergy / same-date, with fixes)
 *   /record-integrity?tab=changes     → What changed   (before/after between dated records)
 *
 * The first two were already sub-views inside the integrity page; they are
 * hoisted into this tab strip so there is only ever one row of tabs. The
 * third is the former /changes page, unchanged.
 */
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { IntegrityIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { ChangesPage } from "./ChangesPage";
import { RecordIntegrityPage } from "./RecordIntegrityPage";

const GROUP = "record-check";

export function RecordCheckHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "discrepancies", label: t("recordCheckHub.tabDiscrepancies") },
    { id: "conflicts", label: t("recordCheckHub.tabConflicts") },
    { id: "changes", label: t("recordCheckHub.tabChanges") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      <HubHeader
        eyebrow={t("recordCheckHub.eyebrow")}
        icon={<IntegrityIcon className="h-4 w-4" />}
        title={t("recordCheckHub.title")}
        description={t("recordCheckHub.subtitle")}
      />

      <TabBar
        tabs={tabs}
        active={active}
        onSelect={setActive}
        group={GROUP}
        label={t("recordCheckHub.tabsLabel")}
      />

      <TabPanel group={GROUP} id="discrepancies" active={active}>
        <RecordIntegrityPage embedded view="discrepancies" />
      </TabPanel>
      <TabPanel group={GROUP} id="conflicts" active={active}>
        <RecordIntegrityPage embedded view="conflicts" />
      </TabPanel>
      <TabPanel group={GROUP} id="changes" active={active}>
        <ChangesPage embedded />
      </TabPanel>
    </div>
  );
}
