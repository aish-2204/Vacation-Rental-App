import { useRef, useState } from 'react';
import { searchPlaces } from '../lib/maps';

/**
 * Address search using OpenStreetMap's Nominatim. Press Enter or click Search
 * (Nominatim's rules do not allow search-as-you-type). Calls onSelect(place) with
 * { name, formatted, lat, lng, address_line1, city, state, zip_code }.
 */
export default function PlaceSearch({ onSelect }) {
  const [text, setText] = useState('');
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const controller = useRef(null);

  async function search(event) {
    event.preventDefault();
    event.stopPropagation();
    if (text.trim().length < 3) return setError('Type at least 3 characters.');
    controller.current?.abort();
    controller.current = new AbortController();
    setBusy(true);
    setError('');
    try {
      const found = await searchPlaces(text.trim(), controller.current.signal);
      setResults(found);
      if (!found.length) setError('No matching address found.');
    } catch (err) {
      if (err.name !== 'AbortError') setError('Address search is unavailable right now. Check your connection.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="place-search">
      <div className="row">
        <input
          type="text"
          value={text}
          placeholder="Search an address or place, e.g. 1 Washington Sq, San Jose"
          aria-label="Search address"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search(e)}
          style={{ flex: 1 }}
        />
        <button type="button" className="btn btn-secondary btn-sm" onClick={search} disabled={busy}>
          {busy ? 'Searching…' : 'Search'}
        </button>
      </div>
      {error && <p className="small muted" style={{ margin: '0.3rem 0 0' }}>{error}</p>}
      {results?.length > 0 && (
        <ul className="place-results">
          {results.map((p, i) => (
            <li key={`${p.lat},${p.lng},${i}`}>
              <button
                type="button"
                onClick={() => {
                  onSelect(p);
                  setResults(null);
                  setText(p.formatted);
                }}
              >
                {p.formatted}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
