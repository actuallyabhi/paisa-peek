package app.paisapeek

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        // A long SMS arrives as several parts; join them per sender.
        Telephony.Sms.Intents.getMessagesFromIntent(intent)
            .groupBy { it.originatingAddress.orEmpty() }
            .forEach { (sender, parts) ->
                enqueueIngest(context, sender, parts.joinToString("") { it.messageBody.orEmpty() }, parts.first().timestampMillis)
            }
    }
}

/** Queues one SMS for upload (retried until it goes through). Also used by the debug-only fake-SMS hook. */
fun enqueueIngest(context: Context, sender: String, text: String, ts: Long) {
    // Banks send from alphanumeric headers (VM-HDFCBK); skip personal numbers so
    // private chats never leave the phone. The server drops OTPs and offers.
    if (Prefs.token(context) == null || sender.none { it.isLetter() }) return
    val work = OneTimeWorkRequestBuilder<IngestWorker>()
        .setInputData(workDataOf("sender" to sender, "text" to text, "ts" to ts))
        .setConstraints(Constraints(requiredNetworkType = NetworkType.CONNECTED))
        .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
        .build()
    WorkManager.getInstance(context).enqueue(work)
}

/** POSTs one SMS to /api/ingest/sms. Retries are safe: the server merges duplicates. */
class IngestWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        if (Prefs.token(applicationContext) == null) return Result.failure()
        val body = JSONObject()
            .put("sender", inputData.getString("sender"))
            .put("text", inputData.getString("text"))
            .put("ts", inputData.getLong("ts", 0))
        val res = try {
            api(applicationContext, "ingest/sms", body)
        } catch (e: java.io.IOException) {
            return Result.retry()
        }
        return when (res.code) {
            in 200..299 -> {
                res.json.optJSONObject("txn")?.let { Notify.newTxn(applicationContext, Txn(it)) }
                Result.success()
            }
            408, 429 -> Result.retry()
            in 400..499 -> Result.failure() // bad token or payload; retrying won't help
            else -> Result.retry()
        }
    }
}
