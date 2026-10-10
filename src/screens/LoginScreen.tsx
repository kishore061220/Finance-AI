/**
 * Sign in.
 *
 * The forms offered depend on what the *server* reports, not on what this build
 * happens to contain. `/api/auth/config` decides:
 *
 *  - `firebase`      -> email/password, and a warning when this build points at
 *                       a different project or has no `google-services.json`.
 *  - `dev` /
 *    `unconfigured`  -> nothing to offer. An explanatory message, because the
 *                       alternative is a form that cannot succeed.
 *
 * The only authentication path this client offers is Firebase. Registering is a
 * Firebase-only operation, so the "create account" toggle appears only when the
 * server has Firebase enabled.
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
import { useSession, isFirebaseAvailable } from '../auth/SessionProvider';
import { space, styles, type } from '../theme';

type Mode = 'signIn' | 'register';

export default function LoginScreen() {
  const { status, config, firebaseProjectIssue, signInWithEmail, signUp } = useSession();

  const [mode, setMode] = useState<Mode>('signIn');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buildFirebase = isFirebaseAvailable();
  const serverSaysFirebase = config?.firebase_enabled ?? false;
  const decisionKnown = config !== null;
  const canOfferForms = serverSaysFirebase || (buildFirebase && !decisionKnown);

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

  if (status === 'loading' && config === null && buildFirebase) {
    return (
      <Screen>
        <View style={styles.centered}>
          <Text style={type.title}>Finance AI</Text>
          <Spinner label="Checking the server" />
        </View>
      </Screen>
    );
  }

  const renderProjectIssue = () => {
    if (!firebaseProjectIssue) return null;
    if (firebaseProjectIssue === 'unconfigured') {
      return (
        <AlertBanner tone="error">
          This build has no google-services.json, so it cannot obtain an ID token
          for the Firebase server. Add the file and rebuild.
        </AlertBanner>
      );
    }
    return (
      <AlertBanner tone="error">
        This app is built against one Firebase project, but the server verifies a
        different one. Sign-in would succeed and then be rejected. Rebuild the app
        with the project the server uses.
      </AlertBanner>
    );
  };

  return (
    <Screen>
      <View style={styles.centered}>
        <Text style={type.title}>Finance AI</Text>
        <Text style={type.small}>
          {canOfferForms
            ? mode === 'signIn'
              ? 'Sign in to see your spending, budgets and loans.'
              : 'Create an account. Email verification is handled by Firebase.'
            : 'This server has no Firebase Authentication configured, so no sign-in form can succeed.'}
        </Text>
      </View>

      {error ? <AlertBanner tone="error">{error}</AlertBanner> : null}

      {!canOfferForms ? (
        <AlertBanner tone="error">
          No sign-in form can succeed against this server. Configure the backend
          with Firebase credentials and build this app with the same Firebase
          project.
        </AlertBanner>
      ) : (
        <>
          {renderProjectIssue()}

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
        </>
      )}

      <Text style={[type.small, { textAlign: 'center', marginTop: space.sm }]}>
        Authentication is handled by Firebase. This app never sees your password.
      </Text>
    </Screen>
  );
}
