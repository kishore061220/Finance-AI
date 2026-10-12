package com.financeai.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import org.json.JSONObject
import java.security.MessageDigest

/**
 * Receives bank SMS broadcasts.
 *
 * The manifest registers this for `android.provider.Telephony.SMS_RECEIVED`,
 * which Android delivers directly to the app (no polling). The receiver does the
 * absolute minimum: it reads the sender and body, hands the message to the JS
 * layer if it is running, and otherwise persists it for the next launch.
 *
 * No message content is logged or sent anywhere from here - the decision to
 * upload belongs to the JavaScript layer, which filters out OTPs, promotions and
 * anything that is not a financial transaction before it reaches the network.
 */
class SmsReceiver : BroadcastReceiver() {

  override fun onReceive(context: Context, intent: Intent) {
    if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

    val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return

    // A long SMS arrives as several PDUs that share one originating address.
    // They are merged so a multipart bank message is parsed as one message
    // rather than as misleading fragments.
    val builders = LinkedHashMap<String, StringBuilder>()
    var timestamp = 0L
    for (part in parts) {
      val sender = part.originatingAddress ?: "unknown"
      builders.getOrPut(sender) { StringBuilder() }.append(part.messageBody ?: "")
      val at = if (part.timestampMillis > 0) part.timestampMillis else System.currentTimeMillis()
      if (at > timestamp) timestamp = at
    }

    for ((sender, builder) in builders) {
      val body = builder.toString()
      if (body.isBlank()) continue

      val item = JSONObject()
      item.put("client_msg_id", "sms-$timestamp-${fingerprint(sender, body)}")
      item.put("sender", sender)
      item.put("body", body)
      item.put("received_at_ms", timestamp)

      if (!SmsReceiverModule.deliver(item)) {
        SmsQueue.enqueue(context.applicationContext, item)
      }
    }
  }

  /** A short, stable id so a retry maps to the same server row. */
  private fun fingerprint(sender: String, body: String): String {
    val digest = MessageDigest.getInstance("SHA-256").digest("$sender|$body".toByteArray())
    return digest.take(8).joinToString("") { "%02x".format(it) }
  }
}
