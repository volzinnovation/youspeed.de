package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.text.DateFormat
import java.util.Date
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

private const val INSPECTOR = "https://inspector.youspeed.de"
private const val FILES_API = "$INSPECTOR/inspector/api/files"

private data class InspectorFile(val id: String, val name: String, val kind: String, val displayName: String)
private data class InspectorLibrary(
    val files: List<InspectorFile>, val examples: List<InspectorFile>, val storage: Boolean, val comparison: Boolean, val tripUpload: Boolean,
)
private data class InspectorPreview(val file: InspectorFile, val html: String?, val text: String?, val truncated: Boolean)
private data class InspectorTrip(val id: String, val label: String)
private data class InspectorSelection(val uri: Uri, val name: String)
private class InspectorRequestError(val messageRes: Int) : IOException()

private fun JSONObject.fileList(field: String): List<InspectorFile> {
    val entries = optJSONArray(field) ?: JSONArray()
    return List(entries.length()) { index ->
        val row = entries.getJSONObject(index)
        val name = row.getString("name")
        InspectorFile(row.getString("id"), name, row.getString("kind"), row.optString("title", name))
    }
}

private fun readInspectorBytes(input: InputStream, limit: Int): ByteArray {
    val output = ByteArrayOutputStream()
    val buffer = ByteArray(16384)
    while (true) {
        val count = input.read(buffer)
        if (count < 0) break
        if (output.size() + count > limit) throw InspectorRequestError(R.string.inspector_files_size)
        output.write(buffer, 0, count)
    }
    return output.toByteArray()
}

private object InspectorFilesClient {
    suspend fun list(token: String): InspectorLibrary = request(token).let {
        InspectorLibrary(it.fileList("files"), it.fileList("examples"), it.getBoolean("storage"), it.getBoolean("comparison"), it.optBoolean("trip_upload"))
    }

    suspend fun preview(token: String, file: InspectorFile): InspectorPreview {
        require(file.id.matches(Regex("[a-f0-9]{32}|ss-r0[37]")))
        val result = request(token, "/${file.id}/${if (file.kind == "track") "comparison" else "preview"}")
        return InspectorPreview(file, result.optString("html").takeIf(String::isNotEmpty),
            result.optString("text"), result.optBoolean("truncated"))
    }

    suspend fun upload(context: Context, token: String, selection: InspectorSelection): InspectorFile {
        val extension = selection.name.substringAfterLast('.', "").lowercase()
        if (extension !in setOf("gpx", "log", "txt", "csv", "json", "jsonl", "ndjson")) {
            throw InspectorRequestError(R.string.inspector_files_type)
        }
        val maxBytes = (if (extension == "gpx") 2 else 16) * 1024 * 1024
        val body = withContext(Dispatchers.IO) {
            val input = if (selection.uri.scheme == "file") {
                File(requireNotNull(selection.uri.path)).inputStream()
            } else {
                context.contentResolver.openInputStream(selection.uri) ?: throw IOException("File unavailable")
            }
            input.use { readInspectorBytes(it, maxBytes) }
        }
        if (body.isEmpty()) throw InspectorRequestError(R.string.inspector_files_size)
        val result = request(token, body = body, name = selection.name)
        val name = result.getString("name")
        return InspectorFile(result.getString("id"), name, result.getString("kind"), name)
    }

    suspend fun uploadTrack(token: String, journal: TripJournal, id: String) {
        val body = withContext(Dispatchers.IO) {
            val root = journal.export(id)
            try {
                File(root, "track.gpx").inputStream().use { readInspectorBytes(it, 2 * 1024 * 1024) }
            } finally {
                root.deleteRecursively()
            }
        }
        if (body.isEmpty()) throw InspectorRequestError(R.string.inspector_files_size)
        val uploaded = request(token, body = body, name = "YouSpeed-$id.gpx")
        check(uploaded.getString("id").isNotBlank() && uploaded.getString("kind") == "track")
    }

    suspend fun uploadTrip(token: String, journal: TripJournal, trip: InspectorTrip) {
        val body = withContext(Dispatchers.IO) {
            val root = journal.export(trip.id)
            try {
                val gpx = File(root, "track.gpx").inputStream().use { readInspectorBytes(it, 2 * 1024 * 1024) }
                val raw = File(root, "journal.json").inputStream().use { readInspectorBytes(it, 16 * 1024 * 1024) }
                val events = JSONObject(raw.toString(Charsets.UTF_8)).getJSONArray("events")
                val logs = JSONArray()
                for (index in 0 until events.length()) {
                    val event = events.getJSONObject(index)
                    if (event.getString("kind") in setOf("gps", "tsr", "sign", "gap")) logs.put(event)
                }
                val encoded = JSONObject().put("schema_version", 1).put("events", logs).toString().toByteArray()
                if (gpx.isEmpty() || encoded.size > 16 * 1024 * 1024) {
                    throw InspectorRequestError(R.string.inspector_files_size)
                }
                ByteBuffer.allocate(4 + gpx.size + encoded.size).putInt(gpx.size).put(gpx).put(encoded).array()
            } finally {
                root.deleteRecursively()
            }
        }
        request(token, "/trip", body, "YouSpeed-${trip.id}.gpx")
    }

    private suspend fun request(token: String, path: String = "", body: ByteArray? = null,
                                name: String? = null): JSONObject = withContext(Dispatchers.IO) {
        val connection = URL(FILES_API + path).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10000
            connection.readTimeout = 60000
            connection.useCaches = false
            connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(body.size)
                connection.setRequestProperty("Content-Type", "application/octet-stream")
                connection.setRequestProperty("X-File-Name", Uri.encode(requireNotNull(name)))
                connection.outputStream.use { it.write(body) }
            }
            val status = connection.responseCode
            if (status !in 200..299) {
                val message = when (status) {
                    401, 403 -> R.string.inspector_files_account
                    413 -> R.string.inspector_files_size
                    503 -> R.string.inspector_files_unavailable
                    else -> R.string.inspector_files_failed
                }
                throw InspectorRequestError(message)
            }
            JSONObject(connection.inputStream.use { readInspectorBytes(it, 4 * 1024 * 1024).toString(Charsets.UTF_8) })
        } finally {
            connection.disconnect()
        }
    }
}

private fun ConsumerUiState.hasInspectorAccount() =
    panoramaxAccountHasToken && panoramaxAccountInstanceName == PanoramaxServerCatalog.default.name

@Composable
internal fun InspectorTrackShareDialog(
    id: String,
    journal: TripJournal,
    controller: ConsumerSessionController?,
    onShareArchive: () -> Unit,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val ui = controller?.uiState
    val available = ui?.hasInspectorAccount() == true
    val recording = ui?.let { DriveRecorderPolicy.isActive(it.driveRecorderState) } == true
    var busy by remember(id) { mutableStateOf(false) }
    var saved by remember(id) { mutableStateOf(false) }
    var error by remember(id) { mutableStateOf<Int?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.inspector_track_share)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (saved) {
                    Text(stringResource(R.string.inspector_track_saved))
                    OutlinedButton(onClick = {
                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$INSPECTOR/inspector/tracks.html")))
                    }) { Text(stringResource(R.string.inspector_files_open_web)) }
                } else {
                    Text(stringResource(R.string.inspector_track_scope))
                    Button(
                        modifier = Modifier.fillMaxWidth().testTag("journal-share-inspector"),
                        enabled = available && !recording && !busy,
                        onClick = {
                            if (!busy && controller != null && !DriveRecorderPolicy.isActive(controller.uiState.driveRecorderState)) {
                                busy = true
                                error = null
                                scope.launch {
                                    try {
                                        val token = withContext(Dispatchers.IO) { controller.inspectorFilesToken() }
                                            ?: throw InspectorRequestError(R.string.inspector_files_account)
                                        InspectorFilesClient.uploadTrack(token, journal, id)
                                        saved = true
                                    } catch (failure: CancellationException) {
                                        throw failure
                                    } catch (failure: InspectorRequestError) {
                                        error = failure.messageRes
                                    } catch (_: Exception) {
                                        error = R.string.inspector_files_failed
                                    } finally {
                                        busy = false
                                    }
                                }
                            }
                        },
                    ) { Text(stringResource(R.string.inspector_track_save)) }
                    if (!available) Text(stringResource(R.string.inspector_files_account))
                    else if (recording) Text(stringResource(R.string.inspector_track_recording))
                    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                    error?.let { Text(stringResource(it)) }
                }
                OutlinedButton(
                    onClick = onShareArchive,
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth().testTag("journal-share-archive"),
                ) { Text(stringResource(R.string.inspector_track_archive)) }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(if (saved) android.R.string.ok else android.R.string.cancel))
            }
        },
    )
}

@Composable
internal fun InspectorFilesSheet(controller: ConsumerSessionController, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val ui = controller.uiState
    val accountKey = Triple(ui.panoramaxAccountInstanceName, ui.panoramaxAccountHasToken, ui.panoramaxAccountConnected)
    var library by remember(accountKey) { mutableStateOf<InspectorLibrary?>(null) }
    var selection by remember(accountKey) { mutableStateOf<InspectorSelection?>(null) }
    var trip by remember(accountKey) { mutableStateOf<InspectorTrip?>(null) }
    var trips by remember(accountKey) { mutableStateOf(emptyList<InspectorTrip>()) }
    var showTrips by remember(accountKey) { mutableStateOf(false) }
    var preview by remember(accountKey) { mutableStateOf<InspectorPreview?>(null) }
    var busy by remember(accountKey) { mutableStateOf(false) }
    var error by remember(accountKey) { mutableStateOf<Int?>(null) }
    val available = ui.hasInspectorAccount()
    val recording = DriveRecorderPolicy.isActive(ui.driveRecorderState)

    suspend fun run(operation: suspend (String) -> Unit) {
        if (busy) return
        busy = true
        error = null
        try {
            val token = withContext(Dispatchers.IO) { controller.inspectorFilesToken() }
                ?: throw InspectorRequestError(R.string.inspector_files_account)
            operation(token)
        } catch (failure: CancellationException) {
            throw failure
        } catch (failure: InspectorRequestError) {
            error = failure.messageRes
        } catch (_: Exception) {
            error = R.string.inspector_files_failed
        } finally {
            busy = false
        }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            val name = runCatching {
                context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                    if (it.moveToFirst()) it.getString(0) else null
                }
            }.getOrNull()
            if (name != null) {
                selection = InspectorSelection(uri, name)
                trip = null
            }
            else error = R.string.inspector_files_failed
        }
    }

    LaunchedEffect(accountKey) {
        if (available) run { token -> library = InspectorFilesClient.list(token) }
    }

    LaunchedEffect(accountKey, library?.tripUpload, recording) {
        if (available && library?.tripUpload == true && !recording) runCatching {
            withContext(Dispatchers.IO) {
                val date = DateFormat.getDateTimeInstance()
                controller.tripJournal.history().mapNotNull { row ->
                    if (row.optString("state") !in setOf("ended", "interrupted", "disabled")) return@mapNotNull null
                    val id = row.getString("id")
                    val start = date.format(Date((row.getDouble("start") * 1000).toLong()))
                    val place = row.optString("end_place", "").takeUnless { it == "null" || it.isBlank() }
                    InspectorTrip(id, listOfNotNull(start, place).joinToString(" · "))
                }
            }
        }.onSuccess { trips = it }.onFailure { if (it is CancellationException) throw it }
    }

    SheetScaffold(stringResource(R.string.inspector_files_title), onDismiss, "inspector-files") {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (!available) {
                Text(stringResource(R.string.inspector_files_account))
            } else {
                Button(onClick = { picker.launch(arrayOf("*/*")) }, enabled = !busy) {
                    Text(stringResource(R.string.inspector_files_choose))
                }
                if (trips.isNotEmpty()) {
                    Box {
                        OutlinedButton(onClick = { showTrips = true }, enabled = !busy && !recording) {
                            Text(stringResource(R.string.inspector_files_choose_trip))
                        }
                        DropdownMenu(expanded = showTrips, onDismissRequest = { showTrips = false }) {
                            trips.forEach { choice ->
                                DropdownMenuItem(text = { Text(choice.label) }, onClick = {
                                    trip = choice
                                    selection = null
                                    showTrips = false
                                })
                            }
                        }
                    }
                }
                trip?.let { chosen ->
                    Text(chosen.label)
                    Button(onClick = {
                        scope.launch {
                            if (DriveRecorderPolicy.isActive(controller.uiState.driveRecorderState)) return@launch
                            run { token ->
                                InspectorFilesClient.uploadTrip(token, controller.tripJournal, chosen)
                                library = InspectorFilesClient.list(token)
                                trip = null
                            }
                        }
                    }, enabled = !busy && !recording) {
                        Text(stringResource(R.string.inspector_files_save_trip))
                    }
                }
                val logPaths = listOf(ui.gpsLogPath, ui.matchLogPath, ui.inventorySignLogPath, ui.runtimeDiagnosticsLogPath)
                val logs = logPaths.filter(String::isNotBlank).map(::File).filter(File::isFile)
                if (logs.isNotEmpty()) {
                    Text(stringResource(R.string.inspector_files_choose_log))
                    logs.forEach { log ->
                        OutlinedButton(onClick = { selection = InspectorSelection(Uri.fromFile(log), log.name); trip = null }, enabled = !busy) {
                            Text(log.name)
                        }
                    }
                }
                selection?.let { chosen ->
                    Text(chosen.name)
                    Button(
                        onClick = {
                            scope.launch {
                                if (DriveRecorderPolicy.isActive(controller.uiState.driveRecorderState)) return@launch
                                run { token ->
                                    val uploaded = InspectorFilesClient.upload(context, token, chosen)
                                    library = library?.let { current ->
                                        if (current.files.any { it.id == uploaded.id }) current
                                        else current.copy(files = listOf(uploaded) + current.files)
                                    }
                                    selection = null
                                }
                            }
                        },
                        enabled = !busy && !recording && library?.storage == true,
                    ) { Text(stringResource(R.string.inspector_files_save)) }
                }
                Text(stringResource(R.string.inspector_files_saved))
                if (library?.storage == false) Text(stringResource(R.string.inspector_files_unavailable))
                if (library?.storage == true && library?.files?.isEmpty() == true) Text(stringResource(R.string.inspector_files_empty))
                for ((files, isExamples) in listOf(library?.files.orEmpty() to false, library?.examples.orEmpty() to true)) {
                    if (isExamples && files.isNotEmpty()) Text(stringResource(R.string.inspector_files_examples))
                    files.forEach { file ->
                        OutlinedButton(
                            onClick = { scope.launch { run { token -> preview = InspectorFilesClient.preview(token, file) } } },
                            enabled = !busy && (file.kind != "track" || library?.comparison == true),
                        ) { Text(file.displayName) }
                    }
                }
                OutlinedButton(onClick = { scope.launch { run { token -> library = InspectorFilesClient.list(token) } } },
                    enabled = !busy) { Text(stringResource(R.string.inspector_files_refresh)) }
            }
            if (busy) LinearProgressIndicator()
            error?.let { Text(stringResource(it)) }
            OutlinedButton(onClick = {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$INSPECTOR/inspector/tracks.html")))
            }) { Text(stringResource(R.string.inspector_files_open_web)) }
        }
    }

    preview?.let { item ->
        SheetScaffold(item.file.displayName, { preview = null }, "inspector-file-preview") {
            val html = item.html
            if (html != null) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = { viewContext ->
                        WebView(viewContext).apply {
                            settings.javaScriptEnabled = true
                            settings.allowFileAccess = false
                            settings.allowContentAccess = false
                            settings.blockNetworkLoads = true
                            webViewClient = object : WebViewClient() {
                                override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?) = true
                            }
                            loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
                        }
                    },
                )
            } else {
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                    Text(item.text.orEmpty(), fontFamily = FontFamily.Monospace)
                    if (item.truncated) Text(stringResource(R.string.inspector_files_truncated))
                }
            }
        }
    }
}
