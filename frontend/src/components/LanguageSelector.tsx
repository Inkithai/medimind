import { SUPPORTED_LANGUAGES, useI18n } from "../i18n/I18nContext";
import type { AppLanguage } from "../i18n/runtime";
import { classNames } from "../utils/format";

export function LanguageSelector({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  const { language, setLanguage, t } = useI18n();
  return (
    <div className={classNames("min-w-0", className)}>
      <label
        htmlFor={compact ? "app-language-compact" : "app-language"}
        className={compact ? "sr-only" : "mb-1 block text-xs font-semibold text-slate-600"}
      >
        {t("common.language")}
      </label>
      <select
        id={compact ? "app-language-compact" : "app-language"}
        value={language}
        onChange={(event) => setLanguage(event.target.value as AppLanguage)}
        aria-label={t("common.selectLanguage")}
        className={classNames(
          "border border-slate-300 bg-white text-sm font-medium text-slate-800 shadow-sm",
          "focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2",
          compact ? "min-h-[44px] max-w-[9.5rem] rounded-xl px-2 py-2" : "h-9 w-full rounded-lg px-2 py-1"
        )}
      >
        {SUPPORTED_LANGUAGES.map((item) => (
          <option key={item.code} value={item.code} lang={item.code}>
            {item.nativeName}{item.nativeName === item.englishName ? "" : ` — ${item.englishName}`}
          </option>
        ))}
      </select>
    </div>
  );
}
