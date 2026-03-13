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
import { useApiKey } from "../context/ApiKeyContext";

export default function SettingsScreen() {
  const { apiKey, baseUrl, setApiKey, setBaseUrl, loaded } = useApiKey();
  const [keyInput, setKeyInput] = useState(apiKey);
  const [baseInput, setBaseInput] = useState(baseUrl);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  if (!loaded) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color="#1b6ca8" />
      </View>
    );
  }

  const save = async () => {
    setSaving(true);
    setMsg("");
    try {
      await setApiKey(keyInput.trim());
      await setBaseUrl(baseInput.trim() || "http://localhost:8000");
      setMsg("Saved. Use Fraud and Care tabs to test.");
    } catch (e) {
      setMsg(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.container}
    >
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>API settings</Text>
        <Text style={styles.label}>API Key (from Admin onboard)</Text>
        <TextInput
          style={styles.input}
          value={keyInput}
          onChangeText={setKeyInput}
          placeholder="bankai_live_..."
          placeholderTextColor="#64748b"
          autoCapitalize="none"
          autoCorrect={false}
        />
        <Text style={styles.label}>API Base URL</Text>
        <TextInput
          style={styles.input}
          value={baseInput}
          onChangeText={setBaseInput}
          placeholder="http://localhost:8000"
          placeholderTextColor="#64748b"
          autoCapitalize="none"
          keyboardType="url"
        />
        <Text style={styles.hint}>
          On device: use your machine IP (e.g. http://192.168.1.x:8000). iOS simulator: localhost. Android emulator: http://10.0.2.2:8000
        </Text>
        {msg ? <Text style={styles.msg}>{msg}</Text> : null}
        <TouchableOpacity
          style={[styles.btn, saving && styles.btnDisabled]}
          onPress={save}
          disabled={saving}
        >
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.btnText}>Save</Text>
          )}
        </TouchableOpacity>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a" },
  centered: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#0f172a" },
  scroll: { padding: 20, paddingTop: 40 },
  title: { fontSize: 22, fontWeight: "700", color: "#f1f5f9", marginBottom: 24 },
  label: { fontSize: 12, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase" },
  input: {
    backgroundColor: "#1e293b",
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 10,
    padding: 14,
    color: "#e2e8f0",
    fontSize: 15,
    marginBottom: 16,
  },
  hint: { fontSize: 11, color: "#64748b", marginBottom: 16 },
  msg: { fontSize: 13, color: "#34d399", marginBottom: 12 },
  btn: {
    backgroundColor: "#1b6ca8",
    padding: 14,
    borderRadius: 10,
    alignItems: "center",
  },
  btnDisabled: { opacity: 0.6 },
  btnText: { color: "#fff", fontWeight: "600", fontSize: 15 },
});
