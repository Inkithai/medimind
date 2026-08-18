import { useMemo, useState } from "react";
import { PREP_CATEGORIES, PREP_ITEMS, type PrepCategory } from "./judgePrepData";

/**
 * Hidden competition Q&A sheet.
 * Reachable only by typing /ygc-prep — not in the sidebar, landing, or footer.
 */
export function JudgePrepPage() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<PrepCategory | "all">("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return PREP_ITEMS.filter((item) => {
      if (category !== "all" && item.category !== category) return false;
      if (!needle) return true;
      return (
        item.q.toLowerCase().includes(needle) ||
        item.say.toLowerCase().includes(needle) ||
        item.answer.toLowerCase().includes(needle)
      );
    });
  }, [category, query]);

  const grouped = useMemo(() => {
    return PREP_CATEGORIES.map((group) => ({
      ...group,
      items: filtered.filter((item) => item.category === group.id),
    })).filter((group) => group.items.length > 0);
  }, [filtered]);

  const expandAll = () => {
    const next: Record<string, boolean> = {};
    for (const item of filtered) next[item.id] = true;
    setOpen(next);
  };

  const collapseAll = () => setOpen({});

  return (
    <div className="judge-prep min-h-screen bg-[#0f172a] text-slate-100">
      <a href="#prep-main" className="skip-link">
        Skip to questions
      </a>

      <header className="sticky top-0 z-20 border-b border-white/10 bg-[#0f172a]/95 backdrop-blur">
        <div className="mx-auto max-w-5xl px-4 py-4 sm:px-6">
          <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-teal-300">
            Hidden route · /ygc-prep · not in the app navigation
          </p>
          <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white sm:text-3xl">
                Judge Q&amp;A prep
              </h1>
              <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-300">
                Spoken answers for YGC Final Round. Only implemented behaviour.
                Hard questions are marked. Open a card, say the highlighted line first.
              </p>
            </div>
            <p className="rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-semibold text-slate-200">
              {filtered.length} / {PREP_ITEMS.length} questions
            </p>
          </div>

          <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="block min-w-0 flex-1">
              <span className="sr-only">Search questions</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search: RAG, FHIR, fake doctors, diagnosis…"
                className="w-full rounded-xl border border-white/15 bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-slate-400 focus:border-teal-400 focus:outline-none focus:ring-2 focus:ring-teal-400/40"
              />
            </label>
            <div className="flex shrink-0 gap-2">
              <button type="button" onClick={expandAll} className="prep-btn">
                Expand all
              </button>
              <button type="button" onClick={collapseAll} className="prep-btn">
                Collapse
              </button>
            </div>
          </div>

          <nav aria-label="Question categories" className="mt-3 flex gap-2 overflow-x-auto pb-1">
            <CategoryChip
              active={category === "all"}
              onClick={() => setCategory("all")}
              label={`All (${PREP_ITEMS.length})`}
            />
            {PREP_CATEGORIES.map((group) => {
              const count = PREP_ITEMS.filter((item) => item.category === group.id).length;
              return (
                <CategoryChip
                  key={group.id}
                  active={category === group.id}
                  onClick={() => setCategory(group.id)}
                  label={`${group.label} (${count})`}
                />
              );
            })}
          </nav>
        </div>
      </header>

      <main id="prep-main" tabIndex={-1} className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        {grouped.length === 0 && (
          <p className="rounded-xl border border-white/10 bg-white/5 px-4 py-8 text-center text-sm text-slate-300">
            No questions match that search.
          </p>
        )}

        <div className="space-y-10">
          {grouped.map((group) => (
            <section key={group.id} aria-labelledby={`prep-${group.id}`}>
              <div className="mb-3">
                <h2 id={`prep-${group.id}`} className="text-lg font-bold text-white">
                  {group.label}
                </h2>
                <p className="text-sm text-slate-400">{group.blurb}</p>
              </div>
              <ul className="space-y-2">
                {group.items.map((item, index) => {
                  const isOpen = Boolean(open[item.id]);
                  return (
                    <li key={item.id}>
                      <article className="overflow-hidden rounded-xl border border-white/10 bg-white/[0.04]">
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          onClick={() =>
                            setOpen((current) => ({ ...current, [item.id]: !current[item.id] }))
                          }
                          className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-white/[0.04]"
                        >
                          <span className="mt-0.5 w-8 shrink-0 font-mono text-xs font-bold text-teal-300">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-semibold leading-snug text-white sm:text-base">
                                {item.q}
                              </span>
                              {item.hard && (
                                <span className="rounded-full bg-amber-400/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-300">
                                  Hard
                                </span>
                              )}
                            </span>
                          </span>
                          <span aria-hidden="true" className="mt-1 text-slate-400">
                            {isOpen ? "−" : "+"}
                          </span>
                        </button>
                        {isOpen && (
                          <div className="space-y-3 border-t border-white/10 px-4 py-4 sm:pl-16">
                            <p className="rounded-lg border border-teal-400/30 bg-teal-400/10 px-3 py-2 text-sm leading-relaxed text-teal-50">
                              <span className="mr-2 text-[10px] font-bold uppercase tracking-wider text-teal-300">
                                Say
                              </span>
                              {item.say}
                            </p>
                            <p className="text-sm leading-relaxed text-slate-200">{item.answer}</p>
                          </div>
                        )}
                      </article>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      </main>

      <style>{`
        .prep-btn {
          min-height: 44px;
          padding: 0 0.9rem;
          border-radius: 0.75rem;
          border: 1px solid rgba(255,255,255,0.15);
          background: rgba(255,255,255,0.05);
          color: #e2e8f0;
          font-size: 0.8rem;
          font-weight: 600;
        }
        .prep-btn:hover { background: rgba(255,255,255,0.1); }
        @media print {
          .judge-prep { background: white; color: #0f172a; }
          .judge-prep header { position: static; background: white; color: #0f172a; }
          .judge-prep article { break-inside: avoid; border-color: #cbd5e1; }
          .judge-prep button { color: #0f172a; }
        }
      `}</style>
    </div>
  );
}

function CategoryChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold transition ${
        active
          ? "bg-teal-400 text-slate-950"
          : "border border-white/15 bg-white/5 text-slate-200 hover:bg-white/10"
      }`}
    >
      {label}
    </button>
  );
}
