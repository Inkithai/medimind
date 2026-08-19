/**
 * Regression coverage: /api/v1/timeline returning 404 (fresh workspace or
 * snapshot still building) must render the Medicines and Documents pages'
 * normal empty states — NOT a hard error screen.
 *
 * The API 404s for users with no record yet by design; the Dashboard and
 * Labs pages already treat that as the first-run empty state. Before this
 * fix, Medicines/Documents rendered the generic ErrorState for the same
 * response, which looked like the app was broken on first visit.
 *
 * Run with: tsx src/pages/__tests__/timelineEmptyState.test.tsx
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";

import { ApiError, api } from "../../api/client";
import { AuthProvider } from "../../context/AuthContext";
import { I18nProvider } from "../../i18n/I18nContext";
import { MedicinesPage } from "../MedicinesPage";
import { DocumentsPage } from "../DocumentsPage";

const dom = new JSDOM("<!DOCTYPE html><html><body><div id='root'></div></body></html>", {
  url: "http://localhost/",
});
(globalThis as Record<string, unknown>).window = dom.window;
(globalThis as Record<string, unknown>).document = dom.window.document;
(globalThis as Record<string, unknown>).localStorage = dom.window.localStorage;
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
try {
  Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
  });
} catch {
  // Node may expose a read-only navigator; react-dom can use that value.
}

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

async function renderPage(Page: typeof MedicinesPage | typeof DocumentsPage): Promise<string> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter>
          <I18nProvider>
            <AuthProvider>
              <Page />
            </AuthProvider>
          </I18nProvider>
        </MemoryRouter>
      </StrictMode>,
    );
    await new Promise((resolve) => window.setTimeout(resolve, 10));
  });
  const html = container.innerHTML;
  act(() => root.unmount());
  container.remove();
  return html;
}

async function main() {
  const originalHealth = api.healthUnauthenticated;
  const originalCreate = api.createAnonymousSession;
  const originalGetTimeline = api.getTimeline;

  try {
    localStorage.clear();
    api.healthUnauthenticated = async () => ({ status: "ok" });
    api.createAnonymousSession = async () => ({
      user_id: "anon_test",
      token: "token",
      session_id: "session",
    });

    // --- 404 = first-run empty state -------------------------------------
    api.getTimeline = async () => {
      throw new ApiError(404, "No timeline found for this user.");
    };

    const medicinesHtml = await renderPage(MedicinesPage);
    assert(
      medicinesHtml.includes("No medicines found"),
      "Medicines: 404 renders the empty state, not an error",
    );
    assert(
      medicinesHtml.includes("Upload documents"),
      "Medicines: 404 empty state links to the upload page",
    );
    assert(
      !medicinesHtml.includes("Something went wrong"),
      "Medicines: 404 does NOT render the generic error screen",
    );

    const documentsHtml = await renderPage(DocumentsPage);
    assert(
      documentsHtml.includes("No documents yet"),
      "Documents: 404 renders the empty state, not an error",
    );
    assert(
      documentsHtml.includes("Upload documents"),
      "Documents: 404 empty state links to the upload page",
    );
    assert(
      !documentsHtml.includes("Something went wrong"),
      "Documents: 404 does NOT render the generic error screen",
    );

    // --- Real failures still surface as errors ---------------------------
    api.getTimeline = async () => {
      throw new ApiError(500, "Server exploded");
    };

    const medicinesErrorHtml = await renderPage(MedicinesPage);
    assert(
      medicinesErrorHtml.includes("Something went wrong"),
      "Medicines: a 500 still renders the error screen",
    );

    const documentsErrorHtml = await renderPage(DocumentsPage);
    assert(
      documentsErrorHtml.includes("Something went wrong"),
      "Documents: a 500 still renders the error screen",
    );
  } finally {
    api.healthUnauthenticated = originalHealth;
    api.createAnonymousSession = originalCreate;
    api.getTimeline = originalGetTimeline;
  }

  console.log("All timeline empty-state regression tests passed.");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
