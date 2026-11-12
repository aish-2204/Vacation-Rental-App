import { ApiError } from './client';

export const UPLOAD_TYPES = {
  'image/jpeg': 'IMAGE',
  'image/png': 'IMAGE',
  'image/webp': 'IMAGE',
  'video/mp4': 'VIDEO',
  'video/webm': 'VIDEO',
};
export const UPLOAD_ACCEPT = Object.keys(UPLOAD_TYPES).join(',');

/**
 * Send a file to the storage upload URL the API issued (presigned URL / SAS).
 * Works for any provider: the ticket says which method, URL and headers to use.
 * Uses XMLHttpRequest because fetch cannot report upload progress.
 */
export function uploadToStorage(ticket, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.method, ticket.upload_url);
    Object.entries(ticket.headers || {}).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }
      let body = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* cloud storage errors are XML or empty */
      }
      reject(
        new ApiError({
          status: xhr.status,
          code: body?.error?.code || 'UPLOAD_FAILED',
          message: body?.error?.message || `Upload failed (${xhr.status}). Please try again.`,
        }),
      );
    };
    xhr.onerror = () =>
      reject(
        new ApiError({
          status: 0,
          code: 'NETWORK_ERROR',
          message: 'Could not reach file storage. Check your connection (or storage CORS settings).',
        }),
      );
    xhr.send(file);
  });
}
