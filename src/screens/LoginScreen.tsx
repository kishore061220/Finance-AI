/**
 * Sign in.
 *
 * The forms offered depend on what the *server* reports, not on what this build
 * happens to contain. `/api/auth/config` decides:
 *
 *  - `firebase`      -> email/password and Google.
 *  - `dev`           -> a development-token button, and only that. No email field,
 *                       because there is no way to verify a password against it.
 *  - `unconfigured`  -> nothing to offer. An explanatory message, because the
 *                       alternative is a form that cannot succeed.
 *
 * Registering is a Firebase-only operation, so the "create account" toggle appears
 * only when the server has Firebase enabled.
 */

import React, { useCallback, useState } from 'react';
import { Text, View } from 'react-native';

import {
  Alert as AlertBanner,
  Button,
  Field,
  Input,
  Screen,
  Spinner,
} from '../components/ui';
import { useSession } from '../auth/SessionProvider';
import { space, styles, type } from '../theme';

type Mode = 'signIn' | 'register';

export default function LoginScreen() {
  const { config, signInWithEmail, signUp, signInAsDeveloper } = useSession();

  const [mode, setMode] = useState<Mode>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const provider = config?.provider ?? null;

  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (cause) {
      // The provider messages are specific and already user-facing ("The password
      // is invalid", "user not found"), so they are passed through as-is.
      setError(cause instanceof Error ? cause.message : 'Sign in failed.');
      setBusy(false);
    }
  }, []);

  const submitCredentials = () => {
    void run(async () => {
      if (mode === 'register') {
        await signUp(email.trim(), password, name.trim());
      } else {
        await signInWithEmail(email.trim(), password);
      }
    });
  };

  if (provider === null) {
    return (
      <Screen>
        <View style={styles.centered}>
          <Text style={type.title}>Finance AI</Text>
          <Spinner label="Checking the server" />
        </View>
      </Screen>
    );
  }

  if (provider === 'unconfigured') {
    return (
      <Screen>
        <View style={styles.centered}>
          <Text style={type.title}>Finance AI</Text>
          <AlertBanner tone="error">
            This server has no authentication provider configured. Set up Firebase
            Authentication, or run a local server with ALLOW_DEV_AUTH=true.
          </AlertBanner>
          <Text style={type.small}>
            Sign in will return once the server is configured.
          </Text>
        </View>
      </Screen>
    );
  }

  if (provider === 'dev') {
    return (
      <Screen>
        <View style={styles.centered}>
          <Text style={type.title}>Finance AI</Text>
          <Text style={type.small}>
            This server is running in development authentication mode. No password is
            checked; the API mints a token for the address entered below.
          </Text>

          {error ? <AlertBanner tone="error">{error}</AlertBanner> : null}

          <Field label="Email">
            <Input
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoComplete="email"
              placeholder="you@example.com"
              accessibilityLabel="Email"
            />
          </Field>

          <Button
            label="Continue as developer"
            onPress={() => {
              void run(() => signInAsDeveloper(email.trim() || 'dev@example.com'));
            }}
            loading={busy}
          />

          <Text style={[type.small, styles.centeredText]}>
            This path is unavailable on a server with Firebase configured, and the API
            refuses to mint these tokens in production.
          </Text>
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <View style={styles.centered}>
        <Text style={type.title}>Finance AI</Text>
        <Text style={type.small}>
          {mode === 'signIn'
            ? 'Sign in to see your spending, budgets and loans.'
            : 'Create an account. Email verification is handled by Firebase.'}
        </Text>
      </View>

      {error ? <AlertBanner tone="error">{error}</AlertBanner> : null}

      {mode === 'register' ? (
        <Field label="Name">
          <Input value={name} onChangeText={setName} accessibilityLabel="Name" autoComplete="name" />
        </Field>
      ) : null}

      <Field label="Email">
        <Input
          value={email}
          onChangeText={setEmail}
          keyboardType="email-address"
          autoCapitalize="none"
          autoComplete="email"
          placeholder="you@example.com"
          accessibilityLabel="Email"
        />
      </Field>

      <Field
        label="Password"
        hint={mode === 'register' ? 'At least 6 characters.' : undefined}
      >
        <Input
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoCapitalize="none"
          autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
          placeholder="••••••••"
          accessibilityLabel="Password"
        />
      </Field>

      <Button
        label={mode === 'signIn' ? 'Sign in' : 'Create account'}
        onPress={submitCredentials}
        loading={busy}
        disabled={email.trim() === '' || password === '' || (mode === 'register' && name.trim() === '')}
      />

      {config?.registration_enabled ? (
        <Button
          label={mode === 'signIn' ? 'Create an account instead' : 'I already have an account'}
          variant="secondary"
          onPress={() => {
            setMode(mode === 'signIn' ? 'register' : 'signIn');
            setError(null);
          }}
        />
      ) : null}

      <Text style={[type.small, { textAlign: 'center', marginTop: space.sm }]}>
        Authentication is handled by Firebase. This app never sees your password.
      </Text>
    </Screen>
  );
}
