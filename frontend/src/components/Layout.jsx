import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Spinner } from './ui';

function UserMenu() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    const close = (event) => box.current && !box.current.contains(event.target) && setOpen(false);
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <div className="user-menu" ref={box}>
      <button className="avatar" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label="Account menu">
        {user.name.trim().charAt(0).toUpperCase() || '?'}
      </button>
      {open && (
        <div className="menu" role="menu">
          <strong>{user.name}</strong>
          <div className="muted small">{user.email}</div>
          <span className={`badge badge-${user.role}`} style={{ alignSelf: 'flex-start' }}>
            {user.role}
          </span>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => {
              setOpen(false);
              logout();
              navigate('/');
            }}
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

function Navbar() {
  const { user } = useAuth();
  let links = [];
  if (!user) links = [{ to: '/', label: 'Search', end: true }];
  if (user?.role === 'CUSTOMER')
    links = [
      { to: '/', label: 'Search', end: true },
      { to: '/bookings', label: 'My bookings' },
    ];
  if (user?.role === 'HOST')
    links = [
      { to: '/host/listings', label: 'My listings' },
      { to: '/host/analytics', label: 'Analytics' },
    ];
  if (user?.role === 'ADMIN')
    links = [
      { to: '/admin/listings', label: 'Listings' },
      { to: '/admin/analytics', label: 'Analytics' },
    ];
  const suffix = user?.role === 'HOST' ? ' Host' : user?.role === 'ADMIN' ? ' Admin' : '';

  return (
    <header className="nav">
      <div className="container nav-inner">
        <Link to={user?.role === 'HOST' ? '/host/listings' : user?.role === 'ADMIN' ? '/admin/listings' : '/'} className="brand">
          <span className="brand-mark" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 32 32">
              <path d="M6 16 16 7l10 9v9h-7v-6h-6v6H6z" fill="#fff" />
            </svg>
          </span>
          Vacation Rental <span className="brand-emoji" aria-hidden="true">🌴</span>{suffix && <span className="brand-role">{suffix}</span>}
        </Link>
        <nav className="nav-links" aria-label="Main">
          {links.map((link) => (
            <NavLink key={link.to} to={link.to} end={link.end}>
              {link.label}
            </NavLink>
          ))}
          {!user && <Link to="/register?role=host">Become a host</Link>}
        </nav>
        <div className="nav-user">
          {user ? (
            <UserMenu />
          ) : (
            <Link to="/login" className="btn btn-secondary btn-sm">
              Log in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}

export default function Layout() {
  return (
    <div className="app">
      <Navbar />
      <main className="container">
        <Outlet />
      </main>
      <footer className="footer">Vacation Rental · SJSU CMPE 202 project</footer>
    </div>
  );
}

/** Wraps routes that need a signed-in user, optionally limited to certain roles. */
export function RequireAuth({ roles, children }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (roles && !roles.includes(user.role)) {
    return (
      <div className="card empty">
        <h3>Access denied</h3>
        <p>Your {user.role.toLowerCase()} account cannot open this page.</p>
        <Link to="/" className="btn">
          Back to Search
        </Link>
      </div>
    );
  }
  return children;
}
