import { useI18n } from "../i18n/I18nContext";

export function MedicalDisclaimer({ medication = false }: { medication?: boolean }) {
  const { t } = useI18n();
  return (
    <aside
      aria-label={t("common.notDiagnosis")}
      className="flex items-start gap-2.5 rounded-xl border border-sky-100 bg-sky-50/70 px-4 py-3 text-xs leading-relaxed text-sky-900"
    >
      <span
        aria-hidden="true"
        className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-100 font-bold text-sky-700"
      >
        i
      </span>
      <p>{t(medication ? "common.medicationDisclaimer" : "common.aiDisclaimer")}</p>
    </aside>
  );
}
