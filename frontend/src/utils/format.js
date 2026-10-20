export const WEEKDAYS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
];

export function money(value, currency = 'USD') {
  if (value === null || value === undefined || value === '') return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(Number(value));
}

const pad = (n) => String(n).padStart(2, '0');

export function toISO(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Parses YYYY-MM-DD as a local calendar date (avoids UTC off-by-one shifts). */
export function parseDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? new Date(+match[1], +match[2] - 1, +match[3]) : new Date(value);
}

export function fmtDate(value, options = { month: 'short', day: 'numeric', year: 'numeric' }) {
  const date = parseDate(value);
  return date ? date.toLocaleDateString('en-US', options) : '—';
}

export function fmtDateTime(value) {
  if (!value) return '—';
  return new Date(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function fmtTime(value) {
  if (!value) return '';
  const [h, m] = value.split(':');
  const date = new Date(2000, 0, 1, Number(h), Number(m));
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

export const hhmm = (value) => (value ? String(value).slice(0, 5) : '');

export function todayISO() {
  return toISO(new Date());
}

export function addDaysISO(iso, days) {
  const date = parseDate(iso);
  date.setDate(date.getDate() + days);
  return toISO(date);
}

export function nightsBetween(checkIn, checkOut) {
  if (!checkIn || !checkOut) return 0;
  return Math.round((parseDate(checkOut) - parseDate(checkIn)) / 86400000);
}

/** Maps backend validation details ([{field, message}]) to { fieldName: message }. */
export function fieldErrors(error) {
  const map = {};
  for (const detail of error?.details || []) {
    const key = String(detail.field || '').split('.').pop();
    if (key && !map[key]) map[key] = detail.message;
  }
  return map;
}

export function errorText(error) {
  if (!error) return '';
  if (error.code === 'NETWORK_ERROR') return error.message;
  if (error.status === 429 && error.retryAfter)
    return `Too many attempts. Try again in ${error.retryAfter} seconds.`;
  return error.message || 'Something went wrong.';
}

export const titleCase = (value) =>
  String(value || '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/^\w/, (c) => c.toUpperCase());
