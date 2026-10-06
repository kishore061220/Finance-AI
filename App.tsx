/**
 * App entry: guarded navigation.
 *
 * The stack is split into `auth` and `app`. Which stack renders depends solely
 * on `SessionStatus`. The session itself decides what to do when a token is
 * present or when Firebase/dev auth is the chosen provider.
 *
 * The app navigator uses tabs for the daily surfaces (dashboard, transactions,
 * budgets) and a stack for the things that are drilled into (loans detail). A
 * direct navigation to an in-app route is impossible while status is anonymous.
 */

import React from 'react';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';

import { SessionProvider, useSession } from './src/auth/SessionProvider';
import { Spinner } from './src/components/ui';
import { colors } from './src/theme';

import LoginScreen from './src/screens/LoginScreen';
import DashboardScreen from './src/screens/DashboardScreen';
import TransactionsScreen from './src/screens/TransactionsScreen';
import BudgetsScreen from './src/screens/BudgetsScreen';
import FraudScreen from './src/screens/FraudScreen';
import LoansScreen from './src/screens/LoansScreen';
import ProfileScreen from './src/screens/ProfileScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import CaptureScreen from './src/screens/CaptureScreen';
import NotificationsScreen from './src/screens/NotificationsScreen';
import MoreScreen from './src/screens/MoreScreen';

const AuthStack = createNativeStackNavigator();
const AppTab = createBottomTabNavigator();
const MoreStackNavigator = createNativeStackNavigator();

function AuthNavigator() {
  return (
    <AuthStack.Navigator screenOptions={{ headerShown: false }}>
      <AuthStack.Screen name="Login" component={LoginScreen} />
    </AuthStack.Navigator>
  );
}

/**
 * The hub stack.
 *
 * Named screens rather than the tab screens' own names, so `More` navigating to
 * `Profile` cannot collide with a `Profile` screen registered elsewhere.
 */
function MoreStack() {
  return (
    <MoreStackNavigator.Navigator screenOptions={{ headerShown: false }}>
      <MoreStackNavigator.Screen name="MoreHome" component={MoreScreen} />
      <MoreStackNavigator.Screen name="Fraud" component={FraudScreen} />
      <MoreStackNavigator.Screen name="Loans" component={LoansScreen} />
      <MoreStackNavigator.Screen name="Notifications" component={NotificationsScreen} />
      <MoreStackNavigator.Screen name="Profile" component={ProfileScreen} />
      <MoreStackNavigator.Screen name="Settings" component={SettingsScreen} />
    </MoreStackNavigator.Navigator>
  );
}

function AppTabs() {
  return (
    <AppTab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
      }}
    >
      <AppTab.Screen name="Dashboard" component={DashboardScreen} />
      <AppTab.Screen name="Transactions" component={TransactionsScreen} />
      <AppTab.Screen name="Capture" component={CaptureScreen} />
      <AppTab.Screen name="Budgets" component={BudgetsScreen} />
      <AppTab.Screen name="More" component={MoreStack} />
    </AppTab.Navigator>
  );
}

function RootNavigator() {
  const { status } = useSession();
  if (status === 'loading') {
    return <Spinner label="Signing you in" />;
  }
  return status === 'authenticated' ? <AppTabs /> : <AuthNavigator />;
}

const navTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    background: colors.canvas,
  },
};

function App() {
  return (
    <SessionProvider>
      <NavigationContainer theme={navTheme}>
        <RootNavigator />
      </NavigationContainer>
    </SessionProvider>
  );
}

export default App;
