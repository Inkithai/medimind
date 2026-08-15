import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useCopy } from "../../i18n";
import type { CareFacility } from "../../types/facility";
import type { Coordinates } from "../../types/location";
import { googleMapsUrl } from "../../utils/facilities";

const TILE_URL =
  import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  import.meta.env.VITE_MAP_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

/**
 * Overview map of the current results.
 *
 * Tiles come from the OpenStreetMap layer (no browser-exposed Google key),
 * while every popup's action deep-links into Google Maps. The map is purely
 * supplementary: the same facilities are listed as accessible cards below, so
 * nothing here is keyboard- or screen-reader-only content.
 */
export function FacilityResultsMap({
  facilities,
  center,
  activeFacilityId,
  className,
}: {
  facilities: CareFacility[];
  center: Coordinates;
  activeFacilityId?: string | null;
  className?: string;
}) {
  const copy = useCopy();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const markersRef = useRef<Map<string, L.Marker>>(new Map());

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    const map = L.map(container, {
      center: [center.latitude, center.longitude],
      zoom: 14,
      zoomControl: false,
      scrollWheelZoom: false,
      keyboard: true,
    });
    mapRef.current = map;
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION, maxZoom: 19 }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    window.setTimeout(() => map.invalidateSize(), 0);

    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      markersRef.current.clear();
    };
    // Only the first center initializes the map; later updates are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();
    markersRef.current.clear();

    const points: L.LatLngExpression[] = [[center.latitude, center.longitude]];
    L.circleMarker([center.latitude, center.longitude], {
      radius: 7,
      color: "#0f172a",
      weight: 2,
      fillColor: "#38bdf8",
      fillOpacity: 1,
    })
      .bindPopup(escapeHtml(copy.location.selectedLocation))
      .addTo(layer);

    facilities.forEach((facility, index) => {
      if (!Number.isFinite(facility.latitude) || !Number.isFinite(facility.longitude)) return;
      points.push([facility.latitude, facility.longitude]);
      const marker = L.marker([facility.latitude, facility.longitude], {
        title: facility.name,
        alt: facility.name,
        keyboard: true,
        icon: L.divIcon({
          className: "care-map-pin-wrapper",
          html: `<span class="care-map-pin">${index + 1}</span>`,
          iconSize: [28, 28],
          iconAnchor: [14, 28],
        }),
      });
      marker.bindPopup(
        `<strong>${escapeHtml(facility.name)}</strong><br/>` +
          `${escapeHtml(facility.address || copy.findCare.addressNotAvailable)}<br/>` +
          `<a href="${escapeHtml(googleMapsUrl(facility))}" target="_blank" rel="noreferrer">${escapeHtml(
            copy.findCare.openInGoogleMaps
          )}</a>`
      );
      marker.addTo(layer);
      markersRef.current.set(facility.id, marker);
    });

    if (points.length > 1) {
      map.fitBounds(L.latLngBounds(points).pad(0.2), { maxZoom: 16 });
    } else {
      map.setView([center.latitude, center.longitude], 14);
    }
  }, [center.latitude, center.longitude, copy, facilities]);

  useEffect(() => {
    if (!activeFacilityId) return;
    const marker = markersRef.current.get(activeFacilityId);
    if (marker && mapRef.current) {
      mapRef.current.panTo(marker.getLatLng());
      marker.openPopup();
    }
  }, [activeFacilityId]);

  return (
    <div className={`relative overflow-hidden rounded-2xl border border-slate-200 ${className || "h-72"}`}>
      <div
        ref={containerRef}
        className="h-full w-full"
        role="application"
        aria-label={`${copy.findCare.mapTitle}. ${copy.findCare.mapDescription} ${copy.findCare.mapListFallback}`}
      />
    </div>
  );
}
