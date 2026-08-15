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

  // A date-only string is a CALENDAR date, not an instant. `new Date(
  // "2026-08-07")` parses as UTC midnight, which renders as Aug 6 anywhere
  // west of UTC — a medical record must never show the wrong day. Build it
  // in local time instead so it displays as written.
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (dateOnly) {
    const year = Number(dateOnly[1]);
    const month = Number(dateOnly[2]);
    const day = Number(dateOnly[3]);
    const d = new Date(year, month - 1, day);
    // JS rolls impossible dates over ("2026-13-01" -> Jan 1 2027), which
    // would show a date the record never contained. An OCR misread must be
    // surfaced as-is, not silently converted into a plausible-looking one.
    const isRealDate =
      !Number.isNaN(d.getTime()) &&
      d.getFullYear() === year &&
      d.getMonth() === month - 1 &&
      d.getDate() === day;
    if (isRealDate) {
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    }
    return trimmed;
  }

  // A full timestamp carries its own offset, so let Date handle it.
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

// Relative recency for lists, e.g. "Yesterday", "3 days ago", "Last week".
// Falls back to formatDate for anything older than a month or unparseable.
export function relativeTime(date: string | null | undefined): string {
  if (!date) return "—";
  const trimmed = date.trim();
  if (!trimmed) return "—";
  const d = new Date(trimmed);
  if (Number.isNaN(d.getTime())) return trimmed;
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 14) return "Last week";
  if (days < 31) return `${Math.floor(days / 7)} weeks ago`;
  return formatDate(trimmed);
}

// Human file size: "1.2 MB", "340 KB".
export function fileSizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
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
