import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import {
  detectInitialLanguage,
  I18nProvider,
  missingTranslationKeys,
  translate,
  useI18n,
} from "../I18nContext";
import { LANGUAGE_STORAGE_KEY } from "../runtime";

const dom = new JSDOM("<!doctype html><html><body><div id='root'></div></body></html>", {
  url: "https://medimind.test/",
});
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

assert(detectInitialLanguage("ta", ["en-US"]) === "ta", "stored language wins on refresh");
assert(detectInitialLanguage(null, ["si-LK", "en-US"]) === "si", "browser Sinhala is detected");
assert(
  detectInitialLanguage(null, ["fr-FR"]) === "en",
  "unsupported browser language falls back to English",
);
assert(translate("si", "nav.dashboard") === "සාරාංශය", "Sinhala catalog renders Unicode text");
assert(translate("ta", "nav.dashboard") === "முகப்பு", "Tamil catalog renders Unicode text");
assert(
  translate("ta", "care.noResultsBody", { radius: 10 }).includes("10"),
  "interpolation works in Tamil",
);
assert(
  missingTranslationKeys("si").length === 0,
  `Sinhala catalog covers every English key: ${missingTranslationKeys("si").join(", ")}`,
);
assert(
  missingTranslationKeys("ta").length === 0,
  `Tamil catalog covers every English key: ${missingTranslationKeys("ta").join(", ")}`,
);

let latestLanguage = "";
function Probe() {
  const { language, setLanguage, t } = useI18n();
  latestLanguage = language;
  useEffect(() => {
    if (language === "ta") setLanguage("si");
  }, [language, setLanguage]);
  return <p>{t("nav.dashboard")}</p>;
}

async function main() {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, "ta");
  const root = createRoot(document.getElementById("root")!);
  await act(async () => {
    root.render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
  assert(latestLanguage === "si", "language can be switched at runtime");
  assert(localStorage.getItem(LANGUAGE_STORAGE_KEY) === "si", "selected language is persisted");
  assert(document.documentElement.lang === "si", "document language follows selection");
  assert(
    document.body.textContent?.includes("සාරාංශය") === true,
    "UI rerenders after language switch",
  );
  act(() => root.unmount());
  console.log("\nAll i18n tests passed.");
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
