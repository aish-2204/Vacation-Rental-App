import { Field } from './ui';
import MapView from './MapView';
import PlaceSearch from './PlaceSearch';
import { mapsEnabled } from '../lib/maps';
import { WEEKDAYS } from '../utils/format';
import { STATE_TIMEZONES, TIMEZONES } from '../utils/listingForm';

/** Controlled fields for the listing's core details. */
export function DetailsFields({ form, setForm, errors = {}, amenities = [] }) {
  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }));
  const toggle = (id) =>
    setForm((f) => ({
      ...f,
      amenity_ids: f.amenity_ids.includes(id) ? f.amenity_ids.filter((a) => a !== id) : [...f.amenity_ids, id],
    }));

  function fillFromPlace(place) {
    setForm((f) => ({
      ...f,
      address_line1: place.address_line1 || f.address_line1,
      city: place.city || f.city,
      state: place.state || f.state,
      zip_code: place.zip_code || f.zip_code,
      latitude: place.lat != null ? place.lat.toFixed(6) : f.latitude,
      longitude: place.lng != null ? place.lng.toFixed(6) : f.longitude,
      timezone: STATE_TIMEZONES[place.state] || f.timezone,
    }));
  }

  const lat = Number(form.latitude);
  const lng = Number(form.longitude);
  const hasPoint =
    form.latitude !== '' && form.longitude !== '' && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;

  return (
    <>
      <PlaceSearch onSelect={fillFromPlace} />
      {mapsEnabled && (
        <p className="muted small" style={{ marginTop: 0 }}>
          Search the address above to fill in the fields below, then check the pin on the map.
        </p>
      )}
      <Field label="Listing name" htmlFor="l-name" error={errors.name}>
        <input id="l-name" type="text" value={form.name} onChange={set('name')} maxLength={160} />
      </Field>
      <Field label="Description" htmlFor="l-desc" error={errors.description}>
        <textarea id="l-desc" value={form.description} onChange={set('description')} maxLength={5000} />
      </Field>
      <div className="form-row">
        <Field label="Address line 1" htmlFor="l-a1" error={errors.address_line1}>
          <input id="l-a1" type="text" value={form.address_line1} onChange={set('address_line1')} maxLength={200} />
        </Field>
        <Field label="Address line 2 (optional)" htmlFor="l-a2" error={errors.address_line2}>
          <input id="l-a2" type="text" value={form.address_line2} onChange={set('address_line2')} maxLength={200} />
        </Field>
      </div>
      <div className="form-row">
        <Field label="City" htmlFor="l-city" error={errors.city}>
          <input id="l-city" type="text" value={form.city} onChange={set('city')} maxLength={100} />
        </Field>
        <Field label="State" htmlFor="l-state" error={errors.state}>
          <input id="l-state" type="text" value={form.state} onChange={set('state')} maxLength={2} placeholder="CA" />
        </Field>
        <Field label="ZIP code" htmlFor="l-zip" error={errors.zip_code}>
          <input id="l-zip" type="text" value={form.zip_code} onChange={set('zip_code')} placeholder="95112" />
        </Field>
      </div>
      <div className="form-row">
        <Field label="Latitude" htmlFor="l-lat" error={errors.latitude} hint="e.g. 37.338200">
          <input id="l-lat" type="number" step="any" value={form.latitude} onChange={set('latitude')} />
        </Field>
        <Field label="Longitude" htmlFor="l-lng" error={errors.longitude} hint="e.g. -121.886300">
          <input id="l-lng" type="number" step="any" value={form.longitude} onChange={set('longitude')} />
        </Field>
        <Field label="Timezone" htmlFor="l-tz" error={errors.timezone} hint="IANA name">
          <input id="l-tz" type="text" list="timezones" value={form.timezone} onChange={set('timezone')} />
          <datalist id="timezones">
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz} />
            ))}
          </datalist>
        </Field>
      </div>
      {mapsEnabled && hasPoint && (
        <div className="field">
          <span className="field-label">Pin preview</span>
          <MapView
            height={260}
            zoom={16}
            markers={[{ id: 'pin', lat, lng, title: form.name || 'Listing location' }]}
            onMove={({ lat: newLat, lng: newLng }) =>
              setForm((f) => ({ ...f, latitude: newLat.toFixed(6), longitude: newLng.toFixed(6) }))
            }
          />
          <span className="hint">Drag the pin to fine-tune the exact location.</span>
        </div>
      )}
      <div className="form-row">
        <Field label="Nightly price (USD)" htmlFor="l-price" error={errors.nightly_price}>
          <input id="l-price" type="number" min="0.01" step="0.01" value={form.nightly_price} onChange={set('nightly_price')} />
        </Field>
        <Field label="Max guests" htmlFor="l-guests" error={errors.max_guests}>
          <input id="l-guests" type="number" min="1" step="1" value={form.max_guests} onChange={set('max_guests')} />
        </Field>
      </div>
      <h3 style={{ marginTop: '0.5rem' }}>Contact details</h3>
      <div className="form-row">
        <Field label="Contact name" htmlFor="l-cn" error={errors.contact_name}>
          <input id="l-cn" type="text" value={form.contact_name} onChange={set('contact_name')} maxLength={120} />
        </Field>
        <Field label="Contact email" htmlFor="l-ce" error={errors.contact_email}>
          <input id="l-ce" type="email" value={form.contact_email} onChange={set('contact_email')} />
        </Field>
        <Field label="Contact phone" htmlFor="l-cp" error={errors.contact_phone}>
          <input id="l-cp" type="tel" value={form.contact_phone} onChange={set('contact_phone')} />
        </Field>
      </div>
      <div className="field">
        <span className="field-label">Amenities</span>
        <div className="chips">
          {amenities.map((a) => (
            <label className="chip" key={a.id}>
              <input type="checkbox" checked={form.amenity_ids.includes(a.id)} onChange={() => toggle(a.id)} />
              {a.name}
            </label>
          ))}
          {amenities.length === 0 && <span className="muted small">No amenities available.</span>}
        </div>
      </div>
    </>
  );
}

