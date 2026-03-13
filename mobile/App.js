import React from "react";
import { NavigationContainer } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { ApiKeyProvider } from "./src/context/ApiKeyContext";
import SettingsScreen from "./src/screens/SettingsScreen";
import FraudTestScreen from "./src/screens/FraudTestScreen";
import CareTestScreen from "./src/screens/CareTestScreen";

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <SafeAreaProvider>
      <ApiKeyProvider>
        <NavigationContainer>
          <Tab.Navigator
            screenOptions={{
              headerStyle: { backgroundColor: "#0f4c75" },
              headerTintColor: "#e2e8f0",
              tabBarStyle: { backgroundColor: "#0f172a", borderTopColor: "#334155" },
              tabBarActiveTintColor: "#38bdf8",
              tabBarInactiveTintColor: "#64748b",
            }}
          >
            <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: "API Key" }} />
            <Tab.Screen name="Fraud" component={FraudTestScreen} options={{ title: "Fraud score" }} />
            <Tab.Screen name="Care" component={CareTestScreen} options={{ title: "Care chat" }} />
          </Tab.Navigator>
        </NavigationContainer>
      </ApiKeyProvider>
    </SafeAreaProvider>
  );
}
