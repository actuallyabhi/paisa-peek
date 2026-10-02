package app.paisapeek

import android.content.Context
import android.webkit.CookieManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Notifications need asking only on Android 13+; before that they're allowed by default. */
fun canNotify(c: Context) = android.os.Build.VERSION.SDK_INT < 33 ||
    c.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) == android.content.pm.PackageManager.PERMISSION_GRANTED

/** Server URL + API token, pasted once from More → SMS auto-capture. */
object Prefs {
    private fun prefs(c: Context) = c.getSharedPreferences("paisapeek", Context.MODE_PRIVATE)
    fun base(c: Context) = prefs(c).getString("base", null)
    /** The SMS token, or null while logged out of the site, so SMS capture and the native Inbox stop with it. */
    fun token(c: Context) = savedToken(c).takeUnless { prefs(c).getBoolean("signed_out", false) }
    fun savedToken(c: Context) = prefs(c).getString("token", null) // kept through a logout, for setup to show
    fun saveSignedIn(c: Context, yes: Boolean) = prefs(c).edit().putBoolean("signed_out", !yes).apply()
    fun save(c: Context, base: String, token: String?) =
        prefs(c).edit().putString("base", base).putString("token", token).apply()

    // The site's own choices, reported by MainActivity, so native screens match them (null = follow the phone).
    fun theme(c: Context) = prefs(c).getString("theme", null) // "dark" / "light"
    fun lang(c: Context) = prefs(c).getString("lang", null)   // django_language cookie: "en" / "hi" / "hi-latn"
    fun saveTheme(c: Context, theme: String) = prefs(c).edit().putString("theme", theme).apply()
    fun saveLang(c: Context, lang: String?) = prefs(c).edit().putString("lang", lang).apply()
}

fun isDark(c: Context) = Prefs.theme(c)?.let { it == "dark" }
    ?: (c.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK == android.content.res.Configuration.UI_MODE_NIGHT_YES)

/** [c] in the language picked on the site (values-hi / values-b+hi+Latn), or unchanged to follow the phone. */
fun localized(c: Context): Context {
    val tag = when (Prefs.lang(c)) { "en" -> "en"; "hi" -> "hi"; "hi-latn" -> "hi-Latn"; else -> return c }
    val config = android.content.res.Configuration(c.resources.configuration)
    config.setLocale(java.util.Locale.forLanguageTag(tag))
    return c.createConfigurationContext(config)
}

class ApiResult(val code: Int, val json: JSONObject) {
    val ok get() = code in 200..299
    /** Ninja puts error messages in "detail" (already in the site's language). */
    fun error(c: Context): String = json.optString("detail").ifEmpty {
        if (code == 404) c.getString(R.string.server_outdated) else c.getString(R.string.server_error, code)
    }
}

/**
 * Calls /api/<path> with the token. Throws IOException when the server can't be reached.
 * [base]/[token] default to the saved ones; setup passes a link that isn't saved yet to test it.
 */
suspend fun api(
    context: Context, path: String, body: JSONObject? = null,
    base: String? = Prefs.base(context), token: String? = Prefs.token(context),
): ApiResult = withContext(Dispatchers.IO) {
    if (base == null) throw java.io.IOException("Not set up")
    val conn = URL("$base/api/$path").openConnection() as HttpURLConnection
    try {
        conn.connectTimeout = 15_000
        conn.readTimeout = 15_000
        if (token != null) conn.setRequestProperty("Authorization", "Bearer $token")
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
