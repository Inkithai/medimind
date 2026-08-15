import { en, type Copy } from "./en";

/**
 * Minimal copy provider. The app ships English today; adding a locale means
 * adding a dictionary here rather than editing components.
 */
const DICTIONARIES: Record<string, Copy> = { en };

export function useCopy(): Copy {
  const language =
    typeof navigator !== "undefined" ? navigator.language.split("-")[0].toLowerCase() : "en";
  return DICTIONARIES[language] || en;
}

export type { Copy };
export { en };
