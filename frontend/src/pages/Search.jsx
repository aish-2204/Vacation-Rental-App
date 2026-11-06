import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { bookingsApi, publicApi } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';
import useAsync from '../hooks/useAsync';
import MapView from '../components/MapView';
import PlaceSearch from '../components/PlaceSearch';
import { mapsEnabled } from '../lib/maps';
import { Empty, ErrorAlert, Field, Pagination, Spinner } from '../components/ui';
import { addDaysISO, fmtDate, money, nightsBetween, todayISO } from '../utils/format';

const PAGE_SIZE = 10;
const PASS_THROUGH = [
  'city',
  'state',
  'zip_code',
  'check_in',
  'check_out',
  'guests',
  'min_price',
  'max_price',
  'latitude',
  'longitude',
  'radius_km',
];

/** "95112", "San Jose", "San Jose, CA" or "San Jose, CA 95112" -> backend filters. */
function parseWhere(text) {
  const t = text.trim();
  if (!t) return {};
  if (/^\d{5}(-\d{4})?$/.test(t)) return { zip_code: t };
  const match = /^(.+?),\s*([A-Za-z]{2})(?:\s+(\d{5}(?:-\d{4})?))?$/.exec(t);
  if (match) {
    const out = { city: match[1].trim(), state: match[2].toUpperCase() };
    if (match[3]) out.zip_code = match[3];
    return out;
  }
  return { city: t };
}

function formFromParams(sp) {
  return {
    where: sp.get('where') || '',
    check_in: sp.get('check_in') || '',
    check_out: sp.get('check_out') || '',
    guests: sp.get('guests') || '',
    min_price: sp.get('min_price') || '',
    max_price: sp.get('max_price') || '',
    latitude: sp.get('latitude') || '',
    longitude: sp.get('longitude') || '',
    radius_km: sp.get('radius_km') || '',
    near: sp.get('near') || '',
    amenities: sp.getAll('amenities'),
    sort: sp.get('sort') || 'rating_desc',
    include_unavailable: sp.get('available_only') === 'false',
  };
}

function paramsFromForm(f) {
  const p = new URLSearchParams();
  if (f.where.trim()) {
    p.set('where', f.where.trim());
    Object.entries(parseWhere(f.where)).forEach(([k, v]) => p.set(k, v));
  }
  ['check_in', 'check_out', 'guests', 'min_price', 'max_price'].forEach((k) => f[k] && p.set(k, f[k]));
  if (f.latitude && f.longitude && f.radius_km) {
    p.set('latitude', f.latitude);
    p.set('longitude', f.longitude);
    p.set('radius_km', f.radius_km);
    if (f.near) p.set('near', f.near);
  }
  f.amenities.forEach((id) => p.append('amenities', id));
  if (f.sort && f.sort !== 'rating_desc') p.set('sort', f.sort);
  if (f.check_in && f.include_unavailable) p.set('available_only', 'false');
  return p;
}

function validate(f) {
  if (f.check_in && !f.check_out) return 'Choose a check-out date.';
  if (f.check_out && !f.check_in) return 'Choose a check-in date.';
  if (f.check_in && f.check_out) {
    const nights = nightsBetween(f.check_in, f.check_out);
    if (nights < 1) return 'Check-out must be after check-in.';
    if (nights > 14) return 'Stays can be at most 14 nights.';
  }
  if (f.min_price && f.max_price && Number(f.min_price) > Number(f.max_price))
    return 'Minimum price cannot exceed maximum price.';
  const some = f.latitude || f.longitude || f.radius_km;
  const all = f.latitude && f.longitude && f.radius_km;
  if (some && !all) return 'Latitude, longitude and radius must be given together.';
  if (f.sort === 'distance_asc' && !all) return 'Sorting by distance needs a location.';
  return '';
}

const stayQuery = (stay) => {
  const q = new URLSearchParams();
  ['check_in', 'check_out', 'guests'].forEach((k) => stay[k] && q.set(k, stay[k]));
  return q.toString() ? `?${q}` : '';
};

function Welcome({ user }) {
  const bookings = useAsync(() => bookingsApi.mine({ page: 1, page_size: 50 }), [user.id]);
  const next = (bookings.data?.data || [])
    .filter((b) => b.status === 'CONFIRMED')
    .sort((a, b) => a.check_in.localeCompare(b.check_in))[0];
  return (
    <section className="welcome">
      <h2>Welcome back, {user.name.split(' ')[0]} 👋</h2>
      {next && (
        <div className="row small">
          <Link to={`/bookings/${next.id}`} className="chip-link">
            Upcoming: {next.listing_name_snapshot} · {fmtDate(next.check_in, { month: 'short', day: 'numeric' })}–
            {fmtDate(next.check_out, { month: 'short', day: 'numeric' })}
          </Link>
          <Link to="/bookings">View my bookings</Link>
        </div>
      )}
    </section>
  );
}

function ResultRow({ listing: l, stay }) {
  const images = l.media.filter((m) => m.media_type === 'IMAGE');
  const videos = l.media.length - images.length;
  const cover = [...images].sort((a, b) => a.sort_order - b.sort_order)[0];
  const hasDates = stay.check_in && stay.check_out;
  const qs = stayQuery(stay);
  return (
    <article className="card result-row">
      <Link to={`/listings/${l.id}${qs}`} className="row-thumb">
        {cover ? <img src={cover.url} alt={cover.caption || l.name} loading="lazy" /> : <span>No photo</span>}
      </Link>
      <div className="row-body">
        <h3>
          <Link to={`/listings/${l.id}${qs}`}>{l.name}</Link>
        </h3>
        <div className="muted small">
          {l.city}, {l.state} {l.zip_code} · up to {l.max_guests} guests · {images.length} photo{images.length === 1 ? '' : 's'}
          {videos > 0 ? `, ${videos} video${videos === 1 ? '' : 's'}` : ''}
          {l.distance_km != null && ` · ${l.distance_km.toFixed(1)} km away`}
        </div>
        {l.amenities.length > 0 && (
          <div className="chips">
            {l.amenities.slice(0, 4).map((a) => (
              <span className="chip" key={a.id}>
                {a.name}
              </span>
            ))}
            {l.amenities.length > 4 && <span className="chip">+{l.amenities.length - 4}</span>}
          </div>
        )}
        <div className="small">
          {l.average_rating != null ? (
            <>
              <span className="stars">{'★'.repeat(Math.round(l.average_rating))}</span> {l.average_rating.toFixed(1)} · {l.review_count} review
              {l.review_count === 1 ? '' : 's'}
            </>
          ) : (
            <span className="muted">No reviews yet</span>
          )}
          {l.bookings_today > 0 && <span style={{ color: 'var(--warn)' }}> · Booked {l.bookings_today} time{l.bookings_today > 1 ? 's' : ''} today</span>}
        </div>
        <div>
          <span className="price">{money(l.nightly_price, l.currency)}</span>
          <span className="muted small">/night</span>
          {l.total_cost && (
            <span className="small">
              {' '}
              · <strong>{money(l.total_cost, l.currency)}</strong> total
            </span>
          )}
        </div>
      </div>
      <div className="row-action">
        {l.available === false ? (
          <button className="btn" disabled>
            Not available
          </button>
        ) : hasDates ? (
          <Link to={`/listings/${l.id}/book${qs}`} className="btn">
            Book
          </Link>
        ) : (
          <Link to={`/listings/${l.id}`} className="btn btn-secondary">
            View
          </Link>
        )}
      </div>
    </article>
  );
}

export default function Search() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [form, setForm] = useState(() => formFromParams(sp));
  const [formError, setFormError] = useState('');
  const [moreOpen, setMoreOpen] = useState(false);
  const [locating, setLocating] = useState(false);
  const [searchAsMove, setSearchAsMove] = useState(false);
  const key = sp.toString();

  useEffect(() => setForm(formFromParams(sp)), [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const amenities = useAsync(() => publicApi.amenities(), []);
  const results = useAsync(() => {
    const params = { page: sp.get('page') || 1, page_size: PAGE_SIZE };
    PASS_THROUGH.forEach((k) => sp.get(k) && (params[k] = sp.get(k)));
    params.sort = sp.get('sort') === 'distance_asc' && !sp.get('latitude') ? 'rating_desc' : sp.get('sort') || 'rating_desc';
    if (sp.get('available_only')) params.available_only = sp.get('available_only');
    params.amenities = sp.getAll('amenities');
    return publicApi.search(params);
  }, [key]);

  const update = (name) => (event) => setForm((f) => ({ ...f, [name]: event.target.value }));

  function apply(next) {
    const problem = validate(next);
    setFormError(problem);
    if (!problem) setSp(paramsFromForm(next));
  }
  const submit = (event) => {
    event.preventDefault();
    apply(form);
  };
  const change = (patch) => {
    const next = { ...form, ...patch };
    setForm(next);
    apply(next);
  };

  function pickPlace(place) {
    if (place.lat == null || place.lng == null) return setFormError('That place has no map location.');
    change({
      where: '',
      near: place.formatted || place.name,
      latitude: place.lat.toFixed(5),
      longitude: place.lng.toFixed(5),
      radius_km: form.radius_km || '25',
    });
  }

  function useMyLocation() {
    if (!navigator.geolocation) return setFormError('Location is not supported by this browser.');
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        change({
          where: '',
          near: 'My location',
          latitude: pos.coords.latitude.toFixed(5),
          longitude: pos.coords.longitude.toFixed(5),
          radius_km: form.radius_km || '25',
        });
      },
      () => {
        setFormError('Could not get your location.');
        setLocating(false);
      },
    );
  }

  const onMapMoved = useCallback(
    ({ lat, lng, radiusKm }) => {
      const next = new URLSearchParams(sp);
      ['where', 'city', 'state', 'zip_code', 'page'].forEach((k) => next.delete(k));
      next.set('latitude', lat.toFixed(5));
      next.set('longitude', lng.toFixed(5));
      next.set('radius_km', Math.min(500, Math.max(0.1, radiusKm)).toFixed(1));
      next.set('near', 'Map area');
      setSp(next, { replace: true });
    },
    [sp, setSp],
  );

  function goToPage(page) {
    const next = new URLSearchParams(sp);
    next.set('page', page);
    setSp(next);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const toggleAmenity = (id) =>
    setForm((f) => ({
      ...f,
      amenities: f.amenities.includes(id) ? f.amenities.filter((a) => a !== id) : [...f.amenities, id],
    }));

  const stay = { check_in: sp.get('check_in'), check_out: sp.get('check_out'), guests: sp.get('guests') };
  const nights = nightsBetween(form.check_in, form.check_out);
  const today = todayISO();
  const data = results.data;
  const total = data?.pagination.total_items ?? 0;
  const summary = [
    `${total} home${total === 1 ? '' : 's'}`,
    sp.get('where') ? `in ${sp.get('where')}` : sp.get('near') ? `near ${sp.get('near')}` : '',
    stay.check_in && stay.check_out
      ? `${fmtDate(stay.check_in, { month: 'short', day: 'numeric' })}–${fmtDate(stay.check_out, { month: 'short', day: 'numeric' })}`
      : '',
    stay.guests ? `${stay.guests} guest${stay.guests === '1' ? '' : 's'}` : '',
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <>
      {user?.role === 'CUSTOMER' ? (
        <Welcome user={user} />
      ) : (
        <section className="hero">
          <h1>Find your next getaway <span aria-hidden="true">🌴</span></h1>
          <p>Cozy cabins, city lofts and beach houses, all in one place.</p>
        </section>
      )}

      <form className="card searchbar" onSubmit={submit}>
        <Field label="Where" htmlFor="s-where">
          <input
            id="s-where"
            type="text"
            placeholder="City/state, zip or address — e.g. San Jose, CA 95112"
            value={form.where}
            onChange={update('where')}
          />
        </Field>
        <Field label="Check-in" htmlFor="s-in">
          <input
            id="s-in"
            type="date"
            min={today}
            value={form.check_in}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                check_in: e.target.value,
                check_out: f.check_out && f.check_out > e.target.value ? f.check_out : '',
              }))
            }
          />
        </Field>
        <Field label="Check-out" htmlFor="s-out">
          <input
            id="s-out"
            type="date"
            min={form.check_in ? addDaysISO(form.check_in, 1) : today}
            max={form.check_in ? addDaysISO(form.check_in, 14) : undefined}
            value={form.check_out}
            onChange={update('check_out')}
          />
        </Field>
        <Field label="Guests" htmlFor="s-guests">
          <input id="s-guests" type="number" min="1" value={form.guests} onChange={update('guests')} placeholder="2" />
        </Field>
        <div className="field">
          <button className="btn">Search</button>
        </div>
      </form>

      {formError && <div className="alert alert-error">{formError}</div>}

      <div className="filter-row">
        {nights > 0 && (
          <span className="chip chip-solid">
            {nights} night{nights === 1 ? '' : 's'} (max 14)
          </span>
        )}
        {form.check_in && form.check_out && (
          <label className="check">
            <input type="checkbox" checked={!form.include_unavailable} onChange={(e) => change({ include_unavailable: !e.target.checked })} />
            Available only
          </label>
        )}
        <label className="check">
          Sort:
          <select value={form.sort} onChange={(e) => change({ sort: e.target.value })} style={{ width: 'auto' }}>
            <option value="rating_desc">Top rated</option>
            <option value="newest">Newest</option>
            <option value="price_asc">Price: low to high</option>
            <option value="price_desc">Price: high to low</option>
            <option value="distance_asc">Distance (needs location)</option>
          </select>
        </label>
        {form.near && form.latitude && (
          <span className="chip chip-solid">
            Near: {form.near}{' '}
            <button type="button" className="chip-x" aria-label="Clear location" onClick={() => change({ near: '', latitude: '', longitude: '', radius_km: '', sort: form.sort === 'distance_asc' ? 'rating_desc' : form.sort })}>
              ×
            </button>
          </span>
        )}
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setMoreOpen((v) => !v)}>
          {moreOpen ? 'Hide filters' : 'More filters'}
        </button>
        {key && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSp(new URLSearchParams())}>
            Clear all
          </button>
        )}
      </div>

      {moreOpen && (
        <form
          className="card"
          style={{ marginBottom: '1rem' }}
          onSubmit={submit}
        >
          <div className="form-row">
            <Field label="Min price / night" htmlFor="f-min">
              <input id="f-min" type="number" min="0" step="1" value={form.min_price} onChange={update('min_price')} />
            </Field>
            <Field label="Max price / night" htmlFor="f-max">
              <input id="f-max" type="number" min="0" step="1" value={form.max_price} onChange={update('max_price')} />
            </Field>
          </div>
          <div className="field">
            <span className="field-label">Amenities</span>
            <div className="chips">
              {(amenities.data?.data || []).map((a) => (
                <label className="chip" key={a.id}>
                  <input type="checkbox" checked={form.amenities.includes(a.id)} onChange={() => toggleAmenity(a.id)} />
                  {a.name}
                </label>
              ))}
            </div>
          </div>
          <div className="field">
            <span className="field-label">Near a location</span>
            <PlaceSearch onSelect={pickPlace} />
            <div className="form-row">
              <input type="number" step="any" placeholder="Latitude" aria-label="Latitude" value={form.latitude} onChange={update('latitude')} />
              <input type="number" step="any" placeholder="Longitude" aria-label="Longitude" value={form.longitude} onChange={update('longitude')} />
              <input type="number" step="any" min="0" placeholder="Radius (km)" aria-label="Radius in km" value={form.radius_km} onChange={update('radius_km')} />
            </div>
            <div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={useMyLocation} disabled={locating}>
                {locating ? 'Locating…' : 'Use my location'}
              </button>
            </div>
          </div>
          <button className="btn">Apply filters</button>
        </form>
      )}

      <ErrorAlert error={results.error} />
      {results.loading && !data ? (
        <Spinner />
      ) : (
        data && (
          <>
            <p className="result-count">{summary}</p>
            <div className="results-layout">
              <div className="result-list" style={{ opacity: results.loading ? 0.6 : 1 }}>
                {data.data.length === 0 ? (
                  <div className="card">
                    <Empty title="No rentals match">
                      <p>Try different dates, a wider price range, or fewer amenities.</p>
                    </Empty>
                  </div>
                ) : (
                  data.data.map((l) => <ResultRow key={l.id} listing={l} stay={stay} />)
                )}
                <Pagination pagination={data.pagination} onPage={goToPage} />
              </div>
              <aside className="map-col">
                <MapView
                  height={480}
                  autoFit={!searchAsMove}
                  markers={data.data.map((l) => ({
                    id: l.id,
                    lat: l.latitude,
                    lng: l.longitude,
                    title: l.name,
                    subtitle: `${money(l.nightly_price, l.currency)} / night · ${l.city}, ${l.state}`,
                  }))}
                  onMarkerClick={(m) => navigate(`/listings/${m.id}${stayQuery(stay)}`)}
                  onIdle={searchAsMove ? onMapMoved : undefined}
                />
                {mapsEnabled && (
                  <label className="check small" style={{ marginTop: '0.5rem' }}>
                    <input type="checkbox" checked={searchAsMove} onChange={(e) => setSearchAsMove(e.target.checked)} />
                    Search as I move the map
                  </label>
                )}
              </aside>
            </div>
          </>
        )
      )}
    </>
  );
}
