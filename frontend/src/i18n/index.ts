import { en, type Copy } from "./en";
import { aboutEn, type AboutCopy } from "./about";

/**
 * Minimal copy provider.
 *
 * The app ships English today. Adding a locale means registering a
 * dictionary here — components read strings through these hooks and never
 * hardcode visible text, so no component changes are needed to translate.
 */
const DICTIONARIES: Record<string, Copy> = { en };
const ABOUT_DICTIONARIES: Record<string, AboutCopy> = { en: aboutEn };

/** BCP-47 tag reduced to the base language, e.g. "en-GB" -> "en". */
function currentLanguage(): string {
  return typeof navigator !== "undefined"
    ? navigator.language.split("-")[0].toLowerCase()
    : "en";
}

export function useCopy(): Copy {
  return DICTIONARIES[currentLanguage()] || en;
}

/** Copy for the About / technical overview page. */
export function useAboutCopy(): AboutCopy {
  return ABOUT_DICTIONARIES[currentLanguage()] || aboutEn;
}

export type { Copy, AboutCopy };
export { en, aboutEn };
