import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { EmptyState } from "../components/EmptyState";
import { SendIcon, RefreshIcon } from "../components/icons";
import { toastMessage, useToast } from "../components/Toast";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { ProviderThread, ProviderMessage } from "../types/api";

export function MessagesPage() {
  const { toastSuccess, toastError } = useToast();
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [threads, setThreads] = useState<ProviderThread[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<ProviderMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [provider, setProvider] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listProviderThreads(credentials);
      setThreads(data.threads || []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load, reloadKey]);

  async function openThread(threadId: string) {
    setActive(threadId);
    try {
      const data = await api.listProviderMessages(credentials, threadId);
      setMessages(data.messages || []);
    } catch {
      setMessages([]);
    }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    setSending(true);
    try {
      const msg = await api.sendProviderMessage(credentials, {
        body: body.trim(),
        provider: provider.trim() || undefined,
        thread_id: active || undefined,
      });
      setBody("");
      if (!active) {
        setActive(msg.thread_id);
      }
      await load();
      if (msg.thread_id) await openThread(msg.thread_id);
      toastSuccess("Message saved", "It is stored securely with your records.");
    } catch (err) {
      toastError("Message not sent", toastMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex min-w-0 flex-col items-start justify-between gap-4 sm:flex-row">
        <div className="min-w-0">
          <h1 className="page-title">{t("messages.title")}</h1>
          <p className="secondary-text mt-2 max-w-2xl">{t("messages.subtitle")}</p>
        </div>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshIcon className="h-4 w-4" />
          {t("common.refresh")}
        </button>
      </div>

      {loading && <LoadingState label={t("common.loading")} />}
      {!loading && error !== null && (
        <ErrorState error={error} onRetry={() => setReloadKey((k) => k + 1)} />
      )}

      {!loading && !error && (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <Card>
            <CardHeader title="Threads" />
            <CardBody className="space-y-1">
              {threads.length === 0 && (
                <p className="text-xs text-slate-400">No threads yet. Start one →</p>
              )}
              {threads.map((th) => (
                <button
                  key={th.thread_id}
                  onClick={() => openThread(th.thread_id)}
                  className={`block w-full rounded-md px-2 py-1.5 text-left text-xs ${
                    active === th.thread_id
                      ? "bg-brand-50 text-brand-700"
                      : "hover:bg-slate-50 text-slate-600"
                  }`}
                >
                  <div className="font-medium">{th.provider || "Provider"}</div>
                  <div className="text-slate-400">{th.message_count} msg</div>
                </button>
              ))}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={active ? `Thread ${active}` : "New message"} />
            <CardBody className="space-y-3">
              {!active && threads.length === 0 && (
                <EmptyState
                  title="Send a message to a provider"
                  description="Messages are stored in your workspace. An operator connects the chosen transport (email/SMS) to deliver them."
                />
              )}
              {messages.length > 0 && (
                <div className="max-h-64 space-y-2 overflow-y-auto">
                  {messages.map((m, i) => (
                    <div
                      key={i}
                      className={`max-w-[80%] rounded-lg px-3 py-2 text-xs ${
                        m.direction === "outbound"
                          ? "ml-auto bg-brand-600 text-white"
                          : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {m.body}
                      <div
                        className={`mt-1 text-[10px] ${m.direction === "outbound" ? "text-brand-100" : "text-slate-400"}`}
                      >
                        {new Date(m.created_at).toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <form onSubmit={send} className="space-y-2">
                {!active && (
                  <input
                    value={provider}
                    onChange={(e) => setProvider(e.target.value)}
                    placeholder="Provider name (optional)"
                    className="block w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
                  />
                )}
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="Type a message…"
                  rows={3}
                  className="block w-full rounded-md border border-slate-300 px-2 py-2 text-sm"
                />
                <button
                  type="submit"
                  disabled={sending || !body.trim()}
                  className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
                >
                  <SendIcon className="h-4 w-4" />
                  {sending ? "Sending…" : "Send"}
                </button>
              </form>
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  );
}
