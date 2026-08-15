import { useCopy } from "../../i18n";
import type { CareFacility, FacilityKind } from "../../types/facility";
import { classNames } from "../../utils/format";
import { googleMapsUrl, telHref } from "../../utils/facilities";
import { LocationIcon } from "../icons";

/**
 * One care result.
 *
 * Rules enforced here:
 * - The heading is always the real provider name from the directory.
 * - Rating, reviews, phone, hours, and address render only when the directory
 *   supplied them; otherwise an explicit "not available" line is shown. No
 *   value is ever fabricated.
 * - "Open in Google Maps" always points at Google Maps.
 */
export function FacilityCard({
  facility,
  isActive,
  onFocusFacility,
}: {
  facility: CareFacility;
  isActive?: boolean;
  onFocusFacility?: (facility: CareFacility) => void;
}) {
  const copy = useCopy();
  const mapsHref = googleMapsUrl(facility);
  const callHref = telHref(facility.phone);
  const headingId = `facility-${facility.id}-name`;

  return (
    <article
      aria-labelledby={headingId}
      onMouseEnter={() => onFocusFacility?.(facility)}
      className={classNames(
        "flex flex-col rounded-2xl border bg-white p-5 shadow-sm transition focus-within:ring-2 focus-within:ring-brand-500 hover:-translate-y-0.5 hover:shadow-md",
        isActive ? "border-brand-400 ring-2 ring-brand-200" : "border-slate-200"
      )}
    >
      <div className="flex items-start gap-3">
        <span
          className={classNames(
            "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl",
            kindTone(facility.kind)
          )}
          aria-hidden="true"
        >
          <CareIcon className="h-5 w-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id={headingId} className="text-base font-bold leading-snug text-slate-900">
            {facility.name}
          </h3>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-slate-600">
              {kindLabel(facility.kind, copy)}
            </span>
            {facility.openNow !== undefined && (
              <span
                className={classNames(
                  "rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider",
                  facility.openNow ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"
                )}
              >
                {facility.openNow ? copy.findCare.openNow : copy.findCare.closedNow}
              </span>
            )}
            {facility.specialtyMatch && facility.specialty && (
              <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-brand-700">
                {copy.findCare.specialtyMatch(facility.specialty)}
              </span>
            )}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <Rating facility={facility} />
            <span
              className={
                facility.distanceKm !== null ? "font-semibold text-brand-700" : "text-slate-400"
              }
            >
              {facility.distanceKm !== null
                ? copy.findCare.distanceAway(distanceLabel(facility.distanceKm))
                : copy.findCare.distanceNotAvailable}
            </span>
          </div>
        </div>
      </div>

      <dl className="mt-4 flex-1 space-y-2 border-t border-slate-100 pt-4 text-sm">
        <div className="flex gap-2">
          <dt className="sr-only">Address</dt>
          <span aria-hidden="true">📍</span>
          <dd className={facility.address ? "text-slate-600" : "italic text-slate-400"}>
            {facility.address || copy.findCare.addressNotAvailable}
          </dd>
        </div>

        <div className="flex gap-2">
          <dt className="sr-only">Phone</dt>
          <span aria-hidden="true">📞</span>
          <dd>
            {callHref ? (
              <a href={callHref} className="font-medium text-brand-700 hover:underline">
                {facility.phone}
              </a>
            ) : (
              <span className="italic text-slate-400">{copy.findCare.phoneNotAvailable}</span>
            )}
          </dd>
        </div>

        <div className="flex gap-2">
          <dt className="sr-only">{copy.findCare.openingHours}</dt>
          <span aria-hidden="true">🕐</span>
          <dd className="min-w-0">
            {facility.openingHours?.length ? (
              <details className="group">
                <summary className="cursor-pointer font-medium text-slate-700 hover:underline">
                  {facility.openNow === undefined
                    ? copy.findCare.openingHours
                    : facility.openNow
                      ? copy.findCare.openNow
                      : copy.findCare.closedNow}
                </summary>
                <ul className="mt-1 space-y-0.5 text-xs text-slate-500">
                  {facility.openingHours.map((hours) => (
                    <li key={hours}>{hours}</li>
                  ))}
                </ul>
              </details>
            ) : facility.openNow !== undefined ? (
              <span className="text-slate-600">
                {facility.openNow ? copy.findCare.openNow : copy.findCare.closedNow}
              </span>
            ) : (
              <span className="italic text-slate-400">{copy.findCare.hoursNotAvailable}</span>
            )}
          </dd>
        </div>
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        <a
          href={mapsHref}
          target="_blank"
          rel="noreferrer"
          aria-label={copy.findCare.openInGoogleMapsAria(facility.name)}
          className="btn-primary min-h-[44px] flex-1 justify-center px-4 py-2 text-sm sm:flex-none"
        >
          <LocationIcon className="h-4 w-4" aria-hidden="true" /> {copy.findCare.openInGoogleMaps}
        </a>
        {callHref && (
          <a
            href={callHref}
            aria-label={copy.findCare.callAria(facility.name)}
            className="btn-secondary min-h-[44px] flex-1 justify-center px-4 py-2 text-sm sm:flex-none"
          >
            <span aria-hidden="true">📞</span> {copy.findCare.call}
          </a>
        )}
        {facility.website && (
          <a
            href={facility.website}
            target="_blank"
            rel="noreferrer"
            aria-label={copy.findCare.websiteAria(facility.name)}
            className="btn-ghost min-h-[44px] px-4 py-2 text-sm"
          >
            {copy.findCare.website}
          </a>
        )}
      </div>

      <p className="mt-3 text-[11px] text-slate-400">
        {copy.findCare.sourcePrefix}: {facility.source} · {copy.findCare.notARecommendation}
      </p>
    </article>
  );
}

function Rating({ facility }: { facility: CareFacility }) {
  const copy = useCopy();
  if (facility.rating === undefined) {
    return <span className="italic text-slate-400">{copy.findCare.noRating}</span>;
  }
  const rating = facility.rating.toFixed(1);
  const count = facility.userRatingCount;
  const reviewsText =
    count === undefined
      ? null
      : count === 1
        ? copy.findCare.review
        : copy.findCare.reviews(count.toLocaleString());
  return (
    <span
      className="text-amber-700"
      aria-label={
        reviewsText
          ? copy.findCare.ratingLabel(rating, reviewsText)
          : copy.findCare.ratingNoCount(rating)
      }
    >
      <span aria-hidden="true">⭐ {rating}</span>
      {reviewsText && (
        <span className="text-slate-400" aria-hidden="true">
          {" "}
          · {reviewsText}
        </span>
      )}
    </span>
  );
}

export function kindLabel(kind: FacilityKind, copy: ReturnType<typeof useCopy>): string {
  const labels: Record<FacilityKind, string> = {
    hospital: copy.findCare.kindHospital,
    clinic: copy.findCare.kindClinic,
    pharmacy: copy.findCare.kindPharmacy,
    laboratory: copy.findCare.kindLaboratory,
    doctor: copy.findCare.kindDoctor,
    other: copy.findCare.kindOther,
  };
  return labels[kind];
}

export function kindTone(kind: FacilityKind): string {
  if (kind === "hospital") return "bg-red-50 text-red-700";
  if (kind === "pharmacy") return "bg-emerald-50 text-emerald-700";
  if (kind === "laboratory") return "bg-amber-50 text-amber-700";
  if (kind === "doctor") return "bg-violet-50 text-violet-700";
  return "bg-sky-50 text-sky-700";
}

export function distanceLabel(distanceKm: number): string {
  if (distanceKm < 1) return `${Math.max(1, Math.round(distanceKm * 1_000))} m`;
  return `${distanceKm.toFixed(distanceKm < 10 ? 1 : 0)} km`;
}

export function CareIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M4 21V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v15" />
      <path d="M9 4V2h6v2M3 21h18M9 21v-4h6v4" />
      <path d="M12 8v5M9.5 10.5h5" />
    </svg>
  );
}
