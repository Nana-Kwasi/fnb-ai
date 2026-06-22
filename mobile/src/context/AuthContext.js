import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import * as SecureStore from "expo-secure-store";

const AUTH_STORE = "bankai_core_auth";

const AuthContext = createContext(null);

function b64(s) {
  if (typeof Buffer !== "undefined") return Buffer.from(s, "utf8").toString("base64");
  if (typeof btoa !== "undefined") return btoa(unescape(encodeURIComponent(s)));
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let out = "";
  for (let i = 0; i < s.length; i += 3) {
    const a = s.charCodeAt(i);
    const b = i + 1 < s.length ? s.charCodeAt(i + 1) : 0;
    const c = i + 2 < s.length ? s.charCodeAt(i + 2) : 0;
    out += chars[a >> 2] + chars[((a & 3) << 4) | (b >> 4)] + (i + 1 < s.length ? chars[((b & 15) << 2) | (c >> 6)] : "=") + (i + 2 < s.length ? chars[c & 63] : "=");
  }
  return out;
}

export function AuthProvider({ children }) {
  const [user, setUserState] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const raw = await SecureStore.getItemAsync(AUTH_STORE);
        if (raw) {
          const { username, password, accountId, careToken } = JSON.parse(raw);
          if (username && password) setUserState({ username, password, accountId: accountId || null, careToken: careToken || null });
        }
      } catch (_) {}
      setLoaded(true);
    })();
  }, []);

  const setUser = useCallback(async (username, password, extra = {}) => {
    const u = username && password ? { username, password, accountId: extra.accountId || null, careToken: extra.careToken || null } : null;
    setUserState(u);
    if (u) await SecureStore.setItemAsync(AUTH_STORE, JSON.stringify(u));
    else await SecureStore.deleteItemAsync(AUTH_STORE);
  }, []);

  const authHeader = user ? `Basic ${b64(`${user.username}:${user.password}`)}` : null;

  return (
    <AuthContext.Provider value={{ user, setUser, authHeader, loaded, isLoggedIn: !!user, careToken: user?.careToken || null, accountId: user?.accountId || null }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
