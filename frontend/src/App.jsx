import { Link, Navigate, Route, Routes } from 'react-router-dom';
import Layout, { RequireAuth } from './components/Layout';
import Login from './pages/Login';

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
        <Route path="login" element={<Login />} />


        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
