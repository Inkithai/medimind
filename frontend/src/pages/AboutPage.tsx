import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Figure, Flow, Node, TechChip } from "../components/about/Diagram";
import {
  BeakerIcon,
  ChatIcon,
  CheckIcon,
  FileIcon,
  LocationIcon,
  PillIcon,
  ShieldIcon,
} from "../components/icons";
import { useAboutCopy } from "../i18n";
import { classNames } from "../utils/format";

/**
 * About / technical overview.
 *
 * Reachable from the sidebar footer, deliberately outside the nine
 * patient-workflow items. All copy comes from the i18n dictionary; this file
 * holds layout only, so translating the page never means editing components.
 */
export function AboutPage() {
  const copy = useAboutCopy();

  const sections = [
    copy.overview,
    copy.features,
    copy.architecture,
    copy.pipeline,
    copy.dataFlow,
    copy.security,
    copy.api,
  ].map((section) => ({ id: section.id, title: section.title }));

  const activeId = useActiveSection(sections.map((section) => section.id));

  return (
    <div className="space-y-8">
      <Header copy={copy} />

      <div className="lg:grid lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-10">
        <TableOfContents sections={sections} activeId={activeId} label={copy.onThisPage} />

        {/* min-w-0 stops a long <pre>/path from widening the grid column. */}
        <div className="min-w-0 space-y-10">
          <Overview copy={copy} />
          <Features copy={copy} />
          <Architecture copy={copy} />
          <Pipeline copy={copy} />
          <DataFlow copy={copy} />
          <Security copy={copy} />
          <ApiOverview copy={copy} />
          <Disclaimer copy={copy} />
        </div>
      </div>
    </div>
  );
}

type Copy = ReturnType<typeof useAboutCopy>;

/** Tracks which section is in view, to highlight the contents list. */
function useActiveSection(ids: string[]): string | null {
  const [activeId, setActiveId] = useState<string | null>(ids[0] ?? null);
  // Read ids without making them an effect dependency (the array is new each render).
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
      // Bias towards the top of the viewport so the heading you're reading wins.
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

function Header({ copy }: { copy: Copy }) {
  return (
    <header>
      <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-brand-700">
        <InfoIcon className="h-3.5 w-3.5" /> {copy.eyebrow}
      </div>
      <h1 className="page-title">{copy.title}</h1>
      <p className="mt-3 max-w-3xl text-base leading-relaxed text-slate-600">{copy.lede}</p>
      <Link to="/dashboard" className="btn-secondary mt-5 inline-flex">
        {copy.backToDashboard}
      </Link>
    </header>
  );
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
              <span className="min-w-0 truncate">{section.title}</span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Section shell: consistent heading hierarchy and scroll offset. */
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

function Overview({ copy }: { copy: Copy }) {
  return (
    <Section id={copy.overview.id} title={copy.overview.title}>
      <Panel>
        <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
          {copy.overview.principlesTitle}
        </h3>
        <ul className="mt-4 grid gap-4 sm:grid-cols-2">
          {copy.overview.principles.map((principle) => (
            <li key={principle.title} className="flex gap-3">
              <span
                className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600"
                aria-hidden="true"
              >
                <CheckIcon className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">{principle.title}</p>
                <p className="mt-0.5 text-sm leading-relaxed text-slate-600">{principle.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </Section>
  );
}

const FEATURE_ICONS: Record<string, (p: { className?: string }) => ReactNode> = {
  document: FileIcon,
  pill: PillIcon,
  beaker: BeakerIcon,
  shield: ShieldIcon,
  chat: ChatIcon,
  location: LocationIcon,
};

const FEATURE_TONES: Record<string, string> = {
  document: "bg-sky-50 text-sky-600",
  pill: "bg-emerald-50 text-emerald-600",
  beaker: "bg-violet-50 text-violet-600",
  shield: "bg-amber-50 text-amber-600",
  chat: "bg-brand-50 text-brand-600",
  location: "bg-rose-50 text-rose-600",
};

function Features({ copy }: { copy: Copy }) {
  return (
    <Section id={copy.features.id} title={copy.features.title} subtitle={copy.features.subtitle}>
      <div className="grid gap-4 md:grid-cols-2">
        {copy.features.items.map((feature) => {
          const Icon = FEATURE_ICONS[feature.icon] || FileIcon;
          return (
            <article
              key={feature.title}
              className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <span
                className={classNames(
                  "flex h-10 w-10 items-center justify-center rounded-xl",
                  FEATURE_TONES[feature.icon] || "bg-slate-100 text-slate-500"
                )}
                aria-hidden="true"
              >
                <Icon className="h-5 w-5" />
              </span>
              <h3 className="mt-3.5 text-base font-bold text-slate-900">{feature.title}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{feature.body}</p>
              <ul className="mt-3.5 space-y-1.5 border-t border-slate-100 pt-3.5">
                {feature.points.map((point) => (
                  <li key={point} className="flex gap-2 text-sm text-slate-600">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-300" aria-hidden="true" />
                    <span className="min-w-0">{point}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </Section>
  );
}

const LAYER_TONES = ["brand", "sky", "violet", "emerald", "amber", "rose", "slate"] as const;

function Architecture({ copy }: { copy: Copy }) {
  return (
    <Section
      id={copy.architecture.id}
      title={copy.architecture.title}
      subtitle={copy.architecture.subtitle}
    >
      <Panel>
        <Figure label={copy.architecture.diagramLabel}>
          <Flow>
            {copy.architecture.layers.map((layer, index) => (
              <div
                key={layer.name}
                className={classNames(
                  "rounded-xl border p-4",
                  TONE_CLASSES[LAYER_TONES[index % LAYER_TONES.length]]
                )}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <p className="text-sm font-bold">{layer.name}</p>
                  <p className="font-mono text-[11px] leading-relaxed opacity-75">{layer.tech}</p>
                </div>
                <p className="mt-1.5 text-sm leading-relaxed opacity-90">{layer.body}</p>
              </div>
            ))}
          </Flow>
        </Figure>
      </Panel>
    </Section>
  );
}

const TONE_CLASSES: Record<string, string> = {
  brand: "border-brand-200 bg-brand-50 text-brand-900",
  sky: "border-sky-200 bg-sky-50 text-sky-900",
  violet: "border-violet-200 bg-violet-50 text-violet-900",
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  rose: "border-rose-200 bg-rose-50 text-rose-900",
  slate: "border-slate-200 bg-slate-50 text-slate-800",
};

function Pipeline({ copy }: { copy: Copy }) {
  const ingest = copy.pipeline.stages.filter((stage) => stage.phase === "ingest");
  const answer = copy.pipeline.stages.filter((stage) => stage.phase === "answer");

  return (
    <Section id={copy.pipeline.id} title={copy.pipeline.title} subtitle={copy.pipeline.subtitle}>
      <Panel>
        <Figure label={copy.pipeline.diagramLabel}>
          <div className="grid gap-6 lg:grid-cols-2">
            <PipelineColumn title={copy.pipeline.ingestTitle} stages={ingest} tone="sky" startAt={1} />
            <PipelineColumn
              title={copy.pipeline.answerTitle}
              stages={answer}
              tone="brand"
              startAt={ingest.length + 1}
            />
          </div>
        </Figure>

        <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <h4 className="text-sm font-bold text-slate-900">{copy.pipeline.selfHealTitle}</h4>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">{copy.pipeline.selfHealBody}</p>
        </div>
      </Panel>
    </Section>
  );
}

function PipelineColumn({
  title,
  stages,
  tone,
  startAt,
}: {
  title: string;
  stages: ReadonlyArray<{ title: string; body: string }>;
  tone: "sky" | "brand";
  startAt: number;
}) {
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
        {stages.map((stage, index) => (
          <Node
            key={stage.title}
            tone={tone}
            title={`${startAt + index}. ${stage.title}`}
            subtitle={stage.body}
          />
        ))}
      </Flow>
    </div>
  );
}

function DataFlow({ copy }: { copy: Copy }) {
  return (
    <Section id={copy.dataFlow.id} title={copy.dataFlow.title} subtitle={copy.dataFlow.subtitle}>
      <Panel>
        <Figure label={copy.dataFlow.diagramLabel}>
          <Flow>
            <Node tone="brand" title={copy.dataFlow.youTitle} subtitle={copy.dataFlow.youBody} />
            <Node tone="sky" title={copy.dataFlow.storeTitle} subtitle={copy.dataFlow.storeBody} />
            <div>
              <Node
                tone="emerald"
                title={copy.dataFlow.useTitle}
                subtitle={copy.dataFlow.useBody}
              />
              {/* Fans out to each feature: a grid on desktop, a stack on mobile. */}
              <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {copy.dataFlow.consumers.map((consumer) => (
                  <li
                    key={consumer.name}
                    className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                  >
                    <p className="text-sm font-semibold text-slate-800">{consumer.name}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{consumer.body}</p>
                  </li>
                ))}
              </ul>
            </div>
          </Flow>
        </Figure>

        <div className="mt-6 rounded-xl border border-brand-200 bg-brand-50 p-4">
          <h4 className="text-sm font-bold text-brand-900">{copy.dataFlow.groundingTitle}</h4>
          <p className="mt-1 text-sm leading-relaxed text-brand-900/80">
            {copy.dataFlow.groundingBody}
          </p>
        </div>
      </Panel>
    </Section>
  );
}

function Security({ copy }: { copy: Copy }) {
  return (
    <Section id={copy.security.id} title={copy.security.title} subtitle={copy.security.subtitle}>
      <div className="space-y-4">
        <Panel>
          <h3 className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-emerald-700">
            <ShieldIcon className="h-4 w-4" aria-hidden="true" />
            {copy.security.implementedTitle}
          </h3>
          <ul className="mt-4 grid gap-4 sm:grid-cols-2">
            {copy.security.implemented.map((item) => (
              <li key={item.title} className="flex gap-3">
                <span
                  className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"
                  aria-hidden="true"
                >
                  <CheckIcon className="h-3.5 w-3.5" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-900">{item.title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-slate-600">{item.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        {/* Stated as plainly as the implemented list — an honest boundary is
            more credible than an inflated feature list. */}
        <Panel className="border-amber-200 bg-amber-50/50">
          <h3 className="text-sm font-bold uppercase tracking-wider text-amber-800">
            {copy.security.notYetTitle}
          </h3>
          <p className="mt-1 text-sm text-amber-900/80">{copy.security.notYetBody}</p>
          <ul className="mt-3 space-y-2">
            {copy.security.notYet.map((item) => (
              <li key={item} className="flex gap-2.5 text-sm leading-relaxed text-amber-900/90">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-amber-400" aria-hidden="true" />
                <span className="min-w-0">{item}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel>
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-500">
            {copy.security.plannedTitle}
          </h3>
          <ul className="mt-3 flex flex-wrap gap-2">
            {copy.security.planned.map((item) => (
              <li
                key={item}
                className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-3 py-1.5 text-sm text-slate-600"
              >
                {item}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </Section>
  );
}

const METHOD_TONES: Record<string, string> = {
  GET: "bg-sky-100 text-sky-800",
  POST: "bg-emerald-100 text-emerald-800",
  DELETE: "bg-rose-100 text-rose-800",
};

function ApiOverview({ copy }: { copy: Copy }) {
  return (
    <Section id={copy.api.id} title={copy.api.title} subtitle={copy.api.subtitle}>
      <div className="space-y-4">
        <Panel className="bg-slate-50">
          <h3 className="text-sm font-bold text-slate-900">{copy.api.authTitle}</h3>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">{copy.api.authBody}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <TechChip>Authorization: Bearer &lt;token&gt;</TechChip>
            <TechChip>X-User-Id: &lt;workspace id&gt;</TechChip>
          </div>
        </Panel>

        {copy.api.groups.map((group) => (
          <Panel key={group.name} className="p-0 sm:p-0">
            <h3 className="border-b border-slate-100 px-5 py-3 text-sm font-bold text-slate-900">
              {group.name}
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
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{endpoint.body}</p>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>
    </Section>
  );
}

function Disclaimer({ copy }: { copy: Copy }) {
  return (
    <aside
      className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900"
      role="note"
    >
      <p className="font-semibold">{copy.disclaimerTitle}</p>
      <p className="mt-1 leading-relaxed text-amber-900/90">{copy.disclaimerBody}</p>
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
