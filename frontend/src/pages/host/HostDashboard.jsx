import { Link } from 'react-router-dom';
import { hostApi } from '../../api/endpoints';
import AnalyticsView from '../../components/AnalyticsView';

export default function HostDashboard() {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Host dashboard</h1>
          <p>How your listings and bookings are performing.</p>
        </div>
        <Link to="/host/listings/new" className="btn">
          + New listing
        </Link>
      </div>
      <AnalyticsView fetcher={hostApi.analytics} />
    </>
  );
}
