import { publicApi } from '../api/endpoints';
import { nightsBetween } from '../utils/format';
import useAsync from './useAsync';

/**
 * Live availability + price quote for a stay. `stay` = { check_in, check_out, guests } (strings).
 * Returns { nights, problem, loading, result } where result is { data } or { error } (or null when the stay is incomplete).
 */
export default function useQuote(listingId, stay, maxGuests) {
  const nights = nightsBetween(stay.check_in, stay.check_out);
  const guests = Number(stay.guests || 1);
  let problem = '';
  if (!stay.check_in || !stay.check_out) problem = 'Choose check-in and check-out dates.';
  else if (nights < 1) problem = 'Check-out must be after check-in.';
  else if (nights > 14) problem = 'Stay must be 1 to 14 nights.';
  else if (!(guests >= 1)) problem = 'At least one guest is required.';
  else if (maxGuests && guests > maxGuests) problem = `This rental sleeps up to ${maxGuests} guests.`;

  const query = useAsync(async () => {
    if (problem) return null;
    try {
      const response = await publicApi.availability(listingId, {
        check_in: stay.check_in,
        check_out: stay.check_out,
        guests,
      });
      return { data: response.data };
    } catch (error) {
      return { error };
    }
  }, [listingId, problem, stay.check_in, stay.check_out, guests]);

  return { nights, problem, loading: !problem && query.loading, result: problem ? null : query.data };
}
