package com.financeai.sms

import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap
import com.facebook.react.modules.core.DeviceEventManagerModule
import org.json.JSONObject

/**
 * Bridge between [SmsReceiver] and JavaScript.
 *
 * - `deliver` is called from the receiver (a non-JS thread) and emits an
 *   `onSmsReceived` event when a React instance is attached.
 * - `getPendingMessages` drains whatever was captured while JS was not running.
 *
 * `addListener`/`removeListeners` exist because `NativeEventEmitter` calls them
 * on the native module; without them the emitter warns and events are dropped.
 */
class SmsReceiverModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  @Volatile
  private var listenerCount = 0

  init {
    instance = this
  }

  override fun getName(): String = NAME

  @ReactMethod
  fun addListener(eventName: String) {
    if (eventName == EVENT_NAME) listenerCount += 1
  }

  @ReactMethod
  fun removeListeners(count: Int) {
    if (count > 0) listenerCount = (listenerCount - count).coerceAtLeast(0)
  }

  /** Whether this build can detect SMS at all (Android with the receiver present). */
  @ReactMethod
  fun isSupported(promise: Promise) {
    promise.resolve(true)
  }

  /** Messages captured while no React instance was attached. */
  @ReactMethod
  fun getPendingMessages(promise: Promise) {
    val pending = SmsQueue.drain(reactContext)
    val result = Arguments.createArray()
    for (i in 0 until pending.length()) {
      pending.optJSONObject(i)?.let { result.pushMap(toMap(it)) }
    }
    promise.resolve(result)
  }

  override fun invalidate() {
    if (instance === this) instance = null
    super.invalidate()
  }

  companion object {
    const val NAME = "SmsReceiver"
    const val EVENT_NAME = "onSmsReceived"

    @Volatile
    private var instance: SmsReceiverModule? = null

    /** Emits to JS if it is listening; returns false so the caller can persist instead. */
    fun deliver(item: JSONObject): Boolean {
      val module = instance ?: return false
      if (module.listenerCount <= 0) return false
      return try {
        module.reactContext
          .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
          .emit(EVENT_NAME, toMap(item))
        true
      } catch (e: Exception) {
        // No JS runtime, or it is tearing down: let the caller queue the message.
        false
      }
    }

    private fun toMap(item: JSONObject): WritableMap {
      val map = Arguments.createMap()
      map.putString("client_msg_id", item.optString("client_msg_id"))
      map.putString("sender", item.optString("sender"))
      map.putString("body", item.optString("body"))
      map.putDouble("received_at_ms", item.optDouble("received_at_ms", 0.0))
      return map
    }
  }
}
