/**
 * Upload — one ingest page, two kinds of input:
 *
 *   /upload             → Photos & PDFs  (the normal path: phone photo, scan, PDF)
 *   /upload?tab=fhir    → FHIR file      (an R4 bundle exported from another system)
 *
 * FHIR import used to sit in the sidebar next to Documents, which implied
 * most people needed it. Its own copy says the opposite. It is the second
 * tab here, and /import redirects onto it.
 */
import { HubHeader, TabBar, TabPanel, useTabParam, type TabSpec } from "../components/TabBar";
import { UploadIcon } from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { FhirImportPage } from "./FhirImportPage";
import { UploadPage } from "./UploadPage";

const GROUP = "upload";

export function UploadHubPage() {
  const { t } = useI18n();
  const tabs: TabSpec[] = [
    { id: "files", label: t("uploadHub.tabFiles") },
    { id: "fhir", label: t("uploadHub.tabFhir") },
  ];
  const [active, setActive] = useTabParam(tabs);

  return (
    <div className="space-y-6">
      <HubHeader
        eyebrow={t("uploadHub.eyebrow")}
        icon={<UploadIcon className="h-4 w-4" />}
        title={t("upload.title")}
        description={t("upload.subtitle")}
      />

      <TabBar
        tabs={tabs}
        active={active}
        onSelect={setActive}
        group={GROUP}
        label={t("uploadHub.tabsLabel")}
      />

      <TabPanel group={GROUP} id="files" active={active}>
        <UploadPage embedded />
      </TabPanel>
      <TabPanel group={GROUP} id="fhir" active={active}>
        <FhirImportPage embedded />
      </TabPanel>
    </div>
  );
}
