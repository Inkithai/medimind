// Formatting helpers shared across pages.

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const pct = Math.round(value * 100);
  return `${pct}%`;
}

export function confidenceTone(value: number | null | undefined): string {
  if (value === null || value === undefined) return "bg-slate-100 text-slate-600";
  if (value >= 0.85) return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (value >= 0.6) return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
  return "bg-red-50 text-red-700 ring-1 ring-red-200";
}

export function severityTone(severity: string): string {
  switch (severity) {
    case "high":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "moderate":
      return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
    case "low":
      return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

export function flagTone(flag: string): string {
  switch (flag) {
    case "high":
      return "bg-red-50 text-red-700 ring-1 ring-red-200";
    case "low":
      return "bg-blue-50 text-blue-700 ring-1 ring-blue-200";
    case "normal":
      return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

export function directionTone(direction: string): string {
  if (direction.startsWith("increasing"))
    return "bg-red-50 text-red-700 ring-1 ring-red-200";
  if (direction.startsWith("decreasing"))
    return "bg-blue-50 text-blue-700 ring-1 ring-blue-200";
  if (direction === "stable") return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
}

// Renders a date string as-is but normalizes ISO timestamps to a readable form.
// Returns "—" for null/empty. Backend dates are often free-form ("05 Jan 2026"),
// so we only prettify strict ISO values and leave the rest untouched.
export function formatDate(date: string | null | undefined): string {
  if (!date) return "—";
  const trimmed = date.trim();
  if (!trimmed) return "—";
  // ISO-ish: YYYY-MM-DD or full ISO timestamp
  if (/^\d{4}-\d{2}-\d{2}/.test(trimmed)) {
    const d = new Date(trimmed);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    }
  }
  return trimmed;
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function classNames(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// Human-readable label for the backend's document_type enum.
export function documentTypeLabel(type: string): string {
  switch (type) {
    case "prescription":
      return "Prescription";
    case "lab_report":
      return "Lab report";
    case "discharge_summary":
      return "Discharge summary";
    default:
      return "Other";
  }
}

export function truncate(text: string, max = 120): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1).trimEnd() + "…";
}
