import { useState } from "react";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { MedicalDisclaimer } from "../components/MedicalDisclaimer";
import { SendIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import type { SymptomAnalysis } from "../types/api";

export function SymptomCheckerPage() {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [symptom, setSymptom] = useState("");
  const [duration, setDuration] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SymptomAnalysis | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!symptom.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await api.analyseSymptom(credentials, symptom.trim(), duration.trim() || undefined));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="min-w-0">
        <h1 className="page-title">{t("symptoms.title")}</h1>
        <p className="secondary-text mt-2 max-w-2xl">{t("symptoms.subtitle")}</p>
      </div>

      <Card>
        <CardBody>
          <form onSubmit={run} className="space-y-3">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Describe a symptom in your own words</span>
              <textarea
                value={symptom}
                onChange={(e) => setSymptom(e.target.value)}
                placeholder="e.g. I've been dizzy and had a dry cough for 3 days"
                rows={3}
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Duration (optional)</span>
              <input
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                placeholder="3 days"
                className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm sm:max-w-xs"
              />
            </label>
            <button
              type="submit"
              disabled={loading || !symptom.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50"
            >
              <SendIcon className="h-4 w-4" />
              {loading ? "Analysing…" : "Cross-reference my record"}
            </button>
          </form>
        </CardBody>
      </Card>

      {error && (
        <Card>
          <CardBody>
            <p className="text-sm text-red-600">{error}</p>
          </CardBody>
        </Card>
      )}

      {result && (
        <Card>
          <CardBody className="space-y-3">
            {result.analysed ? (
              <>
                <div className="flex flex-wrap gap-2">
                  {result.matched_symptoms?.map((s) => (
                    <span key={s} className="rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700">
                      {s}
                    </span>
                  ))}
                </div>
                <p className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                  {result.summary}
                </p>
                {result.findings?.some((f) => f.relevant_medications_on_record.length === 0 &&
                  f.relevant_abnormal_labs.length === 0) && (
                  <p className="text-xs text-slate-400">
                    No medications or abnormal labs on your record matched this symptom.
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-slate-600">{result.note}</p>
            )}
          </CardBody>
        </Card>
      )}

      <MedicalDisclaimer />
    </div>
  );
}
