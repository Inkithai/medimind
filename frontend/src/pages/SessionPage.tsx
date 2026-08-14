import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { Alert } from "../components/Alert";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody, CardHeader } from "../components/Card";
import { QAResultCard } from "../components/QAResultCard";
import { Spinner } from "../components/Spinner";
import {
  PlusIcon,
  SendIcon,
  SessionIcon,
  TrashIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import type { QAResponse, SessionHistory, SessionTurn } from "../types/api";
import { classNames, formatTimestamp } from "../utils/format";

interface UiMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  // Present on assistant messages — the full structured answer.
  result?: QAResponse;
  // Present when an assistant turn failed.
  error?: string;
}

export function SessionPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(8);
  const [creating, setCreating] = useState(false);
  const [sending, setSending] = useState(false);
  const [sessionError, setSessionError] = useState<unknown>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: reducedMotion ? "auto" : "smooth" });
  }, [messages, sending]);

  const startNewSession = useCallback(async () => {
    setCreating(true);
    setSessionError(null);
    setMessages([]);
    try {
      const info = await api.createSession(credentials);
      setSessionId(info.session_id);
    } catch (err) {
      setSessionError(err);
    } finally {
      setCreating(false);
    }
  }, [credentials]);

  const endSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      await api.deleteSession(credentials, sessionId);
    } catch {
      // best-effort — sessions are in-memory and expire on restart anyway
    }
    setSessionId(null);
    setMessages([]);
    setInput("");
  }, [credentials, sessionId]);

  // If the page loads with no active session, offer to start one. We don't
  // auto-create because sessions are server-side (in-memory) and the user
  // may want to resume by ID if they saved one.
  const loadExisting = useCallback(
    async (id: string) => {
      setSessionError(null);
      try {
        const history: SessionHistory = await api.getSession(credentials, id);
        setSessionId(id);
        setMessages(
          history.turns.map((t: SessionTurn) => ({
            role: t.role,
            content: t.content,
            timestamp: t.timestamp,
          }))
        );
      } catch (err) {
        setSessionError(err);
      }
    },
    [credentials]
  );

  async function send() {
    const text = input.trim();
    if (!text || !sessionId || sending) return;
    setInput("");
    setSending(true);
    setSessionError(null);

    const userMsg: UiMessage = {
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const result = await api.postMessage(credentials, sessionId, text, topK);
      const assistantMsg: UiMessage = {
        role: "assistant",
        content: result.answer,
        timestamp: new Date().toISOString(),
        result,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `[${err.status}] ${err.message}`
          : err instanceof Error
          ? err.message
          : "Failed to send message.";
      // A 404 means the session is gone (server restarted) — surface it
      // distinctly so the user knows to start a new session.
      const gone = err instanceof ApiError && err.status === 404;
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "",
          timestamp: new Date().toISOString(),
          error: gone
            ? "This conversation session no longer exists on the server (sessions are held in memory and are dropped when the API restarts). Start a new session to continue."
            : message,
        },
      ]);
      if (gone) setSessionId(null);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="page-title">{t("conversation.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("conversation.subtitle")}</p>
        </div>
        {sessionId ? (
          <button
            onClick={endSession}
            className="inline-flex items-center gap-2 rounded-md border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
          >
            <TrashIcon className="h-4 w-4" />
            {t("conversation.endSession")}
          </button>
        ) : (
          <button
            onClick={startNewSession}
            disabled={creating}
            className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {creating ? <Spinner className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}
            {t("conversation.newSession")}
          </button>
        )}
      </div>

      {sessionError !== null && <ErrorState error={sessionError} />}

      {!sessionId ? (
        <NoSessionView
          creating={creating}
          onStart={startNewSession}
          onResume={loadExisting}
        />
      ) : (
        <Card className="flex flex-col overflow-hidden">
          <CardHeader
            title={t("conversation.conversation")}
            description={t("conversation.remembers")}
            icon={<SessionIcon className="h-5 w-5" />}
          />
          <div
            ref={scrollRef}
            role="log"
            aria-live="polite"
            aria-relevant="additions"
            aria-label={t("conversation.conversation")}
            className="max-h-[55vh] min-h-[300px] space-y-4 overflow-y-auto bg-slate-50/50 px-5 py-4 scroll-thin"
          >
            {messages.length === 0 && (
              <p className="py-12 text-center text-sm text-slate-400">
                {t("conversation.empty")}
              </p>
            )}
            {messages.map((msg, idx) => (
              <MessageBubble key={idx} message={msg} />
            ))}
            {sending && (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <Spinner className="h-4 w-4" />
                {t("conversation.thinking")}
              </div>
            )}
          </div>
          <CardBody className="border-t border-slate-100">
            <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void send(); }}>
              <label htmlFor="conversation-message" className="sr-only">{t("conversation.inputLabel")}</label>
              <input
                id="conversation-message"
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder={t("conversation.placeholder")}
                className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                disabled={sending}
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
              >
                {sending ? <Spinner className="h-4 w-4" /> : <SendIcon className="h-4 w-4" />}
                {t("conversation.send")}
              </button>
            </form>
            <details className="mt-2 text-xs text-slate-500">
              <summary className="cursor-pointer font-medium text-slate-700">{t("ask.advanced")}</summary>
              <div className="mt-2 flex items-center gap-2">
                <label htmlFor="session-topk">{t("ask.amount")}:</label>
                <input
                  id="session-topk"
                  type="range"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(e) => setTopK(parseInt(e.target.value, 10))}
                  className="w-32"
                />
                <span className="font-medium text-slate-700">{topK}</span>
              </div>
            </details>
          </CardBody>
        </Card>
      )}

      <Alert variant="info" title={t("conversation.about")}>
        {t("conversation.aboutBody")}
      </Alert>
    </div>
  );
}

function MessageBubble({ message }: { message: UiMessage }) {
  const isUser = message.role === "user";
  if (message.error) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
          {message.error}
        </div>
      </div>
    );
  }
  return (
    <div className={classNames("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={classNames(
          "max-w-[85%] space-y-2 rounded-lg px-4 py-2 text-sm",
          isUser
            ? "bg-brand-600 text-white"
            : "border border-slate-200 bg-white text-slate-800"
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : message.result ? (
          <QAResultCard result={message.result} embedded />
        ) : (
          <p className="whitespace-pre-wrap">{message.content}</p>
        )}
        <p
          className={classNames(
            "text-[10px]",
            isUser ? "text-brand-100" : "text-slate-400"
          )}
        >
          {formatTimestamp(message.timestamp)}
        </p>
      </div>
    </div>
  );
}

function NoSessionView({
  creating,
  onStart,
  onResume,
}: {
  creating: boolean;
  onStart: () => void;
  onResume: (id: string) => void;
}) {
  const { t } = useI18n();
  const [resumeId, setResumeId] = useState("");

  return (
    <Card>
      <CardBody className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
          <SessionIcon className="h-7 w-7" />
        </div>
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {t("conversation.start")}
          </h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
            {t("conversation.startBody")}
          </p>
        </div>
        <button
          onClick={onStart}
          disabled={creating}
          className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
        >
          {creating ? <Spinner className="h-4 w-4" /> : <PlusIcon className="h-4 w-4" />}
          {t("conversation.create")}
        </button>

        <div className="mt-2 w-full max-w-md border-t border-slate-100 pt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
            {t("conversation.resumeTitle")}
          </p>
          <div className="mt-2 flex gap-2">
            <label htmlFor="resume-session-id" className="sr-only">{t("conversation.resumeTitle")}</label>
            <input
              id="resume-session-id"
              type="text"
              value={resumeId}
              onChange={(e) => setResumeId(e.target.value)}
              placeholder={t("conversation.resumePlaceholder")}
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
            />
            <button
              onClick={() => resumeId.trim() && onResume(resumeId.trim())}
              disabled={!resumeId.trim()}
              className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {t("conversation.resume")}
            </button>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Only works if the session still exists in the API process's memory.
          </p>
        </div>
      </CardBody>
    </Card>
  );
}
