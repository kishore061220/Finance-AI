/**
 * Automatic bank-SMS detection.
 *
 * On Android the native `SmsReceiver` delivers each incoming SMS to this layer.
 * This module is the gatekeeper between the device and the network, and it is
 * deliberately conservative:
 *
 *  1. **Filter before upload.** Only a message that carries both a currency
 *     amount and a debit/credit direction is forwarded. OTPs, promotions,
 *     personal messages and balance-only notices never leave the device. The
 *     server validates again, but the privacy promise is kept here.
 *  2. **Never lose a transaction to a bad connection.** A failed upload is
 *     queued in AsyncStorage and retried; each message carries a stable
 *     `client_msg_id`, so the server deduplicates a retry rather than writing
 *     twice.
 *  3. **No background claim that is not true.** The receiver catches messages
 *     even when the UI is closed, but processing them requires the JS runtime.
 *     Anything captured while JS was not running is persisted natively and
 *     drained on the next launch.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  DeviceEventEmitter,
  NativeEventEmitter,
  NativeModules,
  PermissionsAndroid,
  Platform,
} from 'react-native';

import { smsApi } from './endpoints';
import type { SmsIngestMessage } from '../types';

/** Where the retry queue lives. Namespaced so it cannot collide with session keys. */
export const PENDING_QUEUE_KEY = 'financeai.sms.pending';

/** Whether the user has switched automatic detection on. */
export const AUTO_DETECT_KEY = 'financeai.sms.enabled';

/** Emitted by the native receiver. Must match `SmsReceiverModule.EVENT_NAME`. */
export const SMS_EVENT = 'onSmsReceived';
/** Emitted after an SMS creates (or replays) a saved transaction. */
export const TRANSACTIONS_CHANGED_EVENT = 'financeai.transactions.changed';

/** One SMS as the native receiver reports it. */
export interface IncomingSms {
  client_msg_id: string;
  sender?: string | null;
  body: string;
  /** Device wall-clock time in milliseconds. */
  received_at_ms: number;
}

export interface SmsInboxHandlers {
  /** A message reached the server and was processed. */
  onResult?: (message: SmsIngestMessage) => void;
  /** A message failed to upload and has been queued for retry. */
  onError?: (error: unknown, raw: IncomingSms) => void;
  /** The retry queue changed size. */
  onQueueChange?: (size: number) => void;
}

interface NativeSmsModule {
  isSupported(): Promise<boolean>;
  getPendingMessages(): Promise<IncomingSms[]>;
  addListener(eventName: string): void;
  removeListeners(count: number): void;
}

let queueOperation: Promise<void> = Promise.resolve();

function withQueueLock<T>(operation: () => Promise<T>): Promise<T> {
  const run = queueOperation.then(operation, operation);
  queueOperation = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

// ----------------------------------------------------------------- filter

/** A currency-prefixed figure, e.g. "Rs 500", "INR 1,234.56", "₹450". */
const CURRENCY_AMOUNT = /(?:rs\.?|inr|₹)\s?\d/i;
/** A two-decimal figure without a currency word, e.g. "1,234.56". */
const DECIMAL_AMOUNT = /\b\d[\d,]*\.\d{2}\b/;
/** A debit or credit verb - the signal that a transaction actually happened. */
const DIRECTION =
  /\b(debited|credited|debit|credit|spent|withdrawn|withdrawal|salary|refund|paid|received|transferred|purchase)\b/i;
/** Things that are never a transaction, dropped on the device. */
const NEVER_UPLOAD =
  /\b(otp|one[\s-]?time[\s-]?password|verification code|do not share|valid for \d|expires in|congratulations|you (?:have )?won|discount|coupon|% ?off|subscribe|click here|unsubscribe)\b/i;

/**
 * Whether a message looks like a bank transaction worth uploading.
 *
 * Intentionally strict: a false negative (a real transaction the user adds by
 * hand) is acceptable; uploading an OTP or a personal message is not.
 */
export function looksLikeBankTransaction(body: string): boolean {
  const text = (body || '').trim();
  // Bank notices are sentences; anything shorter is noise.
  if (text.length < 8) return false;
  if (NEVER_UPLOAD.test(text)) return false;
  const hasAmount = CURRENCY_AMOUNT.test(text) || DECIMAL_AMOUNT.test(text);
  return hasAmount && DIRECTION.test(text);
}

// ----------------------------------------------------------------- queue

async function readQueue(): Promise<IncomingSms[]> {
  try {
    const raw = await AsyncStorage.getItem(PENDING_QUEUE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as IncomingSms[]) : [];
  } catch {
    // A corrupt queue must not block the next message.
    return [];
  }
}

async function writeQueue(items: IncomingSms[]): Promise<void> {
  await AsyncStorage.setItem(PENDING_QUEUE_KEY, JSON.stringify(items));
}

function toIso(ms: number): string {
  const value = Number.isFinite(ms) && ms > 0 ? ms : Date.now();
  return new Date(value).toISOString();
}

// ----------------------------------------------------------------- native

function nativeModule(): NativeSmsModule | null {
  const registry = NativeModules as Record<string, unknown>;
  return (registry.SmsReceiver as NativeSmsModule | undefined) ?? null;
}

/** True when this build can receive SMS automatically (Android + native module). */
export function isSmsAutoDetectAvailable(): boolean {
  return Platform.OS === 'android' && nativeModule() !== null;
}

/** Whether RECEIVE_SMS is already granted, without prompting. */
export async function hasSmsPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  try {
    return await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.RECEIVE_SMS);
  } catch {
    return false;
  }
}

/** Persisted opt-in for automatic detection. */
export async function isAutoDetectEnabled(): Promise<boolean> {
  return (await AsyncStorage.getItem(AUTO_DETECT_KEY)) === 'true';
}

export async function setAutoDetectEnabled(value: boolean): Promise<void> {
  await AsyncStorage.setItem(AUTO_DETECT_KEY, value ? 'true' : 'false');
}

/**
 * Ask for the runtime SMS permission.
 *
 * Only RECEIVE_SMS is requested; the app never asks to read the SMS inbox.
 */
export async function requestSmsPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECEIVE_SMS, {
    title: 'Detect bank messages',
    message:
      'Finance-AI reads bank transaction messages to add them to your ledger. OTPs and personal messages are ignored on your device and never uploaded.',
    buttonPositive: 'Allow',
    buttonNegative: 'Not now',
  });
  return result === PermissionsAndroid.RESULTS.GRANTED;
}

// ----------------------------------------------------------------- submit

async function submit(raw: IncomingSms): Promise<SmsIngestMessage> {
  return smsApi.receive({
    client_msg_id: raw.client_msg_id,
    sender: raw.sender ?? null,
    body: raw.body,
    received_at: toIso(raw.received_at_ms),
  });
}

async function enqueue(raw: IncomingSms, handlers: SmsInboxHandlers, error: unknown): Promise<void> {
  await withQueueLock(async () => {
    const queue = await readQueue();
    if (!queue.some((item) => item.client_msg_id === raw.client_msg_id)) {
      queue.push(raw);
      await writeQueue(queue);
      handlers.onQueueChange?.(queue.length);
    }
  });
  handlers.onError?.(error, raw);
}

/** Handle one device message: filter, upload, or queue on failure. */
export async function ingestSms(raw: IncomingSms, handlers: SmsInboxHandlers = {}): Promise<void> {
  if (!looksLikeBankTransaction(raw.body)) {
    // Dropped on the device. Nothing is uploaded, queued or logged.
    return;
  }
  try {
    // `submit` must run even when no `onResult` handler is registered, so it is
    // awaited on its own line. Passing it as an argument to `onResult?.()`
    // would short-circuit and skip the upload whenever `onResult` is absent.
    const result = await submit(raw);
    handlers.onResult?.(result);
    if (result.status === 'SAVED' && result.transaction_id !== null) {
      DeviceEventEmitter.emit(TRANSACTIONS_CHANGED_EVENT);
    }
  } catch (error) {
    await enqueue(raw, handlers, error);
  }
}

/**
 * Retry everything in the queue.
 *
 * Safe to call repeatedly: a message that still fails stays queued, and a
 * message the server already recorded is deduplicated by `client_msg_id`.
 */
export async function flushSmsQueue(handlers: SmsInboxHandlers = {}): Promise<SmsIngestMessage[]> {
  return withQueueLock(async () => {
    const queued = await readQueue();
    if (queued.length === 0) {
      handlers.onQueueChange?.(0);
      return [];
    }

    const remaining: IncomingSms[] = [];
    const results: SmsIngestMessage[] = [];

    for (const item of queued) {
      try {
        const result = await submit(item);
        results.push(result);
        handlers.onResult?.(result);
        if (result.status === 'SAVED' && result.transaction_id !== null) {
          DeviceEventEmitter.emit(TRANSACTIONS_CHANGED_EVENT);
        }
      } catch (error) {
        remaining.push(item);
        handlers.onError?.(error, item);
      }
    }

    await writeQueue(remaining);
    handlers.onQueueChange?.(remaining.length);
    return results;
  });
}

/** Current queue size, for the status screen. */
export async function smsQueueSize(): Promise<number> {
  return (await readQueue()).length;
}

/**
 * Start listening for SMS.
 *
 * Returns an unsubscribe function. Drains natively-buffered messages first, then
 * retries anything already queued. Safe to call on a platform without the
 * native module - it becomes a no-op.
 */
export function startSmsInbox(handlers: SmsInboxHandlers = {}): () => void {
  const module = nativeModule();
  if (Platform.OS !== 'android' || !module) {
    return () => undefined;
  }

  const emitter = new NativeEventEmitter(module as never);
  const subscription = emitter.addListener(SMS_EVENT, (raw: unknown) => {
    void ingestSms(raw as IncomingSms, handlers);
  });

  // Messages the receiver caught while JS was not running.
  void (async () => {
    try {
      const buffered = await module.getPendingMessages();
      for (const raw of buffered) {
        await ingestSms(raw, handlers);
      }
    } catch (error) {
      handlers.onError?.(error, { client_msg_id: '', body: '', received_at_ms: 0 });
    }
  })();

  // Anything that failed to upload previously.
  void flushSmsQueue(handlers);

  return () => subscription.remove();
}
