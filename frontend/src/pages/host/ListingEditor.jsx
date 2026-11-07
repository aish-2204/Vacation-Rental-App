import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { hostApi } from '../../api/endpoints';
import { useToast } from '../../context/ToastContext';
import useAsync from '../../hooks/useAsync';
import { Alert, ErrorAlert, Field, ReasonModal, Spinner, StatusBadge } from '../../components/ui';
import { DetailsFields, HoursEditor, RulesEditor } from '../../components/ListingForm';
import { BlocksTab, HoursTab, PhotosTab, RulesTab } from './ListingTabs';
import { fieldErrors, fmtDateTime } from '../../utils/format';
import {
  defaultHours,
  defaultRules,
  diffPayload,
  emptyForm,
  formFromListing,
  hoursToPayload,
  rulesToPayload,
  toPayload,
  validateForm,
  validateHours,
  validateRules,
} from '../../utils/listingForm';

/* ----------------------------------------------------------------- Create */
function CreateListing() {
  const navigate = useNavigate();
  const toast = useToast();
  const amenities = useAsync(() => hostApi.amenities(), []);
  const [form, setForm] = useState(emptyForm);
  const [hours, setHours] = useState(defaultHours);
  const [rules, setRules] = useState(defaultRules);
  const [photo, setPhoto] = useState({ url: '', caption: '' });
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const found = validateForm(form);
    const week = validateHours(hours) || validateRules(rules);
    if (week) found.week = week;
    if (photo.url.trim() && !/^https:\/\//i.test(photo.url.trim())) found.photo = 'Photo links must start with https://';
    setErrors(found);
    if (Object.keys(found).length) return window.scrollTo({ top: 0, behavior: 'smooth' });

    setBusy(true);
    setError(null);
    try {
      const payload = toPayload(form);
      if (!payload.address_line2) delete payload.address_line2;
      payload.hours = hoursToPayload(hours);
      payload.booking_rules = rulesToPayload(rules);
      if (photo.url.trim())
        payload.media = [
          { url: photo.url.trim(), media_type: 'IMAGE', caption: photo.caption.trim() || null, sort_order: 0 },
        ];
      const response = await hostApi.create(payload);
      toast.success('Listing created and sent for approval.');
      navigate(`/host/listings/${response.data.id}`);
    } catch (err) {
      setError(err);
      setBusy(false);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  const merged = { ...fieldErrors(error), ...errors };
  const hasErrors = Object.keys(errors).length > 0;

  return (
    <>
      <p>
        <Link to="/host/listings">← My listings</Link>
      </p>
      <div className="page-head">
        <div>
          <h1>New listing</h1>
          <p>Submit it for admin approval. It becomes visible to guests once approved.</p>
        </div>
      </div>
      {hasErrors && <Alert type="error">Please fix the highlighted fields{errors.week ? `. ${errors.week}` : ''}.</Alert>}
      <ErrorAlert error={error} />
      <form className="stack" onSubmit={submit} noValidate>
        <section className="card">
          <h2>Property details</h2>
          <DetailsFields form={form} setForm={setForm} errors={merged} amenities={amenities.data?.data || []} />
        </section>
        <section className="card">
          <h2>Cover photo (optional)</h2>
          <p className="muted">At least one image is needed before approval. You can add more after creating the listing.</p>
          <div className="form-row">
            <Field label="Image URL (https)" htmlFor="c-photo" error={errors.photo || merged.media}>
              <input id="c-photo" type="url" value={photo.url} onChange={(e) => setPhoto((p) => ({ ...p, url: e.target.value }))} placeholder="https://…" />
            </Field>
            <Field label="Caption" htmlFor="c-cap">
              <input id="c-cap" type="text" maxLength={200} value={photo.caption} onChange={(e) => setPhoto((p) => ({ ...p, caption: e.target.value }))} />
            </Field>
          </div>
        </section>
        <section className="card">
          <h2>Contact hours</h2>
          <HoursEditor rows={hours} onChange={setHours} />
        </section>
        <section className="card">
          <h2>Arrival &amp; departure rules</h2>
          <RulesEditor rows={rules} onChange={setRules} />
        </section>
        <div className="row">
          <button className="btn" disabled={busy}>
            {busy ? 'Creating…' : 'Create listing'}
          </button>
          <Link to="/host/listings" className="btn btn-secondary">
            Cancel
          </Link>
        </div>
      </form>
    </>
  );
}

/* ------------------------------------------------------------------- Edit */
function DetailsTab({ listing, amenities, onChanged }) {
  const toast = useToast();
  const [form, setForm] = useState(() => formFromListing(listing));
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    const found = validateForm(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    const patch = diffPayload(form, listing);
    if (Object.keys(patch).length === 0) return toast.success('Nothing to save — no changes made.');
    setBusy(true);
    setError(null);
    try {
      await hostApi.patch(listing.id, patch);
      toast.success('Listing saved.');
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const merged = { ...fieldErrors(error), ...errors };
  return (
    <form className="card" onSubmit={submit} noValidate>
      <h2>Property details</h2>
      <ErrorAlert error={error} hideDetails={Object.keys(fieldErrors(error)).length > 0} />
      <DetailsFields form={form} setForm={setForm} errors={merged} amenities={amenities} />
      <button className="btn" disabled={busy}>
        {busy ? 'Saving…' : 'Save changes'}
      </button>
    </form>
  );
}

const TABS = [
  ['details', 'Details'],
  ['photos', 'Photos'],
  ['hours', 'Contact hours'],
  ['rules', 'Booking rules'],
  ['blocks', 'Blocked dates'],
];

function StatusNote({ listing }) {
  switch (listing.status) {
    case 'PENDING':
      return <Alert type="info">Waiting for admin review. Approval needs complete details, at least one photo, and all seven days of hours and rules.</Alert>;
    case 'APPROVED':
      return <Alert type="success">Live on the site. Changes to name, description, location, guests, amenities, photos or booking rules may send it back for approval.</Alert>;
    case 'REJECTED':
      return <Alert type="warn">This listing was rejected. Saving any change sends it back for review.</Alert>;
    case 'REMOVED':
      return (
        <Alert type="error">
          This listing was removed
          {listing.removal ? ` on ${fmtDateTime(listing.removal.created_at)}. Reason: ${listing.removal.reason}` : '.'} It is read-only.
        </Alert>
      );
    default:
      return null;
  }
}

function EditListing({ id }) {
  const toast = useToast();
  const [tab, setTab] = useState('details');
  const [removing, setRemoving] = useState(false);
  const listing = useAsync(() => hostApi.get(id), [id]);
  const amenities = useAsync(() => hostApi.amenities(), []);

  if (listing.loading && !listing.data) return <Spinner />;
  if (listing.error)
    return (
      <div className="card">
        <ErrorAlert error={listing.error} />
        <Link to="/host/listings" className="btn btn-secondary">
          Back to my listings
        </Link>
      </div>
    );
  const data = listing.data.data;
  const readOnly = data.status === 'REMOVED';

  async function remove(reason) {
    await hostApi.remove(data.id, reason);
    toast.success('Listing removed.');
    setRemoving(false);
    listing.reload();
  }

  return (
    <>
      <p>
        <Link to="/host/listings">← My listings</Link>
      </p>
      <div className="page-head">
        <div>
          <h1>{data.name}</h1>
          <p>
            {data.city}, {data.state} · <StatusBadge status={data.status} />
          </p>
        </div>
        <div className="row">
          {data.status === 'APPROVED' && (
            <Link to={`/listings/${data.id}`} className="btn btn-secondary">
              View public page
            </Link>
          )}
          {!readOnly && (
            <button className="btn btn-danger" onClick={() => setRemoving(true)}>
              Remove listing
            </button>
          )}
        </div>
      </div>

      <StatusNote listing={data} />

      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={`tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      <fieldset disabled={readOnly} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        {tab === 'details' && (
          <DetailsTab key={data.updated_at} listing={data} amenities={amenities.data?.data || []} onChanged={listing.reload} />
        )}
        {tab === 'photos' && <PhotosTab listing={data} onChanged={listing.reload} />}
        {tab === 'hours' && <HoursTab key={data.updated_at} listing={data} onChanged={listing.reload} />}
        {tab === 'rules' && <RulesTab key={data.updated_at} listing={data} onChanged={listing.reload} />}
        {tab === 'blocks' && <BlocksTab listing={data} />}
      </fieldset>

      {removing && (
        <ReasonModal
          title={`Remove “${data.name}”?`}
          description="The listing is hidden from guests. Existing bookings and reviews are kept."
          confirmLabel="Remove listing"
          onSubmit={remove}
          onClose={() => setRemoving(false)}
        />
      )}
    </>
  );
}

export default function ListingEditor() {
  const { id } = useParams();
  return id ? <EditListing key={id} id={id} /> : <CreateListing />;
}
