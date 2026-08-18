import { useEffect, useRef, useState, type ReactNode } from "react";
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
 * About / technical overview — an informational page INSIDE the application.
 *
 * Reachable from the sidebar's utility region, deliberately outside the
 * patient-workflow navigation. Every visible string comes from the `about.*`
 * i18n namespace (en/si/ta), so this file holds layout only.
 *
 * Navigation model (redesign): the application sidebar moves between app
 * features; a sticky HORIZONTAL bar below the page header moves between the
 * sections of THIS page ("On this page" dropdown on mobile). There is no
 * secondary side-contents column, no "Back to dashboard" action, and no
 * login/registration UI — MediMind has anonymous workspaces, not accounts.
 *
 * Content is verified against the repository — endpoints against
 * backend/api.py, pipeline stages against medical_extractor.py and
 * retrieval.py. A backend test asserts the documented routes exist.
 */
export function AboutPage() {
  const { t } = useI18n();

  const sections = [
    { id: "overview", title: t("about.overviewTitle"), nav: t("about.navOverview") },
    { id: "features", title: t("about.featuresTitle"), nav: t("about.navFeatures") },
    { id: "how-it-works", title: t("about.howTitle"), nav: t("about.navHow") },
    { id: "safety-intelligence", title: t("about.safetyIntelligenceTitle"), nav: t("about.navSafety") },
    { id: "security", title: t("about.secTitle"), nav: t("about.navPrivacy") },
    { id: "interoperability", title: t("about.interoperabilityTitle"), nav: t("about.navInterop") },
    { id: "api", title: t("about.apiTitle"), nav: t("about.navApi") },
  ];
  const activeId = useActiveSection(sections.map((section) => section.id));

  return (
    <div className="about-page">
      <PageHeader />

      <SectionNavBar sections={sections} activeId={activeId} />

      {/* Major sections get generous separation (~96px); sections anchor
          below the sticky bar when jumped to. */}
      <div className="mt-12 space-y-24">
        <Overview />
        <Features />
        <HowItWorks />
        <SafetyIntelligence />
        <Security />
        <Interoperability />
        <ApiOverview />
        <Disclaimer />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Compact in-app header — not a marketing landing hero. No login, no  */
/* registration, no back button: navigation belongs to the sidebar.    */
/* ------------------------------------------------------------------ */

function PageHeader() {
  const { t } = useI18n();
  const facts = ["fact1", "fact2", "fact3"];
  return (
    <header className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0 max-w-3xl">
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
          <InfoIcon className="h-3.5 w-3.5" /> {t("about.eyebrow")}
        </div>
        <h1 className="page-title">{t("about.title")}</h1>
        <p className="mt-3 text-base leading-relaxed text-slate-600">{t("about.lede")}</p>
        <ul className="mt-4 flex flex-wrap gap-2">
          {facts.map((key) => (
            <li
              key={key}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700"
            >
              <CheckIcon className="h-3.5 w-3.5 shrink-0 text-brand-600" aria-hidden="true" />
              {t(`about.${key}`)}
            </li>
          ))}
        </ul>
        {/* The one contextual action allowed on an informational page. */}
        <a
          href="#how-it-works"
          className="btn-secondary mt-5 inline-flex focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
        >
          {t("about.seeHowItWorks")}
          <span aria-hidden="true" className="text-slate-400">↓</span>
        </a>
      </div>

      {/* Small record-processing illustration (decorative summary; the
          same flow is explained as real text in the sections below). */}
      <div className="w-full max-w-xs shrink-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:w-64">
        <ol className="space-y-3">
          {["headerFlow1", "headerFlow2", "headerFlow3"].map((key, index) => (
            <li key={key} className="flex items-center gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-bold text-brand-700">
                {index + 1}
              </span>
              <span className="min-w-0 flex-1 text-sm font-medium leading-snug text-slate-700">
                {t(`about.${key}`)}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </header>
  );
}

/** Tracks which section is in view, to highlight the section bar. */
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
      // The sticky section bar (~72px) sits above the content; sections are
      // considered "current" only once they reach the top third of the view.
      { rootMargin: "-96px 0px -70% 0px", threshold: 0 }
    );
    for (const id of idsRef.current) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, []);

  return activeId;
}

/**
 * Sticky horizontal section navigation. Desktop: a slim bar with a teal
 * underline on the visible section. Mobile: an "On this page" select that
 * scrolls to the chosen section — separate from the app's navigation drawer.
 */
function SectionNavBar({
  sections,
  activeId,
}: {
  sections: Array<{ id: string; nav: string }>;
  activeId: string | null;
}) {
  const { t } = useI18n();
  return (
    <nav
      aria-label={t("about.sectionNav")}
      className="sticky top-0 z-20 -mx-4 mt-10 border-b border-slate-200 bg-slate-50/95 px-4 py-2 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-12 lg:px-12"
    >
      {/* Desktop: underline tabs spanning the content area (not the app sidebar). */}
      <ul className="hidden gap-1 lg:flex">
        {sections.map((section) => {
          const active = activeId === section.id;
          return (
            <li key={section.id}>
              <a
                href={`#${section.id}`}
                aria-current={active ? "true" : undefined}
                className={classNames(
                  "flex min-h-[44px] items-center whitespace-nowrap border-b-2 px-3 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400",
                  active
                    ? "border-brand-600 font-semibold text-brand-800"
                    : "border-transparent text-slate-600 hover:border-brand-300 hover:text-slate-900"
                )}
              >
                {section.nav}
              </a>
            </li>
          );
        })}
      </ul>

      {/* Mobile: one compact control, independent of the app drawer. */}
      <label className="flex items-center gap-2 lg:hidden">
        <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("about.onThisPage")}
        </span>
        <select
          value={activeId ?? sections[0]?.id ?? ""}
          onChange={(event) => {
            const element = document.getElementById(event.target.value);
            element?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          className="h-11 min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-2 text-sm font-medium text-slate-800 shadow-sm focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-500"
        >
          {sections.map((section) => (
            <option key={section.id} value={section.id}>
              {section.nav}
            </option>
          ))}
        </select>
      </label>
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
    <section id={id} aria-labelledby={`${id}-heading`} className="scroll-mt-24">
      <h2 id={`${id}-heading`} className="section-title">
        {title}
      </h2>
      {subtitle && <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-slate-500">{subtitle}</p>}
      <div className="mt-6">{children}</div>
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

/** Collapsed-by-default technical detail. Keeps every deep-dive available
 *  without making the default page enormous. */
function TechDetails({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group rounded-2xl border border-slate-200 bg-white shadow-sm">
      <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-sm font-semibold text-slate-900 transition hover:text-brand-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">{summary}</span>
        <span
          aria-hidden="true"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-slate-200 text-base font-bold leading-none text-slate-500 transition-transform group-open:rotate-45"
        >
          +
        </span>
      </summary>
      <div className="border-t border-slate-100 px-5 py-5">{children}</div>
    </details>
  );
}

/* ------------------------------------------------------------------ */
/* 1. Overview — what MediMind is, in user language.                   */
/* ------------------------------------------------------------------ */

const CAPABILITIES = [
  { key: "cap1", Icon: FileIcon, tone: "bg-cyan-50 text-cyan-800" },
  { key: "cap2", Icon: ChatIcon, tone: "bg-brand-50 text-brand-700" },
  { key: "cap3", Icon: ShieldIcon, tone: "bg-amber-50 text-amber-800" },
  { key: "cap4", Icon: AppointmentIcon, tone: "bg-teal-50 text-teal-800" },
] as const;

function Overview() {
  const { t } = useI18n();
  const principles = ["p1", "p2", "p3", "p4"];
  return (
    <Section id="overview" title={t("about.overviewTitle")}>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
            {t("about.overviewSubtitle")}
          </h3>
          <ul className="mt-4 grid gap-4">
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

        {/* Four primary capability cards: the intelligence stack summarized
            in user language. Technical detail lives in "How it works". */}
        <div className="grid gap-4 sm:grid-cols-2">
          {CAPABILITIES.map(({ key, Icon, tone }) => (
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
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/* 2. Features — the ten implemented features, grouped by purpose.     */
/* ------------------------------------------------------------------ */

const FEATURE_GROUPS: Array<{
  groupKey: string;
  items: Array<{ key: string; Icon: (p: { className?: string }) => ReactNode; tone: string }>;
}> = [
  {
    groupKey: "fg1",
    items: [
      { key: "f1", Icon: FileIcon, tone: "bg-cyan-50 text-cyan-800" },
      { key: "f2", Icon: PillIcon, tone: "bg-emerald-50 text-emerald-800" },
      { key: "f3", Icon: BeakerIcon, tone: "bg-violet-50 text-violet-800" },
      { key: "f7", Icon: ChangesIcon, tone: "bg-indigo-50 text-indigo-800" },
      { key: "f8", Icon: IntegrityIcon, tone: "bg-orange-50 text-orange-800" },
    ],
  },
  {
    groupKey: "fg2",
    items: [
      { key: "f5", Icon: ChatIcon, tone: "bg-brand-50 text-brand-700" },
      { key: "f4", Icon: ShieldIcon, tone: "bg-amber-50 text-amber-800" },
    ],
  },
  {
    groupKey: "fg3",
    items: [
      { key: "f9", Icon: AppointmentIcon, tone: "bg-teal-50 text-teal-800" },
      { key: "f10", Icon: ReminderIcon, tone: "bg-teal-50 text-teal-800" },
      { key: "f6", Icon: LocationIcon, tone: "bg-cyan-50 text-cyan-800" },
    ],
  },
];

function Features() {
  const { t } = useI18n();
  return (
    <Section id="features" title={t("about.featuresTitle")} subtitle={t("about.featuresSubtitle")}>
      <div className="space-y-8">
        {FEATURE_GROUPS.map((group) => (
          <div key={group.groupKey}>
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
              {t(`about.${group.groupKey}Title`)}
            </h3>
            <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {group.items.map(({ key, Icon, tone }) => (
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
                  <h4 className="mt-3.5 text-base font-bold text-slate-900">{t(`about.${key}Title`)}</h4>
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{t(`about.${key}Body`)}</p>
                </article>
              ))}
            </div>
          </div>
        ))}

        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-white shadow-lg">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-brand-300">
                {t("about.differentiatorEyebrow")}
              </p>
              <h3 className="mt-1 text-lg font-bold">{t("about.differentiatorTitle")}</h3>
            </div>
            <span className="rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-semibold text-slate-200">
              {t("about.differentiatorBadge")}
            </span>
          </div>
          <p className="mt-3 max-w-4xl text-sm leading-relaxed text-slate-300">
            {t("about.differentiatorBody")}
          </p>
        </div>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/* 3. How it works — five steps by default, technical detail on click. */
/* ------------------------------------------------------------------ */

const HOW_STEPS = ["hw1", "hw2", "hw3", "hw4", "hw5"];

function HowItWorks() {
  const { t } = useI18n();
  return (
    <Section id="how-it-works" title={t("about.howTitle")} subtitle={t("about.howSubtitle")}>
      <Figure label={t("about.howDiagram")}>
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {HOW_STEPS.map((key, index) => (
            <li
              key={key}
              className="relative flex flex-col rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-600 text-xs font-bold text-white">
                {index + 1}
              </span>
              <h3 className="mt-2.5 text-sm font-bold leading-snug text-slate-900">
                {t(`about.${key}Title`)}
              </h3>
              <p className="mt-1 text-xs leading-relaxed text-slate-600">{t(`about.${key}Body`)}</p>
            </li>
          ))}
        </ol>
      </Figure>

      <div className="mt-6 space-y-3">
        <TechDetails summary={t("about.archTitle")}>
          <ArchitectureDetail />
        </TechDetails>
        <TechDetails summary={t("about.techDocs")}>
          <PipelineDetail title={t("about.pipeIngest")} keys={["s1", "s2", "s3", "s4"]} tone="sky" />
        </TechDetails>
        <TechDetails summary={t("about.techData")}>
          <DataFlowDetail />
        </TechDetails>
        <TechDetails summary={t("about.techRet")}>
          <RetrievalDetail />
        </TechDetails>
        <TechDetails summary={t("about.techAns")}>
          <PipelineDetail title={t("about.pipeAnswer")} keys={["s8", "s9"]} tone="brand" />
        </TechDetails>
        <TechDetails summary={t("about.capabilitiesTitle")}>
          <CapabilityStackDetail />
        </TechDetails>
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

function ArchitectureDetail() {
  const { t } = useI18n();
  return (
    <Figure label={t("about.archDiagram")}>
      <Flow>
        {LAYERS.map((layer) => (
          <div key={layer.key} className={classNames("rounded-xl border p-4", TONE_CLASSES[layer.tone])}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <p className="text-sm font-bold">{t(`about.${layer.key}Name`)}</p>
              <p className="font-mono text-[11px] leading-relaxed opacity-75">{layer.tech}</p>
            </div>
            <p className="mt-1.5 text-sm leading-relaxed opacity-90">{t(`about.${layer.key}Body`)}</p>
          </div>
        ))}
      </Flow>
    </Figure>
  );
}

function PipelineDetail({
  title,
  keys,
  tone,
}: {
  title: string;
  keys: string[];
  tone: "sky" | "brand";
}) {
  const { t } = useI18n();
  return (
    <Figure label={t("about.pipeDiagram")}>
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
            title={`${index + 1}. ${t(`about.${key}Title`)}`}
            subtitle={t(`about.${key}Body`)}
          />
        ))}
      </Flow>
    </Figure>
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

function DataFlowDetail() {
  const { t } = useI18n();
  return (
    <Figure label={t("about.flowDiagram")}>
      <Flow>
        <Node tone="brand" title={t("about.s5Title")} subtitle={t("about.s5Body")} />
        <Node tone="sky" title={t("about.flowYouTitle")} subtitle={t("about.flowYouBody")} />
        <Node tone="sky" title={t("about.flowStoreTitle")} subtitle={t("about.flowStoreBody")} />
        <div>
          <Node tone="emerald" title={t("about.flowUseTitle")} subtitle={t("about.flowUseBody")} />
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
      <div className="mt-6 rounded-xl border border-brand-200 bg-brand-50 p-4">
        <h4 className="text-sm font-bold text-brand-900">{t("about.groundingTitle")}</h4>
        <p className="mt-1 text-sm leading-relaxed text-brand-900/80">{t("about.groundingBody")}</p>
      </div>
    </Figure>
  );
}

function RetrievalDetail() {
  const { t } = useI18n();
  return (
    <Figure label={t("about.pipeDiagram")}>
      <Flow>
        <Node tone="violet" title={t("about.s6Title")} subtitle={t("about.s6Body")} />
        <Node tone="violet" title={t("about.s7Title")} subtitle={t("about.s7Body")} />
      </Flow>
      <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <h4 className="text-sm font-bold text-slate-900">{t("about.selfHealTitle")}</h4>
        <p className="mt-1 text-sm leading-relaxed text-slate-600">{t("about.selfHealBody")}</p>
      </div>
    </Figure>
  );
}

const CAPABILITY_GROUPS = [
  { key: "cg1", tone: "border-brand-200 bg-brand-50", badge: "bg-brand-600", items: ["c1", "c2", "c3", "c4"] },
  { key: "cg2", tone: "border-emerald-200 bg-emerald-50", badge: "bg-emerald-600", items: ["c5", "c6", "c7", "c8"] },
  { key: "cg3", tone: "border-violet-200 bg-violet-50", badge: "bg-violet-600", items: ["c9", "c10", "c11", "c12"] },
  { key: "cg4", tone: "border-amber-200 bg-amber-50", badge: "bg-amber-600", items: ["c13", "c14", "c15", "c16"] },
] as const;

function CapabilityStackDetail() {
  const { t } = useI18n();
  return (
    <div>
      <p className="text-sm leading-relaxed text-slate-600">{t("about.capabilitiesSubtitle")}</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {CAPABILITY_GROUPS.map((group) => (
          <article key={group.key} className={classNames("rounded-2xl border p-5 shadow-sm", group.tone)}>
            <div className="flex items-center gap-3">
              <span
                className={classNames(
                  "flex h-9 w-9 items-center justify-center rounded-xl text-sm font-black text-white",
                  group.badge
                )}
              >
                ✓
              </span>
              <div>
                <h4 className="text-base font-bold text-slate-900">{t(`about.${group.key}Title`)}</h4>
                <p className="text-xs font-medium text-slate-600">{t(`about.${group.key}Body`)}</p>
              </div>
            </div>
            <ul className="mt-4 grid gap-2">
              {group.items.map((item) => (
                <li key={item} className="flex gap-2 text-sm leading-relaxed text-slate-700">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-50" />
                  {t(`about.${item}`)}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* 4. Safety intelligence — full contrast, prominent boundary.         */
/* ------------------------------------------------------------------ */

const SAFETY_LANES = ["sl1", "sl2", "sl3", "sl4", "sl5", "sl6"];

function SafetyIntelligence() {
  const { t } = useI18n();
  return (
    <Section
      id="safety-intelligence"
      title={t("about.safetyIntelligenceTitle")}
      subtitle={t("about.safetyIntelligenceSubtitle")}
    >
      <Panel>
        <ol className="grid gap-3 md:grid-cols-3">
          {SAFETY_LANES.map((key, index) => (
            <li key={key} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
              <span className="text-xs font-black text-brand-700">0{index + 1}</span>
              <h3 className="mt-2 text-sm font-bold text-slate-900">{t(`about.${key}Title`)}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-700">{t(`about.${key}Body`)}</p>
            </li>
          ))}
        </ol>
        <ul className="mt-5 flex flex-wrap gap-2 border-t border-slate-100 pt-4 text-xs font-semibold text-slate-600">
          {["about.safetyBadge1", "about.safetyBadge2", "about.safetyBadge3", "about.safetyBadge4"].map(
            (key) => (
              <li key={key} className="rounded-full bg-slate-100 px-3 py-1.5">
                {t(key)}
              </li>
            )
          )}
        </ul>
      </Panel>

      {/* The boundary statement must be impossible to miss. */}
      <div
        role="note"
        className="mt-4 rounded-2xl border-2 border-amber-300 bg-amber-50 px-5 py-4 text-sm font-semibold leading-relaxed text-amber-900"
      >
        {t("about.safetyBoundary")}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/* 5. Your anonymous workspace — security & privacy without accounts.  */
/* ------------------------------------------------------------------ */

function Security() {
  const { t } = useI18n();
  const implemented = ["i1", "i2", "i3", "i4", "i5", "i6"];
  const limitations = ["n1", "n2", "n3", "n4", "n5"];
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
            {limitations.map((key) => (
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

/* ------------------------------------------------------------------ */
/* 6. Interoperability — two columns; details behind one click.        */
/* ------------------------------------------------------------------ */

const INTEROP_RESOURCES = ["Patient", "MedicationStatement", "MedicationRequest", "Observation", "AllergyIntolerance", "Condition", "Encounter", "Provenance"];

function Interoperability() {
  const { t } = useI18n();
  return (
    <Section
      id="interoperability"
      title={t("about.interoperabilityTitle")}
      subtitle={t("about.interoperabilitySubtitle")}
    >
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel className="border-sky-200 bg-gradient-to-br from-sky-50 via-white to-brand-50">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.18em] text-sky-700">
                FHIR R4-compatible
              </p>
              <h3 className="mt-1 text-xl font-black text-slate-900">{t("about.fhirTitle")}</h3>
            </div>
            <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-bold text-amber-800">
              {t("about.fhirStatus")}
            </span>
          </div>
          <div className="mt-5 flex flex-wrap items-center gap-2 text-xs font-semibold">
            <span className="rounded-lg bg-white px-3 py-2 shadow-sm ring-1 ring-slate-200">
              {t("about.fhirInput")}
            </span>
            <span aria-hidden="true" className="text-sky-500">→</span>
            <span className="rounded-lg bg-white px-3 py-2 shadow-sm ring-1 ring-slate-200">
              {t("about.fhirBundle")}
            </span>
            <span aria-hidden="true" className="text-sky-500">→</span>
            <span className="rounded-lg bg-emerald-100 px-3 py-2 text-emerald-800">
              {t("about.fhirValidation")}
            </span>
          </div>
          <p className="mt-4 text-sm leading-relaxed text-slate-600">{t("about.fhirBody")}</p>
          <details className="group mt-4 rounded-xl border border-slate-200 bg-white/80">
            <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5 text-sm font-semibold text-sky-800 transition hover:text-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400 [&::-webkit-details-marker]:hidden">
              {t("about.viewResources")}
              <span aria-hidden="true" className="text-slate-400 transition-transform group-open:rotate-180">▾</span>
            </summary>
            <div className="flex flex-wrap gap-2 px-4 pb-4">
              {INTEROP_RESOURCES.map((resource) => (
                <span
                  key={resource}
                  className="rounded-md border border-sky-200 bg-white px-2 py-1 font-mono text-[11px] text-sky-900"
                >
                  {resource}
                </span>
              ))}
            </div>
          </details>
        </Panel>
        <Panel>
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
            {t("about.terminologyTitle")}
          </h3>
          <div className="mt-4 space-y-3">
            {["LOINC", "SNOMED CT", "RxNorm", "ICD-10-CM"].map((code) => (
              <div key={code} className="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2.5">
                <span className="font-mono text-sm font-bold text-slate-800">{code}</span>
                <span className="text-xs font-semibold text-emerald-700">{t("about.mappedWhenKnown")}</span>
              </div>
            ))}
          </div>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">{t("about.terminologyBody")}</p>
        </Panel>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ */
/* 7. API overview — endpoint groups collapsed by default.             */
/* ------------------------------------------------------------------ */

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
      { method: "GET", path: "/api/v1/medication-safety", bodyKey: "about.e6" },
      { method: "POST", path: "/api/v1/medication-safety/reanalyze", bodyKey: "about.e6" },
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
          <details
            key={group.titleKey}
            className="group rounded-2xl border border-slate-200 bg-white shadow-sm"
          >
            <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-400 [&::-webkit-details-marker]:hidden">
              <h3 className="text-sm font-bold text-slate-900 group-hover:text-brand-800">
                {t(group.titleKey)}
              </h3>
              <span className="flex shrink-0 items-center gap-2">
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
                  {t("about.apiEndpoints", { count: group.endpoints.length })}
                </span>
                <span
                  aria-hidden="true"
                  className="text-slate-400 transition-transform group-open:rotate-180"
                >
                  ▾
                </span>
              </span>
            </summary>
            <ul className="divide-y divide-slate-100 border-t border-slate-100">
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
          </details>
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
