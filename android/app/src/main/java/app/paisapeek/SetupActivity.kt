package app.paisapeek

import android.Manifest
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeFlexibleTopAppBar
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import kotlinx.coroutines.launch

/** First-run setup (and "SMS setup" from the launcher shortcut): paste the link, test it, allow access. */
class SetupActivity : ComponentActivity() {
    override fun attachBaseContext(newBase: android.content.Context) = super.attachBaseContext(localized(newBase))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        edgeToEdge()
        val saved = Prefs.base(this)?.let { b -> Prefs.savedToken(this)?.let { "$b/api/ingest/sms?token=$it" } ?: b }.orEmpty()
        setContent {
            PaisapeekTheme {
                SetupScreen(saved, canGoBack = Prefs.base(this) != null, onBack = ::finish) { link ->
                    Prefs.save(this, link.base, link.token)
                    startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
                    finish()
                }
            }
        }
    }
}

/** The pasted link split into the server address and the SMS token (the token is optional). */
private data class Link(val base: String, val token: String?)

private fun parse(text: String): Link? {
    val uri = Uri.parse(text.trim())
    if (uri.scheme !in setOf("http", "https") || uri.host.isNullOrEmpty()) return null
    return Link("${uri.scheme}://${uri.encodedAuthority}", uri.getQueryParameter("token")?.takeIf { it.isNotBlank() })
}

private enum class Tone { Good, Warn, Bad }

/** Plain-words answer for "Test connection", so people know exactly what to fix. */
private suspend fun check(context: android.content.Context, link: Link): Pair<Tone, String> = try {
    val r = api(context, "inbox", base = link.base, token = link.token)
    when {
        r.ok -> Tone.Good to context.getString(R.string.test_ok)
        r.code == 401 && link.token == null -> Tone.Warn to context.getString(R.string.test_no_token)
        r.code == 401 -> Tone.Bad to context.getString(R.string.test_bad_token)
        r.code == 404 -> Tone.Warn to context.getString(R.string.test_outdated)
        else -> Tone.Bad to context.getString(R.string.test_error, r.code)
    }
} catch (e: java.io.IOException) {
    Tone.Bad to context.getString(R.string.test_unreachable)
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
private fun SetupScreen(initial: String, canGoBack: Boolean, onBack: () -> Unit, onSave: (Link) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var text by rememberSaveable { mutableStateOf(initial) }
    val link = parse(text)
    var testing by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<Pair<Tone, String>?>(null) }

    fun granted(p: String) = context.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED
    var sms by remember { mutableStateOf(granted(Manifest.permission.RECEIVE_SMS)) }
    var notify by remember { mutableStateOf(canNotify(context)) }
    var smsAsked by rememberSaveable { mutableStateOf(false) }
    // Coming back from system settings (e.g. "Allow restricted settings") should update the rows.
    LifecycleResumeEffect(Unit) {
        sms = granted(Manifest.permission.RECEIVE_SMS); notify = canNotify(context)
        onPauseOrDispose {}
    }
    val askSms = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { sms = it; smsAsked = true }
    val askNotify = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { notify = it }

    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        topBar = {
            LargeFlexibleTopAppBar(
                title = { Text(stringResource(R.string.connect_title)) },
                subtitle = { Text(stringResource(R.string.connect_subtitle)) },
                navigationIcon = {
                    if (canGoBack) IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back))
                    }
                },
                scrollBehavior = scroll,
            )
        },
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.surface) {
                Column(Modifier.navigationBarsPadding().imePadding().padding(16.dp)) {
                    Button(
                        onClick = { link?.let(onSave) }, enabled = link != null,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
                    ) { Text(stringResource(R.string.save_continue), style = MaterialTheme.typography.titleMedium) }
                }
            }
        },
    ) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Step(1, stringResource(R.string.step_paste), done = link?.token != null) {
                Text(stringResource(R.string.paste_where),
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedTextField(
                    value = text, onValueChange = { text = it; result = null },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.link_label)) },
                    placeholder = { Text("https://…/api/ingest/sms?token=…") },
                    leadingIcon = { Icon(Icons.Filled.Home, null) },
                    trailingIcon = {
                        if (text.isEmpty()) TextButton(onClick = {
                            context.getSystemService(ClipboardManager::class.java).primaryClip?.getItemAt(0)
                                ?.coerceToText(context)?.toString()?.let { text = it.trim(); result = null }
                        }) { Text(stringResource(R.string.paste)) }
                        else IconButton(onClick = { text = ""; result = null }) { Icon(Icons.Filled.Clear, stringResource(R.string.clear)) }
                    },
                    isError = text.isNotBlank() && link == null,
                    supportingText = if (text.isNotBlank() && link == null) {{ Text(stringResource(R.string.not_a_link)) }} else null,
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
                )
                AnimatedVisibility(link != null) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Pill(Icons.Filled.Home, Uri.parse(link?.base.orEmpty()).host.orEmpty(), Tone.Good)
                        if (link?.token != null) Pill(Icons.Filled.Lock, stringResource(R.string.token_found), Tone.Good)
                        else Pill(Icons.Filled.Warning, stringResource(R.string.no_token), Tone.Warn)
                    }
                }
                FilledTonalButton(
                    onClick = { link?.let { scope.launch { testing = true; result = check(context, it); testing = false } } },
                    enabled = link != null && !testing,
                ) {
                    if (testing) LoadingIndicator(Modifier.size(20.dp)) else Icon(Icons.Filled.Check, null, Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.width(ButtonDefaults.IconSpacing))
                    Text(stringResource(if (testing) R.string.testing else R.string.test_connection))
                }
                AnimatedContent(result, label = "test result") { r -> if (r != null) Notice(r.first, r.second) }
            }

            Step(2, stringResource(R.string.step_access), done = sms && notify) {
                Access(Icons.Filled.MailOutline, stringResource(R.string.sms_title), stringResource(R.string.sms_why),
                    sms) { askSms.launch(Manifest.permission.RECEIVE_SMS) }
                Access(Icons.Filled.Notifications, stringResource(R.string.notifications), stringResource(R.string.notify_why),
                    notify) { askNotify.launch(Manifest.permission.POST_NOTIFICATIONS) }
                // Sideloaded apps get SMS blocked as a "restricted setting" until it's allowed by hand.
                AnimatedVisibility(smsAsked && !sms) {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Notice(Tone.Warn, stringResource(R.string.sms_blocked))
                        TextButton(onClick = {
                            context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")))
                        }) { Text(stringResource(R.string.open_settings)) }
                    }
                }
            }
            Spacer(Modifier.heightIn(min = 8.dp))
        }
    }
}

/** A numbered step whose badge turns into a check once it's done. */
@Composable
private fun Step(number: Int, title: String, done: Boolean, content: @Composable () -> Unit) {
    val colors = MaterialTheme.colorScheme
    Card(shape = MaterialTheme.shapes.extraLarge, colors = CardDefaults.cardColors(containerColor = colors.surfaceContainerLow)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(shape = CircleShape, color = if (done) colors.primary else colors.surfaceContainerHighest, modifier = Modifier.size(36.dp)) {
                    Box(contentAlignment = Alignment.Center) {
                        AnimatedContent(done, label = "step badge") { d ->
                            if (d) Icon(Icons.Filled.Check, stringResource(R.string.done), tint = colors.onPrimary)
                            else Text("$number", fontWeight = FontWeight.Bold)
                        }
                    }
                }
                Spacer(Modifier.width(12.dp))
                Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            }
            content()
        }
    }
}

/** One permission: what it's for, and either a check or an Allow button. */
@Composable
private fun Access(icon: ImageVector, title: String, why: String, granted: Boolean, onAllow: () -> Unit) {
    val colors = MaterialTheme.colorScheme
    Surface(shape = MaterialTheme.shapes.large, color = colors.surfaceContainerHighest) {
        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, tint = colors.primary)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(why, style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant)
            }
            Spacer(Modifier.width(8.dp))
            AnimatedContent(granted, label = "permission") { g ->
                if (g) Icon(Icons.Filled.CheckCircle, stringResource(R.string.allowed), tint = toneColor(Tone.Good))
                else Button(onClick = onAllow) { Text(stringResource(R.string.allow)) }
            }
        }
    }
}

@Composable
private fun toneColor(tone: Tone): Color = when (tone) {
    Tone.Good -> goodColor()
    Tone.Warn -> Color(0xFFE0A100)
    Tone.Bad -> MaterialTheme.colorScheme.error
}

@Composable
private fun Pill(icon: ImageVector, label: String, tone: Tone) {
    Surface(shape = CircleShape, color = MaterialTheme.colorScheme.surfaceContainerHighest) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, Modifier.size(16.dp), tint = toneColor(tone))
            Spacer(Modifier.width(6.dp))
            Text(label, style = MaterialTheme.typography.labelLarge)
        }
    }
}

@Composable
private fun Notice(tone: Tone, message: String) {
    val color = toneColor(tone)
    Surface(shape = MaterialTheme.shapes.large, color = color.copy(alpha = 0.12f), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(when (tone) { Tone.Good -> Icons.Filled.CheckCircle; Tone.Warn -> Icons.Filled.Info; Tone.Bad -> Icons.Filled.Warning }, null, tint = color)
            Spacer(Modifier.width(10.dp))
            Text(message, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
