import { useEffect, useRef, useState } from "react";
import type { CarePlace } from "../types/api";
import { useI18n } from "../i18n/I18nContext";
import "leaflet/dist/leaflet.css";

interface CareMapProps {
  center: { lat: number; lon: number };
  places: CarePlace[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTR =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export function CareMap({ center, places, selectedId, onSelect }: CareMapProps) {
  const { t, formatNumber } = useI18n();
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<import("leaflet").Map | null>(null);
  const markersRef = useRef<import("leaflet").CircleMarker[]>([]);
  const onSelectRef = useRef(onSelect);
  const [mapReady, setMapReady] = useState(0);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;

    void import("leaflet").then((L) => {
      if (cancelled || !hostRef.current) return;
      const map = L.map(hostRef.current, { scrollWheelZoom: false }).setView(
        [center.lat, center.lon],
        13,
      );
      L.tileLayer(TILE_URL, { attribution: TILE_ATTR, maxZoom: 19 }).addTo(map);
      mapRef.current = map;
      setMapReady((n) => n + 1);
    });

    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      markersRef.current = [];
    };
    // Recreate only when the search origin changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center.lat, center.lon]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    void import("leaflet").then((L) => {
      if (mapRef.current !== map) return;
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = places.map((place) => {
        const selected = place.id === selectedId;
        const color =
          place.match_kind === "specialty"
            ? "#0f766e"
            : place.place_type === "hospital"
              ? "#b45309"
              : "#334155";
        const marker = L.circleMarker([place.lat, place.lon], {
          radius: selected ? 10 : 7,
          color,
          weight: selected ? 3 : 2,
          fillColor: color,
          fillOpacity: selected ? 0.95 : 0.7,
        })
          .addTo(map)
          .bindPopup(
            `<strong>${escapeHtml(place.name)}</strong><br/>${escapeHtml(formatNumber(place.distance_km, { maximumFractionDigits: 1 }))} km`,
          )
          .on("click", () => onSelectRef.current(place.id));
        return marker;
      });
      if (places.length > 0) {
        const bounds = L.latLngBounds(places.map((p) => [p.lat, p.lon] as [number, number]));
        bounds.extend([center.lat, center.lon]);
        map.fitBounds(bounds.pad(0.2), {
          animate: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        });
      } else {
        map.setView([center.lat, center.lon], 13);
      }
    });
  }, [places, selectedId, center.lat, center.lon, mapReady, formatNumber]);

  return (
    <div
      ref={hostRef}
      className="h-72 w-full overflow-hidden rounded-xl border border-slate-200 bg-slate-100 lg:h-full lg:min-h-[420px]"
      role="region"
      aria-label={t("care.mapLabel")}
    />
  );
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
