package app.paisapeek

import android.Manifest
import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.addCallback
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat

/** The existing PWA is the UI; this activity only hosts it. */
class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private var pendingFiles: ValueCallback<Array<Uri>>? = null
    private var reloadOnReturn = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val base = Prefs.base(this) ?: return run {
            startActivity(Intent(this, SetupActivity::class.java)); finish()
        }
        // People who set up before notifications existed were never asked.
        if (Prefs.token(this) != null && !canNotify(this))
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        // Android's overscroll stretches the whole WebView, fixed header and bottom nav included, so the app
        // wobbles. Chrome only stretches the page content, which is why the PWA felt solid.
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isVerticalScrollBarEnabled = false // an installed PWA shows none either
        web.isHorizontalScrollBarEnabled = false
        applyTheme(isDark(this)) // last choice the site reported, else the phone's; the page corrects it on load
        // The site calls PaisapeekApp.theme("dark"|"light") when it applies or toggles its theme (base.html).
        web.addJavascriptInterface(object {
            @JavascriptInterface fun theme(t: String) {
                Prefs.saveTheme(this@MainActivity, t) // the native Inbox/setup screens use it too
                runOnUiThread { applyTheme(t == "dark") }
            }

            // More → Notifications → Send a test. WebView has no web push, so the app shows it natively.
            // False (and asks for the permission) when notifications are off.
            @JavascriptInterface fun notify(title: String, body: String): Boolean {
                if (!canNotify(this@MainActivity)) {
                    runOnUiThread { requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2) }
                    return false
                }
                Notify.test(this@MainActivity, title, body)
                return true
            }
        }, "PaisapeekApp")
        // Back walks the page history first; with nothing left it falls through to the system (predictive back home).
        val back = onBackPressedDispatcher.addCallback(this, enabled = false) { web.goBack() }
        web.webViewClient = object : WebViewClient() {
            override fun doUpdateVisitedHistory(view: WebView, url: String?, isReload: Boolean) {
                back.isEnabled = view.canGoBack()
            }

            // The language picked on the site lives in its django_language cookie; native screens follow it.
            override fun onPageFinished(view: WebView, url: String?) {
                val lang = CookieManager.getInstance().getCookie(base)?.split(";")
                    ?.map { it.trim() }?.firstOrNull { it.startsWith("django_language=") }?.substringAfter("=")
                if (lang != Prefs.lang(this@MainActivity)) Prefs.saveLang(this@MainActivity, lang)
            }

            // Stay in-app on our server; open everything else (GitHub link etc.) in the browser.
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.toString().startsWith(base) && request.url.path?.trimEnd('/') == "/inbox") {
                    // The Inbox tab is native. After a web edit redirects here, step back off the edit page.
                    if (request.isRedirect && view.canGoBack()) view.goBack()
                    reloadOnReturn = true // refresh the pending badge when we come back
                    startActivity(Intent(this@MainActivity, InboxActivity::class.java))
                    return true
                }
                if (request.url.toString().startsWith(base)) return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }
        }
        // Backup / CSV export / sample CSV: WebView ignores downloads, so hand them to the system with our login cookie.
        web.setDownloadListener { url, userAgent, disposition, mime, _ ->
            if (Build.VERSION.SDK_INT < 29 && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE), 3) // tap Download again after allowing
                return@setDownloadListener
            }
            val name = URLUtil.guessFileName(url, disposition, mime)
            getSystemService(DownloadManager::class.java).enqueue(DownloadManager.Request(Uri.parse(url))
                .addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url))
                .addRequestHeader("User-Agent", userAgent)
                .setMimeType(mime)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name))
            Toast.makeText(this, getString(R.string.downloading, name), Toast.LENGTH_SHORT).show()
        }
        web.webChromeClient = object : WebChromeClient() {
            // <input type="file"> for CSV import and backup restore.
            override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                pendingFiles?.onReceiveValue(null)
                pendingFiles = callback
                startActivityForResult(params.createIntent(), FILE_REQUEST)
                return true
            }
        }
        // The site pads its header/nav with env(safe-area-inset-*), so only make room for the keyboard.
        // WebView ignores its own padding, so inset a container instead.
        setContentView(FrameLayout(this).apply { addView(web) }.padForSystemBars(WindowInsetsCompat.Type.ime()))
        if (savedInstanceState == null) web.loadUrl(base + intent.getStringExtra("path").orEmpty()) else web.restoreState(savedInstanceState)
    }

    /**
     * Like Chrome's theme-color for an installed PWA: paint behind the page in the site's background colour
     * (no white flash between pages) and keep the status/nav bar icons readable on it.
     */
    private fun applyTheme(dark: Boolean) {
        val paper = if (dark) 0xFF15130F.toInt() else 0xFFF4EFE6.toInt() // --paper in ledger/tailwind.css
        web.setBackgroundColor(paper)
        window.decorView.setBackgroundColor(paper)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            isAppearanceLightStatusBars = !dark
            isAppearanceLightNavigationBars = !dark
        }
    }

    /** InboxActivity's Edit opens a web page here. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra("path")?.let { web.loadUrl(Prefs.base(this) + it) }
    }

    override fun onRestart() {
        super.onRestart()
        if (reloadOnReturn && ::web.isInitialized) web.reload()
        reloadOnReturn = false
    }

    @Deprecated("Activity result API needs AndroidX; not worth a dependency here")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != FILE_REQUEST) return super.onActivityResult(requestCode, resultCode, data)
        pendingFiles?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data))
        pendingFiles = null
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        if (::web.isInitialized) web.saveState(outState)
    }


    private companion object { const val FILE_REQUEST = 1 }
}

/** Android 15+ draws apps edge-to-edge; keep content clear of the status/nav bars and keyboard. (Compat: minSdk 26.) */
fun <T : View> T.padForSystemBars(
    types: Int = WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime(),
): T = apply {
    ViewCompat.setOnApplyWindowInsetsListener(this) { v, insets ->
        val i = insets.getInsets(types)
        v.setPadding(i.left, i.top, i.right, i.bottom)
        insets
    }
}
