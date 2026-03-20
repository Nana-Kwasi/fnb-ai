import React, { useState, useEffect } from "react";
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
import { useAuth } from "../context/AuthContext";
import { getMyAccounts, deposit, updateLimit } from "../api";

export default function ProfileScreen() {
  const { user, authHeader, setUser } = useAuth();
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [depositAcc, setDepositAcc] = useState("");
  const [depositAmount, setDepositAmount] = useState("");
  const [limitAcc, setLimitAcc] = useState("");
  const [limitValue, setLimitValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => {
    if (!authHeader) return;
    setLoading(true);
    try {
      const list = await getMyAccounts(authHeader);
      setAccounts(list || []);
      if (list?.length && !depositAcc) setDepositAcc(list[0].account_id);
      if (list?.length && !limitAcc) setLimitAcc(list[0].account_id);
    } catch (_) {}
    setLoading(false);
  };

  useEffect(() => {
    load();
  }, [authHeader]);

  const doDeposit = async () => {
    const acc = depositAcc || accounts[0]?.account_id;
    const amt = parseFloat(depositAmount);
    if (!acc || !(amt > 0)) {
      setMsg("Select account and enter amount");
      return;
    }
    setSubmitting(true);
    setMsg("");
    try {
      await deposit(authHeader, { account_id: acc, amount: amt });
      setMsg("Deposit successful");
      setDepositAmount("");
      load();
    } catch (e) {
      setMsg(e.message || "Deposit failed");
    } finally {
      setSubmitting(false);
    }
  };

  const doSetLimit = async () => {
    const acc = limitAcc || accounts[0]?.account_id;
    const val = limitValue === "" || limitValue === "none" ? null : parseFloat(limitValue);
    if (!acc) {
      setMsg("Select account");
      return;
    }
    setSubmitting(true);
    setMsg("");
    try {
      await updateLimit(authHeader, { account_id: acc, daily_transfer_limit: val });
      setMsg("Limit updated");
      load();
    } catch (e) {
      setMsg(e.message || "Update failed");
    } finally {
      setSubmitting(false);
    }
  };

  const logout = () => {
    Alert.alert("Sign out", "Sign out of this account?", [
      { text: "Cancel", style: "cancel" },
      { text: "Sign out", style: "destructive", onPress: () => setUser(null, null) },
    ]);
  };

  if (loading && accounts.length === 0) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color="#38bdf8" />
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
      <View style={styles.header}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(user?.username || "?").charAt(0).toUpperCase()}</Text>
        </View>
        <Text style={styles.name}>{user?.username}</Text>
        <Text style={styles.subtitle}>Account holder</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Deposit</Text>
        <Text style={styles.cardDesc}>Add funds to your account</Text>
        <Text style={styles.label}>Account</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
          {accounts.map((a) => (
            <TouchableOpacity
              key={a.account_id}
              style={[styles.chip, depositAcc === a.account_id && styles.chipActive]}
              onPress={() => setDepositAcc(a.account_id)}
            >
              <Text style={styles.chipText} numberOfLines={1}>{a.name || a.account_id}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
        <Text style={styles.label}>Amount</Text>
        <TextInput
          style={styles.input}
          value={depositAmount}
          onChangeText={setDepositAmount}
          placeholder="0.00"
          placeholderTextColor="#64748b"
          keyboardType="decimal-pad"
        />
        <TouchableOpacity style={[styles.primaryBtn, submitting && styles.btnDisabled]} onPress={doDeposit} disabled={submitting}>
          {submitting ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.primaryBtnText}>Deposit</Text>}
        </TouchableOpacity>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Daily transfer limit</Text>
        <Text style={styles.cardDesc}>Set a daily cap for transfers</Text>
        <Text style={styles.label}>Account</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.chipRow}>
          {accounts.map((a) => (
            <TouchableOpacity
              key={a.account_id}
              style={[styles.chip, limitAcc === a.account_id && styles.chipActive]}
              onPress={() => setLimitAcc(a.account_id)}
            >
              <Text style={styles.chipText} numberOfLines={1}>{a.name || a.account_id}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
        <Text style={styles.label}>Limit amount (leave empty for no limit)</Text>
        <TextInput
          style={styles.input}
          value={limitValue}
          onChangeText={setLimitValue}
          placeholder="e.g. 5000"
          placeholderTextColor="#64748b"
          keyboardType="decimal-pad"
        />
        <TouchableOpacity style={[styles.secondaryBtn, submitting && styles.btnDisabled]} onPress={doSetLimit} disabled={submitting}>
          <Text style={styles.secondaryBtnText}>Update limit</Text>
        </TouchableOpacity>
      </View>

      {msg ? <Text style={styles.msg}>{msg}</Text> : null}

      <TouchableOpacity style={styles.logoutBtn} onPress={logout} activeOpacity={0.8}>
        <Text style={styles.logoutText}>Sign out</Text>
      </TouchableOpacity>
      <View style={styles.bottomPad} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingTop: 16, paddingBottom: 32 },
  centered: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#0f172a" },
  header: {
    alignItems: "center",
    paddingVertical: 24,
    marginBottom: 8,
  },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: "#0f4c75",
    justifyContent: "center",
    alignItems: "center",
    marginBottom: 12,
  },
  avatarText: { fontSize: 28, fontWeight: "700", color: "#e2e8f0" },
  name: { fontSize: 20, fontWeight: "700", color: "#f1f5f9", marginBottom: 2 },
  subtitle: { fontSize: 13, color: "#64748b" },
  card: {
    backgroundColor: "#1e293b",
    borderRadius: 16,
    padding: 20,
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "#334155",
  },
  cardTitle: { fontSize: 17, fontWeight: "700", color: "#f1f5f9", marginBottom: 4 },
  cardDesc: { fontSize: 13, color: "#94a3b8", marginBottom: 16 },
  label: { fontSize: 12, color: "#94a3b8", marginBottom: 6, textTransform: "uppercase" },
  chipRow: { marginBottom: 12 },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 10,
    backgroundColor: "#0f172a",
    marginRight: 10,
  },
  chipActive: { backgroundColor: "#0f4c75", borderWidth: 1.5, borderColor: "#38bdf8" },
  chipText: { color: "#e2e8f0", fontSize: 14 },
  input: {
    backgroundColor: "#0f172a",
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 12,
    padding: 14,
    color: "#e2e8f0",
    fontSize: 16,
    marginBottom: 14,
  },
  primaryBtn: {
    backgroundColor: "#16a34a",
    padding: 14,
    borderRadius: 12,
    alignItems: "center",
  },
  secondaryBtn: {
    backgroundColor: "transparent",
    padding: 14,
    borderRadius: 12,
    alignItems: "center",
    borderWidth: 1.5,
    borderColor: "#475569",
  },
  btnDisabled: { opacity: 0.6 },
  primaryBtnText: { color: "#fff", fontWeight: "700", fontSize: 16 },
  secondaryBtnText: { color: "#e2e8f0", fontWeight: "600", fontSize: 15 },
  msg: { fontSize: 14, color: "#34d399", marginBottom: 16, textAlign: "center" },
  logoutBtn: {
    marginTop: 8,
    padding: 16,
    alignItems: "center",
    borderRadius: 12,
    backgroundColor: "rgba(248,113,113,0.12)",
    borderWidth: 1,
    borderColor: "#f87171",
  },
  logoutText: { color: "#f87171", fontSize: 16, fontWeight: "600" },
  bottomPad: { height: 24 },
});
