import React, { useState, useRef, useEffect } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  ScrollView,
  Alert,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { useApiKey } from "../context/ApiKeyContext";
import { careChat } from "../api";

const TYPEWRITER_CHARS_PER_TICK = 2;
const TYPEWRITER_MS = 30;

export default function CareTestScreen() {
  const { apiKey, baseUrl, hasKey } = useApiKey();
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState([]);
  const [revealLen, setRevealLen] = useState(0);
  const [sessionId] = useState(() => `sess-${Date.now()}`);
  const [customerId] = useState("acc-demo-001");
  const [message, setMessage] = useState("");
  const [suggestedActions, setSuggestedActions] = useState([]);
  const scrollRef = useRef(null);

  const lastAssistant = messages.length > 0 && messages[messages.length - 1].role === "assistant" ? messages[messages.length - 1].content : null;

  useEffect(() => {
    if (!lastAssistant) {
      setRevealLen(0);
      return;
    }
    setRevealLen(0);
    const len = lastAssistant.length;
    const id = setInterval(() => {
      setRevealLen((n) => {
        if (n >= len) {
          clearInterval(id);
          return len;
        }
        return Math.min(n + TYPEWRITER_CHARS_PER_TICK, len);
      });
    }, TYPEWRITER_MS);
    return () => clearInterval(id);
  }, [messages.length, lastAssistant]);

  useEffect(() => {
    if (messages.length) scrollRef.current?.scrollToEnd({ animated: true });
  }, [messages.length, revealLen]);

  const send = async (text) => {
    const toSend = (text || message || "").trim();
    if (!toSend) return;
    if (!hasKey) {
      Alert.alert("No API key", "Set your API key in Settings first.");
      return;
    }
    setMessage("");
    setMessages((prev) => [...prev, { role: "user", content: toSend }]);
    setLoading(true);
    setSuggestedActions([]);
    try {
      const data = await careChat(apiKey, baseUrl, {
        session_id: sessionId,
        customer_id: customerId,
        message: toSend,
        channel: "mobile_app",
      });
      if (data.error) {
        setMessages((prev) => [...prev, { role: "assistant", content: "Sorry, something went wrong. " + data.error }]);
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: data.response }]);
        if (data.suggested_actions?.length) setSuggestedActions(data.suggested_actions);
      }
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: "Error: " + e.message }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={80}
    >
      <View style={styles.header}>
        <Text style={styles.title}>Care chat</Text>
        <Text style={styles.subtitle}>Session: {sessionId.slice(0, 18)}… · Customer: {customerId}</Text>
      </View>

      <ScrollView
        ref={scrollRef}
        style={styles.chatArea}
        contentContainerStyle={styles.chatContent}
        onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
      >
        {messages.length === 0 && (
          <Text style={styles.placeholder}>Send a message to start. Try "Hello" or "What is my balance?"</Text>
        )}
        {messages.map((m, i) => {
          const isLastAssistant = i === messages.length - 1 && m.role === "assistant";
          const show = isLastAssistant ? m.content.slice(0, revealLen) : m.content;
          return (
            <View key={i} style={m.role === "user" ? styles.userRow : styles.assistantRow}>
              <View style={[styles.bubble, m.role === "user" ? styles.userBubble : styles.assistantBubble]}>
                <Text style={styles.bubbleText}>{show}{isLastAssistant && revealLen < m.content.length ? "▌" : ""}</Text>
              </View>
            </View>
          );
        })}
        {loading && (
          <View style={styles.assistantRow}>
            <View style={[styles.bubble, styles.assistantBubble]}>
              <ActivityIndicator size="small" color="#94a3b8" />
            </View>
          </View>
        )}
        {suggestedActions.length > 0 && !loading && (
          <View style={styles.actionsRow}>
            {suggestedActions.map((action, i) => (
              <TouchableOpacity key={i} style={styles.actionChip} onPress={() => send(action)}>
                <Text style={styles.actionChipText}>{action}</Text>
              </TouchableOpacity>
            ))}
          </View>
        )}
      </ScrollView>

      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          value={message}
          onChangeText={setMessage}
          placeholder="Type a message..."
          placeholderTextColor="#64748b"
          multiline
          maxLength={500}
          editable={!loading}
        />
        <TouchableOpacity
          style={[styles.sendBtn, loading && styles.sendBtnDisabled]}
          onPress={() => send()}
          disabled={loading}
        >
          {loading ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.sendBtnText}>Send</Text>}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#0f172a" },
  header: { paddingHorizontal: 20, paddingTop: 12, paddingBottom: 8, borderBottomWidth: 1, borderBottomColor: "#1e293b" },
  title: { fontSize: 22, fontWeight: "700", color: "#f1f5f9" },
  subtitle: { fontSize: 11, color: "#64748b", marginTop: 2 },
  chatArea: { flex: 1 },
  chatContent: { padding: 16, paddingBottom: 24 },
  placeholder: { fontSize: 14, color: "#64748b", textAlign: "center", marginTop: 24 },
  userRow: { flexDirection: "row", justifyContent: "flex-end", marginBottom: 12 },
  assistantRow: { flexDirection: "row", justifyContent: "flex-start", marginBottom: 12 },
  bubble: { maxWidth: "85%", paddingHorizontal: 14, paddingVertical: 10, borderRadius: 16 },
  userBubble: { backgroundColor: "#c9184a", borderBottomRightRadius: 4 },
  assistantBubble: { backgroundColor: "#1e293b", borderBottomLeftRadius: 4 },
  bubbleText: { fontSize: 15, color: "#e2e8f0", lineHeight: 22 },
  actionsRow: { flexDirection: "row", flexWrap: "wrap", marginTop: 4 },
  actionChip: { backgroundColor: "#334155", paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8, marginRight: 8, marginBottom: 8 },
  actionChipText: { fontSize: 13, color: "#94a3b8" },
  inputRow: { flexDirection: "row", alignItems: "flex-end", padding: 12, paddingBottom: 24, backgroundColor: "#0f172a", borderTopWidth: 1, borderTopColor: "#1e293b" },
  input: {
    flex: 1,
    backgroundColor: "#1e293b",
    borderWidth: 1,
    borderColor: "#334155",
    borderRadius: 22,
    paddingHorizontal: 16,
    paddingVertical: 10,
    paddingTop: 10,
    color: "#e2e8f0",
    fontSize: 15,
    maxHeight: 100,
  },
  sendBtn: { backgroundColor: "#c9184a", marginLeft: 8, paddingHorizontal: 20, paddingVertical: 12, borderRadius: 22, justifyContent: "center", minHeight: 44 },
  sendBtnDisabled: { opacity: 0.6 },
  sendBtnText: { color: "#fff", fontWeight: "600", fontSize: 15 },
});
