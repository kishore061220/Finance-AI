/**
 * Profile: identity, record counts, and the editable fields.
 *
 * The counts come from `/api/auth/profile`, which is a different response model from
 * `/api/auth/me`. It carries the counts but not `is_active`, so it is used only for
 * what it actually has: the saved profile is read back from `updateProfile`, which
 * does return the full user.
 */

import React, { useCallback, useState } from 'react';
import { Text, View } from 'react-native';

import {
  Alert as AlertBanner,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Screen,
  Spinner,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { formatDate } from '../lib/format';
import { useSession } from '../auth/SessionProvider';
import { authApi } from '../services/endpoints';
import { space, styles, type } from '../theme';

export default function ProfileScreen() {
  const { user, signOut } = useSession();
  const profile = useAsync(() => authApi.profile(), []);

  const [name, setName] = useState(user?.name ?? '');
  const [phone, setPhone] = useState(user?.phone_number ?? '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phoneInvalid = phone.trim() !== '' && !/^\+?[0-9 ()-]{6,20}$/.test(phone.trim());

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await authApi.updateProfile({
        name: name.trim(),
        // An empty field is sent as null, not as "": the API would store a blank
        // string that then displays as an empty-but-present phone number.
        phone_number: phone.trim() === '' ? null : phone.trim(),
      });
      setSaved(true);
      profile.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save your profile.');
    } finally {
      setSaving(false);
    }
  }, [name, phone, profile]);

  return (
    <Screen>
      <Text style={type.title}>Profile</Text>

      {profile.initial ? <Spinner label="Loading profile" /> : null}

      {profile.error && !profile.data ? (
        <ErrorState message={profile.error.message} onRetry={profile.reload} />
      ) : null}

      {profile.data ? (
        <Card title="At a glance">
          <Text style={type.body}>{profile.data.email ?? 'No email recorded'}</Text>
          <Text style={type.small}>
            Role {profile.data.role}
            {profile.data.email_verified ? ' · email verified' : ''}
          </Text>
          <View style={[styles.row, { paddingTop: space.xs }]}>
            <Count label="Transactions" value={profile.data.transaction_count} />
            <Count label="Budgets" value={profile.data.budget_count} />
            <Count label="Loans" value={profile.data.loan_count} />
            <Count label="Family" value={profile.data.family_count} />
          </View>
          {profile.data.created_at ? (
            <Text style={[type.small, styles.meta]}>
              Member since {formatDate(profile.data.created_at)}
            </Text>
          ) : null}
        </Card>
      ) : null}

      <Card title="Details">
        {error ? <ErrorState message={error} showRetry={false} /> : null}
        {saved ? <AlertBanner tone="success">Profile saved.</AlertBanner> : null}

        <Field label="Name">
          <Input value={name} onChangeText={setName} accessibilityLabel="Name" />
        </Field>
        <Field
          label="Phone"
          hint="Optional. Used for loan due-date reminders."
          error={phoneInvalid ? 'That does not look like a phone number.' : null}
        >
          <Input
            value={phone}
            onChangeText={setPhone}
            keyboardType="phone-pad"
            placeholder="+91 98765 43210"
            accessibilityLabel="Phone number"
            invalid={phoneInvalid}
          />
        </Field>
        <Button
          label="Save changes"
          onPress={() => { void save(); }}
          loading={saving}
          disabled={name.trim() === '' || phoneInvalid}
        />
      </Card>

      <Button label="Sign out" variant="secondary" onPress={() => { void signOut(); }} />

      {user?.last_login_at ? (
        <Text style={[type.small, styles.meta]}>
          Last signed in {formatDate(user.last_login_at)}
        </Text>
      ) : null}
    </Screen>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <View style={styles.labelCell}>
      <Text style={type.label}>{label}</Text>
      <Text style={type.heading}>{value}</Text>
    </View>
  );
}
