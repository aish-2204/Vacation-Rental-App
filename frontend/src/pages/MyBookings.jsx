import { useState } from 'react';
import { Link } from 'react-router-dom';
import { bookingsApi } from '../api/endpoints';
import { useToast } from '../context/ToastContext';
import useAsync from '../hooks/useAsync';
import useCovers from '../hooks/useCovers';
import { ConfirmModal, Empty, ErrorAlert, Spinner } from '../components/ui';
import { fmtDate, money, todayISO } from '../utils/format';

const TABS = [
  ['upcoming', 'Upcoming'],
  ['past', 'Past'],
  ['cancelled', 'Cancelled'],
];

function tabOf(b, today) {
  if (b.status === 'CANCELLED') return 'cancelled';
  if (b.status === 'COMPLETED' || b.check_out < today) return 'past';
  return 'upcoming';
}

export default function MyBookings() {
  const toast = useToast();
  const [tab, setTab] = useState('upcoming');
  const [target, setTarget] = useState(null);
  const bookings = useAsync(async () => {
    let page = 1;
    let all = [];
    for (;;) {
      const r = await bookingsApi.mine({ page, page_size: 50 });
      all = all.concat(r.data);
      if (page >= r.pagination.total_pages || page >= 10) return all;
      page += 1;
    }
  }, []);
  const list = bookings.data || [];
  const covers = useCovers(list.map((b) => b.listing_id));
  const today = todayISO();
  const shown = list.filter((b) => tabOf(b, today) === tab).sort((a, b) => (tab === 'upcoming' ? a.check_in.localeCompare(b.check_in) : b.check_in.localeCompare(a.check_in)));
  const counts = Object.fromEntries(TABS.map(([k]) => [k, list.filter((b) => tabOf(b, today) === k).length]));

  async function cancel() {
    await bookingsApi.cancel(target.id);
    toast.success('Booking cancelled.');
    setTarget(null);
    bookings.reload();
  }

  return (
    <>
      <div className="page-head">
        <h1>My bookings</h1>
        <Link to="/" className="btn">Find a stay</Link>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'tab active' : 'tab'} onClick={() => setTab(k)}>
            {label} ({counts[k]})
          </button>
        ))}
      </div>
      <ErrorAlert error={bookings.error} />
      {bookings.loading && !bookings.data ? (
        <Spinner />
      ) : shown.length === 0 ? (
        <div className="card">
          <Empty title={`No ${tab} bookings`}>
            {tab === 'upcoming' && <Link to="/" className="btn">Explore rentals</Link>}
          </Empty>
        </div>
      ) : (
        <div className="stack">
          {shown.map((b) => {
            const cover = covers[b.listing_id];
            return (
              <article className="card result-row" key={b.id}>
                <Link to={`/bookings/${b.id}`} className="row-thumb">
                  {cover?.url ? <img src={cover.url} alt="" loading="lazy" /> : <span>No photo</span>}
                </Link>
                <div className="row-body">
                  <h3><Link to={`/bookings/${b.id}`}>{b.listing_name_snapshot}</Link></h3>
                  <div className="muted small">{b.listing_address_snapshot}</div>
                  <strong>{fmtDate(b.check_in)} → {fmtDate(b.check_out)}</strong>
                  <div className="muted small">
                    {b.nights} night{b.nights > 1 ? 's' : ''} · {b.guests} guest{b.guests > 1 ? 's' : ''} · {money(b.total_cost, b.currency)}
                  </div>
                </div>
                <div className="row-action">
                  <Link to={`/bookings/${b.id}`} className="btn btn-secondary btn-sm">View</Link>
                  {b.status === 'COMPLETED' && <Link to={`/bookings/${b.id}/review`} className="btn btn-sm">Write review</Link>}
                  {b.can_cancel && <button className="btn btn-danger btn-sm" onClick={() => setTarget(b)}>Cancel</button>}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {target && (
        <ConfirmModal
          title="Cancel this booking?"
          message={`Your stay at ${target.listing_name_snapshot} (${fmtDate(target.check_in)} – ${fmtDate(target.check_out)}) will be cancelled. You can only cancel before the arrival time.`}
          confirmLabel="Cancel booking"
          onConfirm={cancel}
          onClose={() => setTarget(null)}
        />
      )}
    </>
  );
}
