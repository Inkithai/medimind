import type { ReactNode } from "react";
import { classNames } from "../../utils/format";

/**
 * Diagram primitives for the About page.
 *
 * Built from flex/grid rather than a fixed-width SVG so they reflow instead
 * of scrolling horizontally on a phone: a horizontal chain on desktop
 * becomes a vertical stack on mobile, with the connector arrows rotating to
 * match.
 *
 * Accessibility: each diagram is wrapped in a <figure> with a caption and is
 * marked `role="img"` with an accessible name, while the same information is
 * repeated as real text in the surrounding section — so nothing is available
 * only to sighted users. Connector glyphs are decorative and hidden.
 */

export function Figure({
  label,
  caption,
  children,
}: {
  label: string;
  caption?: string;
  children: ReactNode;
}) {
  return (
    <figure className="not-prose">
      <div role="img" aria-label={label}>
        {children}
      </div>
      {caption && (
        <figcaption className="mt-3 text-xs text-slate-500">{caption}</figcaption>
      )}
    </figure>
  );
}

/** A single step/box in a diagram. */
export function Node({
  title,
  subtitle,
  tone = "slate",
  icon,
  className,
}: {
  title: string;
  subtitle?: string;
  tone?: NodeTone;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={classNames(
        "flex w-full flex-col rounded-xl border px-3.5 py-3 text-left shadow-sm",
        TONES[tone],
        className
      )}
    >
      <span className="flex items-center gap-2">
        {icon && <span className="shrink-0 opacity-80">{icon}</span>}
        <span className="text-sm font-semibold leading-snug">{title}</span>
      </span>
      {subtitle && (
        <span className="mt-1 text-xs leading-relaxed opacity-80">{subtitle}</span>
      )}
    </div>
  );
}

/**
 * Vertical chain of nodes with connectors between them — the layout used for
 * the layered architecture and the pipeline, where order matters.
 */
export function Flow({ children }: { children: ReactNode[] }) {
  const steps = children.filter(Boolean);
  return (
    <div className="flex flex-col">
      {steps.map((step, index) => (
        <div key={index}>
          {step}
          {index < steps.length - 1 && <Connector />}
        </div>
      ))}
    </div>
  );
}

/** Downward connector. Decorative — the order is conveyed by the text too. */
export function Connector({ className }: { className?: string }) {
  return (
    <div
      className={classNames("flex justify-center py-1.5", className)}
      aria-hidden="true"
    >
      <svg viewBox="0 0 12 20" className="h-4 w-3 text-slate-300" fill="none" stroke="currentColor" strokeWidth={1.5}>
        <path d="M6 0v14" />
        <path d="M1.5 10.5 6 15l4.5-4.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export type NodeTone = "slate" | "brand" | "sky" | "emerald" | "violet" | "amber" | "rose";

const TONES: Record<NodeTone, string> = {
  slate: "border-slate-200 bg-white text-slate-800",
  brand: "border-brand-200 bg-brand-50 text-brand-900",
  sky: "border-sky-200 bg-sky-50 text-sky-900",
  emerald: "border-emerald-200 bg-emerald-50 text-emerald-900",
  violet: "border-violet-200 bg-violet-50 text-violet-900",
  amber: "border-amber-200 bg-amber-50 text-amber-900",
  rose: "border-rose-200 bg-rose-50 text-rose-900",
};

/** Small monospace chip for a technology name. */
export function TechChip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-block rounded-md bg-white/70 px-1.5 py-0.5 font-mono text-[11px] font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
      {children}
    </span>
  );
}
