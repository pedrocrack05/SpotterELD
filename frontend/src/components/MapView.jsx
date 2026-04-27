import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix default icon issue with Vite
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom icon factory
const makeIcon = (color, symbol) =>
  L.divIcon({
    html: `
      <div style="
        background:${color};
        width:28px;height:28px;
        border-radius:50% 50% 50% 0;
        transform:rotate(-45deg);
        border:2px solid white;
        box-shadow:0 2px 6px rgba(0,0,0,0.4);
        display:flex;align-items:center;justify-content:center;
      ">
        <span style="transform:rotate(45deg);font-size:12px;line-height:1;">${symbol}</span>
      </div>`,
    className: '',
    iconSize:  [28, 28],
    iconAnchor:[14, 28],
    popupAnchor:[0, -30],
  });

const ICONS = {
  origin:      makeIcon('#4f46e5', '🚛'),
  pickup:      makeIcon('#16a34a', '📦'),
  dropoff:     makeIcon('#dc2626', '🏁'),
  fuel:        makeIcon('#d97706', '⛽'),
  break:       makeIcon('#0ea5e9', '☕'),
  sleeper:     makeIcon('#7c3aed', '💤'),
  inspection:  makeIcon('#475569', '🔍'),
  default:     makeIcon('#64748b', '📍'),
};

function getIcon(action = '') {
  if (action.toLowerCase().includes('fuel'))      return ICONS.fuel;
  if (action.toLowerCase().includes('break'))     return ICONS.break;
  if (action.toLowerCase().includes('sleeper'))   return ICONS.sleeper;
  if (action.toLowerCase().includes('inspection'))return ICONS.inspection;
  if (action.toLowerCase().includes('loading'))   return ICONS.pickup;
  if (action.toLowerCase().includes('unloading')) return ICONS.dropoff;
  return ICONS.default;
}

// Auto-fit bounds when route changes
const MapController = ({ positions }) => {
  const map = useMap();
  useEffect(() => {
    if (positions && positions.length > 1) {
      map.fitBounds(positions, { padding: [40, 40], animate: true });
    }
  }, [positions, map]);
  return null;
};

const MapView = ({ routeData, stopMarkers = [] }) => {
  const defaultCenter = [39.5, -98.35]; // Center of USA

  // Convert [lon, lat] → [lat, lon] for Leaflet
  const positions = (routeData?.coordinates || []).map(([lon, lat]) => [lat, lon]);
  const origin      = positions[0] ?? null;
  const destination = positions[positions.length - 1] ?? null;
  const pickup      = routeData?.pickup_coords ?? null;   // already [lat, lon]

  return (
    <MapContainer center={defaultCenter} zoom={4} className="h-full w-full" style={{ minHeight: '280px' }}>
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://openstreetmap.org">OpenStreetMap</a>'
      />

      <MapController positions={positions} />

      {/* Route polyline */}
      {positions.length > 1 && (
        <Polyline positions={positions} color="#4f46e5" weight={4} opacity={0.85} />
      )}

      {/* Origin marker */}
      {origin && (
        <Marker position={origin} icon={ICONS.origin}>
          <Popup><strong>🚛 Origin</strong></Popup>
        </Marker>
      )}

      {/* Destination marker */}
      {destination && (
        <Marker position={destination} icon={ICONS.dropoff}>
          <Popup><strong>🏁 Destination</strong></Popup>
        </Marker>
      )}

      {/* Pickup marker */}
      {pickup && (
        <Marker position={pickup} icon={ICONS.pickup}>
          <Popup><strong>📦 Pickup Location</strong></Popup>
        </Marker>
      )}
    </MapContainer>
  );
};

export default MapView;