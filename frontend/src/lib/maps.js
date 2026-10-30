// OpenStreetMap helpers. No API key and no billing needed.
// Tiles: OpenStreetMap standard layer. Address search: Nominatim (https://nominatim.org).
// Usage rules: keep to ~1 request per second and show attribution (the map does).

export const mapsEnabled = true;

/** Opens OpenStreetMap in a new tab. */
export const mapLink = (lat, lng) => `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=16/${lat}/${lng}`;

/** Address search through Nominatim (US only). Returns parsed places. */
export async function searchPlaces(query, signal) {
  const url =
    'https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&limit=5&countrycodes=us' +
    `&q=${encodeURIComponent(query)}`;
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(`Search failed (${response.status})`);
  const rows = await response.json();
  return rows.map(parsePlace);
}

/** Converts a Nominatim result into the fields our forms use. */
export function parsePlace(row) {
  const a = row.address || {};
  const iso = a['ISO3166-2-lvl4'] || '';
  return {
    name: row.name || row.display_name.split(',')[0],
    formatted: row.display_name,
    lat: Number(row.lat),
    lng: Number(row.lon),
    address_line1: [a.house_number, a.road].filter(Boolean).join(' '),
    city: a.city || a.town || a.village || a.hamlet || a.suburb || a.county || '',
    state: iso.startsWith('US-') ? iso.slice(3) : '',
    zip_code: (a.postcode || '').slice(0, 10),
  };
}
