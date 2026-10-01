package app.paisapeek

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.animateContentSize
import androidx.compose.material3.ToggleButton
import androidx.compose.material3.ToggleButtonDefaults
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.animation.AnimatedContent
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Add
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeFlexibleTopAppBar
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.pulltorefresh.PullToRefreshDefaults
import androidx.compose.material3.pulltorefresh.rememberPullToRefreshState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Native review screen for bank SMS: replaces the web Inbox tab. */
class InboxActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            PaisapeekTheme {
                InboxScreen(onBack = ::finish, onEdit = { id ->
                    // The web edit page redirects back to /inbox/, which MainActivity sends here again.
                    startActivity(Intent(this, MainActivity::class.java).putExtra("path", "/txns/$id/?next=/inbox/")
                        .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP))
                    finish()
                })
            }
        }
    }
}

// Same palette as the site (ledger/tailwind.css), so web and native screens feel like one app.
private val Light = lightColorScheme(
    primary = Color(0xFFE4572E), onPrimary = Color(0xFFFFFAF3),
    primaryContainer = Color(0xFFFBE3D7), onPrimaryContainer = Color(0xFF231F1A),
    secondaryContainer = Color(0xFFFBE3D7), onSecondaryContainer = Color(0xFF231F1A),
    background = Color(0xFFF4EFE6), surface = Color(0xFFF4EFE6), onSurface = Color(0xFF231F1A),
    surfaceContainerLow = Color(0xFFFFFCF6), surfaceContainer = Color(0xFFFFFCF6),
    surfaceContainerHighest = Color(0xFFEBE4D6), onSurfaceVariant = Color(0xFF766D61),
    outline = Color(0xFFE2D9C8), outlineVariant = Color(0xFFE2D9C8), error = Color(0xFFC7343F),
)
private val Dark = darkColorScheme(
    primary = Color(0xFFFF7048), onPrimary = Color(0xFF1A0F0A),
    primaryContainer = Color(0xFF3D2319), onPrimaryContainer = Color(0xFFF2ECE1),
    secondaryContainer = Color(0xFF3D2319), onSecondaryContainer = Color(0xFFF2ECE1),
    background = Color(0xFF15130F), surface = Color(0xFF15130F), onSurface = Color(0xFFF2ECE1),
    surfaceContainerLow = Color(0xFF1F1C17), surfaceContainer = Color(0xFF1F1C17),
    surfaceContainerHighest = Color(0xFF2A2620), onSurfaceVariant = Color(0xFFA69D8E),
    outline = Color(0xFF37322A), outlineVariant = Color(0xFF37322A), error = Color(0xFFFF6B6B),
)
@Composable private fun goodColor() = if (isSystemInDarkTheme()) Color(0xFF4CC38A) else Color(0xFF1D8457)

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun PaisapeekTheme(content: @Composable () -> Unit) =
    MaterialExpressiveTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, motionScheme = MotionScheme.expressive(), content = content)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun InboxScreen(onBack: () -> Unit, onEdit: (Int) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbar = remember { SnackbarHostState() }
    val txns = remember { mutableStateListOf<Txn>() }
    val busy = remember { mutableStateListOf<Int>() }
    var categories by remember { mutableStateOf(listOf<Pair<Int, String>>()) }
    var kinds by remember { mutableStateOf(listOf<Pair<String, String>>()) }
    var parties by remember { mutableStateOf(listOf<String>()) }
    var loaded by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        try {
            val r = api(context, "inbox")
            if (!r.ok) { error = r.error; return }
            val j = r.json
            txns.clear()
            (0 until j.getJSONArray("txns").length()).forEach { txns += Txn(j.getJSONArray("txns").getJSONObject(it)) }
            categories = j.getJSONArray("categories").let { a -> (0 until a.length()).map { a.getJSONObject(it).run { getInt("id") to getString("name") } } }
            kinds = j.getJSONArray("money_in_kinds").let { a -> (0 until a.length()).map { a.getJSONObject(it).run { getString("id") to getString("name") } } }
            parties = j.getJSONArray("parties").let { a -> (0 until a.length()).map { a.getString(it) } }
            error = null
            loaded = true
        } catch (e: java.io.IOException) {
            error = "Can't reach your Paisapeek server."
        }
    }

    /** Confirm/ignore with Undo; the card comes back at its old spot if undone. */
    fun review(t: Txn, body: JSONObject, done: String) = scope.launch {
        busy += t.id
        try {
            val r = api(context, "txns/${t.id}/status", body)
            if (!r.ok) { snackbar.showSnackbar(r.error); return@launch }
            body.optString("party_name").trim().takeIf { it.isNotEmpty() && parties.none { p -> p.equals(it, true) } }
                ?.let { parties = parties + it }
            val index = txns.indexOf(t)
            txns.remove(t)
            Notify.cancel(context, t.id)
            if (snackbar.showSnackbar(done, "Undo", duration = SnackbarDuration.Short) == SnackbarResult.ActionPerformed &&
                api(context, "txns/${t.id}/status", JSONObject().put("status", "pending")).ok
            ) txns.add(index.coerceAtMost(txns.size), t)
        } catch (e: java.io.IOException) {
            snackbar.showSnackbar("No connection. Try again.")
        } finally {
            busy -= t.id
        }
    }

    LaunchedEffect(Unit) { load() }

    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        topBar = {
            LargeFlexibleTopAppBar(
                title = { Text("Review inbox") },
                subtitle = { if (loaded) Text(if (txns.isEmpty()) "Nothing waiting" else "${txns.size} waiting") },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
                scrollBehavior = scroll,
            )
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        val pull = rememberPullToRefreshState()
        PullToRefreshBox(
            isRefreshing = refreshing,
            onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } },
            state = pull,
            modifier = Modifier.padding(padding).fillMaxSize(),
            indicator = { PullToRefreshDefaults.LoadingIndicator(state = pull, isRefreshing = refreshing, modifier = Modifier.align(Alignment.TopCenter)) },
        ) {
            when {
                !loaded && error == null -> LoadingIndicator(Modifier.align(Alignment.Center).size(64.dp))
                !loaded -> Message("⚠️", error!!, "Make sure the server is running and the URL in SMS setup is right.") {
                    Button(onClick = { error = null; scope.launch { load() } }) { Text("Try again") }
                }
                txns.isEmpty() -> Message("📭", "All caught up.", "New bank SMS show up here and as notifications.")
                else -> LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(txns, key = { it.id }) { t ->
                        TxnCard(
                            t, categories, kinds, parties, busy = t.id in busy,
                            onConfirm = { body -> review(t, body.put("status", "confirmed"), "Confirmed") },
                            onIgnore = { review(t, JSONObject().put("status", "ignored"), "Ignored") },
                            onEdit = { onEdit(t.id) },
                            modifier = Modifier.animateItem(),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun Message(emoji: String, title: String, body: String, action: @Composable () -> Unit = {}) {
    // A LazyColumn so pull-to-refresh still works on the empty and error states.
    LazyColumn(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        item {
            Column(Modifier.padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(emoji, style = MaterialTheme.typography.displayMedium)
                Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
                Text(body, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                action()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun TxnCard(
    t: Txn, categories: List<Pair<Int, String>>, kinds: List<Pair<String, String>>, parties: List<String>, busy: Boolean,
    onConfirm: (JSONObject) -> Unit, onIgnore: () -> Unit, onEdit: () -> Unit, modifier: Modifier,
) {
    var expanded by rememberSaveable(t.id) { mutableStateOf(false) }
    var category by rememberSaveable(t.id) { mutableStateOf(t.category) }
    var kind by rememberSaveable(t.id) { mutableStateOf(t.kind) }
    var party by rememberSaveable(t.id) { mutableStateOf(t.partyName) }
    val needsParty = t.moneyIn && kind != "income" && party.isBlank()
    val colors = MaterialTheme.colorScheme

    Card(modifier.fillMaxWidth(), shape = MaterialTheme.shapes.extraLarge,
        colors = CardDefaults.cardColors(containerColor = colors.surfaceContainerLow)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Text(t.amount.ifEmpty { "Couldn't read amount" }, style = MaterialTheme.typography.headlineMedium,
                        fontWeight = FontWeight.Bold, color = if (t.moneyIn) goodColor() else colors.onSurface)
                    if (t.merchant.isNotEmpty()) Text(t.merchant, style = MaterialTheme.typography.titleMedium)
                    Text(listOf(t.whenText, t.account).filter { it.isNotEmpty() }.joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant)
                }
                Surface(shape = MaterialTheme.shapes.small, color = colors.surfaceContainerHighest) {
                    Text(t.source.uppercase(), Modifier.padding(horizontal = 8.dp, vertical = 2.dp), style = MaterialTheme.typography.labelSmall)
                }
            }

            // The original SMS, two lines until tapped.
            Surface(onClick = { expanded = !expanded }, shape = MaterialTheme.shapes.large, color = colors.surfaceContainerHighest,
                modifier = Modifier.fillMaxWidth().animateContentSize()) {
                Text(t.rawText, Modifier.padding(12.dp), style = MaterialTheme.typography.bodySmall, color = colors.onSurfaceVariant,
                    maxLines = if (expanded) Int.MAX_VALUE else 2, overflow = TextOverflow.Ellipsis)
            }

            if (t.amount.isNotEmpty()) {
                if (t.moneyIn) {
                    KindPicker(kinds, kind) { kind = it }
                    PersonField(party, { party = it }, parties, hint = t.merchant, required = kind != "income", isError = needsParty)
                } else {
                    CategoryPicker(categories, category) { category = it }
                }
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = {
                        onConfirm(if (t.moneyIn) JSONObject().put("kind", kind).put("party_name", party)
                                  else JSONObject().apply { category?.let { put("category", it) } })
                    },
                    enabled = t.amount.isNotEmpty() && !busy && !needsParty,
                    contentPadding = ButtonDefaults.ButtonWithIconContentPadding,
                ) {
                    Icon(Icons.Filled.Check, null, Modifier.size(ButtonDefaults.IconSize))
                    Spacer(Modifier.width(ButtonDefaults.IconSpacing))
                    Text("Confirm")
                }
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onEdit, enabled = !busy) { Text("Edit") }
                TextButton(onClick = onIgnore, enabled = !busy) { Text("Ignore", color = colors.onSurfaceVariant) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CategoryPicker(categories: List<Pair<Int, String>>, selected: Int?, onPick: (Int) -> Unit) {
    var open by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(open, { open = it }) {
        OutlinedTextField(
            value = categories.firstOrNull { it.first == selected }?.second ?: "", onValueChange = {}, readOnly = true,
            label = { Text("Category") }, trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(open) },
            modifier = Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(open, { open = false }) {
            categories.forEach { (id, name) -> DropdownMenuItem(text = { Text(name) }, onClick = { onPick(id); open = false }) }
        }
    }
}

/** Icon + one-line meaning for each money-in kind; the names themselves come (translated) from the server. */
private val KIND_HELP = mapOf(
    "income" to ("💰" to "Salary, refund, cashback. Nobody owes anyone."),
    "repay_in" to ("↩️" to "Someone paid back money you lent them."),
    "borrow" to ("🤝" to "You borrowed this, so now you owe them."),
)

/** Compact toggle buttons that wrap instead of truncating; only the picked one's meaning is spelled out below. */
@OptIn(ExperimentalMaterial3ExpressiveApi::class, ExperimentalLayoutApi::class)
@Composable
private fun KindPicker(kinds: List<Pair<String, String>>, selected: String, onPick: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            kinds.forEach { (id, label) ->
                ToggleButton(
                    checked = id == selected, onCheckedChange = { onPick(id) },
                    modifier = Modifier.semantics { role = Role.RadioButton },
                    // Tonal fill so unpicked options still read as buttons, not plain text.
                    colors = ToggleButtonDefaults.toggleButtonColors(
                        containerColor = MaterialTheme.colorScheme.surfaceContainerHighest,
                        contentColor = MaterialTheme.colorScheme.onSurface,
                    ),
                ) { Text("${KIND_HELP[id]?.first ?: "💸"}  $label") }
            }
        }
        AnimatedContent(KIND_HELP[selected]?.second.orEmpty(), label = "kind help") {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Name field that suggests existing people as you type, or offers to add a new one (created on confirm). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PersonField(value: String, onChange: (String) -> Unit, parties: List<String>, hint: String, required: Boolean, isError: Boolean) {
    var open by remember { mutableStateOf(false) }
    val typed = value.trim()
    val matches = parties.filter { typed.isEmpty() || it.contains(typed, ignoreCase = true) }.take(6)
    val isNew = typed.isNotEmpty() && parties.none { it.equals(typed, ignoreCase = true) }
    ExposedDropdownMenuBox(open && (matches.isNotEmpty() || isNew), { open = it }) {
        OutlinedTextField(
            value, { onChange(it); open = true },
            Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryEditable).fillMaxWidth(),
            label = { Text(if (required) "From whom?" else "From whom? (optional)") },
            leadingIcon = { Icon(Icons.Filled.Person, null) },
            placeholder = if (hint.isNotEmpty()) {{ Text(hint) }} else null,
            isError = isError, singleLine = true,
            supportingText = when {
                isError -> {{ Text("Needed for borrowed or repaid money") }}
                isNew -> {{ Text("New person, added when you confirm") }}
                else -> null
            },
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Words),
        )
        ExposedDropdownMenu(open && (matches.isNotEmpty() || isNew), { open = false }) {
            matches.forEach { name ->
                DropdownMenuItem(text = { Text(name) }, leadingIcon = { Icon(Icons.Filled.Person, null) },
                    onClick = { onChange(name); open = false })
            }
            if (isNew) DropdownMenuItem(
                text = { Text("Add “$typed” as a new person", fontWeight = FontWeight.SemiBold) },
                leadingIcon = { Icon(Icons.Filled.Add, null) },
                onClick = { onChange(typed); open = false },
            )
        }
    }
}
