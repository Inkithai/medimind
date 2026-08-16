import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Figure, Flow, Node, TechChip } from "../components/about/Diagram";
import {
  AppointmentIcon,
  BeakerIcon,
  ChangesIcon,
  ChatIcon,
  CheckIcon,
  FileIcon,
  IntegrityIcon,
  LocationIcon,
  PillIcon,
  ReminderIcon,
  ShieldIcon,
} from "../components/icons";
import { useI18n } from "../i18n/I18nContext";
import { classNames } from "../utils/format";

/**
 * About / technical overview.
 *
 * Reachable from the sidebar footer, deliberately outside the nine
 * patient-workflow items. Every visible string comes from the `about.*`
 * i18n namespace (en/si/ta), so this file holds layout only.
 *
 * Content is verified against the repository — endpoints against
 * backend/api.py, pipeline stages against medical_extractor.py and
 * retrieval.py. A backend test asserts the documented routes exist.
 */
export function AboutPage() {
  const { t } = useI18n();

  const sections = [
    { id: "overview", title: t("about.overviewTitle") },
    { id: "features", title: t("about.featuresTitle") },
    { id: "architecture", title: t("about.archTitle") },
    { id: "pipeline", title: t("about.pipeTitle") },
    { id: "data-flow", title: t("about.flowTitle") },
    { id: "security", title: t("about.secTitle") },
    { id: "api", title: t("about.apiTitle") },
  ];
  const activeId = useActiveSection(sections.map((section) => section.id));

  return (
    <div className="space-y-8">
      <header>
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
          <InfoIcon className="h-3.5 w-3.5" /> {t("about.eyebrow")}
        </div>
        <h1 className="page-title">{t("about.title")}</h1>
        <p className="mt-3 max-w-3xl text-base leading-relaxed text-slate-600">
          {t("about.lede")}
        </p>
        <Link to="/dashboard" className="btn-secondary mt-5 inline-flex">
          {t("about.backToDashboard")}
        </Link>
      </header>

      <div className="lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-10">
        <TableOfContents sections={sections} activeId={activeId} label={t("about.onThisPage")} />

        {/* min-w-0 stops a long endpoint path widening the grid column. */}
        <div className="min-w-0 space-y-10">
          <Overview />
          <Features />
          <Architecture />
          <Pipeline />
          <DataFlow />
          <Security />
          <ApiOverview />
          <Disclaimer />
        </div>
      </div>
    </div>
  );
}

/** Tracks which section is in view, to highlight the contents list. */
function useActiveSection(ids: string[]): string | null {
  const [activeId, setActiveId] = useState<string | null>(ids[0] ?? null);
  const idsRef = useRef(ids);
  idsRef.current = ids;

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveId(visible[0].target.id);
      },
      { rootMargin: "-80px 0px -70% 0px", threshold: 0 }
    );
    for (const id of idsRef.current) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, []);

  return activeId;
}

function TableOfContents({
  sections,
  activeId,
  label,
}: {
  sections: Array<{ id: string; title: string }>;
  activeId: string | null;
  label: string;
}) {
  return (
    <nav aria-label={label} className="mb-8 lg:sticky lg:top-8 lg:mb-0 lg:self-start">
      <p className="px-3 text-xs font-bold uppercase tracking-wider text-slate-400">{label}</p>
      <ol className="mt-2 space-y-0.5">
        {sections.map((section, index) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              aria-current={activeId === section.id ? "true" : undefined}
              className={classNames(
                "flex min-h-[40px] items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                activeId === section.id
                  ? "bg-brand-50 font-semibold text-brand-700"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
              )}
            >
              <span className="w-4 shrink-0 text-xs tabular-nums text-slate-400">{index + 1}</span>
              <span className="min-w-0 break-words">{section.title}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function Section({
  id,
  title,
  subtitle,
  children,
}: {
  id: string;
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className="scroll-mt-8">
      <h2 id={`${id}-heading`} className="section-title">
        {title}
      </h2>
      {subtitle && <p className="mt-1.5 max-w-3xl text-sm text-slate-500">{subtitle}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={classNames(
        "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6",
        className
      )}
    >
      {children}
    </div>
  );
}

function Overview() {
  const { t } = useI18n();
  const principles = ["p1", "p2", "p3", "p4", "p5"];
  return (
    <Section id="overview" title={t("about.overviewTitle")}>
      <Panel>
        <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
          {t("about.overviewSubtitle")}
        </h3>
        <ul className="mt-4 grid gap-4 sm:grid-cols-2">
          {principles.map((key) => (
            <li key={key} className="flex gap-3">
              <span
                className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600"
                aria-hidden="true"
              >
                <CheckIcon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">{t(`about.${key}Title`)}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-slate-600">
                  {t(`about.${key}Body`)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </Section>
  );
}

const FEATURES: Array<{
  key: string;
  Icon: (p: { className?: string }) => ReactNode;
  tone: string;
}> = [
  { key: "f1", Icon: FileIcon, tone: "bg-sky-50 text-sky-600" },
  { key: "f2", Icon: PillIcon, tone: "bg-emerald-50 text-emerald-600" },
  { key: "f3", Icon: BeakerIcon, tone: "bg-violet-50 text-violet-600" },
  { key: "f4", Icon: ShieldIcon, tone: "bg-amber-50 text-amber-600" },
  { key: "f5", Icon: ChatIcon, tone: "bg-brand-50 text-brand-600" },
  { key: "f6", Icon: LocationIcon, tone: "bg-rose-50 text-rose-600" },
  { key: "f7", Icon: ChangesIcon, tone: "bg-indigo-50 text-indigo-700" },
  { key: "f8", Icon: IntegrityIcon, tone: "bg-orange-50 text-orange-700" },
  { key: "f9", Icon: AppointmentIcon, tone: "bg-cyan-50 text-cyan-800" },
  { key: "f10", Icon: ReminderIcon, tone: "bg-fuchsia-50 text-fuchsia-700" },
];

function Features() {
  const { t } = useI18n();
  return (
    <Section id="features" title={t("about.featuresTitle")} subtitle={t("about.featuresSubtitle")}>
      <div className="grid gap-4 md:grid-cols-2">
        {FEATURES.map(({ key, Icon, tone }) => (
          <article
            key={key}
            className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <span
              className={classNames("flex h-10 w-10 items-center justify-center rounded-xl", tone)}
              aria-hidden="true"
            >
              <Icon className="h-5 w-5" />
            </span>
            <h3 className="mt-3.5 text-base font-bold text-slate-900">{t(`about.${key}Title`)}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{t(`about.${key}Body`)}</p>
          </article>
        ))}
      </div>
    </Section>
  );
}

const LAYERS = [
  { key: "l1", tech: "React 18 · TypeScript · Vite · Tailwind · Leaflet", tone: "brand" },
  { key: "l2", tech: "FastAPI · Uvicorn · JWT (HS256)", tone: "sky" },
  { key: "l3", tech: "pdfplumber · PyMuPDF · Pillow · vision model", tone: "violet" },
  { key: "l4", tech: "Supabase (PostgreSQL) · Cloudinary", tone: "emerald" },
  { key: "l5", tech: "Chroma / Supabase chunks · MiniLM or OpenAI embeddings", tone: "amber" },
  { key: "l6", tech: "OpenAI-compatible providers (Groq / Gemini)", tone: "rose" },
  { key: "l7", tech: "Server-side citation validation", tone: "slate" },
] as const;

const TONE_CLASSES: Record<string, string> = {
  brand: "border-brand-200 bg-brand-50 text-brand-900",
  sky: "border-sky-200 bg-sky-50 text-sky-900",
  violet: "border-violet-200 bg-violet-50 text-violet-900",
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  rose: "border-rose-200 bg-rose-50 text-rose-900",
  slate: "border-slate-200 bg-slate-50 text-slate-800",
};

function Architecture() {
  const { t } = useI18n();
  return (
    <Section id="architecture" title={t("about.archTitle")} subtitle={t("about.archSubtitle")}>
      <Panel>
        <Figure label={t("about.archDiagram")}>
          <Flow>
            {LAYERS.map((layer) => (
              <div
                key={layer.key}
                className={classNames("rounded-xl border p-4", TONE_CLASSES[layer.tone])}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <p className="text-sm font-bold">{t(`about.${layer.key}Name`)}</p>
                  <p className="font-mono text-[11px] leading-relaxed opacity-75">{layer.tech}</p>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed opacity-90">
                  {t(`about.${layer.key}Body`)}
                </p>
              </div>
            ))}
          </Flow>
        </Figure>
      </Panel>
    </Section>
  );
}

function Pipeline() {
  const { t } = useI18n();
  const ingest = ["s1", "s2", "s3", "s4", "s5", "s6"];
  const answer = ["s7", "s8", "s9"];
  return (
    <Section id="pipeline" title={t("about.pipeTitle")} subtitle={t("about.pipeSubtitle")}>
      <Panel>
        <Figure label={t("about.pipeDiagram")}>
          <div className="grid gap-6 lg:grid-cols-2">
            <PipelineColumn title={t("about.pipeIngest")} keys={ingest} tone="sky" startAt={1} />
            <PipelineColumn
              title={t("about.pipeAnswer")}
              keys={answer}
              tone="brand"
              startAt={ingest.length + 1}
            />
          </div>
        </Figure>

        <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h4 className="text-sm font-bold text-slate-900">{t("about.selfHealTitle")}</h4>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">{t("about.selfHealBody")}</p>
        </div>
      </Panel>
    </Section>
  );
}

function PipelineColumn({
  title,
  keys,
  tone,
  startAt,
}: {
  title: string;
  keys: string[];
  tone: "sky" | "brand";
  startAt: number;
}) {
  const { t } = useI18n();
  return (
    <div>
      <h4
        className={classNames(
          "mb-3 inline-block rounded-full px-2.5 py-1 text-xs font-bold uppercase tracking-wider",
          tone === "sky" ? "bg-sky-100 text-sky-800" : "bg-brand-100 text-brand-800"
        )}
      >
        {title}
      </h4>
      <Flow>
        {keys.map((key, index) => (
          <Node
            key={key}
            tone={tone}
            title={`${startAt + index}. ${t(`about.${key}Title`)}`}
            subtitle={t(`about.${key}Body`)}
          />
        ))}
      </Flow>
    </div>
  );
}

const CONSUMER_KEYS = [
  "nav.dashboard",
  "nav.documents",
  "nav.medicines",
  "nav.labs",
  "nav.history",
  "nav.changes",
  "nav.appointmentPrep",
  "nav.actionCenter",
  "nav.recordCheck",
  "nav.safety",
  "nav.ask",
];

function DataFlow() {
  const { t } = useI18n();
  return (
    <Section id="data-flow" title={t("about.flowTitle")} subtitle={t("about.flowSubtitle")}>
      <Panel>
        <Figure label={t("about.flowDiagram")}>
          <Flow>
            <Node tone="brand" title={t("about.flowYouTitle")} subtitle={t("about.flowYouBody")} />
            <Node tone="sky" title={t("about.flowStoreTitle")} subtitle={t("about.flowStoreBody")} />
            <div>
              <Node
                tone="emerald"
                title={t("about.flowUseTitle")}
                subtitle={t("about.flowUseBody")}
              />
              {/* Fans out to each feature: a grid on desktop, a stack on mobile. */}
              <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {CONSUMER_KEYS.map((key) => (
                  <li
                    key={key}
                    className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-800"
                  >
                    {t(key)}
                  </li>
                ))}
              </ul>
            </div>
          </Flow>
        </Figure>

        <div className="mt-6 rounded-xl border border-brand-200 bg-brand-50 p-4">
          <h4 className="text-sm font-bold text-brand-900">{t("about.groundingTitle")}</h4>
          <p className="mt-1 text-sm leading-relaxed text-brand-900/80">
            {t("about.groundingBody")}
          </p>
        </div>
      </Panel>
    </Section>
  );
}

function Security() {
  const { t } = useI18n();
  const implemented = ["i1", "i2", "i3", "i4", "i5", "i6"];
  const notClaimed = ["n1", "n2", "n3", "n4"];
  const planned = ["pl1", "pl2", "pl3"];
  return (
    <Section id="security" title={t("about.secTitle")} subtitle={t("about.secSubtitle")}>
      <div className="space-y-4">
        <Panel>
          <h3 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-emerald-700">
            <ShieldIcon className="h-4 w-4" aria-hidden="true" />
            {t("about.secImplemented")}
          </h3>
          <ul className="mt-4 grid gap-4 sm:grid-cols-2">
            {implemented.map((key) => (
              <li key={key} className="flex gap-3">
                <span
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"
                  aria-hidden="true"
                >
                  <CheckIcon className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900">{t(`about.${key}Title`)}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-slate-600">
                    {t(`about.${key}Body`)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        {/* Stated as plainly as the implemented list — an honest boundary is
            more credible than an inflated feature list. */}
        <Panel className="border-amber-200 bg-amber-50/50">
          <h3 className="text-sm font-bold uppercase tracking-wider text-amber-800">
            {t("about.secNotClaimed")}
          </h3>
          <p className="mt-1 text-sm text-amber-900/80">{t("about.secNotClaimedBody")}</p>
          <ul className="mt-3 space-y-2">
            {notClaimed.map((key) => (
              <li key={key} className="flex gap-2.5 text-sm leading-relaxed text-amber-900/90">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-amber-400" aria-hidden="true" />
                <span className="min-w-0">{t(`about.${key}`)}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel>
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
            {t("about.secPlanned")}
          </h3>
          <ul className="mt-3 flex flex-wrap gap-2">
            {planned.map((key) => (
              <li
                key={key}
                className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-1.5 text-sm text-slate-600"
              >
                {t(`about.${key}`)}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </Section>
  );
}

/** Verified against backend/api.py — see test_about_docs_accuracy.py. */
const API_GROUPS: Array<{
  titleKey: string;
  endpoints: Array<{ method: string; path: string; bodyKey: string }>;
}> = [
  {
    titleKey: "about.apiDocuments",
    endpoints: [
      { method: "POST", path: "/api/v1/documents", bodyKey: "about.e1" },
      { method: "GET", path: "/api/v1/timeline", bodyKey: "about.e2" },
      { method: "GET", path: "/api/v1/patient-snapshot", bodyKey: "about.e3" },
    ],
  },
  {
    titleKey: "about.apiJobs",
    endpoints: [
      { method: "GET", path: "/api/v1/jobs", bodyKey: "about.e4" },
      { method: "GET", path: "/api/v1/jobs/{job_id}", bodyKey: "about.e5" },
    ],
  },
  {
    titleKey: "about.apiClinical",
    endpoints: [
      { method: "GET", path: "/api/v1/cross-check", bodyKey: "about.e6" },
      { method: "GET", path: "/api/v1/lab-trends", bodyKey: "about.e7" },
      { method: "GET", path: "/api/v1/changes", bodyKey: "about.e16" },
      { method: "GET", path: "/api/v1/record-integrity", bodyKey: "about.e17" },
      { method: "GET", path: "/api/v1/appointment-prep", bodyKey: "about.e18" },
      { method: "GET", path: "/api/v1/follow-up", bodyKey: "about.e19" },
    ],
  },
  {
    titleKey: "about.apiAsk",
    endpoints: [
      { method: "POST", path: "/api/v1/qa", bodyKey: "about.e8" },
      { method: "POST", path: "/api/v1/sessions", bodyKey: "about.e9" },
      { method: "POST", path: "/api/v1/sessions/{session_id}/messages", bodyKey: "about.e10" },
      { method: "GET", path: "/api/v1/sessions/{session_id}", bodyKey: "about.e11" },
      { method: "DELETE", path: "/api/v1/sessions/{session_id}", bodyKey: "about.e12" },
    ],
  },
  {
    titleKey: "about.apiCare",
    endpoints: [{ method: "GET", path: "/api/v1/care/facilities", bodyKey: "about.e13" }],
  },
  {
    titleKey: "about.apiWorkspace",
    endpoints: [
      { method: "POST", path: "/api/v1/anonymous/session", bodyKey: "about.e14" },
      { method: "GET", path: "/api/v1/health", bodyKey: "about.e15" },
    ],
  },
];

const METHOD_TONES: Record<string, string> = {
  GET: "bg-sky-100 text-sky-800",
  POST: "bg-emerald-100 text-emerald-800",
  DELETE: "bg-rose-100 text-rose-800",
};

function ApiOverview() {
  const { t } = useI18n();
  return (
    <Section id="api" title={t("about.apiTitle")} subtitle={t("about.apiSubtitle")}>
      <div className="space-y-4">
        <Panel className="bg-slate-50">
          <h3 className="text-sm font-bold text-slate-900">{t("about.apiAuthTitle")}</h3>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">{t("about.apiAuthBody")}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <TechChip>Authorization: Bearer &lt;token&gt;</TechChip>
            <TechChip>X-User-Id: &lt;workspace id&gt;</TechChip>
          </div>
        </Panel>

        {API_GROUPS.map((group) => (
          <Panel key={group.titleKey} className="p-0 sm:p-0">
            <h3 className="border-b border-slate-100 px-5 py-3 text-sm font-bold text-slate-900">
              {t(group.titleKey)}
            </h3>
            <ul className="divide-y divide-slate-100">
              {group.endpoints.map((endpoint) => (
                <li key={`${endpoint.method}-${endpoint.path}`} className="px-5 py-3.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={classNames(
                        "rounded-md px-2 py-0.5 font-mono text-[11px] font-bold",
                        METHOD_TONES[endpoint.method] || "bg-slate-100 text-slate-700"
                      )}
                    >
                      {endpoint.method}
                    </span>
                    {/* break-all keeps a long path inside the card on mobile. */}
                    <code className="min-w-0 break-all font-mono text-xs text-slate-800">
                      {endpoint.path}
                    </code>
                  </div>
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
                    {t(endpoint.bodyKey)}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>
    </Section>
  );
}

function Disclaimer() {
  const { t } = useI18n();
  return (
    <aside
      className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900"
      role="note"
    >
      <p className="font-semibold">{t("about.disclaimerTitle")}</p>
      <p className="mt-1 leading-relaxed text-amber-900/90">{t("about.disclaimerBody")}</p>
    </aside>
  );
}

function InfoIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}
