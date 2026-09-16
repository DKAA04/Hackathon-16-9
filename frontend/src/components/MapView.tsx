import L from "leaflet";
import { useEffect } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import type { Level, MapData, MapPoint } from "../api/types";
import { LEVEL_LABEL, TYPE_LABEL, formatCount } from "../lib/format";

const COLOR: Record<Level | "unknown", string> = {
  HIGH: "#b7ff3c",
  MEDIUM: "#ffc857",
  LOW: "#ff6b6b",
  unknown: "#91a59c",
};
const SCHOTEN: [number, number] = [51.2505, 4.5007];
// CARTO Basemap keys are intended for browser tile requests. Restrict the key to
// localhost and the deployed domain in CARTO's key dashboard.
const CARTO_BASEMAP_KEY = import.meta.env.VITE_CARTO_BASEMAP_KEY?.trim();
const CARTO_DARK_URL = "https://{s}.basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png";
const OSM_FALLBACK_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

function FitToPoints({ points, fitKey }: { points: MapPoint[]; fitKey: string }) {
  const map = useMap();
  useEffect(() => {
    if (!points.length) return;
    const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lon] as [number, number]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
    // only when the filter changes, not when a marker changes colour
  }, [fitKey, points.length > 0]);
  return null;
}

function FlyTo({ focus }: { focus: { lat: number; lon: number; key: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (focus) map.flyTo([focus.lat, focus.lon], Math.max(map.getZoom(), 17), { duration: 0.6 });
  }, [focus, map]);
  return null;
}

interface Props {
  data: MapData;
  fitKey: string;
  activeId: string | null;
  selectedIds: Set<string>;
  focus: { lat: number; lon: number; key: number } | null;
  onOpen: (id: string) => void;
  attribution: string | null;
}

export function MapView({ data, fitKey, activeId, selectedIds, focus, onOpen, attribution }: Props) {
  // draw the selected and active markers last so they stay on top
  const ordered = [...data.points].sort((a, b) => rank(a) - rank(b));
  function rank(p: MapPoint) {
    return p.id === activeId ? 2 : selectedIds.has(p.id) ? 1 : 0;
  }

  return (
    <div className="map-wrap">
      <MapContainer center={SCHOTEN} zoom={14} preferCanvas className="map" zoomControl={false}>
        <TileLayer
          url={CARTO_BASEMAP_KEY ? `${CARTO_DARK_URL}?key=${encodeURIComponent(CARTO_BASEMAP_KEY)}` : OSM_FALLBACK_URL}
          subdomains="abcd"
          maxZoom={20}
          attribution={CARTO_BASEMAP_KEY
            ? '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers &copy; <a href="https://carto.com/attributions">CARTO</a>'
            : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-bijdragers'}
        />
        <FitToPoints points={data.points} fitKey={fitKey} />
        <FlyTo focus={focus} />
        {ordered.map((p) => {
          const level = p.confidenceLevel ?? "unknown";
          const active = p.id === activeId;
          const selected = selectedIds.has(p.id);
          return (
            <CircleMarker
              key={p.id}
              center={[p.lat, p.lon]}
              radius={active ? 10 : selected ? 7 : 5}
              pathOptions={{
                color: active || selected ? "#ffffff" : COLOR[level],
                weight: active ? 3 : selected ? 2 : 1.2,
                fillColor: COLOR[level],
                fillOpacity: 0.85,
                dashArray: p.reviewRequired && !active && !selected ? "2 3" : undefined,
              }}
              eventHandlers={{ click: () => onOpen(p.id) }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                <strong>{p.displayName}</strong>
                <br />
                {TYPE_LABEL[p.recordType]} · zekerheid {p.confidenceLevel ? LEVEL_LABEL[p.confidenceLevel].toLowerCase() : "onbekend"}
                {p.reviewRequired ? " · controle nodig" : ""}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>

      <div className="legend" aria-label="Legende">
        <strong>Zekerheid</strong>
        {(["HIGH", "MEDIUM", "LOW"] as Level[]).map((l) => (
          <span key={l}><i style={{ background: COLOR[l] }} /> {LEVEL_LABEL[l]}</span>
        ))}
        <span><i className="dashed" /> controle nodig</span>
        <span className="muted">{formatCount(data.points.length)} op kaart
          {data.skipped > 0 && ` · ${formatCount(data.skipped)} zonder bruikbare coördinaten`}</span>
      </div>
      {attribution && <div className="source-note">Bron: {attribution}</div>}
    </div>
  );
}
