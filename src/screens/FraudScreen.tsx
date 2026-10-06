/**
 * Fraud alerts.
 *
 * Two things this screen deliberately does not do:
 *
 *  - It does not label anything "safe". An alert list shows what the detector
 *    flagged and why; the absence of an alert is not evidence of no fraud, so the
 *    header says so rather than implying an all-clear.
 *  - It does not let a dismissal delete the alert. Dismissal sets `is_dismissed`,
 *    which hides it from the default list but keeps the row and the reasons, so a
 *    dismissed alert is still auditable.
 */

import React, { useCallback, useState } from 'react';
import { RefreshControl, Text, View } from 'react-native';

import {
  Alert as AlertBanner,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Screen,
  Spinner,
  StatusPill,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { formatCurrency, formatDateTime } from '../lib/format';
import { fraudApi } from '../services/endpoints';
import type { FraudAlert } from '../types';
import { colors, riskColor, space, styles, type } from '../theme';

export default function FraudScreen() {
  const [refreshing, setRefreshing] = useState(false);
  const [showDismissed, setShowDismissed] = useState(false);

  const list = useAsync(() => fraudApi.alerts({ include_dismissed: showDismissed }), [
    showDismissed,
  ]);

  const refresh = useCallback(() => {
    setRefreshing(true);
    list.reload();
    setTimeout(() => setRefreshing(false), 500);
  }, [list]);

  const act = useCallback(
    (alert: FraudAlert, action: 'read' | 'dismiss') => {
      const call = action === 'read' ? fraudApi.markRead(alert.id) : fraudApi.dismiss(alert.id);
      void call
        .then(() => list.reload())
        .catch(() => list.reload());
    },
    [list],
  );

  const data = list.data;

  return (
    <Screen
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />
      }
    >
      <Text style={type.title}>Fraud alerts</Text>
      <Text style={type.small}>
        Flagged by the rule engine and, when a model is loaded, by the classifier. An
        empty list means nothing was flagged - not that nothing happened.
      </Text>

      {data && data.unread > 0 ? (
        <AlertBanner tone="info">
          {data.unread} unread alert{data.unread === 1 ? '' : 's'}.
        </AlertBanner>
      ) : null}

      <Button
        label={showDismissed ? 'Hide dismissed' : 'Show dismissed'}
        variant="secondary"
        onPress={() => setShowDismissed((value) => !value)}
      />

      {list.initial ? <Spinner label="Loading alerts" /> : null}

      {list.error && !list.data ? (
        <ErrorState
          message={list.error.isOffline ? 'Cannot reach the API.' : list.error.message}
          onRetry={list.reload}
        />
      ) : null}

      {data && data.items.length === 0 ? (
        <EmptyState
          title="No alerts"
          message="Nothing has been flagged for this account."
        />
      ) : null}

      {data?.items.map((alert) => (
        <AlertCard key={alert.id} alert={alert} onRead={() => act(alert, 'read')} onDismiss={() => act(alert, 'dismiss')} />
      ))}
    </Screen>
  );
}

function AlertCard({
  alert,
  onRead,
  onDismiss,
}: {
  alert: FraudAlert;
  onRead: () => void;
  onDismiss: () => void;
}) {
  const tone = riskColor(alert.risk_level);

  return (
    <Card>
      <View style={styles.row}>
        <StatusPill label={alert.risk_level} color={tone} />
        {alert.is_read ? null : <StatusPill label="New" color={colors.accent} />}
        {alert.is_dismissed ? <StatusPill label="Dismissed" color={colors.muted} /> : null}
      </View>

      <Text style={type.heading}>
        {alert.merchant_snapshot ?? alert.category_snapshot ?? 'Unknown merchant'}
      </Text>
      {alert.amount_snapshot ? (
        <Text style={[type.body, { color: tone }]}>{formatCurrency(alert.amount_snapshot)}</Text>
      ) : null}

      {alert.reasons && alert.reasons.length > 0 ? (
        <View style={styles.tightStack}>
          {alert.reasons.map((reason) => (
            <Text key={reason} style={type.small}>
              • {reason}
            </Text>
          ))}
        </View>
      ) : null}

      <Text style={[type.small, styles.meta]}>
        Risk score {alert.risk_score}/100 · detected by {alert.detection_layer}
        {alert.created_at ? ` · ${formatDateTime(alert.created_at)}` : ''}
      </Text>

      <View style={[styles.row, { gap: space.sm }]}>
        {alert.is_read ? null : (
          <Button
            label="Mark read"
            variant="secondary"
            onPress={onRead}
            style={styles.flexShortButton}
          />
        )}
        {alert.is_dismissed ? null : (
          <Button
            label="Dismiss"
            variant="secondary"
            onPress={onDismiss}
            style={styles.flexShortButton}
          />
        )}
      </View>

      {alert.transaction_id ? (
        <Text style={[type.small, styles.meta]}>
          Related to transaction #{alert.transaction_id}
        </Text>
      ) : null}
    </Card>
  );
}

/** Compact badge for a tab bar, for unread counts. */
export function UnreadBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <View style={styles.badge}>
      <Text style={styles.badgeText}>{count > 99 ? '99+' : count}</Text>
    </View>
  );
}
