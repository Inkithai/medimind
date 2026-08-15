import type { CareFacility } from "../types/api";
import { StatusBadge } from "./StatusBadge";

export function FacilityList({
  facilities,
  selectedId,
  onSelect,
}: {
  facilities: CareFacility[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="max-h-[640px] space-y-2 overflow-y-auto pr-1 scroll-thin">
      {facilities.map((place) => {
        const selected = place.id === selectedId;
        return (
          <li key={place.id}>
            <button
              type="button"
              onClick={() => onSelect(place.id)}
              className={`w-full rounded-xl border bg-white p-4 text-left shadow-sm transition ${
                selected ? "border-brand-300 ring-2 ring-brand-100" : "border-slate-200 hover:border-brand-200"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-900">{place.name}</p>
                  <p className="mt-0.5 text-xs capitalize text-slate-500">{place.kind}</p>
                </div>
                <StatusBadge tone="neutral">{place.distance_km != null ? `${place.distance_km} km` : "distance n/a"}</StatusBadge>
              </div>
              <p className="mt-2 text-xs text-slate-600">{place.address || "Address not listed"}</p>
              <div className="mt-2 flex flex-wrap gap-3 text-xs font-medium">
                {place.phone && (
                  <a href={`tel:${place.phone}`} className="text-brand-600" onClick={(e) => e.stopPropagation()}>
                    Call
                  </a>
                )}
                {place.website && (
                  <a href={place.website} target="_blank" rel="noreferrer" className="text-brand-600" onClick={(e) => e.stopPropagation()}>
                    Website
                  </a>
                )}
                {place.source_url && (
                  <a href={place.source_url} target="_blank" rel="noreferrer" className="text-slate-500" onClick={(e) => e.stopPropagation()}>
                    Listing
                  </a>
                )}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
