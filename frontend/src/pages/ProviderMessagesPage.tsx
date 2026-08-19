/**
 * Provider messages — a restored screen for POST/GET /api/v1/provider-messages.
 *
 * Honest framing matters more than the UI here. The backend stores these
 * notes in the patient's own workspace; there is no delivery transport and
 * no clinician account on the other end. So this page never says "sent":
 * it says the note was saved and can be printed or read out at the visit.
 * That is also why the route used to redirect away — the capability existed
 * with no screen, which is worse than a screen that states its limits.
 */
import { useCallback, useState } from "react";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody, CardHeader } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState, Spinner } from "../components/Spinner";
import { ChatIcon, PrintIcon, SendIcon } from "../components/icons";
import type { EmbeddedPageProps } from "../components/TabBar";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { ProviderMessage, ProviderThread } from "../types/api";
import { formatTimestamp } from "../utils/format";

export function ProviderMessagesPage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [threads, setThreads] = useState<ProviderThread[]>([]);
  const [openThread, setOpenThread] = useState<string | null>(null);
  const [messages, setMessages] = useState<ProviderMessage[]>([]);
  const [provider, setProvider] = useState("");
  const [body, setBody] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.listProviderThreads(credentials);
      setThreads(result.threads || []);
    } catch (err) {
      setThreads([]);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  async function openThreadMessages(threadId: string) {
    if (openThread === threadId) {
      setOpenThread(null);
      setMessages([]);
      return;
    }
    setOpenThread(threadId);
    setMessages([]);
    try {
      const result = await api.listProviderMessages(credentials, threadId);
      setMessages(result.messages || []);
    } catch (err) {
      setError(err);
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!body.trim() || saving) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = await api.sendProviderMessage(credentials, {
        body: body.trim(),
        provider: provider.trim() || undefined,
        thread_id: openThread || undefined,
      });
      setBody("");
      setNotice(t("messages.saved"));
      await load();
      if (openThread === saved.thread_id) {
        const result = await api.listProviderMessages(credentials, saved.thread_id);
        setMessages(result.messages || []);
      }
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        {embedded ? (
          <p className="secondary-text max-w-2xl">{t("messages.subtitle")}</p>
        ) : (
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
              <ChatIcon className="h-4 w-4" /> {t("messages.eyebrow")}
            </div>
            <h1 className="page-title mt-1">{t("messages.title")}</h1>
            <p className="secondary-text mt-2 max-w-2xl">{t("messages.subtitle")}</p>
          </div>
        )}
        {threads.length > 0 && (
          <button type="button" onClick={() => window.print()} className="btn-secondary shrink-0">
            <PrintIcon className="h-4 w-4" aria-hidden="true" />
            {t("messages.print")}
          </button>
        )}
      </header>

      {/* The single most important sentence on this page. */}
      <Alert variant="info" title={t("messages.notDeliveredTitle")}>
        {t("messages.notDeliveredBody")}
      </Alert>

      <Card>
        <CardHeader
          title={t("messages.composeTitle")}
          description={t("messages.composeBody")}
          icon={<ChatIcon className="h-5 w-5" />}
        />
        <CardBody>
          <form onSubmit={save} className="space-y-3" aria-busy={saving}>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">{t("messages.providerLabel")}</span>
              <input
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                placeholder={t("messages.providerPlaceholder")}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm sm:max-w-md"
                disabled={saving}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">{t("messages.bodyLabel")}</span>
              <textarea
                value={body}
                onChange={(event) => setBody(event.target.value)}
                rows={4}
                required
                placeholder={t("messages.bodyPlaceholder")}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                disabled={saving}
              />
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" disabled={saving || !body.trim()} className="btn-primary">
                {saving ? <Spinner className="h-4 w-4" /> : <SendIcon className="h-4 w-4" />}
                {openThread ? t("messages.addToThread") : t("messages.save")}
              </button>
              {openThread && (
                <button
                  type="button"
                  onClick={() => {
                    setOpenThread(null);
                    setMessages([]);
                  }}
                  className="text-sm font-semibold text-slate-600 hover:text-slate-900"
                >
                  {t("messages.startNewThread")}
                </button>
              )}
            </div>
            {notice && (
              <p role="status" className="text-sm font-medium text-emerald-700">
                {notice}
              </p>
            )}
          </form>
        </CardBody>
      </Card>

      {loading && <LoadingState label={t("messages.loading")} />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && threads.length === 0 && error === null && (
        <Card>
          <CardBody className="py-12 text-center">
            <h2 className="section-title">{t("messages.emptyTitle")}</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
              {t("messages.emptyBody")}
            </p>
          </CardBody>
        </Card>
      )}

      {threads.length > 0 && (
        <section className="space-y-3">
          <h2 className="section-title">{t("messages.savedNotes")}</h2>
          {threads.map((thread) => (
            <article
              key={thread.thread_id}
              className="rounded-2xl border border-slate-200 bg-white shadow-sm"
            >
              <button
                type="button"
                onClick={() => void openThreadMessages(thread.thread_id)}
                aria-expanded={openThread === thread.thread_id}
                className="flex w-full flex-wrap items-center justify-between gap-3 px-5 py-4 text-left"
              >
                <div className="min-w-0">
                  <p className="font-semibold text-slate-900">
                    {thread.provider || t("messages.noProvider")}
                  </p>
                  <p className="secondary-text mt-0.5">
                    {t("messages.threadMeta", {
                      count: thread.message_count,
                      when: formatTimestamp(thread.last_at),
                    })}
                  </p>
                </div>
                <span aria-hidden="true" className="text-slate-400">
                  {openThread === thread.thread_id ? "▲" : "▼"}
                </span>
              </button>

              {openThread === thread.thread_id && (
                <div className="space-y-3 border-t border-slate-100 px-5 py-4">
                  {messages.length === 0 ? (
                    <p className="text-sm text-slate-500">{t("common.loading")}</p>
                  ) : (
                    messages.map((message, index) => (
                      <div
                        key={`${message.created_at}-${index}`}
                        className="rounded-xl bg-slate-50 px-4 py-3"
                      >
                        <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                          {message.body}
                        </p>
                        <p className="mt-2 text-xs text-slate-400">
                          {formatTimestamp(message.created_at)}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
