/**
 * The "More" tab: a hub for everything that is not a daily surface.
 *
 * A list of destinations rather than a set of extra tabs, because six or seven tabs
 * would crowd the bar and shrink the tap targets. Each row navigates within the
 * stack that wraps this screen, so the back gesture works as expected.
 */

import React from 'react';
import { Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';

import { Card, NavRow, Screen, SectionTitle } from '../components/ui';
import { useSession } from '../auth/SessionProvider';
import { useAsync } from '../hooks/useAsync';
import { notificationApi } from '../services/endpoints';
import { styles, type } from '../theme';

export default function MoreScreen() {
  const navigation = useNavigation();
  const { user } = useSession();
  const unread = useAsync(() => notificationApi.unreadCount(), []);

  const go = (route: string) => () => {
    navigation.navigate(route as never);
  };

  return (
    <Screen>
      <Text style={type.title}>More</Text>
      {user ? (
        <Text style={type.small}>
          {user.name}
          {user.email ? ` · ${user.email}` : ''}
        </Text>
      ) : null}

      <SectionTitle>Money safety</SectionTitle>
      <Card>
        <NavRow
          label="Fraud alerts"
          detail="Flagged transactions and why they were flagged"
          onPress={go('Fraud')}
          right={
            unread.data && unread.data.unread > 0 ? (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{unread.data.unread}</Text>
              </View>
            ) : null
          }
        />
        <View style={styles.separator} />
        <NavRow
          label="Loans"
          detail="Portfolio, instalments and prepayment estimates"
          onPress={go('Loans')}
        />
      </Card>

      <SectionTitle>Account</SectionTitle>
      <Card>
        <NavRow label="Notifications" onPress={go('Notifications')} />
        <View style={styles.separator} />
        <NavRow label="Profile" onPress={go('Profile')} />
        <View style={styles.separator} />
        <NavRow label="Settings" detail="Server, model, backups, push" onPress={go('Settings')} />
      </Card>
    </Screen>
  );
}
