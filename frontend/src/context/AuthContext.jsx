import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { auth } from '../api/endpoints';
import { setUnauthorizedHandler, tokenStore } from '../api/client';

const AuthContext = createContext(null);

export const homeForRole = (role) =>
  role === 'ADMIN' ? '/admin/listings' : role === 'HOST' ? '/host/listings' : '/';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  useEffect(() => {
    // Any 401 on an authenticated request means the token expired or is invalid.
    setUnauthorizedHandler(logout);
  }, [logout]);

  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    auth
      .me()
      .then((response) => setUser(response.data))
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password, remember = true) => {
    const response = await auth.login({ email, password });
    tokenStore.set(response.data.access_token, remember);
    setUser(response.data.user);
    return response.data.user;
  }, []);

  const register = useCallback(
    async (role, payload) => {
      const call = role === 'HOST' ? auth.registerHost : auth.registerCustomer;
      await call(payload);
      return login(payload.email, payload.password);
    },
    [login],
  );

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
