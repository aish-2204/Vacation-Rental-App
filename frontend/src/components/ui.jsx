import { useEffect, useState } from 'react';
import { errorText } from '../utils/format';

export function Spinner() {
  return <div className="spinner" role="progressbar" aria-label="Loading" />;
}

/** Shows an ApiError (message plus any field details). */
export function ErrorAlert({ error, hideDetails = false }) {
  if (!error) return null;
  const details = hideDetails ? [] : error.details || [];
  return (
    <div className="alert alert-error" role="alert">
      {errorText(error)}
      {details.length > 0 && (
        <ul>
          {details.map((detail, index) => (
            <li key={index}>
              {detail.field ? `${String(detail.field).split('.').pop()}: ` : ''}
              {detail.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Alert({ type = 'info', children }) {
  return <div className={`alert alert-${type}`}>{children}</div>;
}

export function Empty({ title, children }) {
  return (
    <div className="empty">
      <div className="empty-emoji" aria-hidden="true">🏖️</div>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}

export function Stars({ value, count }) {
  if (value === null || value === undefined) return <span className="muted small">No reviews yet</span>;
  const rounded = Math.round(value);
  return (
    <span className="row" style={{ gap: '0.35rem' }}>
      <span className="stars" aria-label={`${value} out of 5`}>
        {'★'.repeat(rounded)}
        <span className="off">{'★'.repeat(5 - rounded)}</span>
      </span>
      <span className="small muted">
        {Number(value).toFixed(1)}
        {count !== undefined ? ` (${count})` : ''}
      </span>
    </span>
  );
}

export function RatingInput({ value, onChange }) {
  return (
    <div className="rating-input" role="radiogroup" aria-label="Rating">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          type="button"
          key={n}
          className={n <= value ? 'on' : ''}
          onClick={() => onChange(n)}
          aria-label={`${n} star${n > 1 ? 's' : ''}`}
          aria-pressed={n === value}
        >
          ★
        </button>
      ))}
    </div>
  );
}

export function Field({ label, error, hint, children, htmlFor }) {
  return (
    <div className={`field ${error ? 'has-error' : ''}`}>
      {label && <label htmlFor={htmlFor}>{label}</label>}
      {children}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}

export function Pagination({ pagination, onPage }) {
  if (!pagination || pagination.total_pages <= 1) return null;
  const { page, total_pages, total_items } = pagination;
  return (
    <nav className="pagination" aria-label="Pagination">
      <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        ← Previous
      </button>
      <span>
        Page {page} of {total_pages} · {total_items} total
      </span>
      <button
        className="btn btn-secondary btn-sm"
        disabled={page >= total_pages}
        onClick={() => onPage(page + 1)}
      >
        Next →
      </button>
    </nav>
  );
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const handler = (event) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

/** Modal that asks for a required text reason (reject / remove listing). */
export function ReasonModal({ title, description, confirmLabel, danger = true, onSubmit, onClose }) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    if (!reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(reason.trim());
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit}>
        {description && <p className="muted">{description}</p>}
        <ErrorAlert error={error} />
        <Field label="Reason" hint="Required. Up to 2000 characters.">
          <textarea
            value={reason}
            maxLength={2000}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
            required
          />
        </Field>
        <div className="modal-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={`btn ${danger ? 'btn-danger' : ''}`} disabled={busy || !reason.trim()}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ConfirmModal({ title, message, confirmLabel, danger = true, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }
  return (
    <Modal title={title} onClose={onClose}>
      <ErrorAlert error={error} />
      <p>{message}</p>
      <div className="modal-actions">
        <button className="btn btn-secondary" onClick={onClose} disabled={busy}>
          Keep it
        </button>
        <button className={`btn ${danger ? 'btn-danger' : ''}`} onClick={confirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
