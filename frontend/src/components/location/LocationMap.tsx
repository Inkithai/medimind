import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Coordinates } from "../../types/location";

interface LocationMapProps {
  coordinates: Coordinates;
  onCoordinatesChange: (coordinates: Coordinates) => void;
  className?: string;
}

const TILE_URL =
  import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  import.meta.env.VITE_MAP_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const pinIcon = L.divIcon({
  className: "location-map-pin-wrapper",
  html: '<span class="location-map-pin"><span></span></span>',
  iconSize: [40, 48],
  iconAnchor: [20, 44],
});

export function LocationMap({ coordinates, onCoordinatesChange, className }: LocationMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const onChangeRef = useRef(onCoordinatesChange);

  useEffect(() => {
    onChangeRef.current = onCoordinatesChange;
  }, [onCoordinatesChange]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    container.setAttribute("role", "application");
    container.setAttribute(
      "aria-label",
      "Location confirmation map. Click the map or drag the pin to adjust the location."
    );

    const map = L.map(container, {
      center: [coordinates.latitude, coordinates.longitude],
      zoom: 14,
      zoomControl: false,
      scrollWheelZoom: true,
      keyboard: true,
    });
    mapRef.current = map;

    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer(TILE_URL, {
      attribution: TILE_ATTRIBUTION,
      maxZoom: 19,
    }).addTo(map);

    const marker = L.marker([coordinates.latitude, coordinates.longitude], {
      draggable: true,
      icon: pinIcon,
      keyboard: true,
      title: "Selected location. Drag to adjust.",
    }).addTo(map);
    markerRef.current = marker;

    map.on("click", (event: L.LeafletMouseEvent) => {
      marker.setLatLng(event.latlng);
      onChangeRef.current({ latitude: event.latlng.lat, longitude: event.latlng.lng });
    });
    marker.on("dragend", () => {
      const point = marker.getLatLng();
      onChangeRef.current({ latitude: point.lat, longitude: point.lng });
    });

    // The component often appears as the picker changes steps. Let layout settle
    // before Leaflet measures its container.
    window.setTimeout(() => map.invalidateSize(), 0);

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // The first coordinates initialize the map; subsequent updates are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const point = L.latLng(coordinates.latitude, coordinates.longitude);
    markerRef.current?.setLatLng(point);
    if (mapRef.current && !mapRef.current.getBounds().pad(-0.25).contains(point)) {
      mapRef.current.panTo(point);
    }
  }, [coordinates.latitude, coordinates.longitude]);

  return (
    <div className={`relative overflow-hidden bg-slate-100 ${className || "h-80"}`}>
      <div ref={containerRef} className="h-full w-full" />
      <div className="pointer-events-none absolute left-3 top-3 z-[500] rounded-lg bg-white/95 px-3 py-2 text-xs font-medium text-slate-700 shadow-sm ring-1 ring-slate-200 backdrop-blur">
        Drag the pin or click the map to adjust
      </div>
    </div>
  );
}
