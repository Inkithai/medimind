import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody, CardHeader } from "../components/Card";
import { QAResultCard } from "../components/QAResultCard";
import { Spinner } from "../components/Spinner";
import { ChatIcon, SendIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import type { QAResponse } from "../types/api";

const SUGGESTION_KEYS = ["ask.suggestion1", "ask.suggestion2", "ask.suggestion3", "ask.suggestion4"] as const;

export function QAPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(8);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QAResponse | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function ask(q?: string) {
    const text = (q ?? question).trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setQuestion(text);
    try {
      const res = await api.ask(credentials, text, topK);
      setResult(res);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">{t("ask.title")}</h1>
        <p className="secondary-text mt-2 max-w-2xl">{t("ask.subtitle")}</p>
      </header>

      <Card>
        <CardHeader
          title={t("ask.question")}
          description={t("ask.description")}
          icon={<ChatIcon className="h-5 w-5" />}
        />
        <CardBody className="space-y-4">
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void ask();
            }}
          >
            <label htmlFor="record-question" className="sr-only">{t("ask.inputLabel")}</label>
            <input
              id="record-question"
              name="question"
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask();
                }
              }}
              placeholder={t("ask.placeholder")}
              aria-describedby="question-help"
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
            >
              {loading ? <Spinner className="h-4 w-4" /> : <SendIcon className="h-4 w-4" />}
              {t("ask.ask")}
            </button>
          </form>
          <p id="question-help" className="sr-only">{t("ask.description")}</p>

          <details className="text-xs text-slate-500">
            <summary className="cursor-pointer font-medium text-slate-700">{t("ask.advanced")}</summary>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label htmlFor="topk">{t("ask.amount")}:</label>
              <input
                id="topk"
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

          <fieldset>
            <legend className="mb-2 text-xs font-semibold text-slate-700">{t("ask.suggestions")}</legend>
            <div className="flex flex-wrap gap-2">
            {SUGGESTION_KEYS.map((key) => {
              const suggestion = t(key);
              return (
              <button
                type="button"
                key={key}
                onClick={() => {
                  setQuestion(suggestion);
                  void ask(suggestion);
                }}
                disabled={loading}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
              >
                {suggestion}
              </button>
              );
            })}
            </div>
          </fieldset>
        </CardBody>
      </Card>

      {loading && (
        <Alert variant="info" title={t("ask.reading")}>
          {t("ask.readingBody")}
        </Alert>
      )}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void ask()} />}

      {!loading && result && (
        <div className="space-y-3">
          <h2 className="section-title">{t("ask.answer")}</h2>
          <QAResultCard result={result} />
        </div>
      )}

      <p className="secondary-text text-center">
        Prefer a back-and-forth chat?{" "}
        <Link to="/conversations" className="font-medium text-brand-600 hover:text-brand-700">
          Open Conversations →
        </Link>
      </p>
    </div>
  );
}
