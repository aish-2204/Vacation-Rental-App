import { Link } from 'react-router-dom';
import { adminApi } from '../../api/endpoints';
import AnalyticsView from '../../components/AnalyticsView';

export default function AdminAnalytics() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Admin dashboard</h1>
          <p>System-wide listings and booking activity.</p>
        </div>
        <Link to="/admin/listings?status=PENDING" className="btn">
          Review pending listings
        </Link>
      </div>
      <AnalyticsView fetcher={adminApi.analytics} />
    </>
  );
}
