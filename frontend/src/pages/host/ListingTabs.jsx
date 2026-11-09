import { useState } from 'react';
import { hostApi } from '../../api/endpoints';
import { useToast } from '../../context/ToastContext';
import useAsync from '../../hooks/useAsync';
import { ConfirmModal, Empty, ErrorAlert, Field, Pagination, Spinner } from '../../components/ui';
import { HoursEditor, RulesEditor } from '../../components/ListingForm';
import { fmtDate, fieldErrors } from '../../utils/format';
import {
  hoursFromListing,
  hoursToPayload,
  rulesFromListing,
  rulesToPayload,
  validateHours,
  validateRules,
} from '../../utils/listingForm';

/* ------------------------------------------------------------------ Photos */
export function HoursTab({ listing, onChanged }) {
  const toast = useToast();
  const [rows, setRows] = useState(() => hoursFromListing(listing.hours));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [local, setLocal] = useState('');

  async function save() {
    const problem = validateHours(rows);
    setLocal(problem);
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      await hostApi.replaceHours(listing.id, hoursToPayload(rows));
      toast.success('Contact hours saved.');
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Contact hours</h2>
      <p className="muted">When guests can reach you, in the listing's local time. These are shown for information only.</p>
      {local && <div className="alert alert-error">{local}</div>}
      <ErrorAlert error={error} />
      <HoursEditor rows={rows} onChange={setRows} />
      <button className="btn" style={{ marginTop: '1rem' }} onClick={save} disabled={busy}>
        {busy ? 'Saving…' : 'Save contact hours'}
      </button>
    </section>
  );
}

export function RulesTab({ listing, onChanged }) {
  const toast = useToast();
  const [rows, setRows] = useState(() => rulesFromListing(listing.booking_rules));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [local, setLocal] = useState('');

  async function save() {
    const problem = validateRules(rows);
    setLocal(problem);
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      await hostApi.replaceRules(listing.id, rulesToPayload(rows));
      toast.success('Booking rules saved.');
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Arrival &amp; departure rules</h2>
      <p className="muted">Allowed arrival and departure windows for each weekday, in local time. At least one arrival day and one departure day are needed for approval.</p>
      {local && <div className="alert alert-error">{local}</div>}
      <ErrorAlert error={error} />
      <RulesEditor rows={rows} onChange={setRows} />
      <button className="btn" style={{ marginTop: '1rem' }} onClick={save} disabled={busy}>
        {busy ? 'Saving…' : 'Save booking rules'}
      </button>
    </section>
  );
}

/* ----------------------------------------------------------- Blocked dates */
