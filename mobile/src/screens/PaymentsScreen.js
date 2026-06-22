import React, { useState, useEffect } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from "react-native";
import * as SecureStore from "expo-secure-store";
import { useAuth } from "../context/AuthContext";
import { getMyAccounts, transferViaGateway } from "../api";

const DEVICE_ID_KEY = "bankai_device_id";

async function getOrCreateDeviceId() {
  let id = await SecureStore.getItemAsync(DEVICE_ID_KEY);
  if (!id) {
    id = `mobile-${Platform.OS}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    await SecureStore.setItemAsync(DEVICE_ID_KEY, id);
  }
  return id;
}

export default function PaymentsScreen() {
  const { authHeader, isLoggedIn } = useAuth();
  const [accounts, setAccounts] = useState([]);
  const [fromAccountId, setFromAccountId] = useState("");
  const [toAccountId, setToAccountId] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [location, setLocation] = useState("GH");
  const [deviceId, setDeviceId] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => {
    getOrCreateDeviceId().then(setDeviceId);
  }, []);

  useEffect(() => {
    if (isLoggedIn && authHeader) {
      getMyAccounts(authHeader).then((list) => {
        setAccounts(list || []);
        if (list?.length && !fromAccountId) setFromAccountId(list[0].account_id);
      });
    }
  }, [isLoggedIn, authHeader]);

  const submit = async () => {
    if (!isLoggedIn) {
      Alert.alert("Sign in", "Sign in to transfer.");
      return;
    }
    const from = fromAccountId || accounts[0]?.account_id;
    const to = toAccountId.trim();
    const amt = parseFloat(amount);
    if (!from || !to || !(amt > 0)) {
      setResult({ error: "From account, receiver account number and amount required" });
      return;
    }
    if (from === to) {
      setResult({ error: "Cannot transfer to same account" });
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const data = await transferViaGateway({
        from_account_id: from,
        to_account_id: to,
        amount: amt,
        currency: currency || "USD",
        device_id: deviceId || undefined,
        location: (location || "GH").trim() || undefined,
        channel: "MOBILE_APP",
      });
      setResult(data.success ? data : { ...data, error: data.message });
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  if (!isLoggedIn) {
    return (
      <View style={styles.container}>
        <Text style={styles.hint}>Sign in to transfer.</Text>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={80}
    >
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={styles.title}>Transfer</Text>
        <Text style={styles.subtitle}>Send money to another account</Text>

        <Text style={styles.label}>From account</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
          {accounts.map((a) => (
            <TouchableOpacity
              key={a.account_id}
              style={[styles.chip, fromAccountId === a.account_id && styles.chipActive]}
              onPress={() => setFromAccountId(a.account_id)}
            >
              <Text style={styles.chipText} numberOfLines={1}>{a.name || a.account_id}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>

        <Text style={styles.label}>Receiver account number</Text>
        <TextInput
          style={styles.input}
          value={toAccountId}
          onChangeText={setToAccountId}
          placeholder="Enter receiver's account number"
          placeholderTextColor="#64748b"
          keyboardType="default"
        />

        <Text style={styles.label}>Amount</Text>
        <TextInput
          style={styles.input}
          value={amount}
          onChangeText={setAmount}
          placeholder="0.00"
          placeholderTextColor="#64748b"
          keyboardType="decimal-pad"
        />

        <Text style={styles.label}>Currency</Text>
        <TextInput
          style={styles.input}
          value={currency}
          onChangeText={setCurrency}
          placeholderTextColor="#64748b"
        />

        <Text style={styles.label}>Country code (for fraud check)</Text>
        <TextInput
          style={styles.input}
          value={location}
          onChangeText={setLocation}
          placeholder="e.g. GH, US, NG"
          placeholderTextColor="#64748b"
          maxLength={2}
          autoCapitalize="characters"
        />

        <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={submit} disabled={loading}>
          {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Transfer</Text>}
        </TouchableOpacity>

        {result && (
          <View style={[styles.result, result.error && styles.resultError]}>
            <Text style={styles.resultTitle}>{result.error ? "Result" : "Done"}</Text>
            <Text style={styles.resultText}>{result.error || result.message}</Text>
            {result.transaction_id ? <Text style={styles.resultText}>Transaction ID: {result.transaction_id}</Text> : null}
            {result.decision ? <Text style={styles.resultText}>Decision: {result.decision}</Text> : null}
            {typeof result.fraud_score === "number" ? (
              <Text style={styles.resultText}>Fraud score: {result.fraud_score}</Text>
            ) : null}
            {Array.isArray(result.reasons) && result.reasons.length ? (
              <Text style={styles.resultText}>Reasons: {result.reasons.join(", ")}</Text>
            ) : null}
          </View>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a" },
  scrollContent: { padding: 20, paddingTop: 24, paddingBottom: 32 },
  hint: { fontSize: 14, color: "#64748b", padding: 20 },
  title: { fontSize: 22, fontWeight: "700", color: "#f1f5f9", marginBottom: 4 },
  subtitle: { fontSize: 14, color: "#64748b", marginBottom: 20 },
  label: { fontSize: 12, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase" },
  chipRow: { marginBottom: 12 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, backgroundColor: "#1e293b", marginRight: 8 },
  chipActive: { backgroundColor: "#0f4c75", borderWidth: 1, borderColor: "#38bdf8" },
  chipText: { color: "#e2e8f0", fontSize: 13 },
  input: {
    backgroundColor: "#1e293b",
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 10,
    padding: 12,
    color: "#e2e8f0",
    fontSize: 15,
    marginBottom: 14,
  },
  btn: { backgroundColor: "#22c55e", padding: 14, borderRadius: 10, alignItems: "center", marginTop: 4 },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: "#0f172a", fontWeight: "700", fontSize: 15 },
  result: {
    marginTop: 20,
    padding: 14,
    backgroundColor: "#1e293b",
    borderRadius: 10,
    borderLeftWidth: 4,
    borderLeftColor: "#22c55e",
  },
  resultError: { borderLeftColor: "#ef4444" },
  resultTitle: { fontSize: 14, fontWeight: "600", color: "#94a3b8", marginBottom: 6 },
  resultText: { fontSize: 13, color: "#e2e8f0", marginBottom: 4 },
});
