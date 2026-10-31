import { useState } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { homeForRole, useAuth } from '../context/AuthContext';
import { Field } from '../components/ui';
import { errorText, fieldErrors } from '../utils/format';

const PHONE = /^\+?[0-9][0-9 ()-]{6,30}[0-9]$/;

function validate(form) {
  const errors = {};
  if (!form.name.trim()) errors.name = 'Enter your name';
  if (!/^\S+@\S+\.\S+$/.test(form.email.trim())) errors.email = 'Enter a valid email address';
  if (!PHONE.test(form.phone.trim())) errors.phone = 'Enter a valid phone number, e.g. 408-555-0101';
  const bytes = new TextEncoder().encode(form.password).length;
  if (bytes < 8 || bytes > 72 || !/[A-Za-z]/.test(form.password) || !/[0-9]/.test(form.password))
    errors.password = 'Min 8 chars, a letter and a digit';
  if (!form.terms) errors.terms = 'Please agree to the Terms';
  return errors;
}

export default function Register() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  const [role, setRole] = useState(sp.get('role') === 'host' ? 'HOST' : 'CUSTOMER');
  const [form, setForm] = useState({ name: '', email: '', phone: '', password: '', terms: false });
  const [clientErrors, setClientErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (user) return <Navigate to={homeForRole(user.role)} replace />;

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));

  async function submit(event) {
    event.preventDefault();
    const found = validate(form);
    setClientErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const created = await register(role, {
        name: form.name.trim(),
        email: form.email.trim(),
        phone: form.phone.trim(),
        password: form.password,
      });
      navigate(homeForRole(created.role), { replace: true });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const serverErrors = fieldErrors(error);
  const errors = { ...serverErrors, ...clientErrors };

  return (
    <div className="auth-card card">
      <h1>Join the fun 🎉</h1>
      <p className="muted small" style={{ marginBottom: '0.4rem' }}>
        I want to…
      </p>
      <div className="role-toggle" role="radiogroup" aria-label="Account type">
        <button type="button" className={`role-option ${role === 'CUSTOMER' ? 'active' : ''}`} onClick={() => setRole('CUSTOMER')} aria-pressed={role === 'CUSTOMER'}>
          <strong>Book stays</strong>
          <span>(Customer)</span>
        </button>
        <button type="button" className={`role-option ${role === 'HOST' ? 'active' : ''}`} onClick={() => setRole('HOST')} aria-pressed={role === 'HOST'}>
          <strong>List my home</strong>
          <span>(Host)</span>
        </button>
      </div>

      {error && Object.keys(serverErrors).length === 0 && (
        <div className="alert alert-error" role="alert">
          {errorText(error)}
          {error.status ? ` (${error.status})` : ''}
        </div>
      )}
      <form onSubmit={submit} noValidate>
        <Field label="Full name" htmlFor="name" error={errors.name}>
          <input id="name" type="text" autoComplete="name" placeholder="Asha Rao" value={form.name} onChange={set('name')} maxLength={120} />
        </Field>
        <Field label="Email" htmlFor="email" error={errors.email}>
          <input id="email" type="email" autoComplete="email" placeholder="asha@example.com" value={form.email} onChange={set('email')} />
        </Field>
        <Field label="Phone" htmlFor="phone" error={errors.phone}>
          <input id="phone" type="tel" autoComplete="tel" placeholder="408-555-0101" value={form.phone} onChange={set('phone')} />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password} hint="Min 8 chars, a letter and a digit">
          <input id="password" type="password" autoComplete="new-password" value={form.password} onChange={set('password')} />
        </Field>
        <div className={`field ${errors.terms ? 'has-error' : ''}`}>
          <label className="check">
            <input type="checkbox" checked={form.terms} onChange={(e) => setForm((f) => ({ ...f, terms: e.target.checked }))} />
            I agree to the Terms
          </label>
          {errors.terms && <span className="error-text">{errors.terms}</span>}
        </div>
        <button className="btn btn-block" disabled={busy}>
          {busy ? 'Creating account…' : 'Create account'}
        </button>
      </form>
      <p className="switch">
        <Link to="/login">Already have an account? Log in</Link>
      </p>
    </div>
  );
}
