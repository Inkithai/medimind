import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Credentials } from "../api/client";

const STORAGE_KEY = "nalam.credentials.v1";

interface StoredCredentials extends Credentials {
  configured: boolean;
}

interface AuthContextValue {
  credentials: Credentials;
  isConfigured: boolean;
  /** True when the user has explicitly set credentials this session (used
   *  to know when to attempt data loads). */
  saveCredentials: (creds: Credentials) => void;
  clearCredentials: () => void;
}

const EMPTY: StoredCredentials = {
  configured: false,
  apiBase: "",
  token: "",
  userId: "",
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function loadStored(): StoredCredentials {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<StoredCredentials>;
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
      };
    }
  } catch {
    // ignore malformed storage
  }
  return EMPTY;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<StoredCredentials>(() => loadStored());

  useEffect(() => {
    if (state.configured) {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          configured: true,
          apiBase: state.apiBase,
          token: state.token,
          userId: state.userId,
        })
      );
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [state]);

  const saveCredentials = useCallback((creds: Credentials) => {
    setState({
      configured: true,
      apiBase: creds.apiBase.trim(),
      token: creds.token.trim(),
      userId: creds.userId.trim(),
    });
  }, []);

  const clearCredentials = useCallback(() => setState(EMPTY), []);

  const value = useMemo<AuthContextValue>(
    () => ({
      credentials: {
        apiBase: state.apiBase,
        token: state.token,
        userId: state.userId,
      },
      isConfigured: state.configured,
      saveCredentials,
      clearCredentials,
    }),
    [state, saveCredentials, clearCredentials]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
