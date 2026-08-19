import type { ReactNode } from "react";
import { classNames } from "../utils/format";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={classNames(
        "min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-w-0 flex-col items-start justify-between gap-3 border-b border-slate-100 px-4 py-4 sm:flex-row sm:gap-4 sm:px-5">
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
        </div>
      </div>
      {action && <div className="max-w-full shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={classNames("min-w-0 px-4 py-4 sm:px-5", className)}>{children}</div>;
}
