export type AppLanguage = "en" | "si" | "ta";

export const LANGUAGE_STORAGE_KEY = "medimind.language.v1";
export const LOCALES: Record<AppLanguage, string> = {
  en: "en-LK",
  si: "si-LK",
  ta: "ta-LK",
};

let activeLanguage: AppLanguage = "en";

export function setRuntimeLanguage(language: AppLanguage): void {
  activeLanguage = language;
}

export function getRuntimeLanguage(): AppLanguage {
  return activeLanguage;
}

export function getRuntimeLocale(): string {
  return LOCALES[activeLanguage];
}

export function normalizeLanguage(value: string | null | undefined): AppLanguage | null {
  const base = value?.trim().toLowerCase().split(/[-_]/)[0];
  return base === "en" || base === "si" || base === "ta" ? base : null;
}
