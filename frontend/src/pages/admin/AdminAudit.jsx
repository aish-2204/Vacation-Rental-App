import { useState } from 'react';
import { Link } from 'react-router-dom';
import { adminApi } from '../../api/endpoints';
import useAsync from '../../hooks/useAsync';
import { Empty, ErrorAlert, Field, Pagination, Spinner, StatusBadge } from '../../components/ui';
import { fmtDateTime } from '../../utils/format';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function AdminAudit() {
  const [page, setPage] = useState(1);
  const [filterInput, setFilterInput] = useState('');
  const [listingId, setListingId] = useState('');
  const [filterError, setFilterError] = useState('');
  const audit = useAsync(() => adminApi.audit({ page, page_size: 15, listing_id: listingId }), [page, listingId]);

  function apply(event) {
    event.preventDefault();
    const value = filterInput.trim();
    if (value && !UUID.test(value)) return setFilterError('Enter a valid listing ID (UUID).');
    setFilterError('');
    setPage(1);
    setListingId(value);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit log</h1>
          <p>Every approval, rejection and removal made by admins.</p>
        </div>
        <Link to="/admin/listings" className="btn btn-secondary">
          Back to moderation
        </Link>
      </div>

      <form className="card row" style={{ marginBottom: '1.25rem', alignItems: 'flex-end' }} onSubmit={apply}>
        <div style={{ flex: 1, minWidth: 260 }}>
          <Field label="Filter by listing ID" htmlFor="audit-listing" error={filterError}>
            <input id="audit-listing" type="text" value={filterInput} onChange={(e) => setFilterInput(e.target.value)} placeholder="All listings" />
          </Field>
        </div>
        <div className="field">
          <div className="row">
            <button className="btn">Filter</button>
            {listingId && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setFilterInput('');
                  setListingId('');
                  setPage(1);
                }}
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </form>

      <ErrorAlert error={audit.error} />
      {audit.loading && !audit.data ? (
        <Spinner />
      ) : audit.data?.data.length === 0 ? (
        <div className="card">
          <Empty title="No actions recorded" />
        </div>
      ) : (
        audit.data && (
          <div className="card card-flush">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Action</th>
                    <th>Listing</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data.data.map((a) => (
                    <tr key={a.id}>
                      <td>{fmtDateTime(a.created_at)}</td>
                      <td>
                        <StatusBadge status={a.action} />
                      </td>
                      <td>
                        <Link to={`/admin/listings/${a.listing_id}`}>{a.listing_id.slice(0, 8)}…</Link>
                      </td>
                      <td>{a.reason || <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
      <Pagination pagination={audit.data?.pagination} onPage={setPage} />
    </>
  );
}
