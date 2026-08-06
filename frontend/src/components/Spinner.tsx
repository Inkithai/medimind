import { classNames } from "../utils/format";

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={classNames("animate-spin", className || "h-4 w-4")}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

export function LoadingState({
  label,
  description,
}: {
  label: string;
  description?: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-6 text-slate-600">
      <Spinner className="h-5 w-5 text-brand-600" />
      <div>
        <p className="text-sm font-medium text-slate-800">{label}</p>
        {description && <p className="text-xs text-slate-500">{description}</p>}
      </div>
    </div>
  );
}
