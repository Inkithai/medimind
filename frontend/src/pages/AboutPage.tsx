import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import {
  AppointmentIcon,
  BeakerIcon,
  ChangesIcon,
  ChatIcon,
  FileIcon,
  InfoIcon,
  IntegrityIcon,
  LocationIcon,
  ReminderIcon,
  ShieldIcon,
  SparkleIcon,
  UploadIcon,
} from "../components/icons";
import { useAuth } from "../context/AuthContext";

const CAPABILITIES = [
  {
    title: "Build a clinical memory",
    description: "Upload prescriptions, laboratory reports, and discharge summaries. MediMind extracts structured visits, medicines, tests, allergies, and notes into one patient-scoped timeline.",
    icon: UploadIcon,
    tone: "bg-sky-50 text-sky-700",
    items: ["PDF and image extraction", "Medical relevance checks", "Multilingual medicine normalization"],
    to: "/documents",
  },
  {
    title: "Understand change over time",
    description: "Deterministic engines compare dated records and laboratory values without asking a language model to calculate the trend.",
    icon: ChangesIcon,
    tone: "bg-indigo-50 text-indigo-700",
    items: ["Lab direction and range crossings", "Before-and-after record changes", "Conservative medication wording"],
    to: "/changes",
  },
  {
    title: "Verify before trusting",
    description: "Record Integrity shows possible identity, allergy, same-date lab, and medication-instruction discrepancies side by side instead of silently selecting a winner.",
    icon: IntegrityIcon,
    tone: "bg-orange-50 text-orange-700",
    items: ["Both source records shown", "Specific verification guidance", "No automatic clinical correction"],
    to: "/record-integrity",
  },
  {
    title: "Review medication safety",
    description: "MediMind compares medication history and documented allergies to surface potential interactions, duplicate prescriptions, conflicting instructions, and allergy conflicts for professional review.",
    icon: ShieldIcon,
    tone: "bg-amber-50 text-amber-700",
    items: ["Interaction severity", "Duplicate and dosage checks", "Professional-review guardrails"],
    to: "/safety",
  },
  {
    title: "Ask with evidence",
    description: "Questions are routed to matching record categories. MediMind checks evidence coverage, validates returned citations, and lowers confidence when the available support is limited.",
    icon: ChatIcon,
    tone: "bg-brand-50 text-brand-700",
    items: ["Patient-scoped retrieval", "Intent-aware evidence selection", "Citation validation and confidence caps"],
    to: "/ask",
  },
  {
    title: "Prepare to act",
    description: "Appointment Prep turns safety findings, trends, and recent changes into a printable handoff and prioritized questions for a clinician.",
    icon: AppointmentIcon,
    tone: "bg-cyan-50 text-cyan-800",
    items: ["Latest documented medication list", "Record-backed clinician questions", "Printable visit checklist"],
    to: "/appointment-prep",
  },
  {
    title: "Keep track of follow-up",
    description: "The Action Center combines findings into one queue. You choose reminder dates, track completion locally, and can export reminders to a calendar.",
    icon: ReminderIcon,
    tone: "bg-fuchsia-50 text-fuchsia-700",
    items: ["Stable grounded tasks", "Browser-only task state", "No invented clinical deadlines"],
    to: "/follow-up",
  },
  {
    title: "Navigate nearby care",
    description: "Record-derived specialty suggestions connect to a provider-neutral public directory with location search, map confirmation, and nearby facility details.",
    icon: LocationIcon,
    tone: "bg-rose-50 text-rose-700",
    items: ["Specialty relevance from records", "Coordinate-based nearby search", "Public listing—not clinical referral"],
    to: "/find-care",
  },
];

const ROADMAP = [
  {
    priority: "Next",
    title: "Persistent correction and conflict resolution",
    description: "Let a patient or clinician correct an extraction, choose the verified source, preserve an audit trail, and rebuild snapshots and the retrieval index safely.",
  },
  {
    priority: "Next",
    title: "Conflict-aware retrieval quarantine",
    description: "Prevent unresolved identity or fact discrepancies from being treated as settled evidence in trends and Q&A—not merely display a warning after ingestion.",
  },
  {
    priority: "Next",
    title: "Page-level evidence highlighting",
    description: "Map every extracted fact and answer claim to a document page and highlighted region, with source-quality and provenance details.",
  },
  {
    priority: "Then",
    title: "Broader longitudinal clinical entities",
    description: "Track diagnoses, symptoms, procedures, vitals, and imaging findings with validated terminology and unit normalization—not just medicines and labs.",
  },
  {
    priority: "Then",
    title: "Secure export, deletion, and clinician sharing",
    description: "Add full data export, server-side deletion and retention controls, plus a consented, time-limited handoff link for a healthcare professional.",
  },
  {
    priority: "Later",
    title: "Delivered reminders and care coordination",
    description: "Optional push/email reminders, verified provider availability, and appointment handoff workflows. Current reminders are browser-managed calendar events only.",
  },
];

export function AboutPage() {
  const { isConfigured } = useAuth();

  return (
    <div className="space-y-10 pb-10">
      <section className="relative overflow-hidden rounded-3xl border border-brand-100 bg-gradient-to-br from-brand-900 via-brand-800 to-slate-900 px-6 py-10 text-white shadow-xl sm:px-10 sm:py-14">
        <div className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="absolute -bottom-32 left-1/3 h-72 w-72 rounded-full bg-brand-300/10 blur-3xl" />
        <div className="relative max-w-3xl">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.12em] text-brand-50">
            <InfoIcon className="h-4 w-4" /> About MediMind
          </div>
          <h1 className="mt-5 text-4xl font-bold leading-tight tracking-tight sm:text-5xl">
            A continuously understandable clinical memory—grounded in your records.
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-brand-50/85">
            MediMind does more than read one report. It assembles a longitudinal patient record, computes changes with deterministic engines, retrieves patient-scoped evidence, and helps turn findings into safer conversations and next steps.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            {isConfigured ? (
              <Link to="/dashboard" className="btn bg-white text-brand-800 hover:bg-brand-50">Open my workspace →</Link>
            ) : (
              <Link to="/" className="btn bg-white text-brand-800 hover:bg-brand-50">Start a private workspace →</Link>
            )}
            <a href="#how-it-works" className="btn border border-white/25 bg-white/5 text-white hover:bg-white/10">How it works</a>
          </div>
        </div>
      </section>

      <section>
        <SectionHeading eyebrow="Available now" title="What has been built" description="The current product spans understanding, verification, evidence-grounded answers, and action—not just document summarization." />
        <div className="mt-6 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {CAPABILITIES.map((capability) => {
            const Icon = capability.icon;
            const content = (
              <>
                <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${capability.tone}`}><Icon className="h-5 w-5" /></div>
                <h3 className="mt-4 text-lg font-bold text-slate-900">{capability.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-600">{capability.description}</p>
                <ul className="mt-4 space-y-2">
                  {capability.items.map((item) => <li key={item} className="flex items-start gap-2 text-xs leading-relaxed text-slate-500"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-500" />{item}</li>)}
                </ul>
                {isConfigured && <p className="mt-5 text-sm font-semibold text-brand-700">Explore feature →</p>}
              </>
            );
            return isConfigured ? (
              <Link key={capability.title} to={capability.to} className="group rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md">{content}</Link>
            ) : (
              <article key={capability.title} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">{content}</article>
            );
          })}
        </div>
      </section>

      <section id="how-it-works" className="scroll-mt-8 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <SectionHeading eyebrow="Hybrid architecture" title="Deterministic where calculation matters. Generative where language helps." description="MediMind keeps numerical comparison, routing, integrity checks, and confidence guardrails outside the answer model." />
        <div className="mt-7 grid gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr] lg:items-stretch">
          <PipelineStep icon={<UploadIcon className="h-5 w-5" />} number="01" title="Understand" text="Extract structured facts, reject irrelevant content, and assemble a dated patient timeline." />
          <Arrow />
          <PipelineStep icon={<BeakerIcon className="h-5 w-5" />} number="02" title="Compute & verify" text="Calculate lab trends and changes; surface conflicting facts with both sources." />
          <Arrow />
          <PipelineStep icon={<SparkleIcon className="h-5 w-5" />} number="03" title="Explain & act" text="Retrieve matching evidence, answer with validated citations, prepare appointments, and organize follow-up." />
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-3xl border border-emerald-200 bg-emerald-50/60 p-6 sm:p-8">
          <SectionHeading eyebrow="Trust model" title="Safety boundaries built into the product" />
          <ul className="mt-6 space-y-4">
            <Boundary icon={<ShieldIcon className="h-5 w-5" />} title="Evidence before fluency" text="No matching record category means an explicit insufficient-evidence response, not a generic medical answer." />
            <Boundary icon={<FileIcon className="h-5 w-5" />} title="Omission is not resolution" text="A missing medicine is not called stopped, and a newly documented medicine is not automatically called newly started." />
            <Boundary icon={<IntegrityIcon className="h-5 w-5" />} title="Disagreement stays visible" text="The integrity layer never silently decides which conflicting source is clinically correct." />
            <Boundary icon={<ReminderIcon className="h-5 w-5" />} title="No invented deadlines" text="MediMind prioritizes a review queue, but reminder dates and clinical timing remain user- or clinician-selected." />
            <Boundary icon={<LocationIcon className="h-5 w-5" />} title="Directory, not referral" text="Nearby care comes from public listings and is not presented as a verified booking, endorsement, or “best doctor” ranking." />
          </ul>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <SectionHeading eyebrow="Data model" title="What “private workspace” means" />
          <div className="mt-6 space-y-4 text-sm leading-relaxed text-slate-600">
            <p><strong className="text-slate-900">No account is required.</strong> The browser stores an anonymous workspace identifier and signed access token so only that workspace can request its records.</p>
            <p><strong className="text-slate-900">Records are not stored only in the browser.</strong> Original files are archived in Cloudinary, structured records and snapshots in Supabase, and retrieval chunks in the configured Chroma or Supabase vector store.</p>
            <p><strong className="text-slate-900">Patient scoping is enforced on every authenticated API request.</strong> The token identity must match the workspace header, and data services use that patient key.</p>
            <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900"><strong>Still pending:</strong> full server-side deletion, retention controls, account recovery, and multi-device access. Do not treat the anonymous demo model as a completed healthcare compliance program.</p>
          </div>
        </div>
      </section>

      <section>
        <SectionHeading eyebrow="Honest roadmap" title="Highest-value features still pending" description="The next phase is primarily about making evidence correctable, governable, and safer to reuse—not adding another generic AI screen." />
        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {ROADMAP.map((item, index) => (
            <article key={item.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-wide ${item.priority === "Next" ? "bg-brand-100 text-brand-800" : item.priority === "Then" ? "bg-sky-100 text-sky-800" : "bg-slate-100 text-slate-700"}`}>{item.priority}</span>
                <span className="text-xs font-bold text-slate-300">{String(index + 1).padStart(2, "0")}</span>
              </div>
              <h3 className="mt-4 text-base font-bold text-slate-900">{item.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{item.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="rounded-3xl bg-slate-900 p-7 text-white sm:p-9">
        <div className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-brand-300">Product thesis</p>
            <h2 className="mt-2 text-2xl font-bold">Understand me. Show me the evidence. Help me prepare the next step.</h2>
            <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-300">MediMind is a patient record intelligence and preparation tool. It does not diagnose, prescribe, replace a clinician, provide emergency triage, or guarantee that extraction from a document is correct.</p>
          </div>
          {isConfigured && <Link to="/appointment-prep" className="btn bg-white text-slate-900 hover:bg-slate-100">Prepare my appointment →</Link>}
        </div>
      </section>
    </div>
  );
}

function SectionHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description?: string }) {
  return <div><p className="text-xs font-bold uppercase tracking-[0.14em] text-brand-700">{eyebrow}</p><h2 className="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">{title}</h2>{description && <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-600">{description}</p>}</div>;
}

function PipelineStep({ icon, number, title, text }: { icon: ReactNode; number: string; title: string; text: string }) {
  return <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5"><div className="flex items-center justify-between"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white">{icon}</span><span className="text-xs font-black tracking-wider text-slate-300">{number}</span></div><h3 className="mt-4 text-lg font-bold text-slate-900">{title}</h3><p className="mt-2 text-sm leading-relaxed text-slate-600">{text}</p></div>;
}

function Arrow() {
  return <div className="hidden items-center justify-center text-2xl text-brand-300 lg:flex" aria-hidden="true">→</div>;
}

function Boundary({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return <li className="flex items-start gap-3"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white text-emerald-700 shadow-sm ring-1 ring-emerald-100">{icon}</span><div><h3 className="text-sm font-bold text-slate-900">{title}</h3><p className="mt-1 text-sm leading-relaxed text-slate-600">{text}</p></div></li>;
}
