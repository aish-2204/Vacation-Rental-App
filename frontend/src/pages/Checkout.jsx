import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { bookingsApi, publicApi } from '../api/endpoints';
import { useToast } from '../context/ToastContext';
import useAsync from '../hooks/useAsync';
import useQuote from '../hooks/useQuote';
import MapView from '../components/MapView';
import { Alert, ConfirmModal, ErrorAlert, Spinner } from '../components/ui';
import { errorText, fmtDate, fmtTime, money } from '../utils/format';
import { mapLink } from '../lib/maps';

function Confirmation({ booking: b, listing }) {
  const toast = useToast();
  const [status, setStatus] = useState(b.status);
  const [cancelling, setCancelling] = useState(false);
  async function cancel() {
    await bookingsApi.cancel(b.id);
    toast.success('Booking cancelled.');
    setStatus('CANCELLED');
    setCancelling(false);
  }
  return (
    <div className="card celebrate" style={{ maxWidth: 720, margin: '0 auto' }}>
      {status !== 'CANCELLED' && (
        <div className="confetti" aria-hidden="true">
          {Array.from({ length: 24 }, (_, i) => (
            <i key={i} style={{ left: `${(i * 4.3) % 100}%`, animationDelay: `${(i % 8) * 0.12}s` }} />
          ))}
        </div>
      )}
      <h1>{status === 'CANCELLED' ? 'Booking cancelled' : 'Booking confirmed 🎉'}</h1>
      <p className="muted">Confirmation {b.id}</p>
      <p>
        <strong>{b.listing_name_snapshot}</strong>
        <br />
        {fmtDate(b.check_in)} {fmtTime(b.check_in_time)} → {fmtDate(b.check_out)} {fmtTime(b.check_out_time)}
        <br />
        {b.nights} night{b.nights > 1 ? 's' : ''} · {b.guests} guest{b.guests > 1 ? 's' : ''} · <strong>{money(b.total_cost, b.currency)}</strong>
      </p>
      <p className="small">{b.listing_address_snapshot}</p>
      {listing && (
        <>
          <MapView markers={[{ id: listing.id, lat: listing.latitude, lng: listing.longitude, title: listing.name }]} zoom={14} height={220} />
          <p className="small">
            <a href={mapLink(listing.latitude, listing.longitude)} target="_blank" rel="noreferrer">Open in OpenStreetMap</a>
          </p>
        </>
      )}
      <div className="row">
        <Link to="/bookings" className="btn">View my bookings</Link>
        {status === 'CONFIRMED' && b.can_cancel && (
          <button className="btn btn-danger" onClick={() => setCancelling(true)}>Cancel booking</button>
        )}
      </div>
      {cancelling && (
        <ConfirmModal
          title="Cancel this booking?"
          message="You can only cancel before your arrival time."
          confirmLabel="Cancel booking"
          onConfirm={cancel}
          onClose={() => setCancelling(false)}
        />
      )}
    </div>
  );
}

export default function Checkout() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const navigate = useNavigate();
  const listingQ = useAsync(() => publicApi.detail(id), [id]);
  const stay = { check_in: sp.get('check_in') || '', check_out: sp.get('check_out') || '', guests: sp.get('guests') || '1' };
  const listing = listingQ.data?.data;
  const q = useQuote(id, stay, listing?.max_guests);
  const [agree, setAgree] = useState(false);
  const [agreeError, setAgreeError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [booking, setBooking] = useState(null);

  if (listingQ.loading && !listing) return <Spinner />;
  if (listingQ.error) return <div className="card"><ErrorAlert error={listingQ.error} /></div>;
  if (booking) return <Confirmation booking={booking} listing={listing} />;

  const quote = q.result?.data;
  const back = `/listings/${id}?${sp.toString()}`;

  async function confirm(event) {
    event.preventDefault();
    if (!agree) return setAgreeError(true);
    setBusy(true);
    setError(null);
    try {
      const response = await bookingsApi.create({
        listing_id: id,
        check_in: stay.check_in,
        check_out: stay.check_out,
        guests: Number(stay.guests),
      });
      setBooking(response.data);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" style={{ maxWidth: 560, margin: '0 auto' }} onSubmit={confirm}>
      <h1>Confirm your booking</h1>
      <p><strong>{listing.name}</strong><br /><span className="muted small">{listing.address_line1}, {listing.city}, {listing.state} {listing.zip_code}</span></p>
      {q.problem && <Alert type="warn">{q.problem}</Alert>}
      {q.loading && <p className="muted">Checking availability…</p>}
      {q.result?.error && <div className="alert alert-error">{errorText(q.result.error)}{q.result.error.status ? ` (${q.result.error.status})` : ''}</div>}
      {quote && !quote.available && <Alert type="warn">Those dates are no longer available.</Alert>}
      {quote?.available && (
        <>
          <div className="quote-line"><span>Check-in</span><span>{fmtDate(quote.quote.check_in)} · {fmtTime(quote.quote.check_in_time)}</span></div>
          <div className="quote-line"><span>Check-out</span><span>{fmtDate(quote.quote.check_out)} · {fmtTime(quote.quote.check_out_time)}</span></div>
          <div className="quote-line"><span>Guests</span><span>{stay.guests}</span></div>
          <div className="quote-line"><span>{money(quote.quote.nightly_price)} × {quote.quote.nights} night{quote.quote.nights > 1 ? 's' : ''}</span><span>{money(quote.total_cost)}</span></div>
          <div className="quote-line quote-total"><span>Total</span><span>{money(quote.total_cost)}</span></div>
        </>
      )}
      <div className={`field ${agreeError && !agree ? 'has-error' : ''}`} style={{ marginTop: '1rem' }}>
        <label className="check">
          <input type="checkbox" checked={agree} onChange={(e) => { setAgree(e.target.checked); setAgreeError(false); }} />
          I agree to the house rules and the check-in / check-out times
        </label>
        {agreeError && !agree && <span className="error-text">Please agree to continue</span>}
      </div>
      {error && <div className="alert alert-error" role="alert">{errorText(error)}{error.status ? ` (${error.status})` : ''}</div>}
      <div className="row">
        <button className="btn" disabled={busy || !quote?.available}>{busy ? 'Booking…' : 'Confirm booking'}</button>
        <button type="button" className="btn btn-secondary" onClick={() => navigate(back)}>Back</button>
      </div>
    </form>
  );
}
