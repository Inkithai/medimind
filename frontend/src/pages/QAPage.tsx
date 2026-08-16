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
import type { QAResponse } from "../types/api";

const SUGGESTIONS = [
  "Which medications are listed in my latest record?",
  "Has my glucose changed over time?",
  "Are there any allergies documented in my records?",
  "What did my doctor note at my last visit?",
];

export function QAPage() {
  const { credentials } = useAuth();
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
        <h1 className="page-title">Ask AI</h1>
        <p className="secondary-text mt-2 max-w-2xl">
          Ask anything about your records. Answers come only from your own documents — never from the
          open internet — with the source file and page cited.
        </p>
      </header>

      <Card>
        <CardHeader
          title="Your question"
          description="MediMind reads your records to answer. It never replaces a doctor."
          icon={<ChatIcon className="h-5 w-5" />}
        />
        <CardBody className="space-y-4">
          <div className="flex gap-2">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask();
                }
              }}
              placeholder="e.g. What was I prescribed for my sinus infection?"
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              disabled={loading}
            />
            <button
              onClick={() => void ask()}
              disabled={loading || !question.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
            >
              {loading ? <Spinner className="h-4 w-4" /> : <SendIcon className="h-4 w-4" />}
              Ask
            </button>
          </div>

          <details className="text-xs text-slate-500">
            <summary className="cursor-pointer font-medium text-slate-600">Advanced</summary>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label htmlFor="topk">How much of your record to read per answer:</label>
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

          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setQuestion(s);
                  void ask(s);
                }}
                disabled={loading}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        </CardBody>
      </Card>

      {loading && (
        <Alert variant="info" title="Reading your records…">
          Looking through your documents for the most relevant passages, then writing the answer.
        </Alert>
      )}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void ask()} />}

      {!loading && result && (
        <div className="space-y-3">
          <h2 className="section-title">Answer</h2>
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
