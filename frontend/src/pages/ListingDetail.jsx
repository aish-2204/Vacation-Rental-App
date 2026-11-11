import { useEffect, useState } from 'react';
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom';
import { publicApi } from '../api/endpoints';
import { useAuth } from '../context/AuthContext';
import useAsync from '../hooks/useAsync';
import useQuote from '../hooks/useQuote';
import { Alert, ErrorAlert, Field, Spinner, Stars } from '../components/ui';
import MapView from '../components/MapView';
import { mapLink } from '../lib/maps';
import { WEEKDAYS, addDaysISO, fmtDate, fmtDateTime, fmtTime, errorText, money, todayISO } from '../utils/format';

function Lightbox({ items, start, onClose }) {
  const [i, setI] = useState(start);
  const prev = () => setI((n) => (n + items.length - 1) % items.length);
  const next = () => setI((n) => (n + 1) % items.length);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') prev();
      if (e.key === 'ArrowRight') next();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  const cur = items[i];
  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="Photo viewer" onClick={onClose}>
      <div className="lightbox-inner" onClick={(e) => e.stopPropagation()}>
        {cur.media_type === 'VIDEO' ? <video src={cur.url} controls /> : <img src={cur.url} alt={cur.caption || ''} />}
        <div className="lightbox-bar">
          <button className="btn btn-secondary btn-sm" onClick={prev}>‹ Prev</button>
          <span>{i + 1} / {items.length}{cur.caption ? ` · ${cur.caption}` : ''}</span>
          <button className="btn btn-secondary btn-sm" onClick={next}>Next ›</button>
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function PhotoGrid({ media, name }) {
  const items = [...(media || [])].sort((a, b) => a.sort_order - b.sort_order);
  const [open, setOpen] = useState(null);
  if (!items.length) return <div className="photo-grid photo-empty muted">No photos yet</div>;
  const shown = items.slice(0, 5);
  return (
    <>
      <div className={`photo-grid photo-${Math.min(shown.length, 5)}`}>
        {shown.map((m, i) => (
          <button key={m.id} type="button" className="photo-cell" onClick={() => setOpen(i)} aria-label={`Open photo ${i + 1}`}>
            {m.media_type === 'IMAGE' ? <img src={m.url} alt={m.caption || name} /> : <span>Video</span>}
          </button>
        ))}
        {items.length > 5 && (
          <button type="button" className="btn btn-secondary btn-sm photo-more" onClick={() => setOpen(0)}>
            View all {items.length} photos
          </button>
        )}
      </div>
      {open != null && <Lightbox items={items} start={open} onClose={() => setOpen(null)} />}
    </>
  );
}

/** Groups consecutive days with identical text: ["a","a","b"] -> [{days:"Mon–Tue", text:"a"}, ...] (no day label when all 7 match). */
function groupDays(texts) {
  const runs = [];
  texts.forEach((text, i) => {
    const last = runs[runs.length - 1];
    if (last && last.text === text) last.end = i;
    else runs.push({ start: i, end: i, text });
  });
  const short = (i) => WEEKDAYS[i].slice(0, 3);
  return runs.map((r) => ({
    text: r.text,
    days: runs.length === 1 ? '' : r.start === r.end ? short(r.start) : `${short(r.start)}–${short(r.end)}`,
  }));
}

function Schedule({ data }) {
  const rules = WEEKDAYS.map((_, i) => data.booking_rules.find((r) => r.weekday === i));
  const hours = WEEKDAYS.map((_, i) => data.hours.find((h) => h.weekday === i));
  const arrival = rules.map((r) => (r?.arrival_allowed ? `${fmtTime(r.arrival_start)} – ${fmtTime(r.arrival_end)}` : 'Not allowed'));
  const departure = rules.map((r) => (r?.departure_allowed ? `${fmtTime(r.departure_start)} – ${fmtTime(r.departure_end)}` : 'Not allowed'));
  const reachable = hours.map((h) => (!h || h.closed ? 'Closed' : `${fmtTime(h.opening_time)} – ${fmtTime(h.closing_time)}`));
  const line = (label, texts) => (
    <div className="sched-line">
      <strong>{label}</strong>{' '}
      {groupDays(texts).map((g, i) => (
        <span key={i}>
          {i > 0 && <span className="muted"> · </span>}
          {g.days && <span className="muted">{g.days} </span>}
          {g.text}
        </span>
      ))}
    </div>
  );
  return (
    <section className="card">
      <h2>Check-in &amp; check-out</h2>
      {line('Check-in', arrival)}
      {line('Check-out', departure)}
      {line('Host reachable', reachable)}
      <details className="sched-details">
        <summary>See full weekly schedule</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Day</th><th>Arrival</th><th>Departure</th><th>Host reachable</th></tr>
            </thead>
            <tbody>
              {WEEKDAYS.map((day, i) => (
                <tr key={day}><td>{day}</td><td>{arrival[i]}</td><td>{departure[i]}</td><td>{reachable[i]}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function BookingPanel({ listing, initial }) {
  const { user } = useAuth();
  const location = useLocation();
  const today = todayISO();
  const [stay, setStay] = useState({ check_in: initial.check_in || '', check_out: initial.check_out || '', guests: initial.guests || '1' });
  const q = useQuote(listing.id, stay, listing.max_guests);
  const set = (name) => (e) => setStay((s) => ({ ...s, [name]: e.target.value }));
  const quote = q.result?.data;
  const qs = new URLSearchParams(stay).toString();
  const checkoutPath = `/listings/${listing.id}/book?${qs}`;
  const unavailable = quote && !quote.available;

  return (
    <aside className="card booking-panel">
      <div>
        <span className="price" style={{ fontSize: '1.4rem' }}>{money(listing.nightly_price, listing.currency)}</span>
        <span className="muted"> / night</span>
      </div>
      <div className="divider" />
      <div className="form-row">
        <Field label="Check-in" htmlFor="b-in">
          <input id="b-in" type="date" min={today} value={stay.check_in}
            onChange={(e) => setStay((s) => ({ ...s, check_in: e.target.value, check_out: s.check_out && s.check_out > e.target.value ? s.check_out : '' }))} />
        </Field>
        <Field label="Check-out" htmlFor="b-out">
          <input id="b-out" type="date" min={stay.check_in ? addDaysISO(stay.check_in, 1) : today}
            max={stay.check_in ? addDaysISO(stay.check_in, 14) : undefined} value={stay.check_out} onChange={set('check_out')} />
        </Field>
      </div>
      <Field label="Guests" htmlFor="b-guests" hint={`Up to ${listing.max_guests}`}>
        <input id="b-guests" type="number" min="1" max={listing.max_guests} value={stay.guests} onChange={set('guests')} />
      </Field>

      {q.problem && stay.check_in && stay.check_out && <Alert type="warn">{q.problem}</Alert>}
      {q.loading && <p className="muted small">Checking availability…</p>}
      {q.result?.error && <div className="alert alert-error">{errorText(q.result.error)}{q.result.error.status ? ` (${q.result.error.status})` : ''}</div>}
      {unavailable && <Alert type="warn">Those dates are not available. Try different dates.</Alert>}
      {quote?.available && (
        <div>
          <div className="quote-line"><span>{money(quote.quote.nightly_price)} × {quote.quote.nights} night{quote.quote.nights > 1 ? 's' : ''}</span><span>{money(quote.total_cost)}</span></div>
          <div className="quote-line muted small"><span>Arrive</span><span>{fmtDate(quote.quote.check_in)} · {fmtTime(quote.quote.check_in_time)}</span></div>
          <div className="quote-line muted small"><span>Depart</span><span>{fmtDate(quote.quote.check_out)} · {fmtTime(quote.quote.check_out_time)}</span></div>
          <div className="quote-line quote-total"><span>Total</span><span>{money(quote.total_cost)}</span></div>
        </div>
      )}
      {!user ? (
        <Link to="/login" state={{ from: checkoutPath }} className={`btn btn-block ${quote?.available ? '' : 'disabled'}`} style={{ marginTop: '0.9rem' }}
          onClick={(e) => !quote?.available && e.preventDefault()}>Log in to book</Link>
      ) : user.role !== 'CUSTOMER' ? (
        <div className="alert alert-info" style={{ marginTop: '0.9rem' }}>Only customer accounts can book stays.</div>
      ) : quote?.available ? (
        <Link to={checkoutPath} className="btn btn-block" style={{ marginTop: '0.9rem' }}>Book this stay</Link>
      ) : (
        <button className="btn btn-block" style={{ marginTop: '0.9rem' }} disabled>Book this stay</button>
      )}
      <p className="muted small" style={{ marginTop: '0.6rem' }}>You won't be charged yet. The server confirms the final price when you book.</p>
    </aside>
  );
}

export default function ListingDetail() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const listing = useAsync(() => publicApi.detail(id), [id]);

  if (listing.loading && !listing.data) return <Spinner />;
  if (listing.error)
    return (
      <div className="card">
        <ErrorAlert error={listing.error} />
        <Link to="/" className="btn btn-secondary">
          Back to search
        </Link>
      </div>
    );
  const data = listing.data.data;

  return (
    <>
      <p>
        <Link to={`/?${sp.toString()}`}>← Back to results</Link>
      </p>
      <div className="page-head">
        <div>
          <h1>{data.name}</h1>
          <p>
            {data.address_line1}
            {data.address_line2 ? `, ${data.address_line2}` : ''}, {data.city}, {data.state} {data.zip_code}
          </p>
        </div>
        <Stars value={data.average_rating} count={data.review_count} />
      </div>

      <div className="detail-layout">
        <div className="stack">
          <PhotoGrid media={data.media} name={data.name} />

          <section className="card">
            <h2>About this rental</h2>
            <p style={{ whiteSpace: 'pre-wrap' }}>{data.description || 'No description provided.'}</p>
            <div className="row">
              <span className="chip">Sleeps {data.max_guests}</span>
              <span className="chip">Rating tier: {data.cost_rating}</span>
              <span className="chip">Timezone: {data.timezone}</span>
            </div>
            {data.amenities.length > 0 && (
              <>
                <div className="divider" />
                <h3>Amenities</h3>
                <div className="chips">
                  {data.amenities.map((a) => (
                    <span className="chip" key={a.id}>
                      {a.name}
                    </span>
                  ))}
                </div>
              </>
            )}
          </section>

          <Schedule data={data} />

          <section className="card">
            <h2>Location</h2>
            <MapView
              markers={[{ id: data.id, lat: data.latitude, lng: data.longitude, title: data.name }]}
              zoom={14}
              height={300}
            />
            <p className="small" style={{ margin: '0.6rem 0 0' }}>
              {data.address_line1}, {data.city}, {data.state} {data.zip_code} ·{' '}
              <a href={mapLink(data.latitude, data.longitude)} target="_blank" rel="noreferrer">
                Open in OpenStreetMap
              </a>
            </p>
          </section>

          <section className="card">
            <h2>Contact host</h2>
            <p style={{ margin: 0 }}>
              {data.contact_name || 'Host'}
              {data.contact_email && (
                <>
                  {' · '}
                  <a href={`mailto:${data.contact_email}`}>{data.contact_email}</a>
                </>
              )}
              {data.contact_phone && ` · ${data.contact_phone}`}
            </p>
          </section>

          <Reviews listingId={data.id} average={data.average_rating} count={data.review_count} />
        </div>

        <BookingPanel
          listing={data}
          initial={{ check_in: sp.get('check_in'), check_out: sp.get('check_out'), guests: sp.get('guests') }}
        />
      </div>
    </>
  );
}
