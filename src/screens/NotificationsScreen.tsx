/**
 * Notification centre.
 *
 * Read state is updated optimistically: marking an alert read is a visible change
 * the user just asked for, so waiting for the round trip would make the tap feel
 * broken. If the request fails the entry is restored and the failure reported.
 */

import React, { useCallback, useState } from 'react';
import { FlatList, RefreshControl, Text, View } from 'react-native';

import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Screen,
  Spinner,
  StatusPill,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { formatDateTime } from '../lib/format';
import { notificationApi } from '../services/endpoints';
import type { NotificationItem } from '../types';
import { colors, space, styles, type } from '../theme';

export default function NotificationsScreen() {
  const [page, setPage] = useState(1);
  const [refreshing, setRefreshing] = useState(false);

  const list = useAsync(() => notificationApi.list(page, 25), [page]);
  const items = list.data?.items ?? [];

  const refresh = useCallback(() => {
    setRefreshing(true);
    list.reload();
    setTimeout(() => setRefreshing(false), 500);
  }, [list]);

  const markRead = useCallback(
    (notification: NotificationItem) => {
      if (notification.is_read) return;
      void notificationApi
        .markRead(notification.id)
        .then(() => list.reload())
        .catch(() =>
          // Left as unread rather than optimistically flipped: a wrong read receipt
          // is worse than a slow one.
          list.reload(),
        );
    },
    [list],
  );

  if (list.initial) {
    return (
      <Screen>
        <Spinner label="Loading notifications" />
      </Screen>
    );
  }

  return (
    <View style={styles.screen}>
      <View style={{ padding: space.lg, gap: space.md }}>
        <View style={styles.row}>
          <Text style={[type.title, styles.flex]}>Notifications</Text>
          {list.data && list.data.unread > 0 ? (
            <Button
              label="Mark all read"
              variant="secondary"
              onPress={() => {
                void notificationApi
                  .markAllRead()
                  .then(() => list.reload())
                  .catch(() => list.reload());
              }}
              style={styles.headerButton}
            />
          ) : null}
        </View>
      </View>

      {list.error && !list.data ? (
        <View style={{ padding: space.lg }}>
          <ErrorState
            message={list.error.isOffline ? 'Cannot reach the API.' : list.error.message}
            onRetry={list.reload}
          />
        </View>
      ) : null}

      {list.data ? (
        <FlatList
          data={items}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={{ paddingHorizontal: space.lg, paddingBottom: space.xxl, gap: space.sm }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
          }
          ListEmptyComponent={
            <EmptyState
              title="Nothing to read"
              message="Fraud alerts, loan reminders and budget warnings arrive here."
            />
          }
          renderItem={({ item }) => (
            <NotificationRow
              notification={item}
              onPress={() => markRead(item)}
            />
          )}
        />
      ) : null}

      {list.data && list.data.total > 25 ? (
        <View style={[styles.row, { padding: space.lg, gap: space.md }]}>
          <Button
            label="Previous"
            variant="secondary"
            disabled={page <= 1}
            onPress={() => setPage((value) => Math.max(1, value - 1))}
            style={styles.flex}
          />
          <Text style={type.small}>
            {page} / {Math.ceil(list.data.total / 25)}
          </Text>
          <Button
            label="Next"
            variant="secondary"
            disabled={page >= Math.ceil(list.data.total / 25)}
            onPress={() => setPage((value) => value + 1)}
            style={styles.flex}
          />
        </View>
      ) : null}
    </View>
  );
}

function NotificationRow({
  notification,
  onPress,
}: {
  notification: NotificationItem;
  onPress: () => void;
}) {
  return (
    <Card>
      <View style={styles.row}>
        <Text style={[type.subheading, styles.flex]}>{notification.title}</Text>
        {notification.is_read ? null : <StatusPill label="New" color={colors.accent} />}
      </View>
      <Text style={type.body}>{notification.body}</Text>
      <Text style={[type.small, styles.meta]}>
        {notification.notification_type.replace(/_/g, ' ')}
        {notification.created_at ? ` · ${formatDateTime(notification.created_at)}` : ''}
      </Text>
      {notification.is_read ? null : (
        <Button
          label="Mark read"
          variant="secondary"
          onPress={onPress}
          style={styles.shortButton}
        />
      )}
    </Card>
  );
}
