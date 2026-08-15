import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { ErrorState } from "../components/ErrorState";
import { Card, CardBody, CardHeader } from "../components/Card";
import { DocumentViewer } from "../components/DocumentViewer";
import { QAResultCard } from "../components/QAResultCard";
import { Spinner } from "../components/Spinner";
import { ChatIcon, SendIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useCopy } from "../i18n";
import type { QAResponse, QASource, Timeline, Visit } from "../types/api";
import { findVisitForSource } from "../utils/sources";

/** Mirrors MAX_QUESTION_LENGTH in backend/api.py. */
const MAX_QUESTION_LENGTH = 2000;
const DEFAULT_TOP_K = 8;
const TOP_K_STORAGE_KEY = "medimind.ask-ai.topk.v1";
/** Warn only near the limit; a counter on every keystroke is noise. */
const COUNTER_VISIBLE_FROM = MAX_QUESTION_LENGTH - 200;

const SUGGESTIONS = [
  "What medications am I currently taking?",
  "What were my most recent lab results?",
  "Are there any allergies documented in my records?",
  "What did my doctor note at my last visit?",
];

function readStoredTopK(): number {
  const stored = Number(localStorage.getItem(TOP_K_STORAGE_KEY));
  return Number.isFinite(stored) && stored >= 1 && stored <= 20 ? stored : DEFAULT_TOP_K;
}

export function QAPage() {
  const copy = useCopy();
  const { credentials } = useAuth();
  const [question, setQuestion] = useState("");
  const [askedQuestion, setAskedQuestion] = useState("");
  const [topK, setTopK] = useState(readStoredTopK);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QAResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [openSource, setOpenSource] = useState<{ source: QASource; visit: Visit | null } | null>(
    null
  );

  const timelineRef = useRef<Timeline | null>(null);
  // A ref, not state: it must block a second submit within the same tick,
  // before React has re-rendered with loading=true.
  const inFlightRef = useRef(false);
  const requestRef = useRef<AbortController | null>(null);
  const answerRef = useRef<HTMLDivElement | null>(null);
  const sourceRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

  // Loaded lazily so a citation can resolve to its document. A failure here
  // must never break asking questions — citations just stay non-clickable.
  useEffect(() => {
    let cancelled = false;
    api
      .getTimeline(credentials)
      .then((timeline) => {
        if (!cancelled) timelineRef.current = timeline;
      })
      .catch(() => {
        if (!cancelled) timelineRef.current = null;
      });
    return () => {
      cancelled = true;
    };
  }, [credentials]);

  useEffect(() => {
    localStorage.setItem(TOP_K_STORAGE_KEY, String(topK));
  }, [topK]);

  const trimmedQuestion = question.trim();
  const isTooLong = question.length > MAX_QUESTION_LENGTH;
  const canSubmit = Boolean(trimmedQuestion) && !isTooLong && !loading;

  const ask = useCallback(
    async (raw?: string) => {
      const text = (raw ?? question).trim();

      if (!text) {
        setValidationError(copy.askAi.emptyQuestionError);
        inputRef.current?.focus();
        return;
      }
      if (text.length > MAX_QUESTION_LENGTH) {
        setValidationError(copy.askAi.tooLongError(MAX_QUESTION_LENGTH));
        inputRef.current?.focus();
        return;
      }
      // Guards the Ask→Ask→Ask double-click: one request, not three.
      if (inFlightRef.current) return;

      inFlightRef.current = true;
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;

      setValidationError(null);
      setLoading(true);
      setError(null);
      setResult(null);
      setOpenSource(null);
      setQuestion(text);
      setAskedQuestion(text);

      try {
        const response = await api.ask(credentials, text, topK, controller.signal);
        if (controller.signal.aborted) return;
        setResult(response);
        window.setTimeout(
          () => answerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
          100
        );
      } catch (requestError) {
        if (controller.signal.aborted) return;
        setError(requestError);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
        inFlightRef.current = false;
      }
    },
    [copy.askAi, credentials, question, topK]
  );

  function handleOpenSource(source: QASource) {
    const visit = findVisitForSource(timelineRef.current, source);
    setOpenSource({ source, visit });
    window.setTimeout(
      () => sourceRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
      100
    );
  }

  function clearAll() {
    requestRef.current?.abort();
    inFlightRef.current = false;
    setQuestion("");
    setAskedQuestion("");
    setResult(null);
    setError(null);
    setValidationError(null);
    setOpenSource(null);
    setLoading(false);
    inputRef.current?.focus();
  }

  const remaining = MAX_QUESTION_LENGTH - question.length;
  const showCounter = question.length >= COUNTER_VISIBLE_FROM;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="page-title">{copy.askAi.title}</h1>
        <p className="secondary-text mt-2 max-w-2xl">{copy.askAi.subtitle}</p>
      </header>

      <Card>
        <CardHeader
          title={copy.askAi.questionLabel}
          description={copy.askAi.groundedNote}
          icon={<ChatIcon className="h-5 w-5" />}
        />
        <CardBody className="space-y-4">
          <div>
            <label htmlFor="ask-question" className="sr-only">
              {copy.askAi.questionLabel}
            </label>
            <textarea
              id="ask-question"
              ref={inputRef}
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value);
                if (validationError) setValidationError(null);
              }}
              onKeyDown={(event) => {
                // Enter asks; Shift+Enter and the IME composition buffer must not.
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  void ask();
                }
              }}
              rows={3}
              placeholder={copy.askAi.placeholder}
              aria-invalid={Boolean(validationError) || isTooLong}
              aria-describedby="ask-question-hint ask-question-error"
              className="block w-full resize-y rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-slate-900 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-100"
            />

            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
              <p id="ask-question-hint" className="text-xs text-slate-400">
                {copy.askAi.submitHint}
              </p>
              {showCounter && (
                <p
                  className={remaining < 0 ? "text-xs font-medium text-red-600" : "text-xs text-slate-400"}
                >
                  {copy.askAi.charactersRemaining(remaining)}
                </p>
              )}
            </div>

            {/* Assertive: the user just pressed Ask and nothing happened. */}
            <p id="ask-question-error" role="alert" aria-live="assertive">
              {validationError && (
                <span className="mt-1 block text-xs font-medium text-red-600">
                  {validationError}
                </span>
              )}
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void ask()}
              disabled={!canSubmit}
              aria-busy={loading}
              className="inline-flex min-h-[44px] flex-1 items-center justify-center gap-2 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60 sm:flex-none"
            >
              {loading ? (
                <Spinner className="h-4 w-4" />
              ) : (
                <SendIcon className="h-4 w-4" aria-hidden="true" />
              )}
              {loading ? copy.askAi.asking : copy.askAi.ask}
            </button>
            {(result || error || question) && !loading && (
              <button
                type="button"
                onClick={clearAll}
                className="btn-secondary min-h-[44px] px-4 py-2 text-sm"
              >
                {copy.askAi.clear}
              </button>
            )}
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              {copy.askAi.suggestionsTitle}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">{copy.askAi.suggestionsHint}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    // Fill the box and let the user edit — don't auto-send.
                    setQuestion(suggestion);
                    setValidationError(null);
                    inputRef.current?.focus();
                  }}
                  disabled={loading}
                  className="min-h-[36px] rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-left text-xs text-slate-600 transition hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-50"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>

          <details className="rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2">
            <summary className="cursor-pointer text-xs font-semibold text-slate-600">
              {copy.askAi.advancedTitle}
            </summary>
            <div className="mt-3">
              <label htmlFor="ask-topk" className="block text-xs font-semibold text-slate-700">
                {copy.askAi.depthLabel}
              </label>
              <div className="mt-1.5 flex items-center gap-3">
                <input
                  id="ask-topk"
                  type="range"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(event) => setTopK(parseInt(event.target.value, 10))}
                  aria-valuetext={copy.askAi.depthValue(topK)}
                  aria-describedby="ask-topk-help"
                  className="h-2 w-40 max-w-full cursor-pointer"
                />
                <span className="text-xs font-semibold text-slate-700">
                  {copy.askAi.depthValue(topK)}
                </span>
              </div>
              <p id="ask-topk-help" className="mt-1.5 text-xs text-slate-500">
                {copy.askAi.depthHelp}
              </p>
            </div>
          </details>
        </CardBody>
      </Card>

      {loading && (
        <Alert variant="info" title={copy.askAi.loadingTitle}>
          {copy.askAi.loadingBody}
        </Alert>
      )}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void ask(askedQuestion)} />}

      {!loading && result && (
        <div ref={answerRef} className="scroll-mt-8 space-y-3">
          <h2 className="section-title">{copy.askAi.answerTitle}</h2>
          <QAResultCard
            result={result}
            question={askedQuestion}
            onOpenSource={timelineRef.current ? handleOpenSource : undefined}
          />
        </div>
      )}

      {openSource && (
        <div ref={sourceRef} className="scroll-mt-8 space-y-3">
          <h2 className="section-title">{openSource.source.source_file}</h2>
          {openSource.visit ? (
            <DocumentViewer visit={openSource.visit} onClose={() => setOpenSource(null)} />
          ) : (
            <Alert variant="info" title="That document isn't available to open">
              This answer cites {openSource.source.source_file}, but the document isn't in your
              records list right now. It may have been removed since the answer was written.
            </Alert>
          )}
        </div>
      )}

      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-center">
        <p className="text-sm text-slate-600">{copy.askAi.singleQuestionNote}</p>
        <p className="secondary-text mt-2">
          {copy.askAi.conversationPrompt}{" "}
          <Link to="/conversations" className="font-medium text-brand-600 hover:text-brand-700">
            {copy.askAi.conversationLink} →
          </Link>
        </p>
      </div>
    </div>
  );
}
