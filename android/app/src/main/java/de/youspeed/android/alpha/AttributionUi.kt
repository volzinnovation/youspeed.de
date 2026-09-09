package de.youspeed.android.alpha

import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun AttributionSheet(onDismiss: () -> Unit) {
    val context = LocalContext.current
    val catalog by produceState<Result<AttributionCatalog>?>(null, context) {
        value = withContext(Dispatchers.IO) {
            runCatching { context.assets.open(AttributionCatalog.ASSET_PATH).bufferedReader().use { AttributionCatalog.decode(it.readText()) } }
        }
    }
    var noticePath by rememberSaveable { mutableStateOf<String?>(null) }
    SheetScaffold(stringResource(R.string.credits_title), onDismiss, "attribution-sheet") {
        val loaded = catalog?.getOrNull()
        when {
            catalog == null -> CircularProgressIndicator()
            loaded == null -> Text(stringResource(R.string.credits_load_error), color = Color.Black)
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize().testTag("attribution-list"),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                item {
                    Text(stringResource(R.string.credits_intro), color = Color.Black)
                    Text(stringResource(R.string.credits_reviewed, loaded.reviewedAt), style = MaterialTheme.typography.bodySmall, color = Color.DarkGray)
                }
                item {
                    Column {
                        AttributionCatalog.NOTICE_PATHS.forEach { path ->
                            OutlinedButton(onClick = { noticePath = path }, modifier = Modifier.fillMaxWidth().testTag("notice-${path.substringBefore('/')}")) {
                                Text(noticeTitle(path))
                            }
                        }
                    }
                }
                AttributionCatalog.CATEGORIES.forEach { category ->
                    val entries = loaded.entries.filter { it.category == category }
                    if (entries.isNotEmpty()) {
                        item(key = "category-$category") {
                            Text(categoryTitle(category), color = Color.Black, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 8.dp))
                        }
                        items(entries, key = { it.id }) { entry -> AttributionCard(entry) }
                    }
                }
            }
        }
    }
    noticePath?.let { path -> AttributionNoticeSheet(path, onDismiss = { noticePath = null }) }
}

@Composable
private fun AttributionCard(entry: AttributionEntry) {
    var expanded by rememberSaveable(entry.id) { mutableStateOf(false) }
    Card(colors = CardDefaults.cardColors(containerColor = Color.White), modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Column(
                modifier = Modifier.fillMaxWidth().clickable(role = Role.Button) { expanded = !expanded }.testTag("credit-${entry.id}"),
            ) {
                Text(entry.title, fontWeight = FontWeight.Bold, color = Color.Black)
                Text(entry.license, color = Color.DarkGray, style = MaterialTheme.typography.bodySmall)
                Text(stringResource(if (expanded) R.string.credits_hide_details else R.string.credits_show_details), color = Color(0xFF095484))
            }
            if (expanded) {
                SelectionContainer {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(stringResource(R.string.credits_attribution, entry.attribution), color = Color.Black)
                        Text(stringResource(R.string.credits_changes, entry.changes), color = Color.Black)
                    }
                }
                AttributionLink(stringResource(R.string.credits_source_link), entry.sourceUrl, "source-${entry.id}")
                AttributionLink(stringResource(R.string.credits_license_link), entry.licenseUrl, "license-${entry.id}")
            }
        }
    }
}

@Composable
private fun AttributionLink(label: String, url: String, tag: String) {
    val handler = LocalUriHandler.current
    val context = LocalContext.current
    val error = stringResource(R.string.credits_link_error)
    TextButton(onClick = {
        runCatching { handler.openUri(url) }.onFailure { Toast.makeText(context, error, Toast.LENGTH_LONG).show() }
    }, modifier = Modifier.testTag(tag)) { Text(label) }
}

@Composable
private fun AttributionNoticeSheet(path: String, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val text by produceState<Result<String>?>(null, path, context) {
        value = withContext(Dispatchers.IO) {
            runCatching { context.assets.open(path).bufferedReader().use { it.readText() }.also { require(it.isNotBlank()) } }
        }
    }
    SheetScaffold(noticeTitle(path), onDismiss, "attribution-notice-sheet") {
        val loaded = text?.getOrNull()
        when {
            text == null -> CircularProgressIndicator()
            loaded == null -> Text(stringResource(R.string.credits_load_error), color = Color.Black)
            else -> SelectionContainer {
                LazyColumn(modifier = Modifier.fillMaxSize().testTag("attribution-notice-text"), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(loaded.split("\n\n")) { paragraph -> Text(paragraph, color = Color.Black, style = MaterialTheme.typography.bodyMedium) }
                }
            }
        }
    }
}

@Composable
private fun noticeTitle(path: String): String = stringResource(when (path) {
    AttributionCatalog.MODEL_NOTICES -> R.string.credits_model_notices
    AttributionCatalog.SPEECH_NOTICES -> R.string.credits_speech_notices
    else -> R.string.credits_full_notices
})

@Composable
private fun categoryTitle(category: String): String = stringResource(when (category) {
    "data" -> R.string.credits_category_data
    "software" -> R.string.credits_category_software
    "model" -> R.string.credits_category_model
    "sign" -> R.string.credits_category_sign
    else -> R.string.credits_category_reference
})
