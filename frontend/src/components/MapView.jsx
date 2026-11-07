import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

const US_CENTER = [39.5, -98.35];

const pinIcon = L.divIcon({
  className: 'osm-pin',
  html: '<span></span>',
  iconSize: [26, 36],
  iconAnchor: [13, 34],
  popupAnchor: [0, -30],
});

function haversineKm(lat1, lng1, lat2, lng2) {
  const rad = (d) => (d * Math.PI) / 180;
  const a =
    Math.sin(rad(lat2 - lat1) / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function popupContent(marker, onOpen) {
  const wrap = document.createElement('div');
  const title = document.createElement('strong');
  title.textContent = marker.title; // textContent, never innerHTML: names come from users
  wrap.appendChild(title);
  if (marker.subtitle) {
    const sub = document.createElement('div');
    sub.textContent = marker.subtitle;
    wrap.appendChild(sub);
  }
  const button = document.createElement('button');
  button.textContent = 'View listing';
  button.className = 'btn btn-sm';
  button.style.marginTop = '6px';
  button.onclick = () => onOpen(marker);
  wrap.appendChild(button);
  return wrap;
}

/**
 * markers: [{ id, lat, lng, title, subtitle }]
 * onMarkerClick(marker): clicking a pin opens a popup with a "View listing" button.
 * onMove({lat, lng}): the (single) pin becomes draggable.
 * autoFit: zoom to show all pins (turn off when the user is steering the map).
 * onIdle({lat, lng, radiusKm}): fired (debounced) after the USER drags or zooms the map.
 */
export default function MapView({ markers = [], zoom = 13, height = 320, onMarkerClick, onMove, autoFit = true, onIdle }) {
  const box = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const placed = useRef(false);
  const programmatic = useRef(false);
  const latest = useRef({});
  latest.current = { markers, onMarkerClick, onMove, zoom, autoFit, onIdle };

  // Create the map once.
  useEffect(() => {
    const first = latest.current.markers[0];
    const m = L.map(box.current, {
      center: first ? [first.lat, first.lng] : US_CENTER,
      zoom: first ? latest.current.zoom : 4,
    });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
    }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    map.current = m;

    let timer;
    m.on('moveend', () => {
      if (programmatic.current) {
        programmatic.current = false;
        return;
      }
      if (!latest.current.onIdle) return;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const c = m.getCenter();
        const ne = m.getBounds().getNorthEast();
        latest.current.onIdle({ lat: c.lat, lng: c.lng, radiusKm: haversineKm(c.lat, c.lng, ne.lat, ne.lng) });
      }, 600);
    });
    // Container may have changed size after first paint (sticky column, tabs).
    const fix = setTimeout(() => m.invalidateSize(), 100);

    return () => {
      clearTimeout(timer);
      clearTimeout(fix);
      m.remove();
      map.current = null;
      placed.current = false;
    };
  }, []);

  // Draw pins whenever the markers change.
  const key = JSON.stringify(markers.map((m) => [m.id, m.lat, m.lng, m.title, m.subtitle]));
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const { markers: list, onMarkerClick: open, onMove: move, zoom: z } = latest.current;
    layer.current.clearLayers();
    list.forEach((item) => {
      const pin = L.marker([item.lat, item.lng], { icon: pinIcon, title: item.title, draggable: Boolean(move) });
      if (open) pin.bindPopup(popupContent(item, open));
      if (move) pin.on('dragend', () => move({ lat: pin.getLatLng().lat, lng: pin.getLatLng().lng }));
      pin.addTo(layer.current);
    });

    if (list.length > 1 && latest.current.autoFit) {
      programmatic.current = true;
      m.fitBounds(L.latLngBounds(list.map((i) => [i.lat, i.lng])), { padding: [40, 40], maxZoom: 15 });
    } else if (list.length === 1) {
      const target = [list[0].lat, list[0].lng];
      if (!placed.current) {
        programmatic.current = true;
        m.setView(target, z);
        placed.current = true;
      } else if (!m.getBounds().contains(target)) {
        programmatic.current = true;
        m.panTo(target);
      }
    }
  }, [key]);

  return (
    <div className="map-wrap" style={{ height }}>
      <div ref={box} className="map-canvas" role="region" aria-label="Map" />
    </div>
  );
}
