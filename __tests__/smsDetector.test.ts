/**
 * Automatic SMS detection.
 *
 * The behaviour that matters here is not "does it parse a message" - the server
 * owns parsing. It is the three promises the device layer makes: only bank
 * transactions leave the phone, a failed upload is not lost, and a retry does not
 * create a second transaction. Those are what these tests pin down.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { DeviceEventEmitter, NativeModules, Platform } from 'react-native';

import { api } from '../src/services/api';
import {
  PENDING_QUEUE_KEY,
  flushSmsQueue,
  ingestSms,
  isSmsAutoDetectAvailable,
  looksLikeBankTransaction,
  smsQueueSize,
  startSmsInbox,
  type IncomingSms,
} from '../src/services/smsDetector';
import type { SmsIngestMessage } from '../src/types';

const captured: { url?: string; method?: string; data?: unknown }[] = [];
let failUploads = false;

const DEVICE_MESSAGE: IncomingSms = {
  client_msg_id: 'sms-1700000000000-abcdef12',
  sender: 'VM-SBIINB',
  body: 'Your a/c XX1234 debited by Rs 450.00 at SWIGGY on 12-10-26',
  received_at_ms: 1700000000000,
};

function serverMessage(overrides: Partial<SmsIngestMessage> = {}): SmsIngestMessage {
  return {
    id: 1,
    user_id: 1,
    client_msg_id: DEVICE_MESSAGE.client_msg_id,
    sender: DEVICE_MESSAGE.sender ?? null,
    body: DEVICE_MESSAGE.body,
    received_at: '2023-11-14T22:13:20.000Z',
    status: 'SAVED',
    parsed: { amount: '450.00', transaction_type: 'expense', merchant: 'SWIGGY' },
    confidence: 0.92,
    rejection_reason: null,
    error_message: null,
    transaction_id: 10,
    transaction: null,
    created_at: '2023-11-14T22:13:20.000Z',
    updated_at: '2023-11-14T22:13:20.000Z',
    ...overrides,
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

beforeEach(async () => {
  captured.length = 0;
  failUploads = false;
  await AsyncStorage.clear();

  Platform.OS = 'android';
  NativeModules.SmsReceiver = {
    isSupported: jest.fn(async () => true),
    getPendingMessages: jest.fn(async () => []),
    addListener: jest.fn(),
    removeListeners: jest.fn(),
  };

  api.defaults.adapter = (async (config: (typeof captured)[number]) => {
    captured.push(config);
    if (failUploads) throw new Error('network down');
    return { data: serverMessage(), status: 201, statusText: 'Created', headers: {}, config };
  }) as never;
});

describe('looksLikeBankTransaction', () => {
  it('accepts a debit and a credit', () => {
    expect(looksLikeBankTransaction('Your a/c XX1234 debited by Rs 450.00 at SWIGGY')).toBe(true);
    expect(looksLikeBankTransaction('INR 1,000.00 credited to your account')).toBe(true);
  });

  it('rejects an OTP even though it mentions a transaction', () => {
    expect(
      looksLikeBankTransaction('123456 is your OTP for a Rs 450.00 transaction. Do not share.'),
    ).toBe(false);
  });

  it('rejects a promotion', () => {
    expect(
      looksLikeBankTransaction('Congratulations! You won a Rs 500 discount coupon. Click here.'),
    ).toBe(false);
  });

  it('rejects a balance-only notice with no direction', () => {
    expect(looksLikeBankTransaction('Your available balance is Rs 5,000.00')).toBe(false);
  });

  it('rejects a personal message', () => {
    expect(looksLikeBankTransaction('Hey, are we still meeting at 5?')).toBe(false);
  });
});

describe('isSmsAutoDetectAvailable', () => {
  it('is available on Android with the native module present', () => {
    expect(isSmsAutoDetectAvailable()).toBe(true);
  });

  it('is unavailable when the native module is missing', () => {
    delete (NativeModules as Record<string, unknown>).SmsReceiver;
    expect(isSmsAutoDetectAvailable()).toBe(false);
  });

  it('is unavailable on iOS', () => {
    Platform.OS = 'ios';
    expect(isSmsAutoDetectAvailable()).toBe(false);
  });
});

describe('ingestSms', () => {
  it('uploads a transaction with a stable idempotency key and no user id', async () => {
    const results: SmsIngestMessage[] = [];
    await ingestSms(DEVICE_MESSAGE, { onResult: (message) => results.push(message) });

    expect(captured).toHaveLength(1);
    expect(captured[0].url).toBe('/api/sms/messages');
    const body = JSON.parse(String(captured[0].data));
    expect(body.client_msg_id).toBe(DEVICE_MESSAGE.client_msg_id);
    expect(body.sender).toBe(DEVICE_MESSAGE.sender);
    expect(body.received_at).toBe('2023-11-14T22:13:20.000Z');
    expect(JSON.stringify(body)).not.toContain('user_id');
    expect(results).toHaveLength(1);
  });

  it('drops a non-transaction without uploading it', async () => {
    const results: SmsIngestMessage[] = [];
    await ingestSms(
      { client_msg_id: 'x', body: '123456 is your OTP. Do not share.', received_at_ms: 1 },
      { onResult: (message) => results.push(message) },
    );

    expect(captured).toHaveLength(0);
    expect(results).toHaveLength(0);
  });

  it('queues the message for retry when the upload fails', async () => {
    failUploads = true;
    const errors: unknown[] = [];
    await ingestSms(DEVICE_MESSAGE, { onError: (error) => errors.push(error) });

    expect(errors).toHaveLength(1);
    expect(await smsQueueSize()).toBe(1);
  });
});

describe('flushSmsQueue', () => {
  it('clears the queue and reports results when the retry succeeds', async () => {
    failUploads = true;
    await ingestSms(DEVICE_MESSAGE, {});
    expect(await smsQueueSize()).toBe(1);

    failUploads = false;
    const results = await flushSmsQueue();

    expect(results).toHaveLength(1);
    expect(await smsQueueSize()).toBe(0);
  });

  it('keeps the message queued when the retry keeps failing', async () => {
    failUploads = true;
    await ingestSms(DEVICE_MESSAGE, {});

    await flushSmsQueue();

    expect(await smsQueueSize()).toBe(1);
  });

  it('persists the queue under the documented storage key', async () => {
    failUploads = true;
    await ingestSms(DEVICE_MESSAGE, {});

    const raw = await AsyncStorage.getItem(PENDING_QUEUE_KEY);
    expect(JSON.parse(String(raw))[0].client_msg_id).toBe(DEVICE_MESSAGE.client_msg_id);
  });
});

describe('startSmsInbox', () => {
  it('is a no-op without the native module', () => {
    delete (NativeModules as Record<string, unknown>).SmsReceiver;
    const stop = startSmsInbox();
    expect(typeof stop).toBe('function');
    expect(() => stop()).not.toThrow();
    expect(captured).toHaveLength(0);
  });

  it('uploads a message delivered by the native emitter and stops on unsubscribe', async () => {
    const stop = startSmsInbox();
    DeviceEventEmitter.emit('onSmsReceived', DEVICE_MESSAGE);
    await tick();

    expect(captured).toHaveLength(1);

    stop();
    DeviceEventEmitter.emit('onSmsReceived', { ...DEVICE_MESSAGE, client_msg_id: 'second' });
    await tick();

    expect(captured).toHaveLength(1);
  });

  it('uploads messages buffered natively while JS was not running', async () => {
    (NativeModules.SmsReceiver.getPendingMessages as jest.Mock).mockResolvedValue([DEVICE_MESSAGE]);

    const stop = startSmsInbox();
    await tick();
    await tick();
    stop();

    expect(captured).toHaveLength(1);
    expect(captured[0].url).toBe('/api/sms/messages');
  });
});
