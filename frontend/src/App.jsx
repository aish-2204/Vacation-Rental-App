import { Link, Navigate, Route, Routes } from 'react-router-dom';
import Layout, { RequireAuth } from './components/Layout';
import Login from './pages/Login';
import Register from './pages/Register';
import Search from './pages/Search';
import Checkout from './pages/Checkout';
import HostAnalytics from './pages/host/HostAnalytics';
import HostListings from './pages/host/HostListings';
import ListingEditor from './pages/host/ListingEditor';

function NotFound() {
  return (
    <div className="card empty">
      <h3>Page not found</h3>
      <p>The page you are looking for does not exist.</p>
      <Link to="/" className="btn">
        Back to Explore
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* Public */}
        <Route index element={<Search />} />
        <Route
          path="listings/:id/book"
          element={
            <RequireAuth roles={['CUSTOMER']}>
              <Checkout />
            </RequireAuth>
          }
        />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />


        {/* Host */}
        <Route path="host" element={<Navigate to="/host/listings" replace />} />
        <Route
          path="host/listings"
          element={
            <RequireAuth roles={['HOST']}>
              <HostListings />
            </RequireAuth>
          }
        />
        <Route
          path="host/listings/new"
          element={
            <RequireAuth roles={['HOST']}>
              <ListingEditor />
            </RequireAuth>
          }
        />
        <Route
          path="host/listings/:id"
          element={
            <RequireAuth roles={['HOST']}>
              <ListingEditor />
            </RequireAuth>
          }
        />

        <Route path="host/analytics" element={<RequireAuth roles={['HOST']}><HostAnalytics /></RequireAuth>} />

        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
