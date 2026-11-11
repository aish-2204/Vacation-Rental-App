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
function MediaRow({ listing, item, onChanged }) {
  const toast = useToast();
  const [caption, setCaption] = useState(item.caption || '');
  const [order, setOrder] = useState(String(item.sort_order));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const dirty = caption !== (item.caption || '') || order !== String(item.sort_order);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await hostApi.patchMedia(listing.id, item.id, {
        caption: caption.trim() || null,
        sort_order: parseInt(order, 10) || 0,
      });
      toast.success('Media updated.');
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    await hostApi.deleteMedia(listing.id, item.id);
    toast.success('Media removed.');
    setConfirmDelete(false);
    onChanged();
  }

  return (
    <div className="media-row">
      <div className="thumb">
        {item.media_type === 'IMAGE' ? <img src={item.url} alt={item.caption || ''} /> : <video src={item.url} muted preload="metadata" />}
      </div>
      <div>
        <div className="small muted" style={{ wordBreak: 'break-all' }}>
          {item.media_type} · {item.url}
        </div>
        <ErrorAlert error={error} />
        <div className="form-row" style={{ marginTop: '0.4rem' }}>
          <input type="text" value={caption} maxLength={200} placeholder="Caption" aria-label="Caption" onChange={(e) => setCaption(e.target.value)} />
          <input type="number" min="0" value={order} aria-label="Sort order" title="Sort order" onChange={(e) => setOrder(e.target.value)} />
        </div>
      </div>
      <div className="row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
        <button className="btn btn-sm" disabled={!dirty || busy} onClick={save}>
          Save
        </button>
        <button className="btn btn-danger btn-sm" onClick={() => setConfirmDelete(true)}>
          Delete
        </button>
      </div>
      {confirmDelete && (
        <ConfirmModal
          title="Delete this media?"
          message="Removing photos can send an approved listing back for review."
          confirmLabel="Delete"
          onConfirm={remove}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  );
}

export function PhotosTab({ listing, onChanged }) {
  const toast = useToast();
  const [form, setForm] = useState({ url: '', media_type: 'IMAGE', caption: '', sort_order: String(listing.media.length) });
  const [source, setSource] = useState('upload');
  const [file, setFile] = useState(null);
  const [fileKey, setFileKey] = useState(0);
  const [progress, setProgress] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const errors = fieldErrors(error);
  const items = [...listing.media].sort((a, b) => a.sort_order - b.sort_order);
  const fileType = file ? UPLOAD_TYPES[file.type] : null;

  function pickFile(event) {
    const picked = event.target.files?.[0] || null;
    setError(null);
    setFile(picked);
    if (picked && UPLOAD_TYPES[picked.type]) setForm((f) => ({ ...f, media_type: UPLOAD_TYPES[picked.type] }));
  }

  async function add(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let url = form.url.trim();
      let mediaType = form.media_type;
      if (source === 'upload') {
        // 1) ask the API for a one-file upload URL, 2) send the file straight to storage.
        const ticket = (await hostApi.mediaUploadUrl(listing.id, { content_type: file.type, size_bytes: file.size })).data;
        setProgress(0);
        await uploadToStorage(ticket, file, setProgress);
        url = ticket.public_url;
        mediaType = ticket.media_type;
      }
      // 3) save the media record (the API verifies uploaded files before saving).
      await hostApi.addMedia(listing.id, {
        url,
        media_type: mediaType,
        caption: form.caption.trim() || null,
        sort_order: parseInt(form.sort_order, 10) || 0,
      });
      toast.success('Media added.');
      setForm({ url: '', media_type: 'IMAGE', caption: '', sort_order: String(listing.media.length + 1) });
      setFile(null);
      setFileKey((k) => k + 1);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  const ready = source === 'upload' ? Boolean(fileType) : Boolean(form.url.trim());

  return (
    <div className="stack">
      <section className="card">
        <h2>Add a photo or video</h2>
        <p className="muted">Upload a file or paste an HTTPS link. At least one image is required before approval.</p>
        <div className="form-row" role="radiogroup" aria-label="Media source">
          <label>
            <input type="radio" name="m-source" checked={source === 'upload'} onChange={() => setSource('upload')} /> Upload a file
          </label>
          <label>
            <input type="radio" name="m-source" checked={source === 'link'} onChange={() => setSource('link')} /> Paste a link
          </label>
        </div>
        <ErrorAlert error={error} hideDetails={Object.keys(errors).length > 0} />
        <form onSubmit={add}>
          {source === 'upload' ? (
            <Field label="Photo or video (JPEG, PNG, WebP, MP4, WebM)" htmlFor="m-file" error={errors.size_bytes || errors.content_type || errors.url}>
              <input key={fileKey} id="m-file" type="file" accept={UPLOAD_ACCEPT} onChange={pickFile} required />
              {file && !fileType && <span className="small">This file type is not supported.</span>}
              {progress !== null && (
                <progress max="100" value={progress} aria-label="Upload progress">
                  {progress}%
                </progress>
              )}
            </Field>
          ) : (
            <Field label="Media URL" htmlFor="m-url" error={errors.url}>
              <input id="m-url" type="url" placeholder="https://…" value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} required />
            </Field>
          )}
          <div className="form-row">
            <Field label="Type" htmlFor="m-type">
              <select id="m-type" value={form.media_type} disabled={source === 'upload'} onChange={(e) => setForm((f) => ({ ...f, media_type: e.target.value }))}>
                <option value="IMAGE">Image</option>
                <option value="VIDEO">Video</option>
              </select>
            </Field>
            <Field label="Caption (optional)" htmlFor="m-cap" error={errors.caption}>
              <input id="m-cap" type="text" maxLength={200} value={form.caption} onChange={(e) => setForm((f) => ({ ...f, caption: e.target.value }))} />
            </Field>
            <Field label="Sort order" htmlFor="m-order" error={errors.sort_order}>
              <input id="m-order" type="number" min="0" value={form.sort_order} onChange={(e) => setForm((f) => ({ ...f, sort_order: e.target.value }))} />
            </Field>
          </div>
          <button className="btn" disabled={busy || !ready}>
            {busy ? (progress !== null ? `Uploading… ${progress}%` : 'Adding…') : 'Add media'}
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Current media ({items.length})</h2>
        {items.length === 0 ? (
          <Empty title="No media yet" />
        ) : (
          items.map((item) => <MediaRow key={`${item.id}-${item.caption}-${item.sort_order}`} listing={listing} item={item} onChanged={onChanged} />)
        )}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------ Hours & rules */
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
