/**
 * Settings: environment, auth provider, ML status, backups, push, sign out.
 *
 * This screen is mostly diagnostics. It shows what the server says it is capable of
 * rather than guessing from the app, because the two genuinely differ: the app can
 * have Firebase configured while the API has it disabled, and only the API's answer
 * determines whether a request will work.
 */

import React, { useCallback, useState } from 'react';
import { Platform, Text, View } from 'react-native';

import {
  Alert as AlertBanner,
  Button,
  Card,
  ErrorState,
  LabeledValue,
  Screen,
  SectionTitle,
  Spinner,
  StatusPill,
} from '../components/ui';
import { useSession } from '../auth/SessionProvider';
import { useAsync } from '../hooks/useAsync';
import { formatDateTime } from '../lib/format';
import { backupApi, mlApi } from '../services/endpoints';
import { pushPlatform, pushService } from '../services/push';
import { API_BASE_URL } from '../config';
import { colors, space, styles, type } from '../theme';

export default function SettingsScreen() {
  const { config, user, signOut } = useSession();
  const ml = useAsync(() => mlApi.status(), []);
  const backups = useAsync(() => backupApi.list(), []);
  const [pushState, setPushState] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const enablePush = useCallback(async () => {
    setBusy(true);
    setPushState(null);
    try {
      const result = await pushService.ensurePermission();
      setPushState(result.message);
      if (result.registered) setPushState(`${result.message} This device is registered.`);
    } catch (cause) {
      setPushState(
        cause instanceof Error
          ? cause.message
          : 'Push could not be enabled on this device.',
      );
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <Screen>
      <Text style={type.title}>Settings</Text>

      <SectionTitle>Session</SectionTitle>
      <Card>
        <LabeledValue label="Signed in as" value={user?.email ?? user?.name ?? 'Unknown'} />
        <LabeledValue label="Role" value={user?.role ?? 'unknown'} />
        <View style={styles.row}>
          <Text style={type.label}>Provider</Text>
          <StatusPill
            label={config?.provider ?? 'unknown'}
            color={config?.provider === 'firebase' ? colors.positive : colors.warning}
          />
        </View>
        <Text style={type.small}>
          {config?.firebase_enabled
            ? 'This server accepts Firebase ID tokens.'
            : 'This server does not accept Firebase tokens.'}
        </Text>
        {config?.app_env && config.app_env !== 'production' ? (
          <AlertBanner tone="info">
            Server environment: {config.app_env}. Development authentication is only
            available outside production.
          </AlertBanner>
        ) : null}
      </Card>

      <SectionTitle>Fraud model</SectionTitle>
      {ml.initial ? <Spinner label="Checking model status" /> : null}
      {ml.error ? <ErrorState message={ml.error.message} onRetry={ml.reload} /> : null}
      {ml.data ? (
        <Card>
          <View style={styles.row}>
            <Text style={[type.body, styles.flex]}>
              {ml.data.model_loaded ? ml.data.model_name ?? 'Model loaded' : 'No model loaded'}
            </Text>
            <StatusPill
              label={ml.data.model_loaded ? 'ML' : 'Rules only'}
              color={ml.data.model_loaded ? colors.positive : colors.warning}
            />
          </View>
          <Text style={type.small}>{ml.data.message}</Text>
          <Text style={[type.small, styles.meta]}>
            {ml.data.feature_count} features · {ml.data.scoring_mode} ·{' '}
            {ml.data.user_transaction_count} transactions on this account
          </Text>
          {ml.data.load_error ? (
            <Text style={[type.small, { color: colors.danger }]}>
              Load error: {ml.data.load_error}
            </Text>
          ) : null}
        </Card>
      ) : null}

      <SectionTitle>Backups</SectionTitle>
      {backups.initial ? <Spinner label="Loading backups" /> : null}
      {backups.data ? (
        <Card>
          <View style={styles.row}>
            <Text style={[type.body, styles.flex]}>
              {backups.data.provider ?? 'No provider configured'}
            </Text>
            <StatusPill
              label={backups.data.configured ? 'Configured' : 'Not configured'}
              color={backups.data.configured ? colors.positive : colors.warning}
            />
          </View>
          <Text style={type.small}>{backups.data.message}</Text>
          {backups.data.items.length > 0 ? (
            backups.data.items.slice(0, 5).map((backup) => (
              <View key={backup.id} style={{ paddingTop: space.xs, gap: 2 }}>
                <Text style={type.small}>
                  {backup.provider} · {backup.status} · {backup.record_count ?? 0} records
                </Text>
                <Text style={[type.small, styles.meta]}>
                  {backup.completed_at ? formatDateTime(backup.completed_at) : 'not completed'}
                  {backup.error_message ? ` · ${backup.error_message}` : ''}
                </Text>
              </View>
            ))
          ) : null}
        </Card>
      ) : null}

      <SectionTitle>Notifications</SectionTitle>
      <Card>
        <Text style={type.small}>
          Push needs Firebase Cloud Messaging. Without a configured Firebase project
          the request is refused by the platform, and the reason is shown here rather
          than failing silently.
        </Text>
        {pushState ? <AlertBanner tone="info">{pushState}</AlertBanner> : null}
        <Button
          label="Enable push notifications"
          variant="secondary"
          onPress={() => { void enablePush(); }}
          loading={busy}
        />
      </Card>

      <SectionTitle>About</SectionTitle>
      <Card>
        <LabeledValue label="API base URL" value={API_BASE_URL} />
        <LabeledValue label="Platform" value={Platform.OS} />
        <LabeledValue label="Push platform" value={pushPlatform} />
      </Card>

      <Button label="Sign out" variant="danger" onPress={() => { void signOut(); }} />
    </Screen>
  );
}
