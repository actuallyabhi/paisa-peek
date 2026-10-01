package app.paisapeek

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Debug builds only. adb can't fake an incoming SMS on a real phone, so this feeds one into the same
 * upload → notification path:
 *   adb shell am broadcast -n app.paisapeek/.FakeSmsReceiver --es sender VM-HDFCBK --es text "Spent Rs.450 ..."
 */
class FakeSmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) =
        enqueueIngest(context, intent.getStringExtra("sender").orEmpty(), intent.getStringExtra("text").orEmpty(), System.currentTimeMillis())
}
