import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { bookingsApi } from '../api/endpoints';
import { useToast } from '../context/ToastContext';
import useAsync from '../hooks/useAsync';
import { ConfirmModal, ErrorAlert, Spinner, StatusBadge } from '../components/ui';
import { fmtDate, fmtDateTime, fmtTime, money } from '../utils/format';

export default function BookingDetail() {
  const { id } = useParams();
  const toast = useToast();
  const booking = useAsync(() => bookingsApi.get(id), [id]);
  const [confirmCancel, setConfirmCancel] = useState(false);

  if (booking.loading && !booking.data) return <Spinner />;
  if (booking.error)
    return (
      <div className="card">
        <ErrorAlert error={booking.error} />
        <Link to="/bookings" className="btn btn-secondary">
          Back to my bookings
        </Link>
      </div>
    );
  const b = booking.data.data;

  async function cancel() {
    await bookingsApi.cancel(b.id);
    toast.success('Booking cancelled.');
    setConfirmCancel(false);
    booking.reload();
  }

  const rows = [
    ['Check-in', `${fmtDate(b.check_in)} · ${fmtTime(b.check_in_time)}`],
    ['Check-out', `${fmtDate(b.check_out)} · ${fmtTime(b.check_out_time)}`],
    ['Nights', b.nights],
    ['Guests', b.guests],
    ['Nightly price', money(b.nightly_price_snapshot, b.currency)],
    ['Total', money(b.total_cost, b.currency)],
    ['Address', `${b.listing_address_snapshot}`],
    ['Booked on', fmtDateTime(b.created_at)],
  ];
  if (b.cancelled_at) rows.push(['Cancelled on', fmtDateTime(b.cancelled_at)]);

  return (
    <>
      <p>
        <Link to="/bookings">← My bookings</Link>
      </p>
      <div className="card" style={{ maxWidth: 720 }}>
        <div className="row spread" style={{ alignItems: 'flex-start' }}>
          <div>
            <h1 style={{ marginBottom: '0.15rem' }}>{b.listing_name_snapshot}</h1>
            <div className="muted small">Confirmation {b.id}</div>
          </div>
          <StatusBadge status={b.status} />
        </div>
        <div className="divider" />
        <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.5rem 1.5rem' }}>
          {rows.map(([label, value]) => (
            <div key={label} style={{ display: 'contents' }}>
              <dt className="muted">{label}</dt>
              <dd style={{ margin: 0, fontWeight: 600 }}>{value}</dd>
            </div>
          ))}
        </dl>
        <div className="divider" />
        <div className="row">
          <Link to={`/listings/${b.listing_id}`} className="btn btn-secondary">
            View listing
          </Link>
          {b.status === 'COMPLETED' && (
            <Link to={`/bookings/${b.id}/review`} className="btn">
              Write a review
            </Link>
          )}
          {b.can_cancel && (
            <button className="btn btn-danger" onClick={() => setConfirmCancel(true)}>
              Cancel booking
            </button>
          )}
        </div>
      </div>

      {confirmCancel && (
        <ConfirmModal
          title="Cancel this booking?"
          message="You can only cancel before your arrival time."
          confirmLabel="Cancel booking"
          onConfirm={cancel}
          onClose={() => setConfirmCancel(false)}
        />
      )}
    </>
  );
}
