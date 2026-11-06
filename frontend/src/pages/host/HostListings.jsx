import { useState } from 'react';
import { Link } from 'react-router-dom';
import { hostApi } from '../../api/endpoints';
import { useToast } from '../../context/ToastContext';
import useAsync from '../../hooks/useAsync';
import { Empty, ErrorAlert, Pagination, ReasonModal, Spinner, StatusBadge } from '../../components/ui';
import { fmtDate, money } from '../../utils/format';

const STATUSES = ['', 'PENDING', 'APPROVED', 'REJECTED', 'REMOVED'];

export default function HostListings() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const [removing, setRemoving] = useState(null);
  const listings = useAsync(() => hostApi.list({ page, page_size: 10, status }), [page, status]);

  async function remove(reason) {
    await hostApi.remove(removing.id, reason);
    toast.success('Listing removed.');
    setRemoving(null);
    listings.reload();
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>My listings</h1>
          <p>New and edited listings wait for admin approval before guests can see them.</p>
        </div>
        <Link to="/host/listings/new" className="btn">
          + New listing
        </Link>
      </div>

      <div className="tabs" role="tablist">
        {STATUSES.map((s) => (
          <button
            key={s || 'all'}
            role="tab"
            className={`tab ${status === s ? 'active' : ''}`}
            onClick={() => {
              setStatus(s);
              setPage(1);
            }}
          >
            {s ? s.charAt(0) + s.slice(1).toLowerCase() : 'All'}
          </button>
        ))}
      </div>

      <ErrorAlert error={listings.error} />
      {listings.loading && !listings.data ? (
        <Spinner />
      ) : listings.data?.data.length === 0 ? (
        <div className="card">
          <Empty title="No listings here">
            <Link to="/host/listings/new" className="btn">
              Create your first listing
            </Link>
          </Empty>
        </div>
      ) : (
        listings.data && (
          <div className="card card-flush">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Location</th>
                    <th>Price / night</th>
                    <th>Guests</th>
                    <th>Status</th>
                    <th>Updated</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {listings.data.data.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <strong>{l.name}</strong>
                      </td>
                      <td>
                        {l.city}, {l.state} {l.zip_code}
                      </td>
                      <td>{money(l.nightly_price, l.currency)}</td>
                      <td>{l.max_guests}</td>
                      <td>
                        <StatusBadge status={l.status} />
                      </td>
                      <td>{fmtDate(l.updated_at)}</td>
                      <td className="actions">
                        <Link to={`/host/listings/${l.id}`} className="btn btn-secondary btn-sm">
                          {l.status === 'REMOVED' ? 'View' : 'Edit'}
                        </Link>
                        {l.status === 'APPROVED' && (
                          <Link to={`/listings/${l.id}`} className="btn btn-ghost btn-sm">
                            Public page
                          </Link>
                        )}
                        {l.status !== 'REMOVED' && (
                          <button className="btn btn-danger btn-sm" onClick={() => setRemoving(l)}>
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
      <Pagination pagination={listings.data?.pagination} onPage={setPage} />

      {removing && (
        <ReasonModal
          title={`Remove “${removing.name}”?`}
          description="The listing is hidden from guests. Existing bookings and reviews are kept."
          confirmLabel="Remove listing"
          onSubmit={remove}
          onClose={() => setRemoving(null)}
        />
      )}
    </>
  );
}
