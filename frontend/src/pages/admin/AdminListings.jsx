import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { adminApi } from '../../api/endpoints';
import { useToast } from '../../context/ToastContext';
import useAsync from '../../hooks/useAsync';
import { ConfirmModal, Empty, ErrorAlert, Pagination, ReasonModal, Spinner, StatusBadge } from '../../components/ui';
import { fmtDate, money } from '../../utils/format';

const TABS = [
  ['PENDING', 'Pending review'],
  ['', 'All'],
  ['APPROVED', 'Approved'],
  ['REJECTED', 'Rejected'],
  ['REMOVED', 'Removed'],
];

export default function AdminListings() {
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const status = sp.get('status') ?? 'PENDING';
  const page = Number(sp.get('page')) || 1;
  const [action, setAction] = useState(null); // { type, listing }
  const [zip, setZip] = useState('');
  const [sort, setSort] = useState('oldest');

  const listings = useAsync(
    () =>
      status === 'PENDING'
        ? adminApi.pending({ page, page_size: 10 })
        : adminApi.list({ page, page_size: 10, status }),
    [status, page],
  );

  const rows = (listings.data?.data || [])
    .filter((l) => !zip.trim() || l.zip_code.startsWith(zip.trim()))
    .sort((a, b) =>
      sort === 'name' ? a.name.localeCompare(b.name) : sort === 'newest' ? b.updated_at.localeCompare(a.updated_at) : a.updated_at.localeCompare(b.updated_at),
    );

  const setView = (nextStatus, nextPage = 1) => {
    const next = new URLSearchParams();
    next.set('status', nextStatus);
    if (nextPage > 1) next.set('page', nextPage);
    setSp(next);
  };

  async function approve() {
    await adminApi.approve(action.listing.id);
    toast.success(`“${action.listing.name}” approved.`);
    setAction(null);
    listings.reload();
  }
  async function reject(reason) {
    await adminApi.reject(action.listing.id, reason);
    toast.success(`“${action.listing.name}” rejected.`);
    setAction(null);
    listings.reload();
  }
  async function remove(reason) {
    await adminApi.remove(action.listing.id, reason);
    toast.success(`“${action.listing.name}” removed.`);
    setAction(null);
    listings.reload();
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Listing moderation</h1>
          <p>Approve, reject or remove listings. Every action is recorded in the audit log.</p>
        </div>
        <Link to="/admin/audit" className="btn btn-secondary">
          View audit log
        </Link>
      </div>

      <div className="tabs" role="tablist">
        {TABS.map(([value, label]) => (
          <button key={label} role="tab" aria-selected={status === value} className={`tab ${status === value ? 'active' : ''}`} onClick={() => setView(value)}>
            {label}
          </button>
        ))}
      </div>

      <div className="filter-row">
        {status === 'PENDING' && listings.data && <span className="chip chip-solid">{listings.data.pagination.total_items} pending</span>}
        <label className="check">ZIP:
          <input type="text" value={zip} onChange={(e) => setZip(e.target.value)} placeholder="e.g. 951" style={{ width: 100 }} />
        </label>
        <label className="check">Sort (this page):
          <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ width: 'auto' }}>
            <option value="oldest">Oldest first</option>
            <option value="newest">Newest first</option>
            <option value="name">Name</option>
          </select>
        </label>
      </div>
      <ErrorAlert error={listings.error} />
      {listings.loading && !listings.data ? (
        <Spinner />
      ) : listings.data?.data.length === 0 ? (
        <div className="card">
          <Empty title={status === 'PENDING' ? 'Nothing waiting for review' : 'No listings found'} />
        </div>
      ) : (
        listings.data && (
          <div className="card card-flush" style={{ opacity: listings.loading ? 0.6 : 1 }}>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Listing</th>
                    <th>Location</th>
                    <th>Price / night</th>
                    <th>Status</th>
                    <th>Updated</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <Link to={`/admin/listings/${l.id}`}>
                          <strong>{l.name}</strong>
                        </Link>
                        <div className="muted small">Up to {l.max_guests} guests</div>
                      </td>
                      <td>
                        {l.city}, {l.state} {l.zip_code}
                      </td>
                      <td>{money(l.nightly_price, l.currency)}</td>
                      <td>
                        <StatusBadge status={l.status} />
                      </td>
                      <td>{fmtDate(l.updated_at)}</td>
                      <td className="actions">
                        <Link to={`/admin/listings/${l.id}`} className="btn btn-secondary btn-sm">
                          Review
                        </Link>
                        {l.status === 'PENDING' && (
                          <>
                            <button className="btn btn-sm" onClick={() => setAction({ type: 'approve', listing: l })}>
                              Approve
                            </button>
                            <button className="btn btn-danger btn-sm" onClick={() => setAction({ type: 'reject', listing: l })}>
                              Reject
                            </button>
                          </>
                        )}
                        {l.status !== 'REMOVED' && (
                          <button className="btn btn-secondary btn-sm" onClick={() => setAction({ type: 'remove', listing: l })}>
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
      <Pagination pagination={listings.data?.pagination} onPage={(p) => setView(status, p)} />

      {action?.type === 'approve' && (
        <ConfirmModal
          title="Approve this listing?"
          message={`“${action.listing.name}” will become visible to guests. It must have full details, a photo, and weekly hours and rules.`}
          confirmLabel="Approve"
          danger={false}
          onConfirm={approve}
          onClose={() => setAction(null)}
        />
      )}
      {action?.type === 'reject' && (
        <ReasonModal
          title={`Reject “${action.listing.name}”`}
          description="The host will see the listing as rejected."
          confirmLabel="Reject listing"
          onSubmit={reject}
          onClose={() => setAction(null)}
        />
      )}
      {action?.type === 'remove' && (
        <ReasonModal
          title={`Remove “${action.listing.name}”`}
          description="The listing is hidden from guests; bookings and reviews are retained."
          confirmLabel="Remove listing"
          onSubmit={remove}
          onClose={() => setAction(null)}
        />
      )}
    </>
  );
}
