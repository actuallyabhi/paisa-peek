package app.paisapeek

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.view.WindowInsets
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout

/** The existing PWA is the UI; this activity only hosts it. */
class MainActivity : Activity() {
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
        if (Prefs.token(this) != null && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2)
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.webViewClient = object : WebViewClient() {
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
        setContentView(FrameLayout(this).apply { addView(web) }.padForSystemBars(WindowInsets.Type.ime()))
        if (savedInstanceState == null) web.loadUrl(base + intent.getStringExtra("path").orEmpty()) else web.restoreState(savedInstanceState)
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

    @Deprecated("Fine for minSdk 26; predictive back can come later")
    override fun onBackPressed() {
        if (::web.isInitialized && web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    private companion object { const val FILE_REQUEST = 1 }
}

/** Android 15+ draws apps edge-to-edge; keep content clear of the status/nav bars and keyboard. */
fun <T : View> T.padForSystemBars(
    types: Int = WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or WindowInsets.Type.ime(),
): T = apply {
    setOnApplyWindowInsetsListener { v, insets ->
        val i = insets.getInsets(types)
        v.setPadding(i.left, i.top, i.right, i.bottom)
        insets
    }
}
