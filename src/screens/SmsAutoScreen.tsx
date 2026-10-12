/**
 * Automatic bank-SMS detection.
 *
 * This screen is where the user turns detection on and reviews what it did. The
 * design keeps two promises visible:
 *
 *  - **Nothing is hidden.** Every received message that reached the server is
 *    listed with its outcome, including the ones that were ignored because they
 *    were not transactions.
 *  - **The user has the last word.** A message the parser was not confident
 *    enough to save waits as "Needs review" and is only written on an explicit
 *    confirm.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { RefreshControl, Text, View } from 'react-native';

import {
  Alert as AlertBanner,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Screen,
  SectionTitle,
  Spinner,
  StatusPill,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { useSmsInbox } from '../hooks/useSmsInbox';
import { errorMessage } from '../services/api';
import { smsApi } from '../services/endpoints';
import {
  hasSmsPermission,
  isAutoDetectEnabled,
  isSmsAutoDetectAvailable,
  requestSmsPermission,
  setAutoDetectEnabled,
} from '../services/smsDetector';
import type { SmsIngestMessage, SmsIngestStatus } from '../types';
import { colors, space, styles, type } from '../theme';

const STATUS_META: Record<SmsIngestStatus, { label: string; color: string }> = {
  PROCESSING: { label: 'Processing', color: colors.accent },
  SAVED: { label: 'Saved', color: colors.positive },
  DUPLICATE: { label: 'Duplicate', color: colors.muted },
  PENDING_REVIEW: { label: 'Needs review', color: colors.warning },
  INVALID: { label: 'Ignored', color: colors.muted },
  REJECTED: { label: 'Rejected', color: colors.muted },
  ERROR: { label: 'Upload failed', color: colors.danger },
};

export default function SmsAutoScreen() {
  const available = isSmsAutoDetectAvailable();

  const [enabled, setEnabled] = useState(false);
  const [permission, setPermission] = useState<'unknown' | 'granted' | 'denied'>('unknown');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<number | null>(null);

  const inbox = useSmsInbox(enabled);
  const history = useAsync(() => smsApi.list({ page_size: 25 }), [inbox.revision]);

  useEffect(() => {
    void (async () => {
      if (!available) return;
      const [savedEnabled, granted] = await Promise.all([
        isAutoDetectEnabled(),
        hasSmsPermission(),
      ]);
      setPermission(granted ? 'granted' : 'denied');
      // A revoked runtime permission must never leave the UI/listener claiming
      // that automatic detection is active.
      setEnabled(savedEnabled && granted);
    })();
  }, [available]);

  const enable = useCallback(async () => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      if (!(await hasSmsPermission())) {
        const granted = await requestSmsPermission();
        setPermission(granted ? 'granted' : 'denied');
        if (!granted) {
          setNotice(
            'Permission was not granted. You can allow Messages for Finance-AI in Android Settings and try again.',
          );
          return;
        }
      }
      await setAutoDetectEnabled(true);
      setEnabled(true);
      setNotice('Automatic detection is on. New bank messages are added automatically.');
    } catch (error) {
      setActionError(errorMessage(error, 'Could not turn on automatic detection.'));
    } finally {
      setBusy(false);
    }
  }, []);

  const disable = useCallback(async () => {
    await setAutoDetectEnabled(false);
    setEnabled(false);
    setNotice('Automatic detection is off. Messages are no longer read.');
  }, []);

  const decide = useCallback(
    async (message: SmsIngestMessage, action: 'confirm' | 'reject') => {
      setActingOn(message.id);
      setActionError(null);
      try {
        if (action === 'confirm') {
          await smsApi.confirm(message.id);
        } else {
          await smsApi.reject(message.id);
        }
        history.reload();
      } catch (error) {
        setActionError(errorMessage(error, 'That message could not be updated.'));
      } finally {
        setActingOn(null);
      }
    },
    [history],
  );

  return (
    <Screen
      refreshControl={
        <RefreshControl
          refreshing={history.loading && !history.initial}
          onRefresh={history.reload}
          tintColor={colors.accent}
        />
      }
    >
      <Text style={type.title}>Automatic SMS detection</Text>
      <Text style={type.small}>
        While this is on, Finance-AI reads bank transaction messages as they arrive and
        adds them to your ledger. OTPs, promotions and personal messages are filtered on
        your device and never uploaded.
      </Text>

      {actionError ? <AlertBanner tone="error">{actionError}</AlertBanner> : null}
      {inbox.error ? <AlertBanner tone="error">{inbox.error}</AlertBanner> : null}
      {notice ? <AlertBanner tone="success">{notice}</AlertBanner> : null}

      {!available ? (
        <Card title="Not available on this device">
          <Text style={type.small}>
            Automatic detection needs the Android app with the SMS receiver. On this build
            you can still paste a message in the Capture tab.
          </Text>
        </Card>
      ) : (
        <Card title="Detection">
          <View style={styles.row}>
            <Text style={[type.body, styles.flex]}>
              {enabled ? 'Reading bank messages' : 'Off'}
            </Text>
            <StatusPill
              label={enabled ? 'On' : 'Off'}
              color={enabled ? colors.positive : colors.muted}
            />
          </View>

          {permission === 'denied' && !enabled ? (
            <Text style={type.small}>
              Permission not granted yet. Turning detection on asks Android for access to
              incoming messages only.
            </Text>
          ) : null}

          {inbox.queueSize > 0 ? (
            <Text style={[type.small, { color: colors.warning }]}>
              {inbox.queueSize} message{inbox.queueSize === 1 ? '' : 's'} waiting to upload.
              They will be retried automatically.
            </Text>
          ) : null}

          {enabled ? (
            <Button
              label="Turn off"
              variant="secondary"
              onPress={() => {
                void disable();
              }}
            />
          ) : (
            <Button
              label="Turn on automatic detection"
              loading={busy}
              onPress={() => {
                void enable();
              }}
            />
          )}
        </Card>
      )}

      {inbox.events.length > 0 ? (
        <>
          <SectionTitle>Now</SectionTitle>
          <Card>
            {inbox.events.map((message) => (
              <MessageRow key={`live-${message.id}`} message={message} />
            ))}
          </Card>
        </>
      ) : null}

      <SectionTitle>Received messages</SectionTitle>
      {history.initial ? (
        <Spinner label="Loading messages" />
      ) : history.error ? (
        <ErrorState message={history.error.message} onRetry={history.reload} />
      ) : !history.data || history.data.items.length === 0 ? (
        <EmptyState
          title="No messages yet"
          message="Bank messages that arrive while detection is on will appear here."
        />
      ) : (
        <Card>
          {history.data.items.map((message) => (
            <View key={message.id} style={{ gap: space.sm }}>
              <MessageRow message={message} />
              {message.status === 'PENDING_REVIEW' ? (
                <View style={styles.row}>
                  <Button
                    label="Confirm"
                    style={styles.flexShortButton}
                    loading={actingOn === message.id}
                    onPress={() => {
                      void decide(message, 'confirm');
                    }}
                  />
                  <Button
                    label="Not a transaction"
                    variant="secondary"
                    style={styles.flexShortButton}
                    disabled={actingOn === message.id}
                    onPress={() => {
                      void decide(message, 'reject');
                    }}
                  />
                </View>
              ) : null}
              <View style={styles.separator} />
            </View>
          ))}
        </Card>
      )}
    </Screen>
  );
}

function MessageRow({ message }: { message: SmsIngestMessage }) {
  const meta = STATUS_META[message.status];
  return (
    <View style={{ gap: space.xs }}>
      <View style={styles.row}>
        <Text style={[type.body, styles.flex]} numberOfLines={1}>
          {message.sender ? message.sender : 'Bank message'}
        </Text>
        <StatusPill label={meta.label} color={meta.color} />
      </View>
      <Text style={type.small}>{parsedSummary(message)}</Text>
      <Text style={[type.small, styles.meta]} numberOfLines={2}>
        {message.body}
      </Text>
      {message.status === 'ERROR' && message.error_message ? (
        <Text style={[type.small, { color: colors.danger }]}>
          Upload failed ({message.error_message}). It will be retried.
        </Text>
      ) : null}
      {message.status === 'PENDING_REVIEW' && message.confidence != null ? (
        <Text style={[type.small, { color: colors.warning }]}>
          Parsed with {Math.round(message.confidence * 100)}% confidence - please check it.
        </Text>
      ) : null}
    </View>
  );
}

/** A one-line description built from the server's parser snapshot. */
function parsedSummary(message: SmsIngestMessage): string {
  const parsed = message.parsed ?? {};
  const amount = typeof parsed.amount === 'string' ? parsed.amount : null;
  const direction = typeof parsed.transaction_type === 'string' ? parsed.transaction_type : null;
  const merchant = typeof parsed.merchant === 'string' ? parsed.merchant : null;

  if (!amount) return 'No amount found';
  const head = direction ? `${direction} ${amount}` : amount;
  return merchant ? `${head} · ${merchant}` : head;
}
