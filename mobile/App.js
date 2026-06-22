import React, { useState } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { ApiKeyProvider } from "./src/context/ApiKeyContext";
import { AuthProvider, useAuth } from "./src/context/AuthContext";
import SettingsScreen from "./src/screens/SettingsScreen";
import HomeScreen from "./src/screens/HomeScreen";
import PaymentsScreen from "./src/screens/PaymentsScreen";
import CareTestScreen from "./src/screens/CareTestScreen";
import ProfileScreen from "./src/screens/ProfileScreen";
import LoginScreen from "./src/screens/LoginScreen";
import RegisterScreen from "./src/screens/RegisterScreen";

const Tab = createBottomTabNavigator();

const tabIcons = {
  Home: { active: "wallet", inactive: "wallet-outline" },
  Pay: { active: "card", inactive: "card-outline" },
  Care: { active: "chatbubbles", inactive: "chatbubbles-outline" },
  Profile: { active: "person", inactive: "person-outline" },
  Settings: { active: "settings", inactive: "settings-outline" },
};

function AuthGate() {
  const { user, loaded } = useAuth();
  const [authMode, setAuthMode] = useState("login");

  if (!loaded) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color="#38bdf8" />
      </View>
    );
  }
  if (!user) {
    if (authMode === "register") {
      return <RegisterScreen onLogin={() => setAuthMode("login")} />;
    }
    return <LoginScreen onRegister={() => setAuthMode("register")} />;
  }

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerStyle: { backgroundColor: "#0c3d5c" },
        headerTintColor: "#f1f5f9",
        headerTitleStyle: { fontWeight: "600", fontSize: 18 },
        tabBarStyle: {
          backgroundColor: "#0f172a",
          borderTopWidth: 1,
          borderTopColor: "#1e293b",
          height: 60,
          paddingBottom: 8,
          paddingTop: 8,
        },
        tabBarActiveTintColor: "#38bdf8",
        tabBarInactiveTintColor: "#64748b",
        tabBarLabelStyle: { fontSize: 11, fontWeight: "500" },
        tabBarIcon: ({ focused, color, size }) => {
          const icons = tabIcons[route.name];
          const name = icons ? (focused ? icons.active : icons.inactive) : "ellipse-outline";
          return <Ionicons name={name} size={24} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Home" component={HomeScreen} options={{ title: "Accounts" }} />
      <Tab.Screen name="Pay" component={PaymentsScreen} options={{ title: "Pay" }} />
      <Tab.Screen name="Care" component={CareTestScreen} options={{ title: "Support" }} />
      <Tab.Screen name="Profile" component={ProfileScreen} options={{ title: "Profile" }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: "Settings" }} />
    </Tab.Navigator>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <ApiKeyProvider>
          <NavigationContainer>
            <AuthGate />
          </NavigationContainer>
        </ApiKeyProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#0f172a" },
});
