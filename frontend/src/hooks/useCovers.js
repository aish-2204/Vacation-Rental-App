import { publicApi } from '../api/endpoints';
import useAsync from './useAsync';

const cache = new Map();

/** Cover photo + name of a public listing (null url when it has no photo or is no longer public). */
export async function listingCover(id) {
  if (cache.has(id)) return cache.get(id);
  let value;
  try {
    const response = await publicApi.detail(id);
    const image = [...response.data.media]
      .sort((a, b) => a.sort_order - b.sort_order)
      .find((m) => m.media_type === 'IMAGE');
    value = { url: image?.url || null, name: response.data.name };
  } catch {
    value = { url: null, name: null };
  }
  cache.set(id, value);
  return value;
}

/** Map of listingId -> { url, name } for the given ids. */
export default function useCovers(ids) {
  const unique = [...new Set(ids)];
  const key = [...unique].sort().join(',');
  const covers = useAsync(async () => {
    const entries = await Promise.all(unique.map(async (id) => [id, await listingCover(id)]));
    return Object.fromEntries(entries);
  }, [key]);
  return covers.data || {};
}
