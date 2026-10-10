/**
 * Runtime configuration.
 *
 * The API base URL is the one value that has to differ per environment, and it
 * differs per *platform* as well: an Android emulator reaches the host machine
 * through a special alias, while the iOS simulator shares the host's network
 * stack and uses loopback. Getting this wrong is the single most common reason a
 * React Native app cannot talk to a local backend, so it is resolved in one
 * place here rather than repeated in each service.
 */

import { Platform } from 'react-native';

/**
 * Overrides the built-in default. Set it to an absolute URL for a device on the
 * same network, e.g. `http://192.168.1.20:8000`.
 *
 * A physical device cannot reach `10.0.2.2` or `127.0.0.1` - those refer to the
 * device itself, or to the emulator's own view of the host.
 */
export const API_BASE_URL_OVERRIDE: string | null = null;

/** The host machine, as seen from the current platform. */
export function defaultApiBaseUrl(): string {
  // 10.0.2.2 is the Android emulator's alias for the host loopback interface.
  // The iOS simulator runs natively on the host and uses 127.0.0.1.
  const host = Platform.OS === 'android' ? '10.0.2.2' : '127.0.0.1';
  return `http://${host}:8000`;
}

export const API_BASE_URL = API_BASE_URL_OVERRIDE ?? defaultApiBaseUrl();

/** How often the fraud and notification badge counts are refreshed, in ms. */
export const BADGE_POLL_INTERVAL_MS = 60_000;
