import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50/50 px-6 py-12 text-center"
    >
      {icon && <div className="text-slate-400">{icon}</div>}
      <div>
        <p className="text-sm font-semibold text-slate-700">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
