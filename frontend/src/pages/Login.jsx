import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { homeForRole, useAuth } from '../context/AuthContext';
import { Field } from '../components/ui';
import { errorText, fieldErrors } from '../utils/format';

const DEMO_PASSWORD = 'DemoOnly!2026';
const DEMO_ACCOUNTS = [
  ['Customer', 'customer1@example.test'],
  ['Host', 'host1@example.test'],
  ['Admin', 'admin@example.test'],
];

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (user) return <Navigate to={location.state?.from || homeForRole(user.role)} replace />;

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const signedIn = await login(email, password, remember);
      navigate(location.state?.from || homeForRole(signedIn.role), { replace: true });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const errors = fieldErrors(error);
  const hasFieldErrors = Object.keys(errors).length > 0;

  return (
    <div className="auth-card card">
      <h1>Welcome back 👋</h1>
      <p className="muted small">
        Browsing is open to everyone. Log in to book a stay, manage listings, or use the admin tools. If you clicked Book,
        you return to checkout after logging in.
      </p>
      {error && !hasFieldErrors && (
        <div className="alert alert-error" role="alert">
          {errorText(error)}
          {error.status ? ` (${error.status})` : ''}
        </div>
      )}
      <form onSubmit={submit} noValidate>
        <Field label="Email" htmlFor="email" error={errors.email}>
          <input id="email" type="email" autoComplete="email" placeholder="asha@example.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Field>
        <Field label="Password" htmlFor="password" error={errors.password}>
          <input id="password" type="password" autoComplete="current-password" placeholder="••••••••" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <label className="check" style={{ marginBottom: '1rem' }}>
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember me
        </label>
        <button className="btn btn-block" disabled={busy || !email || !password}>
          {busy ? 'Signing in…' : 'Log in'}
        </button>
      </form>
      <p className="switch">
        <Link to="/register">New here? Create an account</Link>
      </p>

      {import.meta.env.DEV && (
        <div className="demo-box">
          <strong>Local demo accounts</strong>
          <p className="muted small" style={{ margin: '0.25rem 0 0.5rem' }}>
            Password for all: {DEMO_PASSWORD} (development only)
          </p>
          <div className="row">
            {DEMO_ACCOUNTS.map(([label, demoEmail]) => (
              <button
                key={label}
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  setEmail(demoEmail);
                  setPassword(DEMO_PASSWORD);
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
