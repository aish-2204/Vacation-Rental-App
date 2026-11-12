import { Link, Navigate, Route, Routes } from 'react-router-dom';
import Layout, { RequireAuth } from './components/Layout';
import Login from './pages/Login';
import Register from './pages/Register';
import Search from './pages/Search';
import ListingDetail from './pages/ListingDetail';
import MyBookings from './pages/MyBookings';
import Checkout from './pages/Checkout';
import HostAnalytics from './pages/host/HostAnalytics';
import AdminAnalytics from './pages/admin/AdminAnalytics';
import HostListings from './pages/host/HostListings';
import ListingEditor from './pages/host/ListingEditor';
import AdminListings from './pages/admin/AdminListings';

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
        <Route path="listings/:id" element={<ListingDetail />} />
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

        {/* Customer */}
        <Route
          path="bookings"
          element={
            <RequireAuth roles={['CUSTOMER']}>
              <MyBookings />
            </RequireAuth>
          }
        />

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

        {/* Admin */}
        <Route path="admin/analytics" element={<RequireAuth roles={['ADMIN']}><AdminAnalytics /></RequireAuth>} />
        <Route path="admin" element={<Navigate to="/admin/listings" replace />} />
        <Route
          path="admin/listings"
          element={
            <RequireAuth roles={['ADMIN']}>
              <AdminListings />
            </RequireAuth>
          }
        />

        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
