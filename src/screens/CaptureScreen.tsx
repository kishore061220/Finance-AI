/**
 * Capture a transaction from a bank SMS or a receipt photo.
 *
 * The parse and the write are separate steps on purpose. `/sms/parse` returns a
 * proposal with a confidence score and writes nothing; the parsed fields are shown
 * for confirmation, and only an explicit save creates the transaction. An SMS
 * parser that guesses is only safe if a human can see the guess first.
 *
 * On-device OCR reads the text with ML Kit; the API then parses that text. Neither
 * step needs the image to leave the device.
 */

import React, { useCallback, useState } from 'react';
import { Image, Platform, Pressable, Text, View } from 'react-native';
import { launchCamera, launchImageLibrary } from 'react-native-image-picker';

import { Alert, Button, Card, Field, Input, Screen, Spinner } from '../components/ui';
import { recognizeText } from '../services/ocr';
import { captureApi } from '../services/endpoints';
import type { OcrParseResponse, SmsParseResponse, TransactionType } from '../types';
import { colors, radius, space, styles, type } from '../theme';
import { TransactionForm } from './TransactionsScreen';

type Mode = 'choose' | 'sms' | 'receipt';

/** Below this the parser is guessing; the user is told rather than trusted. */
const LOW_CONFIDENCE = 0.6;

export default function CaptureScreen() {
  const [mode, setMode] = useState<Mode>('choose');
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [rawText, setRawText] = useState('');
  const [sms, setSms] = useState<SmsParseResponse | null>(null);
  const [receipt, setReceipt] = useState<OcrParseResponse | null>(null);
  const [parsed, setParsed] = useState<{
    amount: string;
    transaction_type: TransactionType;
    category: string;
    merchant: string;
    description: string;
    transaction_date: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parseSms = useCallback(async (text: string) => {
    setBusy(true);
    setError(null);
    try {
      const result = await captureApi.parseSms(text);
      setSms(result);
      setParsed({
        amount: result.amount ?? '',
        transaction_type: result.transaction_type ?? 'expense',
        category: result.category ?? '',
        merchant: result.merchant ?? '',
        description: '',
        transaction_date: result.transaction_date?.slice(0, 10) ?? '',
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not read that SMS.');
    } finally {
      setBusy(false);
    }
  }, []);

  const parseReceipt = useCallback(async (text: string) => {
    setBusy(true);
    setError(null);
    try {
      const result = await captureApi.parseOcr(text);
      setReceipt(result);
      setParsed({
        // A receipt's line items are the real signal; the total is the fallback
        // for a single-item capture.
        amount:
          result.line_items.length === 1
            ? result.line_items[0].amount
            : (result.total ?? ''),
        transaction_type: result.line_items[0]?.transaction_type ?? 'expense',
        // Left blank deliberately: the API assigns a category per line item on
        // commit, and pre-filling one here would apply it to the whole receipt.
        category: '',
        merchant: result.merchant ?? '',
        description: result.line_items.map((item) => item.description).join(', '),
        transaction_date: result.transaction_date?.slice(0, 10) ?? '',
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not read that receipt.');
    } finally {
      setBusy(false);
    }
  }, []);

  const pickImage = useCallback(
    async (source: 'camera' | 'library') => {
      setError(null);
      try {
        const response =
          source === 'camera'
            ? await launchCamera({ mediaType: 'photo', quality: 0.8 })
            : await launchImageLibrary({ mediaType: 'photo', quality: 0.8 });

        if (response.didCancel) return;
        if (response.errorCode) {
          setError(response.errorMessage ?? 'Could not open the image.');
          return;
        }
        const uri = response.assets?.[0]?.uri;
        if (!uri) {
          setError('No image was selected.');
          return;
        }

        setImageUri(uri);
        setBusy(true);
        try {
          const text = await recognizeText(uri);
          if (!text.trim()) {
            setError('No text found in that image. Try a clearer, flatter photo.');
            return;
          }
          setRawText(text);
          await parseReceipt(text);
        } catch (cause) {
          setError(
            cause instanceof Error
              ? cause.message
              : 'On-device text recognition is unavailable on this device.',
          );
        } finally {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : 'Could not open the camera.');
      }
    },
    [parseReceipt],
  );

  const reset = () => {
    setMode('choose');
    setSms(null);
    setReceipt(null);
    setParsed(null);
    setRawText('');
    setImageUri(null);
    setError(null);
  };

  if (parsed) {
    return (
      <TransactionForm
        categories={CATEGORIES}
        initial={parsed}
        onClose={reset}
        onSaved={reset}
      />
    );
  }

  return (
    <Screen>
      <Text style={type.title}>Capture</Text>
      <Text style={type.small}>
        Paste a bank SMS or photograph a receipt. Nothing is saved until you confirm.
      </Text>

      {error ? <Alert tone="error">{error}</Alert> : null}
      {busy ? <Spinner label="Reading" /> : null}

      {mode === 'choose' ? (
        <Card title="Add from a source">
          <Button label="Paste a bank SMS" onPress={() => setMode('sms')} />
          {Platform.OS === 'android' ? (
            <Button
              label="Scan a receipt"
              variant="secondary"
              onPress={() => setMode('receipt')}
            />
          ) : (
            <Text style={type.small}>
              Receipt scanning uses on-device ML Kit, which this build only supports on
              Android. Paste the receipt text instead.
            </Text>
          )}
        </Card>
      ) : null}

      {mode === 'sms' ? (
        <Card title="Bank SMS">
          <Field
            label="Message text"
            hint="The text is sent to the API's parser. Review what it finds before saving."
          >
            <Input
              value={rawText}
              onChangeText={setRawText}
              multiline
              style={[styles.input, styles.inputMultiline]}
              placeholder="INR 450.00 debited at SWIGGY on 12-10-2026"
              accessibilityLabel="SMS text"
            />
          </Field>
          <Button
            label="Parse"
            onPress={() => { void parseSms(rawText); }}
            loading={busy}
            disabled={rawText.trim().length < 4}
          />
          {sms ? <ParsedSummary sms={sms} /> : null}
        </Card>
      ) : null}

      {mode === 'receipt' ? (
        <Card title="Receipt">
          <Text style={type.small}>
            Text is recognised on the device with ML Kit; only the recognised text is
            sent for parsing.
          </Text>
          {imageUri ? (
            <Image
              source={{ uri: imageUri }}
              style={{ width: '100%', height: 220, borderRadius: radius.sm }}
              resizeMode="cover"
              accessibilityLabel="Captured receipt"
            />
          ) : null}
          <Button label="Take a photo" onPress={() => { void pickImage('camera'); }} loading={busy} />
          <Button
            label="Choose from library"
            variant="secondary"
            onPress={() => { void pickImage('library'); }}
          />
          {rawText ? (
            <Field label="Recognised text" hint="Edit this if the reading looks wrong.">
              <Input
                value={rawText}
                onChangeText={setRawText}
                multiline
                style={[styles.input, styles.inputMultiline]}
                accessibilityLabel="Recognised receipt text"
              />
            </Field>
          ) : null}
          {rawText ? (
            <Button
              label="Parse receipt"
              variant="secondary"
              onPress={() => { void parseReceipt(rawText); }}
              loading={busy}
            />
          ) : null}
          {receipt ? <ReceiptSummary receipt={receipt} /> : null}
        </Card>
      ) : null}

      {mode !== 'choose' ? (
        <Pressable accessibilityRole="button" onPress={reset} style={{ alignSelf: 'center' }}>
          <Text style={styles.link}>Back</Text>
        </Pressable>
      ) : null}
    </Screen>
  );
}

/**
 * What the SMS parser found.
 *
 * The confidence is shown even when it is high. A user who can see that a field
 * was machine-read can correct it; one who cannot will either trust a wrong amount
 * or stop trusting the feature.
 */
function ParsedSummary({ sms }: { sms: SmsParseResponse }) {
  const low = sms.confidence < LOW_CONFIDENCE;

  return (
    <View
      style={{
        backgroundColor: colors.surfaceAlt,
        borderRadius: radius.sm,
        padding: space.md,
        gap: space.xs,
      }}
    >
      <View style={styles.row}>
        <Text style={[type.subheading, styles.flex]}>Parsed</Text>
        <Text style={[type.small, { color: low ? colors.warning : colors.positive }]}>
          {Math.round(sms.confidence * 100)}% confidence
        </Text>
      </View>
      {low ? (
        <Text style={[type.small, { color: colors.warning }]}>
          Low confidence. Check every field before saving.
        </Text>
      ) : null}
      <Text style={type.body}>
        {sms.amount ? `${sms.transaction_type ?? 'expense'} ${sms.amount}` : 'No amount found'}
      </Text>
      {sms.merchant ? <Text style={type.small}>Merchant: {sms.merchant}</Text> : null}
      {sms.category ? <Text style={type.small}>Category: {sms.category}</Text> : null}
      {sms.transaction_date ? (
        <Text style={type.small}>Date: {sms.transaction_date}</Text>
      ) : null}
      {sms.bank_reference ? (
        <Text style={type.small}>Reference: {sms.bank_reference}</Text>
      ) : null}
      <Text style={[type.small, { fontStyle: 'italic' }]}>Parser: {sms.parser}</Text>
      {sms.notes.length > 0 ? (
        <Text style={[type.small, { color: colors.warning }]}>{sms.notes.join(' ')}</Text>
      ) : null}
    </View>
  );
}

function ReceiptSummary({ receipt }: { receipt: OcrParseResponse }) {
  return (
    <View
      style={{
        backgroundColor: colors.surfaceAlt,
        borderRadius: radius.sm,
        padding: space.md,
        gap: space.xs,
      }}
    >
      <View style={styles.row}>
        <Text style={[type.subheading, styles.flex]}>Line items</Text>
        <Text style={type.small}>{Math.round(receipt.confidence * 100)}% confidence</Text>
      </View>
      {receipt.line_items.length === 0 ? (
        <Text style={type.small}>No individual line items were recognised.</Text>
      ) : (
        receipt.line_items.map((item, position) => (
          <View key={`${item.raw_line}-${position}`} style={styles.row}>
            <Text style={[type.small, styles.flex]} numberOfLines={1}>
              {item.description}
            </Text>
            <Text style={type.small}>{item.amount}</Text>
          </View>
        ))
      )}
      {receipt.total ? <Text style={type.body}>Total: {receipt.total}</Text> : null}
      {receipt.merchant ? <Text style={type.small}>Merchant: {receipt.merchant}</Text> : null}
    </View>
  );
}

const CATEGORIES = [
  'Food',
  'Transport',
  'Housing',
  'Utilities',
  'Healthcare',
  'Education',
  'Entertainment',
  'Shopping',
  'Other',
];
