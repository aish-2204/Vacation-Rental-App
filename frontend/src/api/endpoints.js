import { api } from './client';

export const auth = {
  login: (body) => api.post('/auth/login', body, { auth: false }),
  registerCustomer: (body) => api.post('/auth/register/customer', body, { auth: false }),
  registerHost: (body) => api.post('/auth/register/host', body, { auth: false }),
  me: () => api.get('/auth/me'),
};

export const publicApi = {
  amenities: () => api.get('/amenities', undefined, { auth: false }),
  search: (params) => api.get('/listings/search', params, { auth: false }),
  detail: (id, params) => api.get(`/listings/${id}`, params, { auth: false }),
  availability: (id, params) => api.get(`/listings/${id}/availability`, params, { auth: false }),
  reviews: (id, params) => api.get(`/listings/${id}/reviews`, params, { auth: false }),
};

export const hostApi = {
  amenities: () => api.get('/host/amenities'),
  list: (params) => api.get('/host/listings', params),
  create: (body) => api.post('/host/listings', body),
  get: (id) => api.get(`/host/listings/${id}`),
  patch: (id, body) => api.patch(`/host/listings/${id}`, body),
  remove: (id, reason) => api.del(`/host/listings/${id}`, { reason }),
  replaceHours: (id, hours) => api.put(`/host/listings/${id}/hours`, { hours }),
  replaceRules: (id, booking_rules) =>
    api.put(`/host/listings/${id}/booking-rules`, { booking_rules }),
  blocks: (id, params) => api.get(`/host/listings/${id}/blocks`, params),
  addBlock: (id, body) => api.post(`/host/listings/${id}/blocks`, body),
  deleteBlock: (id, blockId) => api.del(`/host/listings/${id}/blocks/${blockId}`),
  addMedia: (id, body) => api.post(`/host/listings/${id}/media`, body),
  patchMedia: (id, mediaId, body) => api.patch(`/host/listings/${id}/media/${mediaId}`, body),
  deleteMedia: (id, mediaId) => api.del(`/host/listings/${id}/media/${mediaId}`),
  analytics: (params) => api.get('/host/analytics', params),
};

