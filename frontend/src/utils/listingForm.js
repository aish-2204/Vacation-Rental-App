import { hhmm } from './format';

export const TIMEZONES = [
  'America/Los_Angeles',
  'America/Denver',
  'America/Phoenix',
  'America/Chicago',
  'America/New_York',
  'America/Anchorage',
  'Pacific/Honolulu',
];

export const emptyForm = () => ({
  name: '',
  description: '',
  address_line1: '',
  address_line2: '',
  city: '',
  state: '',
  zip_code: '',
  latitude: '',
  longitude: '',
  timezone: 'America/Los_Angeles',
  contact_name: '',
  contact_email: '',
  contact_phone: '',
  nightly_price: '',
  max_guests: '',
  amenity_ids: [],
});

export function formFromListing(l) {
  return {
    name: l.name,
    description: l.description || '',
    address_line1: l.address_line1,
    address_line2: l.address_line2 || '',
    city: l.city,
    state: l.state,
    zip_code: l.zip_code,
    latitude: String(l.latitude),
    longitude: String(l.longitude),
    timezone: l.timezone,
    contact_name: l.contact_name || '',
    contact_email: l.contact_email || '',
    contact_phone: l.contact_phone || '',
    nightly_price: String(l.nightly_price),
    max_guests: String(l.max_guests),
    amenity_ids: (l.amenities || []).map((a) => a.id),
  };
}

/** Converts form strings into the exact types the API expects (decimals as strings). */
export function toPayload(f) {
  return {
    name: f.name.trim(),
    description: f.description.trim(),
    address_line1: f.address_line1.trim(),
    address_line2: f.address_line2.trim() || null,
    city: f.city.trim(),
    state: f.state.trim().toUpperCase(),
    zip_code: f.zip_code.trim(),
    latitude: Number(f.latitude).toFixed(6),
    longitude: Number(f.longitude).toFixed(6),
    timezone: f.timezone.trim(),
    contact_name: f.contact_name.trim(),
    contact_email: f.contact_email.trim(),
    contact_phone: f.contact_phone.trim(),
    nightly_price: Number(f.nightly_price).toFixed(2),
    currency: 'USD',
    max_guests: parseInt(f.max_guests, 10),
    amenity_ids: [...f.amenity_ids],
  };
}

/** Only the fields that changed, so untouched approved listings are not sent back for review. */
export function diffPayload(form, original) {
  const next = toPayload(form);
  const prev = toPayload(formFromListing(original));
  const patch = {};
  for (const key of Object.keys(next)) {
    const a = JSON.stringify(key === 'amenity_ids' ? [...next[key]].sort() : next[key]);
    const b = JSON.stringify(key === 'amenity_ids' ? [...prev[key]].sort() : prev[key]);
    if (a !== b) patch[key] = next[key];
  }
  return patch;
}

const ZIP = /^[0-9]{5}(-[0-9]{4})?$/;
const PHONE = /^(\+?[0-9][0-9 ()-]{6,30}[0-9])?$/;

export function validateForm(f) {
  const e = {};
  if (!f.name.trim()) e.name = 'Enter a name';
  if (!f.address_line1.trim()) e.address_line1 = 'Enter the street address';
  if (!f.city.trim()) e.city = 'Enter the city';
  if (!/^[A-Za-z]{2}$/.test(f.state.trim())) e.state = 'Use a 2-letter state code';
  if (!ZIP.test(f.zip_code.trim())) e.zip_code = 'Use 12345 or 12345-6789';
  const lat = Number(f.latitude);
  const lng = Number(f.longitude);
  if (f.latitude === '' || Number.isNaN(lat) || lat < -90 || lat > 90) e.latitude = 'Latitude must be between -90 and 90';
  if (f.longitude === '' || Number.isNaN(lng) || lng < -180 || lng > 180) e.longitude = 'Longitude must be between -180 and 180';
  if (!f.timezone.trim()) e.timezone = 'Enter an IANA timezone';
  if (!(Number(f.nightly_price) > 0)) e.nightly_price = 'Price must be greater than 0';
  if (!/^[0-9]+$/.test(f.max_guests) || parseInt(f.max_guests, 10) < 1) e.max_guests = 'Enter a whole number, 1 or more';
  if (f.contact_email.trim() && !/^\S+@\S+\.\S+$/.test(f.contact_email.trim())) e.contact_email = 'Enter a valid email';
  if (!PHONE.test(f.contact_phone.trim())) e.contact_phone = 'Enter a valid phone number';
  return e;
}

/* ---------- Weekly contact hours ---------- */
export const defaultHours = () =>
  Array.from({ length: 7 }, (_, weekday) => ({
    weekday,
    closed: false,
    opening_time: '09:00',
    closing_time: '18:00',
  }));

export function hoursFromListing(list) {
  const base = defaultHours();
  return base.map((row) => {
    const found = (list || []).find((h) => h.weekday === row.weekday);
    if (!found) return row;
    return {
      weekday: row.weekday,
      closed: found.closed,
      opening_time: hhmm(found.opening_time) || '09:00',
      closing_time: hhmm(found.closing_time) || '18:00',
    };
  });
}

export const hoursToPayload = (rows) =>
  rows.map((r) => ({
    weekday: r.weekday,
    closed: r.closed,
    opening_time: r.closed ? null : r.opening_time,
    closing_time: r.closed ? null : r.closing_time,
  }));

export function validateHours(rows) {
  for (const r of rows)
    if (!r.closed && !(r.opening_time && r.closing_time && r.opening_time < r.closing_time))
      return 'Open days need an opening time before the closing time.';
  return '';
}

/* ---------- Weekly arrival/departure rules ---------- */
export const defaultRules = () =>
  Array.from({ length: 7 }, (_, weekday) => ({
    weekday,
    arrival_allowed: true,
    arrival_start: '15:00',
    arrival_end: '22:00',
    arrival_default: '15:00',
    departure_allowed: true,
    departure_start: '07:00',
    departure_end: '11:00',
    departure_default: '11:00',
  }));

export function rulesFromListing(list) {
  return defaultRules().map((row) => {
    const f = (list || []).find((r) => r.weekday === row.weekday);
    if (!f) return row;
    const out = { weekday: row.weekday, arrival_allowed: f.arrival_allowed, departure_allowed: f.departure_allowed };
    for (const k of ['arrival_start', 'arrival_end', 'arrival_default', 'departure_start', 'departure_end', 'departure_default'])
      out[k] = hhmm(f[k]) || row[k];
    return out;
  });
}

export const rulesToPayload = (rows) =>
  rows.map((r) => {
    const out = {
      weekday: r.weekday,
      arrival_allowed: r.arrival_allowed,
      departure_allowed: r.departure_allowed,
    };
    for (const dir of ['arrival', 'departure'])
      for (const part of ['start', 'end', 'default'])
        out[`${dir}_${part}`] = r[`${dir}_allowed`] ? r[`${dir}_${part}`] : null;
    return out;
  });

export function validateRules(rows) {
  for (const r of rows)
    for (const dir of ['arrival', 'departure']) {
      if (!r[`${dir}_allowed`]) continue;
      const s = r[`${dir}_start`];
      const e = r[`${dir}_end`];
      const d = r[`${dir}_default`];
      if (!s || !e || !d || !(s <= d && d <= e)) return `Each allowed ${dir} needs start ≤ default ≤ end.`;
    }
  return '';
}

// Main timezone for each US state. Split-timezone states may need a manual edit by the host.
const NY = 'America/New_York';
const CH = 'America/Chicago';
const DN = 'America/Denver';
const LA = 'America/Los_Angeles';
export const STATE_TIMEZONES = {
  AL: CH, AK: 'America/Anchorage', AZ: 'America/Phoenix', AR: CH, CA: LA, CO: DN, CT: NY, DE: NY, DC: NY,
  FL: NY, GA: NY, HI: 'Pacific/Honolulu', ID: DN, IL: CH, IN: NY, IA: CH, KS: CH, KY: NY, LA: CH, ME: NY,
  MD: NY, MA: NY, MI: NY, MN: CH, MS: CH, MO: CH, MT: DN, NE: CH, NV: LA, NH: NY, NJ: NY, NM: DN, NY: NY,
  NC: NY, ND: CH, OH: NY, OK: CH, OR: LA, PA: NY, RI: NY, SC: NY, SD: CH, TN: CH, TX: CH, UT: DN, VT: NY,
  VA: NY, WA: LA, WV: NY, WI: CH, WY: DN,
};
