/**
 * Toast notifications.
 *
 * After an action (saving, deleting, downloading, re-reading a document)
 * the user must be told what happened without hunting for a message
 * somewhere on the page. Toasts appear in a fixed region, announce
 * themselves to screen readers, and always pair their colour with an icon
 * and a word ("Done", "Could not finish", "Please note") so status is
 * never carried by colour alone.
 *
 * Deliberately dependency-free and low-motion: no animation library, no
 * sliding/bouncing, one small fade. Success/info messages clear
 * themselves after a few seconds; errors stay until dismissed, because a
 * failure the user did not read is a failure they think succeeded.
 */
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
import { classNames } from "../utils/format";

export type ToastTone = "success" | "error" | "info";

export interface ToastOptions {
  /** Short headline, e.g. "Document removed". */
  title: string;
  /** Optional detail sentence in plain language. */
  description?: string;
  tone?: ToastTone;
  /** Milliseconds before auto-dismiss. Errors never auto-dismiss. */
  durationMs?: number;
}

interface ToastRecord extends Required<Pick<ToastOptions, "title" | "tone">> {
  id: number;
  description?: string;
  durationMs: number | null;
}

interface ToastApi {
  /** Show a toast. Returns its id so callers can dismiss it early. */
  showToast: (options: ToastOptions) => number;
  /** Convenience wrappers used by pages. */
  toastSuccess: (title: string, description?: string) => number;
  toastError: (title: string, description?: string) => number;
  toastInfo: (title: string, description?: string) => number;
  dismissToast: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_DURATION_MS = 6000;

const TONE_STYLES: Record<ToastTone, { box: string; iconWrap: string; label: string }> = {
  success: {
    box: "border-emerald-300 bg-emerald-50 text-emerald-900",
    iconWrap: "bg-emerald-600 text-white",
    label: "Done",
  },
  error: {
    box: "border-red-300 bg-red-50 text-red-900",
    iconWrap: "bg-red-600 text-white",
    label: "Could not finish",
  },
  info: {
    box: "border-sky-300 bg-sky-50 text-sky-900",
    iconWrap: "bg-sky-600 text-white",
    label: "Please note",
  },
};

function ToneIcon({ tone }: { tone: ToastTone }) {
  if (tone === "success") {
    return (
      <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="h-5 w-5">
        <path
          fillRule="evenodd"
          d="M16.7 5.3a1 1 0 010 1.4l-7.5 7.5a1 1 0 01-1.4 0L3.3 9.7a1 1 0 111.4-1.4l3.8 3.8 6.8-6.8a1 1 0 011.4 0z"
          clipRule="evenodd"
        />
      </svg>
    );
  }
  if (tone === "error") {
    return (
      <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="h-5 w-5">
        <path
          fillRule="evenodd"
          d="M10 2a8 8 0 100 16 8 8 0 000-16zm.75 4.25a.75.75 0 00-1.5 0v4.5a.75.75 0 001.5 0v-4.5zM10 15a1 1 0 100-2 1 1 0 000 2z"
          clipRule="evenodd"
        />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="h-5 w-5">
      <path
        fillRule="evenodd"
        d="M10 2a8 8 0 100 16 8 8 0 000-16zm0 4a1 1 0 110 2 1 1 0 010-2zm.75 4.5a.75.75 0 00-1.5 0v4a.75.75 0 001.5 0v-4z"
        clipRule="evenodd"
      />
    </svg>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismissToast = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const showToast = useCallback(
    ({ title, description, tone = "success", durationMs }: ToastOptions) => {
      const id = nextId.current++;
      // An error the user missed reads as a silent success, so errors wait
      // for an explicit dismissal.
      const lifetime =
        tone === "error" ? null : typeof durationMs === "number" ? durationMs : DEFAULT_DURATION_MS;
      setToasts((current) => {
        const next = [...current, { id, title, description, tone, durationMs: lifetime }];
        // Keep the stack readable — oldest messages fall off first.
        return next.slice(-4);
      });
      if (lifetime !== null) {
        timers.current.set(
          id,
          setTimeout(() => {
            timers.current.delete(id);
            setToasts((current) => current.filter((toast) => toast.id !== id));
          }, lifetime),
        );
      }
      return id;
    },
    [],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach((timer) => clearTimeout(timer));
      pending.clear();
    };
  }, []);

  const value = useMemo<ToastApi>(
    () => ({
      showToast,
      dismissToast,
      toastSuccess: (title, description) => showToast({ title, description, tone: "success" }),
      toastError: (title, description) => showToast({ title, description, tone: "error" }),
      toastInfo: (title, description) => showToast({ title, description, tone: "info" }),
    }),
    [showToast, dismissToast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismissToast} />
    </ToastContext.Provider>
  );
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastRecord[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div
      className="pointer-events-none fixed inset-x-0 bottom-0 z-[200] flex flex-col items-center gap-3 px-4 pb-4 sm:bottom-6 sm:right-6 sm:left-auto sm:items-end sm:px-0 sm:pb-0"
      aria-live="polite"
      aria-relevant="additions text"
    >
      {toasts.map((toast) => {
        const style = TONE_STYLES[toast.tone];
        return (
          <div
            key={toast.id}
            role={toast.tone === "error" ? "alert" : "status"}
            className={classNames(
              "pointer-events-auto flex w-full max-w-md gap-3 rounded-xl border-2 p-4 shadow-lg",
              style.box,
            )}
          >
            <span
              className={classNames(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                style.iconWrap,
              )}
              aria-hidden="true"
            >
              <ToneIcon tone={toast.tone} />
            </span>
            <div className="min-w-0 flex-1">
              {/* The word carries the status too, so it is readable without colour. */}
              <p className="text-xs font-bold uppercase tracking-wide opacity-80">{style.label}</p>
              <p className="text-base font-semibold leading-snug">{toast.title}</p>
              {toast.description && (
                <p className="mt-1 text-sm leading-relaxed opacity-90">{toast.description}</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              className="-m-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-current opacity-70 transition hover:bg-white/60 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
            >
              <span className="sr-only">Close this message</span>
              <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" className="h-5 w-5">
                <path d="M6.3 5a.9.9 0 00-1.3 1.3L8.7 10l-3.7 3.7A.9.9 0 106.3 15L10 11.3 13.7 15a.9.9 0 001.3-1.3L11.3 10 15 6.3A.9.9 0 0013.7 5L10 8.7 6.3 5z" />
              </svg>
            </button>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Access the toast API. Safe to call outside a provider (tests, isolated
 * component renders): the calls simply become no-ops rather than crashing
 * a page.
 */
export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  return (
    context ?? {
      showToast: () => 0,
      toastSuccess: () => 0,
      toastError: () => 0,
      toastInfo: () => 0,
      dismissToast: () => undefined,
    }
  );
}

/** Turn an unknown thrown value into a sentence a non-technical user can read. */
export function toastMessage(error: unknown, fallback = "Please try again."): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = String((error as { message: unknown }).message || "").trim();
    if (message) return message;
  }
  if (typeof error === "string" && error.trim()) return error.trim();
  return fallback;
}
