import { Link } from "react-router-dom";

/** Optional branch only. Never auto-opens Find Care and never picks a facility. */
export function ConsiderProfessionalCare({
  message = "Consider discussing this with a healthcare professional.",
}: {
  message?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
      <p>{message}</p>
      <p className="mt-2">
        <Link to="/find-care" className="font-medium text-brand-600 hover:text-brand-700">
          Find nearby care
        </Link>
        <span className="text-slate-500"> — optional. MediMind will not choose a facility for you.</span>
      </p>
    </div>
  );
}
