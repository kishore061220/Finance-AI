/**
 * Push notification registration.
 *
 * Three steps, and any of them can fail on a fresh clone without a Firebase
 * project: ask for OS permission, get an FCM token, register it with the API.
 *
 * Each failure is reported as a sentence for the user rather than an exception.
 * "Push is unavailable because google-services.json is missing" is actionable;
 * a rejected promise from a native module is not. `ensurePermission` never throws,
 * so a screen can render the reason without a try/catch of its own.
 *
 * The token is registered against the signed-in account and re-registered on
 * launch, because FCM rotates tokens and an unregistered device silently stops
 * receiving.
 */

import { PermissionsAndroid, Platform } from 'react-native';
import { firebaseAuth } from './firebase';
import { notificationApi } from './endpoints';

/** The messaging module, loaded lazily. */
type MessagingModule = typeof import('@react-native-firebase/messaging');

export interface PushOutcome {
  registered: boolean;
  message: string;
}

/** The platform label the API stores, so it can choose the right payload. */
export const pushPlatform = Platform.OS === 'ios' ? 'IOS' : 'ANDROID';

/**
 * Asks for the Android 13+ notification permission.
 *
 * Needed because RNFirebase does not do it: `messaging().requestPermission()`
 * returns `AUTHORIZED` on Android without prompting or checking anything, so
 * trusting its result alone registers a token that can never be delivered.
 * `POST_NOTIFICATIONS` itself comes from the FCM SDK's manifest, which merges
 * into the app, so only the runtime request is needed here.
 *
 * Android 12 and below grant notifications implicitly, so there is nothing to ask.
 */
async function ensureAndroidNotificationPermission(): Promise<boolean> {
  // `Version` is a string on iOS, so the platform check is what makes this safe to
  // compare numerically.
  if (Platform.OS !== 'android' || Number(Platform.Version) < 33) return true;

  const permission = PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS;
  if (await PermissionsAndroid.check(permission)) return true;

  const result = await PermissionsAndroid.request(permission, {
    title: 'Allow notifications',
    message:
      'FinanceAI notifies you about fraud alerts and budget thresholds. Nothing else is sent.',
    buttonPositive: 'Allow',
    buttonNegative: 'Not now',
  });

  return result === PermissionsAndroid.RESULTS.GRANTED;
}

/** Asks for the iOS notification permission, which is all iOS needs. */
async function ensureIosNotificationPermission(
  messaging: MessagingModule,
): Promise<boolean> {
  // Resolves to the status itself rather than an object with `authorizationStatus`.
  const status = await messaging.default().requestPermission();
  return (
    status === messaging.AuthorizationStatus.AUTHORIZED ||
    // Authorised provisionally, without ever prompting.
    status === messaging.AuthorizationStatus.PROVISIONAL
  );
}

export const pushService = {
  platform: pushPlatform,

  /**
   * Request permission and register this device.
   *
   * Returns rather than throws for every expected outcome; the caller shows
   * `message`.
   */
  async ensurePermission(): Promise<PushOutcome> {
    const auth = await firebaseAuth();
    if (!auth) {
      return {
        registered: false,
        message:
          'Push needs a Firebase project. This build has no google-services.json, so ' +
          'no FCM token can be issued. See the README.',
      };
    }

    let messaging: MessagingModule;
    try {
      messaging = require('@react-native-firebase/messaging') as MessagingModule;
    } catch {
      return {
        registered: false,
        message: 'The Firebase messaging module is not available in this build.',
      };
    }

    let granted: boolean;
    try {
      granted =
        Platform.OS === 'android'
          ? await ensureAndroidNotificationPermission()
          : await ensureIosNotificationPermission(messaging);
    } catch (cause) {
      return {
        registered: false,
        message:
          cause instanceof Error
            ? `Could not request notification permission: ${cause.message}`
            : 'Could not request notification permission.',
      };
    }

    if (!granted) {
      return {
        registered: false,
        message: 'Notification permission was declined for this app. Enable it in system settings.',
      };
    }

    try {
      const token = await messaging.default().getToken();
      if (!token) {
        return {
          registered: false,
          message: 'Firebase returned an empty messaging token.',
        };
      }
      await notificationApi.registerDevice(token, pushPlatform);
      return {
        registered: true,
        message: 'This device can receive notifications.',
      };
    } catch (cause) {
      return {
        registered: false,
        message:
          cause instanceof Error
            ? `Could not register this device for push: ${cause.message}`
            : 'Could not register this device for push.',
      };
    }
  },

  /**
   * Background event handler.
   *
   * Registered from `index.js` because a handler registered later will not run for
   * a notification that launched the app from terminated. Only logs the receipt:
   * acting on it here would race the React tree, which is not mounted yet.
   */
  async registerBackgroundHandler(): Promise<() => void> {
    const auth = await firebaseAuth();
    if (!auth) return () => undefined;

    try {
      const messaging = require('@react-native-firebase/messaging') as MessagingModule;
      return messaging.default().onMessage(() => {
        // Foreground messages are rendered by the notification screen instead, so
        // showing a system alert here would duplicate them.
      });
    } catch {
      return () => undefined;
    }
  },
};
