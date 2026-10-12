/**
 * Live SMS inbox state for a screen.
 *
 * Subscribes to the native receiver only while `enabled`, so the app is not
 * listening before the user opts in. Every arriving message that the server
 * processed bumps `revision`, which a screen uses as a dependency to refresh its
 * persisted history list.
 */

import { useCallback, useEffect, useState } from 'react';

import { errorMessage } from '../services/api';
import { smsQueueSize, startSmsInbox } from '../services/smsDetector';
import type { SmsIngestMessage } from '../types';

export interface SmsInboxState {
  /** Messages processed during this app session, newest first. */
  events: SmsIngestMessage[];
  /** How many messages are waiting to be uploaded. */
  queueSize: number;
  /** Set when a message could not be uploaded. */
  error: string | null;
  /** Increments whenever a message is processed, to trigger a history refresh. */
  revision: number;
  clearError: () => void;
}

export function useSmsInbox(enabled: boolean): SmsInboxState {
  const [events, setEvents] = useState<SmsIngestMessage[]>([]);
  const [queueSize, setQueueSize] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    void smsQueueSize()
      .then(setQueueSize)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    const stop = startSmsInbox({
      onResult: (message) => {
        setEvents((previous) =>
          [message, ...previous.filter((item) => item.id !== message.id)].slice(0, 20),
        );
        setRevision((count) => count + 1);
      },
      onError: (cause) => setError(errorMessage(cause, 'Could not upload a bank message.')),
      onQueueChange: setQueueSize,
    });

    return stop;
  }, [enabled]);

  const clearError = useCallback(() => setError(null), []);

  return { events, queueSize, error, revision, clearError };
}
