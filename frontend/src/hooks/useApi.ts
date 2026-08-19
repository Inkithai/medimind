import { useCallback, useEffect, useRef, useState } from "react";

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: unknown;
}

interface UseApiResult<T, Args extends unknown[]> extends ApiState<T> {
  run: (...args: Args) => Promise<T | null>;
  reset: () => void;
  setData: (data: T | null) => void;
}

// Generic hook for calling an async API function on demand, tracking
// loading/error/data. If `immediate` is true the call fires on mount
// (and whenever deps change).
export function useApi<T, Args extends unknown[] = []>(
  fn: (...args: Args) => Promise<T>,
  options?: { immediate?: boolean; deps?: unknown[] },
): UseApiResult<T, Args> {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: false,
    error: null,
  });
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const run = useCallback(async (...args: Args) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fnRef.current(...args);
      setState({ data, loading: false, error: null });
      return data;
    } catch (err) {
      setState({ data: null, loading: false, error: err });
      return null;
    }
  }, []);

  const reset = useCallback(() => setState({ data: null, loading: false, error: null }), []);

  const setData = useCallback((data: T | null) => setState((s) => ({ ...s, data })), []);

  useEffect(() => {
    if (options?.immediate) {
      void run(...([] as unknown[] as Args));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, options?.deps ?? []);

  return { ...state, run, reset, setData };
}
