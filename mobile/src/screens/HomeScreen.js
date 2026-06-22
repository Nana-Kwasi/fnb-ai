import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  RefreshControl,
} from "react-native";
import { useAuth } from "../context/AuthContext";
import { getMyAccounts, getTransactions } from "../api";

function AccountRow({ account, onPress }) {
  return (
    <TouchableOpacity style={styles.accRow} onPress={() => onPress(account.account_id)}>
      <View style={{ flex: 1 }}>
        <Text style={styles.accName}>{account.name || account.account_id}</Text>
        <Text style={styles.accMeta}>
          {account.currency} {Number(account.balance).toFixed(2)}
          {account.daily_limit != null ? ` · Limit ${account.daily_limit}` : ""}
        </Text>
      </View>
      <Text style={styles.accId}>{account.account_id}</Text>
    </TouchableOpacity>
  );
}

function TxRow({ tx }) {
  const isCredit = (tx.amount || 0) > 0;
  return (
    <View style={styles.txRow}>
      <View style={{ flex: 1 }}>
        <Text style={styles.txMerchant}>{tx.merchant || "—"}</Text>
        <Text style={styles.txMeta}>{tx.at ? new Date(tx.at).toLocaleString() : ""}</Text>
      </View>
      <Text style={[styles.txAmount, { color: isCredit ? "#22c55e" : "#e2e8f0" }]}>
        {isCredit ? "+" : ""}{tx.amount} {tx.currency}
      </Text>
    </View>
  );
}

export default function HomeScreen() {
  const { authHeader, isLoggedIn } = useAuth();
  const [accounts, setAccounts] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const loadAccounts = async (isRefresh = false) => {
    if (!authHeader) return;
    isRefresh ? setRefreshing(true) : setLoading(true);
    setError("");
    try {
      const list = await getMyAccounts(authHeader);
      setAccounts(list || []);
    } catch (e) {
      setError(e.message || "Failed to load accounts");
    } finally {
      isRefresh ? setRefreshing(false) : setLoading(false);
    }
  };

  const loadTransactions = async (accountId) => {
    setError("");
    try {
      const list = await getTransactions(accountId);
      setTransactions(Array.isArray(list) ? list : []);
    } catch (e) {
      setError(e.message || "Failed to load transactions");
      setTransactions([]);
    }
  };

  useEffect(() => {
    if (isLoggedIn && authHeader) loadAccounts();
  }, [isLoggedIn, authHeader]);

  useEffect(() => {
    if (selectedId) loadTransactions(selectedId);
  }, [selectedId]);

  if (!isLoggedIn) {
    return (
      <View style={styles.container}>
        <Text style={styles.hint}>Sign in to see your accounts.</Text>
      </View>
    );
  }

  if (selectedId) {
    const account = accounts.find((a) => a.account_id === selectedId);
    return (
      <View style={styles.container}>
        <TouchableOpacity style={styles.backBtn} onPress={() => setSelectedId(null)}>
          <Text style={styles.backText}>← Accounts</Text>
        </TouchableOpacity>
        <Text style={styles.title}>{account?.name || selectedId}</Text>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <FlatList
          data={transactions}
          keyExtractor={(item, i) => item.transaction_id + i}
          renderItem={({ item }) => <TxRow tx={item} />}
          contentContainerStyle={transactions.length === 0 ? { flexGrow: 1, justifyContent: "center" } : { paddingVertical: 8 }}
          ListEmptyComponent={<Text style={styles.empty}>No transactions</Text>}
        />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Accounts</Text>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {loading && accounts.length === 0 ? (
        <ActivityIndicator style={{ marginTop: 24 }} color="#38bdf8" />
      ) : (
        <FlatList
          data={accounts}
          keyExtractor={(item) => item.account_id}
          renderItem={({ item }) => <AccountRow account={item} onPress={setSelectedId} />}
          contentContainerStyle={accounts.length === 0 ? { flexGrow: 1, justifyContent: "center" } : { paddingVertical: 8 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => loadAccounts(true)} tintColor="#38bdf8" />
          }
          ListEmptyComponent={<Text style={styles.empty}>No accounts. Register to get one.</Text>}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a", padding: 16, paddingTop: 24 },
  title: { fontSize: 22, fontWeight: "700", color: "#f1f5f9", marginBottom: 8 },
  hint: { fontSize: 14, color: "#64748b", padding: 16 },
  error: { fontSize: 13, color: "#f97316", marginBottom: 8 },
  empty: { fontSize: 13, color: "#64748b", textAlign: "center" },
  backBtn: { marginBottom: 12 },
  backText: { color: "#38bdf8", fontSize: 15 },
  accRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: "#1e293b",
  },
  accName: { fontSize: 16, color: "#e2e8f0", marginBottom: 2 },
  accMeta: { fontSize: 12, color: "#64748b" },
  accId: { fontSize: 11, color: "#475569", marginLeft: 8 },
  txRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: "#1e293b",
  },
  txMerchant: { fontSize: 15, color: "#e2e8f0" },
  txMeta: { fontSize: 12, color: "#64748b" },
  txAmount: { fontSize: 14, fontWeight: "600", marginLeft: 8 },
});
