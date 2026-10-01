package app.paisapeek

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject

/** One notification per captured bank SMS, with Confirm / Ignore right on it. */
object Notify {
    private const val CHANNEL = "sms"

    private fun manager(c: Context): NotificationManager {
        val m = c.getSystemService(NotificationManager::class.java)
        m.createNotificationChannel(NotificationChannel(CHANNEL, localized(c).getString(R.string.channel_sms), NotificationManager.IMPORTANCE_DEFAULT))
        return m
    }

    private fun builder(c: Context) = Notification.Builder(c, CHANNEL)
        .setSmallIcon(R.drawable.ic_stat_rupee)
        .setAutoCancel(true)
        .setContentIntent(inboxIntent(c))

    private fun inboxIntent(c: Context) = PendingIntent.getActivity(c, 0, Intent(c, InboxActivity::class.java), PendingIntent.FLAG_IMMUTABLE)

    fun newTxn(context: Context, t: Txn) {
        val c = localized(context)
        // Without the notification permission notify() is a silent no-op; the Inbox still has it.
        val title = listOf(t.amount.ifEmpty { c.getString(R.string.amount_unreadable) }, t.merchant).filter { it.isNotEmpty() }.joinToString(" · ")
        // Confirm straight from the shade only when nothing is missing; a spend without a category needs the Inbox.
        val ready = t.amount.isNotEmpty() && (t.moneyIn || t.category != null)
        val b = builder(c)
            .setContentTitle(title)
            .setSubText(t.categoryName.ifEmpty { c.getString(if (t.moneyIn) R.string.money_in else R.string.no_category) }) // header; stays when expanded
            .setContentText(if (ready) t.rawText else c.getString(R.string.pick_category))
            .setStyle(Notification.BigTextStyle().bigText(t.rawText))
        b.addAction(if (ready) action(c, t.id, "confirmed", c.getString(R.string.confirm))
                    else Notification.Action.Builder(null, c.getString(R.string.review), inboxIntent(c)).build())
        b.addAction(action(c, t.id, "ignored", c.getString(R.string.ignore)))
        manager(c).notify(t.id, b.build())
    }

    fun failed(context: Context, id: Int, message: String) {
        val c = localized(context)
        manager(c).notify(id, builder(c).setContentTitle(c.getString(R.string.update_failed))
            .setContentText(c.getString(R.string.tap_to_review, message)).build())
    }

    fun test(c: Context, title: String, body: String) =
        manager(c).notify(0, builder(c).setContentTitle(title).setContentText(body).build()) // txn ids start at 1

    fun cancel(c: Context, id: Int) = manager(c).cancel(id)

    private fun action(c: Context, id: Int, status: String, label: String): Notification.Action {
        val intent = Intent(c, NotifyActionReceiver::class.java).putExtra("id", id).putExtra("status", status)
        val pi = PendingIntent.getBroadcast(c, id * 2 + if (status == "ignored") 1 else 0, intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Action.Builder(null, label, pi).build()
    }
}

/** Confirms as-is (the server's guessed category / kind) or ignores, then clears the notification. */
class NotifyActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra("id", 0)
        val status = intent.getStringExtra("status") ?: return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val res = api(context, "txns/$id/status", JSONObject().put("status", status))
                if (res.ok) Notify.cancel(context, id) else Notify.failed(context, id, res.error(localized(context)))
            } catch (e: java.io.IOException) {
                Notify.failed(context, id, localized(context).getString(R.string.no_connection))
            } finally {
                pending.finish()
            }
        }
    }
}
