const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api/v1').replace(
  /\/+$/,
  '',
);
const TOKEN_KEY = 'vr.token';

export const tokenStore = {
  get() {
    try {
      return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  // remember=true keeps the login after the browser closes; false keeps it for this tab only.
  set(token, remember = true) {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(TOKEN_KEY);
      (remember ? localStorage : sessionStorage).setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable */
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

let onUnauthorized = null;
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

/** Error shaped like the backend envelope: { error: { code, message, details[] }, request_id } */
export class ApiError extends Error {
  constructor({ status, code, message, details = [], requestId, retryAfter }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.retryAfter = retryAfter;
  }
}

function buildQuery(params) {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) value.forEach((item) => sp.append(key, String(item)));
    else sp.append(key, String(value));
  }
  const text = sp.toString();
  return text ? `?${text}` : '';
}

async function request(method, path, { params, body, auth = true } = {}) {
  const headers = { Accept: 'application/json' };
  const token = tokenStore.get();
  if (auth && token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(`${BASE}${path}${buildQuery(params)}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError({
      status: 0,
      code: 'NETWORK_ERROR',
      message:
        'Cannot reach the server. Make sure the backend is running and the API URL is correct.',
    });
  }

  let json = null;
  try {
    json = await response.json();
  } catch {
    /* non-JSON body */
  }

  if (!response.ok || (json && json.success === false)) {
    const error = json?.error || {};
    const apiError = new ApiError({
      status: response.status,
      code: error.code || 'ERROR',
      message: error.message || `Request failed (${response.status})`,
      details: error.details || [],
      requestId: json?.request_id || response.headers.get('X-Request-ID'),
      retryAfter: response.headers.get('Retry-After'),
    });
    if (response.status === 401 && auth && token && onUnauthorized) onUnauthorized();
    throw apiError;
  }
  return json;
}

export const api = {
  get: (path, params, options) => request('GET', path, { params, ...options }),
  post: (path, body, options) => request('POST', path, { body, ...options }),
  patch: (path, body, options) => request('PATCH', path, { body, ...options }),
  put: (path, body, options) => request('PUT', path, { body, ...options }),
  del: (path, body, options) => request('DELETE', path, { body, ...options }),
};
