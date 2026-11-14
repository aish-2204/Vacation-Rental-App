import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { adminApi } from '../../api/endpoints';
import { useToast } from '../../context/ToastContext';
import useAsync from '../../hooks/useAsync';
import { ConfirmModal, ErrorAlert, ReasonModal, Spinner, StatusBadge } from '../../components/ui';
import { WEEKDAYS, fmtDateTime, fmtTime, money, titleCase } from '../../utils/format';

export default function AdminListingDetail() {
  const { id } = useParams();
  const toast = useToast();
  const [action, setAction] = useState(null);
  const listing = useAsync(() => adminApi.get(id), [id]);
  const history = useAsync(() => adminApi.audit({ listing_id: id, page_size: 20 }), [id]);

  if (listing.loading && !listing.data) return <Spinner />;
  if (listing.error)
    return (
      <div className="card">
        <ErrorAlert error={listing.error} />
        <Link to="/admin/listings" className="btn btn-secondary">
          Back to moderation
        </Link>
      </div>
    );
  const l = listing.data.data;
  const refresh = () => {
    listing.reload();
    history.reload();
  };

  async function approve() {
    await adminApi.approve(l.id);
    toast.success('Listing approved.');
    setAction(null);
    refresh();
  }
  async function reject(reason) {
    await adminApi.reject(l.id, reason);
    toast.success('Listing rejected.');
    setAction(null);
    refresh();
  }
  async function remove(reason) {
    await adminApi.remove(l.id, reason);
    toast.success('Listing removed.');
    setAction(null);
    refresh();
  }

  const issues = [];
  if (!l.media.some((m) => m.media_type === 'IMAGE')) issues.push('No image yet');
  if (l.hours.length < 7) issues.push('Contact hours incomplete');
  if (l.booking_rules.length < 7) issues.push('Booking rules incomplete');
  if (!l.description.trim()) issues.push('No description');

  return (
    <>
      <p>
        <Link to="/admin/listings">← Moderation</Link>
      </p>
      <div className="page-head">
        <div>
          <h1>{l.name}</h1>
          <p>
            <StatusBadge status={l.status} /> · Host {l.host_id}
          </p>
        </div>
        <div className="row">
          {l.status === 'PENDING' && (
            <>
              <button className="btn" onClick={() => setAction('approve')}>
                Approve
              </button>
              <button className="btn btn-danger" onClick={() => setAction('reject')}>
                Reject
              </button>
            </>
          )}
          {l.status !== 'REMOVED' && (
            <button className="btn btn-secondary" onClick={() => setAction('remove')}>
              Remove
            </button>
          )}
        </div>
      </div>

      {l.status === 'PENDING' && issues.length > 0 && (
        <div className="alert alert-warn">
          Approval may be blocked until these are fixed by the host:
          <ul>
            {issues.map((i) => (
              <li key={i}>{i}</li>
            ))}
          </ul>
        </div>
      )}
      {l.removal && (
        <div className="alert alert-error">
          Removed {fmtDateTime(l.removal.created_at)} — {l.removal.reason}
        </div>
      )}

      <div className="grid grid-2" style={{ alignItems: 'start' }}>
        <div className="stack">
          <section className="card">
            <h2>Details</h2>
            <p style={{ whiteSpace: 'pre-wrap' }}>{l.description || <span className="muted">No description.</span>}</p>
            <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.4rem 1.25rem' }}>
              {[
                ['Address', `${l.address_line1}${l.address_line2 ? `, ${l.address_line2}` : ''}, ${l.city}, ${l.state} ${l.zip_code}`],
                ['Coordinates', `${l.latitude}, ${l.longitude}`],
                ['Timezone', l.timezone],
                ['Price', `${money(l.nightly_price, l.currency)} / night (${l.cost_rating})`],
                ['Max guests', l.max_guests],
                ['Contact', [l.contact_name, l.contact_email, l.contact_phone].filter(Boolean).join(' · ') || '—'],
                ['Created', fmtDateTime(l.created_at)],
                ['Updated', fmtDateTime(l.updated_at)],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'contents' }}>
                  <dt className="muted">{k}</dt>
                  <dd style={{ margin: 0 }}>{v}</dd>
                </div>
              ))}
            </dl>
            {l.amenities.length > 0 && (
              <>
                <div className="divider" />
                <div className="chips">
                  {l.amenities.map((a) => (
                    <span className="chip" key={a.id}>
                      {a.name}
                    </span>
                  ))}
                </div>
              </>
            )}
          </section>

          <section className="card">
            <h2>Photos &amp; media ({l.media.length})</h2>
            {l.media.length === 0 ? (
              <p className="muted">None yet.</p>
            ) : (
              <div className="grid grid-3">
                {[...l.media]
                  .sort((a, b) => a.sort_order - b.sort_order)
                  .map((m) => (
                    <div key={m.id}>
                      <div className="thumb" style={{ borderRadius: 8 }}>
                        {m.media_type === 'IMAGE' ? <img src={m.url} alt={m.caption || ''} /> : <span className="small">Video</span>}
                      </div>
                      {m.caption && <div className="small muted">{m.caption}</div>}
                    </div>
                  ))}
              </div>
            )}
          </section>
        </div>

        <div className="stack">
          <section className="card">
            <h2>Hours &amp; booking rules</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Contact</th>
                    <th>Arrival</th>
                    <th>Departure</th>
                  </tr>
                </thead>
                <tbody>
                  {WEEKDAYS.map((day, i) => {
                    const h = l.hours.find((x) => x.weekday === i);
                    const r = l.booking_rules.find((x) => x.weekday === i);
                    return (
                      <tr key={day}>
                        <td>{day.slice(0, 3)}</td>
                        <td>{!h ? '—' : h.closed ? 'Closed' : `${fmtTime(h.opening_time)}–${fmtTime(h.closing_time)}`}</td>
                        <td>{!r ? '—' : r.arrival_allowed ? `${fmtTime(r.arrival_start)}–${fmtTime(r.arrival_end)}` : 'No'}</td>
                        <td>{!r ? '—' : r.departure_allowed ? `${fmtTime(r.departure_start)}–${fmtTime(r.departure_end)}` : 'No'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h2>Moderation history</h2>
            {history.loading && !history.data ? (
              <Spinner />
            ) : history.data?.data.length === 0 ? (
              <p className="muted">No admin actions yet.</p>
            ) : (
              history.data?.data.map((a) => (
                <div className="review" key={a.id}>
                  <div className="row spread">
                    <StatusBadge status={a.action} />
                    <span className="muted small">{fmtDateTime(a.created_at)}</span>
                  </div>
                  {a.reason && <p style={{ margin: '0.4rem 0 0' }}>{a.reason}</p>}
                </div>
              ))
            )}
          </section>
        </div>
      </div>

      {action === 'approve' && (
        <ConfirmModal
          title="Approve this listing?"
          message="It becomes visible to guests."
          confirmLabel="Approve"
          danger={false}
          onConfirm={approve}
          onClose={() => setAction(null)}
        />
      )}
      {action === 'reject' && (
        <ReasonModal title={`Reject “${l.name}”`} description="The host will see the listing as rejected." confirmLabel="Reject listing" onSubmit={reject} onClose={() => setAction(null)} />
      )}
      {action === 'remove' && (
        <ReasonModal title={`Remove “${l.name}”`} description={`Currently ${titleCase(l.status)}. Bookings and reviews are retained.`} confirmLabel="Remove listing" onSubmit={remove} onClose={() => setAction(null)} />
      )}
    </>
  );
}
