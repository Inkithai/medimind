import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, type Credentials } from "../api/client";

const STORAGE_KEY = "medimind.session.v1";
const LEGACY_KEY = "nalam.credentials.v1";

interface StoredSession extends Credentials {
  configured: boolean;
  createdAt?: string;
}

interface AuthContextValue {
  credentials: Credentials;
  isConfigured: boolean;
  isInitializing: boolean;
  initError: string | null;
  saveCredentials: (creds: Credentials) => void;
  clearCredentials: () => void;
  refreshSession: () => Promise<void>;
  createNewWorkspace: () => Promise<void>;
}

const EMPTY: StoredSession = {
  configured: false,
  apiBase: "",
  token: "",
  userId: "",
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function loadStored(): StoredSession {
  // Try new key first, fallback to legacy nalam key for migration
  const keys = [STORAGE_KEY, LEGACY_KEY];
  for (const key of keys) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw) as Partial<StoredSession>;
      if (
        parsed &&
        typeof parsed.token === "string" &&
        typeof parsed.userId === "string" &&
        parsed.token.trim() &&
        parsed.userId.trim()
      ) {
        return {
          configured: true,
          apiBase: typeof parsed.apiBase === "string" ? parsed.apiBase : "",
          token: parsed.token,
          userId: parsed.userId,
          createdAt:
            typeof parsed.createdAt === "string" ? parsed.createdAt : undefined,
        };
      }
    } catch {
      // ignore malformed
    }
  }
  return EMPTY;
}

function persist(state: StoredSession) {
  if (state.configured) {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        configured: true,
        apiBase: state.apiBase,
        token: state.token,
        userId: state.userId,
        createdAt: state.createdAt || new Date().toISOString(),
      })
    );
  } else {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(LEGACY_KEY);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoredSession>(() => loadStored());
  const [initializing, setInitializing] = useState<boolean>(() => !state.configured);
  const [initError, setInitError] = useState<string | null>(null);

  // React 18 <StrictMode> (see main.tsx) runs mount effects as
  // setup → cleanup → setup on the SAME fiber. The first ref prevents a
  // duplicate POST; the second tells the in-flight first setup that the
  // provider is live again after StrictMode's synthetic cleanup. A local
  // `cancelled` variable cannot do that: it remains true forever and leaves
  // isInitializing stuck after the one provisioning request succeeds.
  const provisioningStarted = useRef(false);
  const providerMounted = useRef(false);

  const createAnonymous = useCallback(async (apiBase = "") => {
    const res = await api.createAnonymousSession(apiBase);
    const next: StoredSession = {
      configured: true,
      apiBase: apiBase.trim(),
      token: res.token,
      userId: res.user_id,
      createdAt: new Date().toISOString(),
    };
    setState(next);
    persist(next);
    return next;
  }, []);

  // Auto-provision on first load if no session exists.
  useEffect(() => {
    providerMounted.current = true;
    const markUnmounted = () => {
      providerMounted.current = false;
    };

    if (state.configured) {
      setInitializing(false);
      return markUnmounted;
    }
    if (provisioningStarted.current) {
      // StrictMode re-ran this effect; the first invocation is already
      // provisioning. Keep this setup's cleanup so a real unmount is still
      // distinguished from StrictMode's temporary cleanup.
      return markUnmounted;
    }
    provisioningStarted.current = true;
    (async () => {
      setInitializing(true);
      setInitError(null);
      try {
        // Use VITE_API_URL if set (production), else empty string (same-origin/Vite proxy).
        // Optional chaining also keeps non-Vite test runners from crashing here.
        const apiBase = (import.meta.env?.VITE_API_URL as string) || "";
        // Quick health check before creating session
        try {
          await api.healthUnauthenticated(apiBase);
        } catch {
          // health failed but try session creation anyway (maybe proxy misconfig)
        }
        await createAnonymous(apiBase);
      } catch (err) {
        if (providerMounted.current) {
          const msg =
            err instanceof Error ? err.message : "Failed to create workspace";
          setInitError(msg);
        }
      } finally {
        if (providerMounted.current) setInitializing(false);
      }
    })();
    return markUnmounted;
    // only run once on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    persist(state);
  }, [state]);

  const saveCredentials = useCallback((creds: Credentials) => {
    const next: StoredSession = {
      configured: true,
      apiBase: creds.apiBase.trim(),
      token: creds.token.trim(),
      userId: creds.userId.trim(),
      createdAt: new Date().toISOString(),
    };
    setState(next);
    persist(next);
  }, []);

  const clearCredentials = useCallback(() => {
    const empty = EMPTY;
    setState(empty);
    persist(empty);
    provisioningStarted.current = false;
  }, []);

  const refreshSession = useCallback(async () => {
    // Re-issue anonymous session using same apiBase
    await createAnonymous(state.apiBase);
  }, [createAnonymous, state.apiBase]);

  const createNewWorkspace = useCallback(async () => {
    provisioningStarted.current = false;
    clearCredentials();
    setInitializing(true);
    setInitError(null);
    try {
      await createAnonymous(state.apiBase);
    } catch (err) {
      setInitError(err instanceof Error ? err.message : "Failed to create workspace");
    } finally {
      setInitializing(false);
    }
  }, [clearCredentials, createAnonymous, state.apiBase]);

  const value = useMemo<AuthContextValue>(
    () => ({
      credentials: {
        apiBase: state.apiBase,
        token: state.token,
        userId: state.userId,
      },
      isConfigured: state.configured,
      isInitializing: initializing,
      initError,
      saveCredentials,
      clearCredentials,
      refreshSession,
      createNewWorkspace,
    }),
    [state, initializing, initError, saveCredentials, clearCredentials, refreshSession, createNewWorkspace]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
