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
  ScrollView,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import { registerUser } from "../api";

export default function RegisterScreen({ onLogin, onSuccess }) {
  const { setUser } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [country, setCountry] = useState("GH");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    const u = username.trim();
    const p = password;
    if (!u || !p || !fullName.trim()) {
      setError("Username, password and full name required");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await registerUser({
        username: u,
        password: p,
        full_name: fullName.trim(),
        email: email.trim() || "user@example.com",
        phone: phone.trim() || "",
        country: country.trim() || "GH",
      });
      await setUser(u, p);
    } catch (e) {
      setError(e.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Create account</Text>
        <Text style={styles.subtitle}>Core banking demo</Text>
        <TextInput style={styles.input} value={username} onChangeText={(t) => { setUsername(t); setError(""); }} placeholder="Username" placeholderTextColor="#64748b" autoCapitalize="none" />
        <TextInput style={styles.input} value={password} onChangeText={(t) => { setPassword(t); setError(""); }} placeholder="Password" placeholderTextColor="#64748b" secureTextEntry />
        <TextInput style={styles.input} value={fullName} onChangeText={(t) => { setFullName(t); setError(""); }} placeholder="Full name" placeholderTextColor="#64748b" />
        <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="Email (optional)" placeholderTextColor="#64748b" keyboardType="email-address" />
        <TextInput style={styles.input} value={phone} onChangeText={setPhone} placeholder="Phone (optional)" placeholderTextColor="#64748b" keyboardType="phone-pad" />
        <TextInput style={styles.input} value={country} onChangeText={setCountry} placeholder="Country" placeholderTextColor="#64748b" />
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={submit} disabled={loading}>
          {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Register</Text>}
        </TouchableOpacity>
        {onLogin ? (
          <TouchableOpacity style={styles.link} onPress={onLogin}>
            <Text style={styles.linkText}>Already have an account? Sign in</Text>
          </TouchableOpacity>
        ) : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a" },
  scroll: { padding: 24, paddingTop: 40, paddingBottom: 48 },
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
