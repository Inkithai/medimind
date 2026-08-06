import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
  const [initializing, setInitializing] = useState<boolean>(() => !loadStored().configured);
  const [initError, setInitError] = useState<string | null>(null);

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

  // Auto-provision on first load if no session exists
  useEffect(() => {
    if (state.configured) {
      setInitializing(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setInitializing(true);
      setInitError(null);
      try {
        // Use empty apiBase = same-origin (Vite proxy)
        const apiBase = "";
        // Quick health check before creating session
        try {
          await api.healthUnauthenticated(apiBase);
        } catch {
          // health failed but try session creation anyway (maybe proxy misconfig)
        }
        const session = await createAnonymous(apiBase);
        if (!cancelled) {
          setState(session);
        }
      } catch (err) {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : "Failed to create workspace";
          setInitError(msg);
        }
      } finally {
        if (!cancelled) setInitializing(false);
      }
    })();
    return () => {
      cancelled = true;
    };
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
  }, []);

  const refreshSession = useCallback(async () => {
    // Re-issue anonymous session using same apiBase
    await createAnonymous(state.apiBase);
  }, [createAnonymous, state.apiBase]);

  const createNewWorkspace = useCallback(async () => {
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
