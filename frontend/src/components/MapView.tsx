import type { CareFacility } from "../types/api";

/**
 * Map adapter seam. This page does not import Leaflet/Mapbox.
 * Swap the body later without rewriting FindCarePage.
 */
export function MapView({
  originLabel,
  facilities,
  selectedId,
}: {
  originLabel?: string;
  facilities: CareFacility[];
  selectedId: string | null;
}) {
  const selected = facilities.find((item) => item.id === selectedId) || facilities[0];
  if (!selected) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
        Search a city to see nearby facilities. The map renderer is optional.
      </div>
    );
  }
  const osm = `https://www.openstreetmap.org/?mlat=${selected.latitude}&mlon=${selected.longitude}#map=16/${selected.latitude}/${selected.longitude}`;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5">
      <p className="text-sm font-semibold text-slate-800">{selected.name}</p>
      <p className="mt-1 text-xs text-slate-500">
        {originLabel ? `Near ${originLabel}` : "Selected facility"}
        {selected.distance_km != null ? ` · ${selected.distance_km} km` : ""}
      </p>
      <a
        href={osm}
        target="_blank"
        rel="noreferrer"
        className="mt-3 inline-flex text-sm font-medium text-brand-600 hover:text-brand-700"
      >
        Open in external map →
      </a>
      <p className="mt-3 text-xs text-slate-400">
        Rendering is an adapter. Leaflet or MapLibre can replace this panel without changing search.
      </p>
    </div>
  );
}
