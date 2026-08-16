import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { AlertIcon, CheckIcon, FileIcon, ReminderIcon, UploadIcon } from "../components/icons";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import type { FollowUpPlan, FollowUpTask } from "../types/api";
import { formatDate } from "../utils/format";

type TaskState = Record<string, { completed: boolean; reminderDate: string }>;
type View = "open" | "completed";

function readState(key: string): TaskState {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) || "{}");
    return parsed && typeof parsed === "object" ? (parsed as TaskState) : {};
  } catch {
    return {};
  }
}

export function FollowUpPage() {
  const { credentials } = useAuth();
  const storageKey = `medimind.follow-up.v1.${credentials.userId}`;
  const [plan, setPlan] = useState<FollowUpPlan | null>(null);
  const [taskState, setTaskState] = useState<TaskState>(() => readState(storageKey));
  const [stateWorkspace, setStateWorkspace] = useState(storageKey);
  const [view, setView] = useState<View>("open");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPlan(await api.getFollowUpPlan(credentials));
      setTaskState(readState(storageKey));
      setStateWorkspace(storageKey);
    } catch (err) {
      setPlan(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials, storageKey]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (stateWorkspace === storageKey) {
      localStorage.setItem(storageKey, JSON.stringify(taskState));
    }
  }, [stateWorkspace, storageKey, taskState]);

  const completedCount = plan?.tasks.filter((task) => taskState[task.id]?.completed).length || 0;
  const openHighCount = plan?.tasks.filter((task) => task.priority === "high" && !taskState[task.id]?.completed).length || 0;
  const visibleTasks = useMemo(
    () => plan?.tasks.filter((task) => Boolean(taskState[task.id]?.completed) === (view === "completed")) || [],
    [plan, taskState, view]
  );

  function updateTask(taskId: string, patch: Partial<TaskState[string]>) {
    setTaskState((previous) => ({
      ...previous,
      [taskId]: {
        completed: previous[taskId]?.completed || false,
        reminderDate: previous[taskId]?.reminderDate || "",
        ...patch,
      },
    }));
  }

  return (
    <div className="space-y-6">
      <header>
        <div className="flex items-center gap-2 text-sm font-semibold text-brand-700"><ReminderIcon className="h-4 w-4" /> Follow-up intelligence</div>
        <h1 className="page-title mt-1">My Action Center</h1>
        <p className="secondary-text mt-2 max-w-2xl">
          One grounded queue for facts to verify and questions to take to a clinician. You control completion and reminder dates.
        </p>
      </header>

      {loading && <LoadingState label="Building your action queue" description="Combining safety checks, trends, recent changes, and record-integrity findings." />}
      {!loading && error !== null && <FollowUpError error={error} onRetry={() => void load()} />}

      {!loading && plan && (
        <>
          <div className="grid gap-4 sm:grid-cols-4">
            <Metric label="Open" value={plan.summary.total - completedCount} tone="neutral" />
            <Metric label="Completed" value={completedCount} tone="success" />
            <Metric label="Review first" value={openHighCount} tone={openHighCount ? "warning" : "neutral"} />
            <Metric label="Record checks" value={plan.summary.record_verification} tone="neutral" />
          </div>

          <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-5 text-sm leading-relaxed text-sky-900">
            <p className="font-semibold">You set the schedule</p>
            <p className="mt-1">{plan.note} Reminder dates are saved only in this browser workspace.</p>
          </div>

          <div className="flex items-center justify-between gap-4 border-b border-slate-200">
            <div className="flex gap-1">
              <Tab active={view === "open"} onClick={() => setView("open")}>Open ({plan.summary.total - completedCount})</Tab>
              <Tab active={view === "completed"} onClick={() => setView("completed")}>Completed ({completedCount})</Tab>
            </div>
            <button type="button" onClick={() => void load()} className="mb-2 text-sm font-semibold text-brand-700 hover:text-brand-900">Refresh findings</button>
          </div>

          {visibleTasks.length > 0 ? (
            <div className="space-y-4">
              {visibleTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  state={taskState[task.id] || { completed: false, reminderDate: "" }}
                  onChange={(patch) => updateTask(task.id, patch)}
                />
              ))}
            </div>
          ) : (
            <Card>
              <CardBody className="py-14 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-700"><CheckIcon className="h-7 w-7" /></div>
                <h2 className="mt-4 section-title">{view === "open" ? "Your queue is clear" : "No completed actions yet"}</h2>
                <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
                  {view === "open" ? "All record-backed follow-up items have been marked complete." : "Completed items will remain here so you can review or reopen them."}
                </p>
              </CardBody>
            </Card>
          )}

          <p className="text-xs leading-relaxed text-slate-500">{plan.method}</p>
        </>
      )}
    </div>
  );
}

function TaskCard({ task, state, onChange }: { task: FollowUpTask; state: TaskState[string]; onChange: (patch: Partial<TaskState[string]>) => void }) {
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const overdue = Boolean(state.reminderDate) && !state.completed && state.reminderDate < todayLocal();
  const style = priorityStyle(task.priority);

  return (
    <article className={`overflow-hidden rounded-2xl border bg-white shadow-sm ${state.completed ? "border-emerald-200 opacity-80" : style.border}`}>
      <div className="p-5 sm:p-6">
        <div className="flex items-start gap-4">
          <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${state.completed ? "bg-emerald-50 text-emerald-700" : style.icon}`}>
            {state.completed ? <CheckIcon className="h-5 w-5" /> : task.kind === "record_verification" ? <FileIcon className="h-5 w-5" /> : <AlertIcon className="h-5 w-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${style.badge}`}>{task.priority} priority</span>
              <span className="text-xs font-medium text-slate-400">{task.category}</span>
              {overdue && <span className="rounded-full bg-red-50 px-2.5 py-1 text-[11px] font-bold text-red-700 ring-1 ring-red-200">Your reminder passed</span>}
            </div>
            <h2 className={`mt-2 card-title ${state.completed ? "line-through decoration-slate-400" : ""}`}>{task.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-slate-700">{task.action}</p>
            <p className="mt-2 text-sm leading-relaxed text-slate-500">{task.reason}</p>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-amber-100 bg-amber-50/60 px-4 py-3 text-xs leading-relaxed text-amber-900">
          <span className="font-bold">Timing guardrail: </span>{task.timing_guardrail}
        </div>

        <div className="mt-5 flex flex-col gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-4 sm:flex-row sm:items-end">
          <label className="min-w-0 flex-1 text-sm font-semibold text-slate-700">
            My reminder date <span className="font-normal text-slate-400">(optional)</span>
            <input
              type="date"
              value={state.reminderDate}
              onChange={(event) => onChange({ reminderDate: event.target.value })}
              className="mt-1.5 block min-h-[44px] w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-normal focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100"
            />
          </label>
          {state.reminderDate && (
            <button type="button" onClick={() => downloadCalendar(task, state.reminderDate)} className="btn-secondary whitespace-nowrap px-4 py-2 text-sm">
              Add to calendar
            </button>
          )}
          <button type="button" onClick={() => onChange({ completed: !state.completed })} className={state.completed ? "btn-secondary whitespace-nowrap px-4 py-2 text-sm" : "btn-primary whitespace-nowrap px-4 py-2 text-sm"}>
            <CheckIcon className="h-4 w-4" /> {state.completed ? "Reopen" : "Mark complete"}
          </button>
        </div>
      </div>

      {task.evidence.length > 0 && (
        <div className="border-t border-slate-100 bg-slate-50/70 px-5 py-3 text-xs">
          <button type="button" onClick={() => setEvidenceOpen((value) => !value)} className="font-semibold text-brand-700">
            {evidenceOpen ? "Hide" : "Show"} supporting records ({task.evidence.length})
          </button>
          {evidenceOpen && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-slate-500">
              {task.evidence.map((source, index) => source.document_url ? (
                <a key={index} href={source.document_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-700 underline decoration-brand-300 underline-offset-2"><FileIcon className="h-3 w-3" />{source.source_file || formatDate(source.date)}</a>
              ) : <span key={index} className="inline-flex items-center gap-1"><FileIcon className="h-3 w-3" />{source.source_file || formatDate(source.date)}</span>)}
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" onClick={onClick} className={`border-b-2 px-4 py-3 text-sm font-semibold transition ${active ? "border-brand-600 text-brand-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>{children}</button>;
}

function Metric({ label, value, tone }: { label: string; value: number; tone: "neutral" | "warning" | "success" }) {
  const color = tone === "warning" ? "border-amber-200 text-amber-700" : tone === "success" ? "border-emerald-200 text-emerald-700" : "border-slate-200 text-slate-900";
  return <div className={`rounded-2xl border bg-white p-5 shadow-sm ${color}`}><p className="text-sm font-medium text-slate-500">{label}</p><p className="mt-1 text-3xl font-bold">{value}</p></div>;
}

function FollowUpError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = error && typeof error === "object" && "status" in error ? (error as { status?: number }).status : undefined;
  if (status === 404) return <Card><CardBody className="py-14 text-center"><ReminderIcon className="mx-auto h-10 w-10 text-brand-600" /><h2 className="mt-4 section-title">Upload records to build an action queue</h2><p className="mx-auto mt-2 max-w-md text-sm text-slate-500">Follow-up items must be grounded in your own records.</p><Link to="/upload" className="btn-primary mt-5"><UploadIcon className="h-5 w-5" /> Upload records</Link></CardBody></Card>;
  return <ErrorState error={error} onRetry={onRetry} />;
}

function priorityStyle(priority: FollowUpTask["priority"]) {
  if (priority === "high") return { border: "border-amber-200", icon: "bg-amber-50 text-amber-700", badge: "bg-amber-100 text-amber-800" };
  if (priority === "medium") return { border: "border-sky-200", icon: "bg-sky-50 text-sky-700", badge: "bg-sky-100 text-sky-800" };
  return { border: "border-slate-200", icon: "bg-slate-100 text-slate-600", badge: "bg-slate-100 text-slate-700" };
}

function todayLocal() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function downloadCalendar(task: FollowUpTask, date: string) {
  const start = date.replace(/-/g, "");
  const endDate = new Date(`${date}T12:00:00`);
  endDate.setDate(endDate.getDate() + 1);
  const end = `${endDate.getFullYear()}${String(endDate.getMonth() + 1).padStart(2, "0")}${String(endDate.getDate()).padStart(2, "0")}`;
  const escape = (value: string) => value.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/,/g, "\\,").replace(/;/g, "\\;");
  const content = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MediMind//Follow-up//EN", "BEGIN:VEVENT",
    `UID:${task.id}@medimind`, `DTSTART;VALUE=DATE:${start}`, `DTEND;VALUE=DATE:${end}`,
    `SUMMARY:${escape(`MediMind follow-up: ${task.title}`)}`,
    `DESCRIPTION:${escape(`${task.action}\n\n${task.timing_guardrail}`)}`,
    "END:VEVENT", "END:VCALENDAR",
  ].join("\r\n");
  const url = URL.createObjectURL(new Blob([content], { type: "text/calendar;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `medimind-follow-up-${date}.ics`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
