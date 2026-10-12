package com.financeai.sms

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * On-device holding area for SMS messages that arrived while the JavaScript
 * runtime was not alive.
 *
 * Android delivers `SMS_RECEIVED` to this app's manifest receiver even when the
 * process has no running React instance, so the receiver cannot assume it can
 * hand a message straight to JS. Anything it cannot deliver is written here and
 * drained by [SmsReceiverModule.getPendingMessages] on the next launch.
 *
 * This file lives in the app's private `filesDir`: it is never uploaded, never
 * logged, and only ever read back by this app.
 */
internal object SmsQueue {

  private const val FILE_NAME = "sms_pending.json"

  // A misbehaving device must not be able to grow this without bound; older
  // entries are dropped rather than letting the file grow forever.
  private const val MAX_QUEUE = 200

  private fun file(context: Context): File = File(context.filesDir, FILE_NAME)

  @Synchronized
  fun enqueue(context: Context, item: JSONObject) {
    val current = read(context)
    current.put(item)

    val trimmed = JSONArray()
    val start = maxOf(0, current.length() - MAX_QUEUE)
    for (i in start until current.length()) {
      trimmed.put(current.get(i))
    }
    write(context, trimmed)
  }

  /** Returns every queued message and clears the store in the same critical section. */
  @Synchronized
  fun drain(context: Context): JSONArray {
    val current = read(context)
    write(context, JSONArray())
    return current
  }

  /** Number of queued messages, for diagnostics. */
  @Synchronized
  fun size(context: Context): Int = read(context).length()

  private fun read(context: Context): JSONArray {
    val handle = file(context)
    if (!handle.exists()) return JSONArray()
    return try {
      JSONArray(handle.readText())
    } catch (e: Exception) {
      // A corrupt file must not crash the receiver; start from empty.
      JSONArray()
    }
  }

  private fun write(context: Context, array: JSONArray) {
    try {
      file(context).writeText(array.toString())
    } catch (e: Exception) {
      // Best effort. The broadcast must never crash the app process.
    }
  }
}
