import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { bookingsApi, reviewsApi } from '../api/endpoints';
import { useToast } from '../context/ToastContext';
import useAsync from '../hooks/useAsync';
import { ErrorAlert, Field, RatingInput, Spinner } from '../components/ui';
import { errorText, fieldErrors, fmtDate } from '../utils/format';

const MAX = 1000;

export default function ReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const booking = useAsync(() => bookingsApi.get(id), [id]);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [problem, setProblem] = useState({});

  if (booking.loading && !booking.data) return <Spinner />;
  if (booking.error) return <div className="card"><ErrorAlert error={booking.error} /></div>;
  const b = booking.data.data;

  async function submit(event) {
    event.preventDefault();
    const found = {};
    if (!rating) found.rating = 'Choose a rating from 1 to 5';
    if (!comment.trim()) found.comment = 'Write a few words about your stay';
    setProblem(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      await reviewsApi.create({ booking_id: b.id, rating, comment: comment.trim() });
      toast.success('Thanks for your review!');
      navigate('/bookings');
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }
  const server = fieldErrors(error);
  return (
    <form className="card" style={{ maxWidth: 560, margin: '0 auto' }} onSubmit={submit} noValidate>
      <h1>How was your stay?</h1>
      <p className="muted">{b.listing_name_snapshot} · {fmtDate(b.check_in)} – {fmtDate(b.check_out)}</p>
      <Field label="Rating" error={problem.rating || server.rating}>
        <RatingInput value={rating} onChange={setRating} />
      </Field>
      <Field label="Your review" htmlFor="comment" error={problem.comment || server.comment} hint={`${comment.length} / ${MAX}`}>
        <textarea id="comment" rows={6} maxLength={MAX} value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      {error && Object.keys(server).length === 0 && (
        <div className="alert alert-error">{errorText(error)}{error.status ? ` (${error.status})` : ''}</div>
      )}
      <div className="row">
        <button className="btn" disabled={busy}>{busy ? 'Submitting…' : 'Submit review'}</button>
        <Link to="/bookings" className="btn btn-secondary">Cancel</Link>
      </div>
    </form>
  );
}
