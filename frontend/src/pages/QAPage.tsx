import { useState } from "react";
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
  "What medications am I currently taking?",
  "What were my most recent lab results?",
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
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Ask a question</h1>
        <p className="mt-1 text-sm text-slate-500">
          Single-shot retrieval-augmented Q&amp;A over your indexed medical
          timeline. There is no server-side conversation state — each question
          is answered independently. Use Conversations for multi-turn follow-ups.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Question"
          description="Grounded only in your extracted records; the model never diagnoses."
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

          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-slate-500">Retrieved chunks:</label>
            <input
              type="range"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(parseInt(e.target.value, 10))}
              className="w-32"
            />
            <span className="text-xs font-medium text-slate-700">{topK}</span>
          </div>

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
        <Alert variant="info" title="Retrieving and answering">
          The question is being embedded, matched against your indexed record,
          and answered strictly from the retrieved chunks.
        </Alert>
      )}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void ask()} />}

      {!loading && result && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Answer
          </h2>
          <QAResultCard result={result} />
        </div>
      )}
    </div>
  );
}
