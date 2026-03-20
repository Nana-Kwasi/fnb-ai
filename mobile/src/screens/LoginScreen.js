import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import { loginUser, makeBasicAuth } from "../api";

export default function LoginScreen({ onRegister, onSuccess }) {
  const { setUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    const u = username.trim();
    const p = password;
    if (!u || !p) {
      setError("Username and password required");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const authHeader = makeBasicAuth(u, p);
      const out = await loginUser(authHeader);
      await setUser(u, p, { accountId: out.account_id || null, careToken: out.care_token || null });
    } catch (e) {
      setError(e.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.container}>
      <Text style={styles.title}>Sign in</Text>
      <Text style={styles.subtitle}>Core banking demo</Text>
      <TextInput
        style={styles.input}
        value={username}
        onChangeText={(t) => { setUsername(t); setError(""); }}
        placeholder="Username"
        placeholderTextColor="#64748b"
        autoCapitalize="none"
      />
      <TextInput
        style={styles.input}
        value={password}
        onChangeText={(t) => { setPassword(t); setError(""); }}
        placeholder="Password"
        placeholderTextColor="#64748b"
        secureTextEntry
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={submit} disabled={loading}>
        {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Sign in</Text>}
      </TouchableOpacity>
      {onRegister ? (
        <TouchableOpacity style={styles.link} onPress={onRegister}>
          <Text style={styles.linkText}>Create account</Text>
        </TouchableOpacity>
      ) : null}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a", padding: 24, justifyContent: "center" },
  title: { fontSize: 26, fontWeight: "700", color: "#f1f5f9", marginBottom: 4 },
  subtitle: { fontSize: 14, color: "#64748b", marginBottom: 24 },
  input: {
    backgroundColor: "#1e293b",
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 10,
    padding: 14,
    color: "#e2e8f0",
    fontSize: 16,
    marginBottom: 12,
  },
  error: { fontSize: 13, color: "#f97316", marginBottom: 8 },
  btn: { backgroundColor: "#0f4c75", padding: 14, borderRadius: 10, alignItems: "center", marginTop: 8 },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: "#e2e8f0", fontWeight: "700", fontSize: 16 },
  link: { marginTop: 20, alignItems: "center" },
  linkText: { color: "#38bdf8", fontSize: 14 },
});
