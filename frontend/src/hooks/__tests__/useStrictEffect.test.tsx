/**
 * Proves that useStrictEffect() collapses React 18 <StrictMode>'s dev
 * double-invocation of effects into ONE run per mount (fixing the
 * same-second duplicate GETs seen in backend logs), while still re-running
 * when deps actually change.
 *
 * Note: this must run with the React DEVELOPMENT build (StrictMode's
 * setup→cleanup→setup effect behavior is dev-only). Run via
 * `npm run test:hook` (the script sets NODE_ENV=development).
 */
import { StrictMode, act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";

import { useStrictEffect } from "../useStrictEffect";

// Minimal DOM for react-dom's createRoot.
const dom = new JSDOM("<!DOCTYPE html><html><body><div id='root'></div></body></html>");
(globalThis as Record<string, unknown>).window = dom.window;
(globalThis as Record<string, unknown>).document = dom.window.document;
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
try {
  Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
  });
} catch {
  // Node 22 already exposes a read-only navigator — react-dom is fine with it.
}

function Probe({
  onRun,
  onPlainRun,
  reloadKey,
}: {
  onRun: () => void;
  onPlainRun: () => void;
  reloadKey: number;
}) {
  // Baseline: a plain useEffect — StrictMode (dev, createRoot) double-invokes this.
  useEffect(() => {
    onPlainRun();
  }, [reloadKey]);

  // The fix: useStrictEffect — should run once per distinct deps.
  useStrictEffect(() => {
    onRun();
  }, [reloadKey]);

  return null;
}

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  console.log(`PASS: ${msg}`);
}

function mountProbe() {
  const runs: number[] = [];
  const plainRuns: number[] = [];
  const container = document.getElementById("root")!;

  let root!: Root;
  act(() => {
    root = createRoot(container);
    root.render(
      <StrictMode>
        <Probe
          onRun={() => runs.push(1)}
          onPlainRun={() => plainRuns.push(1)}
          reloadKey={0}
        />
      </StrictMode>
    );
  });

  const rerender = (reloadKey: number) => {
    act(() => {
      root.render(
        <StrictMode>
          <Probe
            onRun={() => runs.push(1)}
            onPlainRun={() => plainRuns.push(1)}
            reloadKey={reloadKey}
          />
        </StrictMode>
      );
    });
  };

  const unmount = () => {
    act(() => {
      root.unmount();
    });
  };

  return { runs, plainRuns, rerender, unmount };
}

// 1. On mount under StrictMode, the plain effect fires TWICE (the bug),
//    useStrictEffect fires exactly ONCE (the fix).
{
  const { runs, plainRuns, unmount } = mountProbe();
  assert(
    plainRuns.length === 2,
    `plain useEffect under StrictMode+createRoot fires 2x (observed ${plainRuns.length}) — this is the duplicate-GET bug`
  );
  assert(
    runs.length === 1,
    `useStrictEffect under StrictMode fires exactly 1x (observed ${runs.length})`
  );
  unmount();
}

// 2. A genuine deps change (Refresh button bumping reloadKey) still re-runs.
{
  const { runs, plainRuns, rerender, unmount } = mountProbe();
  rerender(1);
  assert(
    runs.length === 2,
    `useStrictEffect re-runs when deps change (observed ${runs.length})`
  );
  // React 18 StrictMode double-invokes only MOUNT effects (2 on mount);
  // update effects run once. Baseline total = 3, our hook = 2 (once per
  // distinct deps value).
  assert(
    plainRuns.length === 3,
    `plain useEffect fired 2x on mount + 1x on update (observed ${plainRuns.length})`
  );
  unmount();
}

// 3. Same-deps re-render (e.g. unrelated state change) must NOT re-run.
{
  const { runs, rerender, unmount } = mountProbe();
  rerender(0); // same reloadKey value — deps unchanged
  assert(
    runs.length === 1,
    `useStrictEffect does not re-run on same-deps re-render (observed ${runs.length})`
  );
  unmount();
}

console.log("\nAll useStrictEffect tests passed.");
