import { useEffect, useRef } from "react";

/**
 * StrictMode-safe useEffect for one-shot data loads.
 *
 * React 18 <StrictMode> (dev) mounts every component twice: setup →
 * cleanup → setup. A plain `useEffect(() => { void load(); }, deps)` thus
 * fires load() TWICE per page visit — two identical API calls and two
 * Supabase queries per mount (visible in backend logs as same-second
 * duplicate GETs, e.g. "GET /api/v1/timeline" logged twice 150ms apart).
 *
 * This hook runs `effect` once per distinct deps value: the StrictMode
 * re-invoke sees identical deps and is skipped, while a real change
 * (reloadKey bumped by a Refresh button, new credentials, new upload
 * result) re-runs it as normal. Production builds never double-invoke
 * effects, so this is a no-op there.
 */
export function useStrictEffect(
  effect: () => void | (() => void),
  deps: readonly unknown[]
): void {
  const lastDeps = useRef<readonly unknown[] | null>(null);

  useEffect(() => {
    const prev = lastDeps.current;
    lastDeps.current = deps;
    const changed =
      prev === null ||
      prev.length !== deps.length ||
      prev.some((d, i) => !Object.is(d, deps[i]));
    if (!changed) return undefined;
    return effect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
