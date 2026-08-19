import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Alert } from "../components/Alert";
import { Card, CardBody, CardHeader } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { ChartIcon, FileIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { AnalysisLogRecord } from "../types/api";
import { formatConfidence, formatDate } from "../utils/format";

export function AnalysesPage() {
  const { credentials } = useAuth();
  const [records, setRecords] = useState<AnalysisLogRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listAnalyses(credentials);
      setRecords(data.analyses || []);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">AI analysis logs</h1>
        <p className="secondary-text mt-2">
          Patient-scoped records of document extraction summaries and saved Q&A answers. These are audit/display logs, not model reasoning.
        </p>
      </div>

      <Alert variant="info" title="Medical safety note">
        AI-assisted information is for understanding uploaded records and should be verified with a qualified healthcare professional. MediMind does not expose chain-of-thought reasoning.
      </Alert>

      {loading && <LoadingState label="Loading analysis logs…" />}
      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}
      {!loading && !error && records.length === 0 && (
        <Card>
          <CardBody>
            <EmptyState title="No analysis logs yet" description="Upload documents or ask questions to populate this audit view." />
            <div className="mt-4 text-center">
              <Link to="/upload" className="btn-primary">Upload documents</Link>
            </div>
          </CardBody>
        </Card>
      )}
      {!loading && !error && records.length > 0 && (
        <div className="space-y-3">
          {records.map((record) => (
            record.analysis_type === "qa" ? <QaAnalysisCard key={record.id} record={record} /> : <ExtractionAnalysisCard key={record.id} record={record} />
          ))}
        </div>
      )}
    </div>
  );
}

function ExtractionAnalysisCard({ record }: { record: AnalysisLogRecord }) {
  const result = record.result || {};
  const counts = (typeof result.persisted_counts === "object" && result.persisted_counts !== null ? result.persisted_counts : {}) as Record<string, number>;
  const source = String(result.source_file || "uploaded document");
  const docId = String(result.document_id || "");
  return (
    <Card>
      <CardHeader title="Document extraction" description={`${source}${record.created_at ? ` · ${formatDate(record.created_at)}` : ""}`} icon={<FileIcon className="h-5 w-5" />} />
      <CardBody className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone="brand">{String(result.document_type_detected || "document")}</StatusBadge>
          {typeof record.confidence === "number" && <StatusBadge tone="success">{formatConfidence(record.confidence)}</StatusBadge>}
        </div>
        {record.summary && <p className="text-sm leading-relaxed text-slate-700">{record.summary}</p>}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {[
            ["Meds", counts.medications],
            ["Labs", counts.lab_results],
            ["Findings", counts.findings],
            ["Events", counts.events],
            ["Allergies", counts.allergies],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-center">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
              <p className="text-lg font-bold text-slate-900">{Number(value || 0)}</p>
            </div>
          ))}
        </div>
        {docId && <Link to={`/documents?document=${encodeURIComponent(docId)}`} className="text-sm font-semibold text-brand-700 hover:underline">Open source document →</Link>}
      </CardBody>
    </Card>
  );
}

function QaAnalysisCard({ record }: { record: AnalysisLogRecord }) {
  const result = record.result || {};
  const paragraphs = Array.isArray(result.paragraphs) ? result.paragraphs.map(String) : [];
  const citations = Array.isArray(result.citations) ? result.citations as Array<Record<string, unknown>> : [];
  return (
    <Card>
      <CardHeader title="Medical Q&A" description={record.created_at ? formatDate(record.created_at) : "Saved assistant answer"} icon={<ChartIcon className="h-5 w-5" />} />
      <CardBody className="space-y-3">
        {paragraphs.length > 0 ? paragraphs.map((text, index) => <p key={index} className="text-sm leading-relaxed text-slate-700">{text}</p>) : <p className="text-sm text-slate-500">No answer text stored.</p>}
        {citations.length > 0 && (
          <div className="space-y-2 rounded-lg bg-slate-50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Citations</p>
            {citations.map((citation, index) => (
              <p key={index} className="text-xs text-slate-700">
                <span className="font-semibold">{String(citation.documentTitle || citation.document_title || "Source")}</span>
                {citation.quote ? ` — “${String(citation.quote)}”` : ""}
              </p>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
