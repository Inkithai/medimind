import { Link } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";

/** Optional branch only. Never auto-opens Find Care and never picks a facility. */
export function ConsiderProfessionalCare({ message }: { message?: string }) {
  const { t } = useI18n();
  return (
    <aside
      className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700"
      aria-label={t("care.recommendation")}
    >
      <p>{message || t("care.discussDefault")}</p>
      <p className="mt-2">
        <Link to="/find-care" className="font-medium text-brand-700 hover:text-brand-800">
          {t("care.findNearby")}
        </Link>{" "}
        <span className="text-slate-600">— {t("care.optionalNoChoice")}</span>
      </p>
    </aside>
  );
}
