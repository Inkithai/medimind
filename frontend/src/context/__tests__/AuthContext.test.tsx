/**
 * Regression coverage for anonymous provisioning under React 18 StrictMode.
 *
 * StrictMode runs mount effects as setup → cleanup → setup. The API request
 * must be shared by those setups, while the surviving setup must still clear
 * `isInitializing` (and surface failures) when that request settles.
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";

import { api } from "../../api/client";
import { AuthProvider, useAuth } from "../AuthContext";

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

type AuthSnapshot = ReturnType<typeof useAuth>;

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

function requireSnapshot(holder: { latest?: AuthSnapshot }): AuthSnapshot {
  if (!holder.latest) throw new Error("FAIL: AuthProvider did not render a state snapshot");
  return holder.latest;
}

async function settleAsyncWork() {
  await act(async () => {
    await new Promise((resolve) => window.setTimeout(resolve, 10));
  });
}

function mountProvider(onSnapshot: (snapshot: AuthSnapshot) => void): Root {
  function Probe() {
    onSnapshot(useAuth());
    return null;
  }

  const container = document.getElementById("root")!;
  const root = createRoot(container);
  act(() => {
    root.render(
      <StrictMode>
        <AuthProvider>
          <Probe />
        </AuthProvider>
      </StrictMode>
    );
  });
  return root;
}

async function main() {
  const originalHealth = api.healthUnauthenticated;
  const originalCreate = api.createAnonymousSession;

  try {
    // Successful first load: one POST and a ready workspace, never a spinner
    // left behind by the synthetic first cleanup.
    localStorage.clear();
    let createCalls = 0;
    const observed: { latest?: AuthSnapshot } = {};
    api.healthUnauthenticated = async () => ({ status: "ok" });
    api.createAnonymousSession = async () => {
      createCalls += 1;
      return { user_id: "anon_test", token: "token", session_id: "session" };
    };

    const successfulRoot = mountProvider((snapshot) => {
      observed.latest = snapshot;
    });
    await settleAsyncWork();
    const successfulState = requireSnapshot(observed);

    assert(createCalls === 1, `StrictMode creates one anonymous session (observed ${createCalls})`);
    assert(successfulState.isConfigured === true, "successful provisioning configures the workspace");
    assert(successfulState.isInitializing === false, "successful provisioning clears the loading state");
    assert(successfulState.initError === null, "successful provisioning has no setup error");
    act(() => successfulRoot.unmount());

    // Failure follows the same StrictMode path. The surviving setup must stop
    // loading and expose the error so the landing-page Retry action appears.
    localStorage.clear();
    createCalls = 0;
    const failedObserved: { latest?: AuthSnapshot } = {};
    api.createAnonymousSession = async () => {
      createCalls += 1;
      throw new Error("session service unavailable");
    };

    const failedRoot = mountProvider((snapshot) => {
      failedObserved.latest = snapshot;
    });
    await settleAsyncWork();
    const failedState = requireSnapshot(failedObserved);

    assert(createCalls === 1, `failed StrictMode provisioning also makes one request (observed ${createCalls})`);
    assert(failedState.isConfigured === false, "failed provisioning does not configure a workspace");
    assert(failedState.isInitializing === false, "failed provisioning clears the loading state");
    assert(
      failedState.initError === "session service unavailable",
      "failed provisioning exposes an actionable error"
    );
    act(() => failedRoot.unmount());
  } finally {
    api.healthUnauthenticated = originalHealth;
    api.createAnonymousSession = originalCreate;
    localStorage.clear();
  }

  console.log("\nAll AuthContext tests passed.");
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
