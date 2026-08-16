import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Spinner } from "../components/Spinner";
import { BeakerIcon, ChartIcon, PillIcon, ShieldIcon, UploadIcon, SparkleIcon } from "../components/icons";

export function LandingPage() {
  const { isConfigured, isInitializing, initError, createNewWorkspace } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (isConfigured && !isInitializing) {
      navigate("/dashboard", { replace: true });
    }
  }, [isConfigured, isInitializing, navigate]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-brand-50">
      {/* Header */}
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
            <span className="text-lg font-bold">M</span>
          </div>
          <div>
            <p className="text-lg font-bold leading-tight text-slate-900">MediMind</p>
            <p className="text-xs text-slate-500">Your health, in one place</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate("/about")}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            About
          </button>
          {isConfigured && (
            <button
              onClick={() => navigate("/dashboard")}
              className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Go to workspace
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 pb-20 pt-8">
        <div className="grid gap-12 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
          <div className="space-y-8">
            <div className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700">
              <span className="h-2 w-2 animate-pulse rounded-full bg-brand-600" />
              No sign-up • Anonymous browser-held workspace
            </div>

            <div className="space-y-4">
              <h1 className="text-4xl font-bold leading-tight tracking-tight text-slate-900 sm:text-5xl">
                Understand your medical documents in one place.
              </h1>
              <p className="max-w-xl text-lg leading-relaxed text-slate-600">
                Upload prescriptions, lab reports, and discharge summaries. MediMind finds the medicines,
                test results, and allergies inside, builds your personal health history, watches for safety
                issues, and answers your questions inside an anonymous workspace whose access key stays in this browser.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {isInitializing ? (
                <div className="flex items-center gap-2 rounded-xl bg-slate-100 px-5 py-3 text-sm font-medium text-slate-600">
                  <Spinner className="h-4 w-4" />
                  Creating your private workspace…
                </div>
              ) : initError ? (
                <div className="space-y-3">
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                    We couldn't set up your workspace: {initError}. Please check your connection and try
                    again.
                  </div>
                  <button
                    onClick={() => void createNewWorkspace()}
                    className="rounded-xl bg-slate-900 px-6 py-3 text-sm font-semibold text-white hover:bg-slate-800"
                  >
                    Retry creating workspace
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => navigate("/dashboard")}
                  className="group inline-flex items-center gap-2 rounded-xl bg-brand-600 px-7 py-3.5 text-base font-semibold text-white shadow-lg shadow-brand-600/20 hover:bg-brand-700"
                >
                  <UploadIcon className="h-5 w-5" />
                  Start My Health Record
                  <span className="ml-1 transition group-hover:translate-x-0.5">→</span>
                </button>
              )}
              <p className="text-xs text-slate-500">
                No email. No password. Your workspace ID stays in this browser only.
              </p>
            </div>

            <div className="grid gap-4 pt-4 sm:grid-cols-3">
              <Feature
                icon={<UploadIcon className="h-5 w-5" />}
                title="Upload reports"
                desc="PDF, JPG, PNG, WebP — printed or scanned"
              />
              <Feature
                icon={<PillIcon className="h-5 w-5" />}
                title="See your history"
                desc="Medicines, labs and visits in date order"
              />
              <Feature
                icon={<SparkleIcon className="h-5 w-5" />}
                title="Ask questions"
                desc="Answers from your own documents, with sources"
              />
            </div>
          </div>

          {/* Right visual */}
          <div className="relative">
            <div className="rounded-[24px] border border-slate-200 bg-white p-6 shadow-xl shadow-slate-200/60">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-slate-800">Patient workspace</p>
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 ring-1 ring-emerald-200">
                  Anonymous
                </span>
              </div>

              <div className="mt-5 space-y-3">
                <Step done label="Open MediMind" sub="Nothing to install, nothing to sign up for" />
                <Step done label="Your private workspace is ready" sub="Created automatically; its access key stays in this browser" />
                <Step active label="Upload medical documents" sub="Prescriptions • Lab reports • Discharge summaries" />
                <Step label="We read them for you" sub="Medicines, lab results, allergies, safety alerts" />
                <Step label="Your health record comes together" />
                <Step label="Browse history, track trends, ask questions" />
              </div>
            </div>

            <div className="absolute -bottom-6 -left-6 -z-10 h-32 w-32 rounded-full bg-brand-100 blur-2xl" />
            <div className="absolute -top-6 -right-6 -z-10 h-32 w-32 rounded-full bg-sky-100 blur-2xl" />
          </div>
        </div>

        {/* Pillars */}
        <div className="mt-20 grid gap-6 rounded-[20px] border border-slate-200 bg-white p-6 sm:grid-cols-2 lg:grid-cols-4">
          <Pillar
            icon={<PillIcon className="h-5 w-5" />}
            title="My Medicines"
            items={["Current & historical", "Source: file • page", "Traceability"]}
          />
          <Pillar
            icon={<BeakerIcon className="h-5 w-5" />}
            title="Test Results"
            items={["Value, range, flag", "Trend across visits", "Approaching threshold"]}
          />
          <Pillar
            icon={<ShieldIcon className="h-5 w-5" />}
            title="Safety Warnings"
            items={["Interactions", "Duplicates", "Allergy conflicts"]}
          />
          <Pillar
            icon={<ChartIcon className="h-5 w-5" />}
            title="Ask"
            items={["Answers from your records", "Source file & page cited", "Follow-up questions"]}
          />
        </div>
      </main>
    </div>
  );
}

function Feature({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="flex gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
        {icon}
      </div>
      <div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
        <p className="text-xs text-slate-500">{desc}</p>
      </div>
    </div>
  );
}

function Step({
  label,
  sub,
  done,
  active,
}: {
  label: string;
  sub?: string;
  done?: boolean;
  active?: boolean;
}) {
  return (
    <div className="flex gap-3">
      <div
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
          done
            ? "bg-emerald-600 text-white"
            : active
            ? "bg-brand-600 text-white ring-4 ring-brand-100"
            : "bg-slate-100 text-slate-400"
        }`}
      >
        {done ? "✓" : active ? "●" : "○"}
      </div>
      <div>
        <p className={`text-sm ${active ? "font-semibold text-slate-900" : "font-medium text-slate-700"}`}>
          {label}
        </p>
        {sub && <p className="text-xs text-slate-500">{sub}</p>}
      </div>
    </div>
  );
}

function Pillar({ icon, title, items }: { icon: React.ReactNode; title: string; items: string[] }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white">{icon}</div>
        <p className="text-sm font-semibold text-slate-900">{title}</p>
      </div>
      <ul className="mt-3 space-y-1.5">
        {items.map((it) => (
          <li key={it} className="flex items-center gap-2 text-xs text-slate-600">
            <span className="h-1 w-1 rounded-full bg-slate-400" />
            {it}
          </li>
        ))}
      </ul>
    </div>
  );
}
