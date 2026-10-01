package app.paisapeek

import android.content.Context
import android.webkit.CookieManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Server URL + API token, pasted once from More → SMS auto-capture. */
object Prefs {
    private fun prefs(c: Context) = c.getSharedPreferences("paisapeek", Context.MODE_PRIVATE)
    fun base(c: Context) = prefs(c).getString("base", null)
    fun token(c: Context) = prefs(c).getString("token", null)
    fun save(c: Context, base: String, token: String?) =
        prefs(c).edit().putString("base", base).putString("token", token).apply()
}

class ApiResult(val code: Int, val json: JSONObject) {
    val ok get() = code in 200..299
    /** Ninja puts error messages in "detail". */
    val error get() = json.optString("detail").ifEmpty { "Server said $code" }
}

/** Calls /api/<path> with the token. Throws IOException when the server can't be reached. */
suspend fun api(context: Context, path: String, body: JSONObject? = null): ApiResult = withContext(Dispatchers.IO) {
    val base = Prefs.base(context) ?: throw java.io.IOException("Not set up")
    val conn = URL("$base/api/$path").openConnection() as HttpURLConnection
    try {
        conn.connectTimeout = 15_000
        conn.readTimeout = 15_000
        conn.setRequestProperty("Authorization", "Bearer ${Prefs.token(context)}")
        // The WebView's cookies carry the language picked on the site, so labels match it.
        runCatching { CookieManager.getInstance().getCookie(base) }.getOrNull()?.let { conn.setRequestProperty("Cookie", it) }
        if (body != null) {
            conn.requestMethod = "POST"
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
        }
        val code = conn.responseCode
        val text = (if (code < 400) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
        ApiResult(code, runCatching { JSONObject(text) }.getOrDefault(JSONObject()))
    } finally {
        conn.disconnect()
    }
}

/** A pending transaction from /api/inbox (display strings come pre-formatted from the server). */
data class Txn(
    val id: Int, val amount: String, val moneyIn: Boolean, val merchant: String, val whenText: String,
    val account: String, val source: String, val rawText: String, val kind: String,
    val category: Int?, val categoryName: String, val partyName: String,
) {
    constructor(j: JSONObject) : this(
        j.getInt("id"), j.optString("amount"), j.optBoolean("money_in"), j.optString("merchant"), j.optString("when"),
        j.optString("account"), j.optString("source"), j.optString("raw_text"), j.optString("kind"),
        if (j.isNull("category")) null else j.optInt("category"), j.optString("category_name"), j.optString("party_name"),
    )
}
