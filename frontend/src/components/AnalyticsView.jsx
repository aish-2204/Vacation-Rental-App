import { useState } from 'react';
import useAsync from '../hooks/useAsync';
import { ErrorAlert, Field, Spinner } from './ui';
import { fmtDate, fmtDateTime, money, titleCase } from '../utils/format';

function Stat({ label, value, hint }) {
  return (
    <div className="card stat">
      <span className="label">{label}</span>
      <span className="value">{value}</span>
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}

function DailyChart({ days }) {
  if (!days.length) return null;
  const width = 760;
  const height = 220;
  const pad = { top: 12, right: 8, bottom: 28, left: 34 };
  const max = Math.max(1, ...days.map((d) => d.bookings_created));
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const slot = innerW / days.length;
  const barW = Math.max(2, Math.min(18, slot * 0.38));
  const y = (v) => pad.top + innerH - (v / max) * innerH;
  const ticks = [0, Math.ceil(max / 2), max].filter((v, i, arr) => arr.indexOf(v) === i);
  const labelEvery = Math.ceil(days.length / 8);

  return (
    <>
      <div className="legend">
        <span>
          <i style={{ background: 'var(--primary)' }} />
          Created
        </span>
        <span>
          <i style={{ background: '#f97316' }} />
          Cancelled
        </span>
      </div>
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Bookings created and cancelled per day"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} stroke="#e2e8f0" />
            <text x={pad.left - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="#64748b">
              {t}
            </text>
          </g>
        ))}
        {days.map((d, i) => {
          const cx = pad.left + slot * i + slot / 2;
          return (
            <g key={d.date}>
              <title>
                {fmtDate(d.date)}: {d.bookings_created} created, {d.cancelled_bookings} cancelled
              </title>
              <rect
                x={cx - barW - 1}
                y={y(d.bookings_created)}
                width={barW}
                height={innerH - (y(d.bookings_created) - pad.top)}
                rx="2"
                fill="var(--primary)"
              />
              <rect
                x={cx + 1}
                y={y(d.cancelled_bookings)}
                width={barW}
                height={innerH - (y(d.cancelled_bookings) - pad.top)}
                rx="2"
                fill="#f97316"
              />
              {i % labelEvery === 0 && (
                <text x={cx} y={height - 8} textAnchor="middle" fontSize="10.5" fill="#64748b">
                  {fmtDate(d.date, { month: 'short', day: 'numeric' })}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </>
  );
}

/** `fetcher(params)` is hostApi.analytics or adminApi.analytics. */
export default function AnalyticsView({ fetcher }) {
  const [period, setPeriod] = useState('30');
  const [zipInput, setZipInput] = useState('');
  const [zip, setZip] = useState('');
  const [zipError, setZipError] = useState('');

  const analytics = useAsync(() => fetcher({ period_days: period, zip_code: zip }), [period, zip]);

  function applyZip(event) {
    event.preventDefault();
    const value = zipInput.trim();
    if (value && !/^[0-9]{5}(-[0-9]{4})?$/.test(value)) return setZipError('Use 12345 or 12345-6789');
    setZipError('');
    setZip(value);
  }

  const data = analytics.data?.data;

  return (
    <>
      <form className="card row" style={{ marginBottom: '1.25rem', alignItems: 'flex-end' }} onSubmit={applyZip}>
        <Field label="Period" htmlFor="a-period">
          <select id="a-period" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="30">Last 30 days</option>
            <option value="60">Last 60 days</option>
            <option value="90">Last 90 days</option>
          </select>
        </Field>
        <Field label="ZIP code (optional)" htmlFor="a-zip" error={zipError}>
          <input id="a-zip" type="text" value={zipInput} onChange={(e) => setZipInput(e.target.value)} placeholder="All ZIP codes" />
        </Field>
        <div className="field">
          <div className="row">
            <button className="btn">Apply</button>
            {zip && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setZip('');
                  setZipInput('');
                }}
              >
                Clear ZIP
              </button>
            )}
          </div>
        </div>
      </form>

      <ErrorAlert error={analytics.error} />
      {analytics.loading && !data ? (
        <Spinner />
      ) : (
        data && (
          <div className="stack" style={{ opacity: analytics.loading ? 0.6 : 1 }}>
            <p className="muted small">
              {fmtDateTime(data.window_start)} – {fmtDateTime(data.window_end)} (UTC)
              {data.zip_code ? ` · ZIP ${data.zip_code}` : ''}
            </p>
            <div className="grid grid-4">
              <Stat label="Listings" value={data.total_listings} hint={`${data.new_listings_in_period} new in period`} />
              <Stat label="Bookings created" value={data.bookings_created} />
              <Stat label="Cancellations" value={data.cancelled_bookings} hint={`${data.net_bookings} net bookings`} />
              <Stat label="Booking value" value={money(data.booking_value_usd, data.currency)} hint="Saved totals, not paid revenue" />
            </div>

            <section className="card">
              <h2>Bookings per day</h2>
              <DailyChart days={data.daily_bookings} />
            </section>

            <div className="grid grid-2">
              <section className="card">
                <h2>Listings by status</h2>
                <div className="table-wrap">
                  <table>
                    <tbody>
                      {Object.entries(data.listing_status_counts).map(([status, count]) => (
                        <tr key={status}>
                          <td>
                            <span className={`badge badge-${status}`}>{titleCase(status)}</span>
                          </td>
                          <td className="right">
                            <strong>{count}</strong>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              <section className="card">
                <h2>Rentals by ZIP</h2>
                {data.rentals_by_zip.length === 0 ? (
                  <p className="muted">No listings in this scope.</p>
                ) : (
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>ZIP</th>
                          <th className="right">Listings</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.rentals_by_zip.map((row) => (
                          <tr key={row.zip_code}>
                            <td>{row.zip_code}</td>
                            <td className="right">{row.total_listings}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>

            <section className="card">
              <h2>Bookings by ZIP</h2>
              {data.bookings_by_zip.length === 0 ? (
                <p className="muted">No bookings in this period.</p>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>ZIP</th>
                        <th className="right">Created</th>
                        <th className="right">Cancelled</th>
                        <th className="right">Net</th>
                        <th className="right">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.bookings_by_zip.map((row) => (
                        <tr key={row.zip_code}>
                          <td>{row.zip_code}</td>
                          <td className="right">{row.bookings_created}</td>
                          <td className="right">{row.cancelled_bookings}</td>
                          <td className="right">{row.net_bookings}</td>
                          <td className="right">{money(row.booking_value_usd, data.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        )
      )}
    </>
  );
}
