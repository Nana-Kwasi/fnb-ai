import React, { createContext, useContext, useState, useEffect } from "react";
import * as SecureStore from "expo-secure-store";

const KEY_STORE = "bankai_api_key";
const BASE_STORE = "bankai_api_base";

const ApiKeyContext = createContext(null);

export function ApiKeyProvider({ children }) {
  const [apiKey, setApiKeyState] = useState("");
  const [baseUrl, setBaseUrlState] = useState("http://localhost:8000");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const k = await SecureStore.getItemAsync(KEY_STORE);
        const b = await SecureStore.getItemAsync(BASE_STORE);
        if (k) setApiKeyState(k);
        if (b) setBaseUrlState(b);
      } finally {
        setLoaded(true);
      }
    })();
  }, []);

  const setApiKey = async (value) => {
    setApiKeyState(value || "");
    if (value) await SecureStore.setItemAsync(KEY_STORE, value);
    else await SecureStore.deleteItemAsync(KEY_STORE);
  };

  const setBaseUrl = async (value) => {
    const v = value || "http://localhost:8000";
    setBaseUrlState(v);
    await SecureStore.setItemAsync(BASE_STORE, v);
  };

  return (
    <ApiKeyContext.Provider
      value={{
        apiKey,
        baseUrl,
        setApiKey,
        setBaseUrl,
        loaded,
        hasKey: !!apiKey?.trim(),
      }}
    >
      {children}
    </ApiKeyContext.Provider>
  );
}

export function useApiKey() {
  const ctx = useContext(ApiKeyContext);
  if (!ctx) throw new Error("useApiKey must be used inside ApiKeyProvider");
  return ctx;
}
