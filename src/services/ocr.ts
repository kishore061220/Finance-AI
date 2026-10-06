/**
 * On-device text recognition for receipts.
 *
 * Uses ML Kit's bundled text recogniser, which runs entirely on the device: the
 * image never leaves the phone, and only the recognised text is sent to the API
 * for parsing. That matters for a finance app - a receipt carries a merchant name,
 * a total, and often an account identifier.
 *
 * The bundled model ships with the app. `bundled` is left explicit rather than
 * defaulting, because the alternative - downloading the model on first use - needs
 * a working Play Services connection and silently fails on a device without one.
 *
 * ML Kit requires `google-services.json`, so on a build without it this module
 * throws a message explaining the setup rather than an opaque native error.
 */

import TextRecognition from '@react-native-ml-kit/text-recognition';

/** Thrown when the recogniser is unavailable, so the UI can explain why. */
export class OcrUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'OcrUnavailableError';
    Object.setPrototypeOf(this, OcrUnavailableError.prototype);
  }
}

/**
 * Read text from an image on the device.
 *
 * @param uri A local `file://` or `content://` URI from the image picker.
 */
export async function recognizeText(uri: string): Promise<string> {
  let result;
  try {
    result = await TextRecognition.recognize(uri);
  } catch (cause) {
    // ML Kit throws a native exception when google-services.json is absent or the
    // model failed to load. Neither is worth a stack trace in the UI.
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new OcrUnavailableError(
      `On-device text recognition is unavailable. Add android/app/google-services.json ` +
        `and rebuild. (${detail})`,
    );
  }

  // Blocks arrive as separate arrays of lines; a flat join with newlines preserves
  // line boundaries, which the API's receipt parser uses to group items.
  const text = result.blocks
    .flatMap((block) => block.lines)
    .map((line) => line.text)
    .join('\n');

  return text;
}
