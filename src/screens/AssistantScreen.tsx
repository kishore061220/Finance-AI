/**
 * Assistant.
 *
 * A thin chat over `POST /api/assistant`. Two details worth keeping:
 *
 *  - The history sent with each question is everything already on screen, not
 *    including the message being asked. Putting the new message in both places
 *    would show it to the engine twice.
 *  - The reply carries `provider`, `model` and `fallback`. When `fallback` is
 *    true the answer came from the built-in engine rather than the configured
 *    LLM, and the screen says so instead of passing it off as the remote model.
 */

import React, { useCallback, useRef, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import {
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Screen,
  Spinner,
} from '../components/ui';
import { useAsync } from '../hooks/useAsync';
import { assistantApi } from '../services/endpoints';
import type { AssistantMessage } from '../types';
import { colors, radius, styles, type } from '../theme';

/** Chat bubbles. The tail corner is flattened on the side the speaker sits. */
const bubble = StyleSheet.create({
  base: { maxWidth: '90%' },
  user: {
    alignSelf: 'flex-end',
    backgroundColor: colors.accentSoft,
    borderBottomRightRadius: radius.sm,
    borderBottomLeftRadius: radius.lg,
  },
  assistant: {
    alignSelf: 'flex-start',
    backgroundColor: colors.surface,
    borderBottomRightRadius: radius.lg,
    borderBottomLeftRadius: radius.sm,
  },
});

export default function AssistantScreen() {
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastMeta, setLastMeta] = useState<string | null>(null);

  // Monotonic key, so a message is never identified by its position in the list.
  const nextKey = useRef(0);
  const keys = useRef<number[]>([]);

  const config = useAsync(() => assistantApi.config(), []);

  const ask = useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || busy) return;

      const history = messages.slice();
      setMessages((current) => [...current, { role: 'user', content: trimmed }]);
      keys.current.push((nextKey.current += 1));
      setDraft('');
      setBusy(true);
      setError(null);

      try {
        const response = await assistantApi.ask({ message: trimmed, history });
        setMessages((current) => [...current, { role: 'assistant', content: response.reply }]);
        keys.current.push((nextKey.current += 1));
        setLastMeta(
          response.fallback
            ? `${response.provider} · built-in fallback`
            : `${response.provider}${response.model ? ` · ${response.model}` : ''}`,
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'The assistant could not answer.');
      } finally {
        setBusy(false);
      }
    },
    [messages, busy],
  );

  return (
    <Screen>
      <Text style={type.title}>Assistant</Text>

      {config.initial ? <Spinner label="Loading assistant" /> : null}

      {config.error && !config.data ? (
        <ErrorState
          message={config.error.isOffline ? 'Cannot reach the API.' : config.error.message}
          onRetry={config.reload}
        />
      ) : null}

      {config.data ? <Text style={type.small}>{config.data.message}</Text> : null}

      {config.data && config.data.suggestions.length > 0 ? (
        <View style={[styles.row, styles.chipRow]}>
          {config.data.suggestions.slice(0, 6).map((suggestion) => (
            <Button
              key={suggestion}
              label={suggestion}
              variant="secondary"
              onPress={() => { void ask(suggestion); }}
              style={styles.smallButton}
            />
          ))}
        </View>
      ) : null}

      {messages.map((message, index) => (
        <View
          key={keys.current[index] ?? index}
          style={[
            styles.card,
            bubble.base,
            message.role === 'user' ? bubble.user : bubble.assistant,
          ]}
        >
          <Text style={type.body}>{message.content}</Text>
        </View>
      ))}

      {lastMeta ? <Text style={[type.small, styles.meta]}>{lastMeta}</Text> : null}

      {busy ? <Spinner label="Thinking" /> : null}

      {error ? <ErrorState message={error} showRetry={false} /> : null}

      <Card>
        <Field label="Your question">
          <Input
            value={draft}
            onChangeText={setDraft}
            placeholder="How much did I spend on food this month?"
            multiline
            accessibilityLabel="Assistant question"
            onSubmitEditing={() => { void ask(draft); }}
          />
        </Field>
        <Button
          label="Ask"
          onPress={() => { void ask(draft); }}
          loading={busy}
          disabled={draft.trim() === '' || busy}
        />
      </Card>

      {messages.length > 0 ? (
        <Button
          label="Clear conversation"
          variant="secondary"
          onPress={() => {
            setMessages([]);
            keys.current = [];
            setLastMeta(null);
            setError(null);
          }}
        />
      ) : null}
    </Screen>
  );
}
