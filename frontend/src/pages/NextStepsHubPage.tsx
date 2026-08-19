/**
 * Next steps — everything that happens after the record has been read and
 * checked. Four tabs, two of which are restored screens:
 *
 *   /appointment-prep                  → Appointment prep  (printable clinician handoff)
 *   /appointment-prep?tab=queue        → Action Center     (follow-up queue, reminders, .ics)
 *   /appointment-prep?tab=preventive   → Preventive        (screening / immunisation reminders)
 *   /appointment-prep?tab=messages     → Messages          (notes for a provider)
 *
 * Preventive care and Provider messages both had working APIs and product
 * copy but their routes redirected away, so the features looked deleted.
 * They are real tabs again. /follow-up, /preventive-care and /messages
 * redirect onto the matching tab.
 */
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { AppointmentIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { AppointmentPrepPage } from "./AppointmentPrepPage";
import { FollowUpPage } from "./FollowUpPage";
import { PreventiveCarePage } from "./PreventiveCarePage";
import { ProviderMessagesPage } from "./ProviderMessagesPage";

const GROUP = "next-steps";

export function NextStepsHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "prep", label: t("nextSteps.tabPrep") },
    { id: "queue", label: t("nextSteps.tabQueue") },
    { id: "preventive", label: t("nextSteps.tabPreventive") },
    { id: "messages", label: t("nextSteps.tabMessages") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      {/* print:hidden — the prep tab is designed to be printed as a handoff
          sheet, and the hub chrome must not appear on that page. */}
      <div className="space-y-6 print:hidden">
        <HubHeader
          eyebrow={t("nextSteps.eyebrow")}
          icon={<AppointmentIcon className="h-4 w-4" />}
          title={t("nextSteps.title")}
          description={t("nextSteps.subtitle")}
        />

        <TabBar
          tabs={tabs}
          active={active}
          onSelect={setActive}
          group={GROUP}
          label={t("nextSteps.tabsLabel")}
        />
      </div>

      <TabPanel group={GROUP} id="prep" active={active}>
        <AppointmentPrepPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="queue" active={active}>
        <FollowUpPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="preventive" active={active}>
        <PreventiveCarePage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="messages" active={active}>
        <ProviderMessagesPage embedded />
      </TabPanel>
    </div>
  );
}
