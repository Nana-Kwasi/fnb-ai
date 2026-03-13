import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  Alert,
} from "react-native";
import { useApiKey } from "../context/ApiKeyContext";
import { fraudScore } from "../api";

function defaultTs() {
  return new Date().toISOString().slice(0, 19) + "Z";
}

export default function FraudTestScreen() {
  const { apiKey, baseUrl, hasKey } = useApiKey();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [transactionId, setTransactionId] = useState("tx-" + Date.now());
  const [accountId, setAccountId] = useState("acc-demo-001");
  const [amount, setAmount] = useState("150.00");
  const [currency, setCurrency] = useState("GHS");
  const [merchantCategory, setMerchantCategory] = useState("retail");
  const [location, setLocation] = useState("GH");
  const [deviceId, setDeviceId] = useState("device-1");
  const [timestamp, setTimestamp] = useState(defaultTs());

  const run = async () => {
    if (!hasKey) {
      Alert.alert("No API key", "Set your API key in Settings first.");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const data = await fraudScore(apiKey, baseUrl, {
        transaction_id: transactionId,
        account_id: accountId,
        amount: parseFloat(amount) || 0,
        currency: currency || "GHS",
        merchant_category: merchantCategory || null,
        location: location || null,
        device_id: deviceId || null,
        timestamp: timestamp || defaultTs(),
      });
      setResult(data);
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.scroll}>
      <Text style={styles.title}>Fraud score</Text>
      <Text style={styles.label}>Transaction ID</Text>
      <TextInput style={styles.input} value={transactionId} onChangeText={setTransactionId} placeholderTextColor="#64748b" />
      <Text style={styles.label}>Account ID</Text>
      <TextInput style={styles.input} value={accountId} onChangeText={setAccountId} placeholderTextColor="#64748b" />
      <Text style={styles.label}>Amount</Text>
      <TextInput style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholderTextColor="#64748b" />
      <Text style={styles.label}>Currency</Text>
      <TextInput style={styles.input} value={currency} onChangeText={setCurrency} placeholderTextColor="#64748b" />
      <Text style={styles.label}>Merchant category</Text>
      <TextInput style={styles.input} value={merchantCategory} onChangeText={setMerchantCategory} placeholderTextColor="#64748b" />
      <Text style={styles.label}>Location (country code)</Text>
      <TextInput style={styles.input} value={location} onChangeText={setLocation} placeholderTextColor="#64748b" />
      <Text style={styles.label}>Device ID</Text>
      <TextInput style={styles.input} value={deviceId} onChangeText={setDeviceId} placeholderTextColor="#64748b" />
      <Text style={styles.label}>Timestamp (ISO)</Text>
      <TextInput style={styles.input} value={timestamp} onChangeText={setTimestamp} placeholderTextColor="#64748b" />

      <TouchableOpacity style={[styles.btn, loading && styles.btnDisabled]} onPress={run} disabled={loading}>
        {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnText}>Score transaction</Text>}
      </TouchableOpacity>

      {result && (
        <View style={[styles.result, result.error && styles.resultError]}>
          <Text style={styles.resultTitle}>{result.error ? "Error" : "Result"}</Text>
          {result.error ? (
            <Text style={styles.resultText}>{result.error}</Text>
          ) : (
            <>
              <Text style={styles.resultText}>Decision: {result.decision}</Text>
              <Text style={styles.resultText}>Score: {result.fraud_score}</Text>
              <Text style={styles.resultText}>Confidence: {result.confidence}</Text>
              <Text style={styles.resultText}>Action: {result.recommended_action}</Text>
              <Text style={styles.resultText}>Time: {result.processing_time_ms}ms</Text>
              {result.reasons && result.reasons.length ? (
                <Text style={styles.resultText}>Reasons: {result.reasons.join(", ")}</Text>
              ) : null}
            </>
          )}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a" },
  scroll: { padding: 20, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: "700", color: "#f1f5f9", marginBottom: 20 },
  label: { fontSize: 12, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase" },
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
  btn: { backgroundColor: "#6a0dad", padding: 14, borderRadius: 10, alignItems: "center", marginTop: 8 },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: "#fff", fontWeight: "600", fontSize: 15 },
  result: {
    marginTop: 24,
    padding: 16,
    backgroundColor: "#1e293b",
    borderRadius: 10,
    borderLeftWidth: 4,
    borderLeftColor: "#22c55e",
  },
  resultError: { borderLeftColor: "#ef4444" },
  resultTitle: { fontSize: 14, fontWeight: "600", color: "#94a3b8", marginBottom: 8 },
  resultText: { fontSize: 13, color: "#e2e8f0", marginBottom: 4 },
});
