import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { en } from "./locales/en";
import { si } from "./locales/si";
import { ta } from "./locales/ta";
import {
  LANGUAGE_STORAGE_KEY,
  LOCALES,
  normalizeLanguage,
  setRuntimeLanguage,
  type AppLanguage,
} from "./runtime";

const catalogs: Record<AppLanguage, object> = { en, si, ta };

export const SUPPORTED_LANGUAGES: Array<{
  code: AppLanguage;
  nativeName: string;
  englishName: string;
}> = [
  { code: "en", nativeName: "English", englishName: "English" },
  { code: "si", nativeName: "සිංහල", englishName: "Sinhala" },
  { code: "ta", nativeName: "தமிழ்", englishName: "Tamil" },
];

type InterpolationValues = Record<string, string | number>;

interface I18nValue {
  language: AppLanguage;
  locale: string;
  setLanguage: (language: AppLanguage) => void;
  t: (key: string, values?: InterpolationValues) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatDate: (
    value: string | Date | null | undefined,
    options?: Intl.DateTimeFormatOptions,
  ) => string;
  formatDateTime: (value: string | Date | null | undefined) => string;
  formatList: (values: string[]) => string;
}

const I18nContext = createContext<I18nValue | undefined>(undefined);

function flattenKeys(catalog: object, prefix = ""): string[] {
  return Object.entries(catalog).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return value && typeof value === "object" ? flattenKeys(value, path) : [path];
  });
}

export function missingTranslationKeys(language: Exclude<AppLanguage, "en">): string[] {
  return flattenKeys(en).filter((key) => lookup(catalogs[language], key) === undefined);
}

function lookup(catalog: object, key: string): string | undefined {
  let current: unknown = catalog;
  for (const part of key.split(".")) {
    if (!current || typeof current !== "object" || !(part in current)) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === "string" ? current : undefined;
}

export function translate(
  language: AppLanguage,
  key: string,
  values: InterpolationValues = {},
): string {
  const template = lookup(catalogs[language], key) ?? lookup(en, key) ?? key;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : `{{${name}}}`,
  );
}

export function detectInitialLanguage(
  stored: string | null,
  browserLanguages: readonly string[],
): AppLanguage {
  const saved = normalizeLanguage(stored);
  if (saved) return saved;
  for (const candidate of browserLanguages) {
    const detected = normalizeLanguage(candidate);
    if (detected) return detected;
  }
  return "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, updateLanguage] = useState<AppLanguage>(() =>
    detectInitialLanguage(
      typeof localStorage === "undefined" ? null : localStorage.getItem(LANGUAGE_STORAGE_KEY),
      typeof navigator === "undefined" ? [] : navigator.languages || [navigator.language],
    ),
  );

  const setLanguage = useCallback((next: AppLanguage) => {
    updateLanguage(next);
  }, []);

  useEffect(() => {
    setRuntimeLanguage(language);
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    document.documentElement.lang = language;
    document.documentElement.dir = "ltr";
  }, [language]);

  const locale = LOCALES[language];
  const value = useMemo<I18nValue>(
    () => ({
      language,
      locale,
      setLanguage,
      t: (key, values) => translate(language, key, values),
      formatNumber: (number, options) => new Intl.NumberFormat(locale, options).format(number),
      formatDate: (input, options) => {
        if (!input) return "—";
        const date = input instanceof Date ? input : new Date(input);
        if (Number.isNaN(date.getTime())) return String(input);
        return new Intl.DateTimeFormat(
          locale,
          options ?? {
            year: "numeric",
            month: "short",
            day: "numeric",
          },
        ).format(date);
      },
      formatDateTime: (input) => {
        if (!input) return "—";
        const date = input instanceof Date ? input : new Date(input);
        if (Number.isNaN(date.getTime())) return String(input);
        return new Intl.DateTimeFormat(locale, {
          dateStyle: "medium",
          timeStyle: "short",
        }).format(date);
      },
      formatList: (values) =>
        new Intl.ListFormat(locale, {
          style: "long",
          type: "conjunction",
        }).format(values),
    }),
    [language, locale, setLanguage],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
