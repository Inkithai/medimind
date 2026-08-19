/**
 * Preventive care — screening and immunisation reminders from
 * GET /api/v1/preventive-care.
 *
 * This is a restored screen: the backend has always computed care gaps and
 * the app has always advertised them in its copy, but /preventive-care
 * redirected to the Action Center and the reminders were only visible as a
 * small inline strip there. It now has its own tab under Next steps.
 *
 * The reminders are general, age/sex/condition-based prompts — never a
 * statement that the patient is overdue for something specific, and never a
 * diagnosis. When the profile is incomplete the page says which field is
 * missing rather than showing an empty list.
 */
import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Card, CardBody } from "../components/Card";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";
import { ReminderIcon, SettingsIcon } from "../components/icons";
import type { EmbeddedPageProps } from "../components/TabBar";
import { useAuth } from "../context/AuthContext";
import { useStrictEffect } from "../hooks/useStrictEffect";
import { useI18n } from "../i18n/I18nContext";
import type { CareGap, PreventiveCareReport } from "../types/api";

const KIND_LABELS: Record<string, string> = {
  vaccination: "Vaccination",
  screening: "Screening",
  monitoring: "Monitoring",
};

function kindLabel(kind: string) {
  return KIND_LABELS[kind] || kind || "Reminder";
}

/** "soon" is the only priority the backend escalates; everything else is routine. */
function priorityTone(priority: string): "warning" | "neutral" {
  return String(priority).toLowerCase() === "soon" ? "warning" : "neutral";
}

export function PreventiveCarePage({ embedded }: EmbeddedPageProps = {}) {
  const { credentials } = useAuth();
  const { t } = useI18n();
  const [report, setReport] = useState<PreventiveCareReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await api.getPreventiveCare(credentials));
    } catch (err) {
      setReport(null);
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [credentials]);

  useStrictEffect(() => {
    void load();
  }, [load]);

  const gaps: CareGap[] = report?.care_gaps || [];
  // Age and sex drive most of the rules, so an empty list usually means an
  // incomplete profile rather than "nothing is due".
  const profileIncomplete = report != null && (report.age == null || !report.sex);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        {embedded ? (
          <p className="secondary-text max-w-2xl">{t("preventive.subtitle")}</p>
        ) : (
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-brand-700">
              <ReminderIcon className="h-4 w-4" /> {t("preventive.eyebrow")}
            </div>
            <h1 className="page-title mt-1">{t("preventive.title")}</h1>
            <p className="secondary-text mt-2 max-w-2xl">{t("preventive.subtitle")}</p>
          </div>
        )}
      </header>

      {loading && <LoadingState label={t("preventive.loading")} />}

      {!loading && error !== null && <ErrorState error={error} onRetry={() => void load()} />}

      {!loading && report && (
        <>
          <div className="rounded-2xl border border-sky-100 bg-sky-50/70 p-5 text-sm leading-relaxed text-sky-900">
            <p className="font-semibold">{t("preventive.generalTitle")}</p>
            <p className="mt-1">{report.note || t("preventive.generalBody")}</p>
          </div>

          {profileIncomplete && (
            <Card>
              <CardBody className="flex flex-wrap items-center justify-between gap-4">
                <div className="min-w-0">
                  <p className="font-semibold text-slate-900">{t("preventive.profileTitle")}</p>
                  <p className="secondary-text mt-1">
                    {report.age == null && !report.sex
                      ? t("preventive.profileBodyBoth")
                      : report.age == null
                        ? t("preventive.profileBodyAge")
                        : t("preventive.profileBodySex")}
                  </p>
                </div>
                <Link to="/settings" className="btn-secondary shrink-0">
                  <SettingsIcon className="h-4 w-4" aria-hidden="true" />
                  {t("preventive.openSettings")}
                </Link>
              </CardBody>
            </Card>
          )}

          {gaps.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {gaps.map((gap, index) => (
                <article
                  key={`${gap.kind}-${gap.title}-${index}`}
                  className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge tone="info">{kindLabel(gap.kind)}</StatusBadge>
                    <StatusBadge tone={priorityTone(gap.priority)}>{gap.priority}</StatusBadge>
                  </div>
                  <h2 className="mt-3 card-title">{gap.title}</h2>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">{gap.detail}</p>
                </article>
              ))}
            </div>
          ) : (
            !profileIncomplete && (
              <Card>
                <CardBody className="py-12 text-center">
                  <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
                    <ReminderIcon className="h-7 w-7" />
                  </div>
                  <h2 className="mt-4 section-title">{t("preventive.emptyTitle")}</h2>
                  <p className="mx-auto mt-2 max-w-lg text-sm text-slate-500">
                    {t("preventive.emptyBody")}
                  </p>
                </CardBody>
              </Card>
            )
          )}

          <p className="text-xs leading-relaxed text-slate-500">{t("preventive.disclaimer")}</p>
        </>
      )}
    </div>
  );
}
