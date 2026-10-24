import { api } from './client';

export const auth = {
  login: (body) => api.post('/auth/login', body, { auth: false }),
  registerCustomer: (body) => api.post('/auth/register/customer', body, { auth: false }),
  registerHost: (body) => api.post('/auth/register/host', body, { auth: false }),
  me: () => api.get('/auth/me'),
};

