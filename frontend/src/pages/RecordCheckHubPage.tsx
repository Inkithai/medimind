/**
 * Record check — "can I trust what was read out of my documents?"
 *
 *   /record-check                   → What changed   (before/after between dated records)
 *   /record-check?tab=discrepancies → Discrepancies  (facts that disagree across documents)
 *   /record-check?tab=conflicts     → Conflicts      (identity / allergy / same-date, with fixes)
 *
 * What changed leads: it is the question people actually arrive with after a
 * new document lands. The two integrity views were already sub-views inside
 * the integrity page; they are hoisted into this tab strip so there is only
 * ever one row of tabs.
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
    { id: "changes", label: t("recordCheckHub.tabChanges") },
    { id: "discrepancies", label: t("recordCheckHub.tabDiscrepancies") },
    { id: "conflicts", label: t("recordCheckHub.tabConflicts") },
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

      <TabPanel group={GROUP} id="changes" active={active}>
        <ChangesPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="discrepancies" active={active}>
        <RecordIntegrityPage embedded view="discrepancies" />
      </TabPanel>
      <TabPanel group={GROUP} id="conflicts" active={active}>
        <RecordIntegrityPage embedded view="conflicts" />
      </TabPanel>
    </div>
  );
}
