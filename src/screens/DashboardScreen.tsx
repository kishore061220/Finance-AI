import React from 'react';
import {
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';

type DashboardScreenProps = {
  navigation: any;
  route: any;
};

function DashboardScreen({
  navigation,
  route,
}: DashboardScreenProps) {
  const user = route.params?.user;

  return (
    <View style={styles.container}>
      <Text style={styles.logo}>Finance-AI</Text>

      <Text style={styles.title}>Dashboard</Text>

      <Text style={styles.welcome}>
        Welcome, {user?.name || 'User'}!
      </Text>

      <Text style={styles.email}>
        {user?.email || ''}
      </Text>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Account</Text>

        <Text style={styles.cardText}>
          User ID: {user?.id || '-'}
        </Text>

        <Text style={styles.cardText}>
          Authentication: Successful
        </Text>
      </View>

      <TouchableOpacity
        style={styles.logoutButton}
        onPress={() => navigation.replace('Login')}>
        <Text style={styles.logoutText}>Logout</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f7fb',
    padding: 24,
    justifyContent: 'center',
  },

  logo: {
    fontSize: 30,
    fontWeight: '800',
    color: '#2563eb',
    textAlign: 'center',
    marginBottom: 20,
  },

  title: {
    fontSize: 30,
    fontWeight: '700',
    color: '#111827',
    textAlign: 'center',
  },

  welcome: {
    fontSize: 20,
    fontWeight: '600',
    color: '#374151',
    textAlign: 'center',
    marginTop: 15,
  },

  email: {
    fontSize: 15,
    color: '#6b7280',
    textAlign: 'center',
    marginTop: 5,
  },

  card: {
    backgroundColor: '#ffffff',
    borderRadius: 14,
    padding: 20,
    marginTop: 30,
    borderWidth: 1,
    borderColor: '#e5e7eb',
  },

  cardTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827',
    marginBottom: 15,
  },

  cardText: {
    fontSize: 15,
    color: '#4b5563',
    marginBottom: 8,
  },

  logoutButton: {
    height: 50,
    backgroundColor: '#dc2626',
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 25,
  },

  logoutText: {
    color: '#ffffff',
    fontSize: 16,
    fontWeight: '700',
  },
});

export default DashboardScreen;