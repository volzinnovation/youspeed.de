package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.graphics.Outline
import android.view.View
import android.view.ViewOutlineProvider
import android.widget.MediaController
import android.widget.VideoView
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.StarBorder
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Upload
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.zIndex
import androidx.exifinterface.media.ExifInterface
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.File
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt

private fun parityText(en: String, de: String, fr: String, nl: String) = ConsumerUiStrings.text(en, de, fr, nl)
private fun dateText(value: Instant): String = DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT)
    .withLocale(Locale.getDefault()).withZone(ZoneId.systemDefault()).format(value)
private fun onOff(value: Boolean) = if (value) parityText("On", "Ein", "Activé", "Aan") else parityText("Off", "Aus", "Désactivé", "Uit")
private fun doneLabel() = parityText("Done", "Fertig", "Terminé", "Gereed")
private fun deleteLabel() = parityText("Delete", "Löschen", "Supprimer", "Verwijderen")
private fun cancelLabel() = parityText("Cancel", "Abbrechen", "Annuler", "Annuleren")

@Composable
internal fun RecorderModuleStrip(
    controller: ConsumerSessionController,
    modifier: Modifier = Modifier,
    onPreviewRequested: (() -> Unit)? = null,
) {
    val ui = controller.uiState
    var previewDialog by remember { mutableStateOf(false) }
    var details by remember { mutableStateOf(false) }
    var now by remember { mutableStateOf(Instant.now()) }
    LaunchedEffect(ui.driveRecorderStartedAt) {
        while (ui.driveRecorderStartedAt != null) { now = Instant.now(); delay(1_000) }
    }
    val seconds = ui.driveRecorderStartedAt?.let { Duration.between(it, now).seconds.coerceAtLeast(0) } ?: 0
    val elapsed = if (seconds >= 3600) "%d:%02d:%02d".format(seconds / 3600, seconds / 60 % 60, seconds % 60)
        else "%02d:%02d".format(seconds / 60, seconds % 60)
    val canToggle = ui.driveRecorderState == DriveRecorderState.RECORDING
    val stateLabel = when (ui.driveRecorderState) {
        DriveRecorderState.RECORDING -> parityText("Recording", "Aufnahme", "Enregistrement", "Opname")
        DriveRecorderState.STOPPING -> parityText("Stopping…", "Wird beendet…", "Arrêt…", "Stoppen…")
        DriveRecorderState.REQUESTING_PERMISSION, DriveRecorderState.PREPARING ->
            parityText("Preparing…", "Vorbereitung…", "Préparation…", "Voorbereiden…")
        DriveRecorderState.FAILED -> parityText("Failed", "Fehlgeschlagen", "Échec", "Mislukt")
        DriveRecorderState.DENIED, DriveRecorderState.UNAVAILABLE ->
            parityText("Unavailable", "Nicht verfügbar", "Indisponible", "Niet beschikbaar")
        DriveRecorderState.DISABLED -> onOff(false)
    }
    val foreground = Color(0xFFF5F5F5)
    Surface(
        modifier = modifier.fillMaxWidth().padding(horizontal = 8.dp),
        shape = RoundedCornerShape(14.dp),
        color = Color(0xFF202124),
        contentColor = foreground,
        border = BorderStroke(1.dp, Color(0xFF74777B)),
    ) {
        Column(Modifier.padding(horizontal = 10.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f).testTag("recorder-elapsed-time"), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(stateLabel, color = foreground, style = MaterialTheme.typography.labelSmall)
                    Text(elapsed, color = foreground, fontFamily = FontFamily.Monospace,
                        fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.titleSmall)
                }
                RecorderModuleButton(
                    label = "Dashcam",
                    status = if (ui.driveRecorderDashcamTransitioning)
                        parityText("Changing…", "Wird geändert…", "Modification…", "Wijzigen…") else onOff(ui.driveRecorderDashcamActive),
                    selected = ui.driveRecorderDashcamActive || ui.driveRecorderDashcamTransitioning,
                    enabled = canToggle && !ui.driveRecorderDashcamTransitioning,
                    onClick = controller::toggleDriveRecorderDashcam,
                    modifier = Modifier.weight(1f).testTag("recorder-dashcam-module"),
                )
                RecorderModuleButton(
                    label = parityText("Signs", "Schilder", "Panneaux", "Borden"),
                    status = if (ui.trafficSignRecognitionUnavailable)
                        parityText("Unavailable", "Nicht verfügbar", "Indisponible", "Niet beschikbaar") else onOff(ui.trafficSignRecognitionEnabled),
                    selected = ui.trafficSignRecognitionEnabled,
                    enabled = canToggle,
                    onClick = controller::toggleDriveRecorderTrafficSignRecognition,
                    modifier = Modifier.weight(1f).testTag("recorder-tsr-module"),
                )
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Panoramax · ${ui.panoramaxCaptureCount} · " + onOff(ui.driveRecorderPanoramaxActive),
                    modifier = Modifier.weight(1f).padding(vertical = 5.dp).testTag("recorder-panoramax-module"),
                    color = foreground, style = MaterialTheme.typography.labelMedium)
                if (ui.driveRecorderDashcamActive) IconButton(
                    onClick = { onPreviewRequested?.invoke() ?: run { previewDialog = true } },
                    modifier = Modifier.testTag("recorder-show-preview"),
                ) {
                    Icon(Icons.Default.CameraAlt, tint = foreground,
                        contentDescription = parityText("Camera preview", "Kameravorschau", "Aperçu caméra", "Cameravoorbeeld"))
                }
                if (ui.trafficSignRecognitionEnabled) IconButton(onClick = { details = true },
                    modifier = Modifier.testTag("recorder-show-recognition-details")) {
                    Icon(Icons.Default.Info, tint = foreground,
                        contentDescription = parityText("Recognition details", "Erkennungsdetails", "Détails de reconnaissance", "Herkenningsdetails"))
                }
            }
        }
    }
    if (previewDialog) SheetScaffold(parityText("Camera preview", "Kameravorschau", "Aperçu caméra", "Cameravoorbeeld"),
        { previewDialog = false }, "recorder-preview-sheet") {
        RecorderPreviewWorkspace(controller, Modifier.fillMaxSize(), true)
    }
    if (details) SheetScaffold(parityText("Recognition details", "Erkennungsdetails", "Détails de reconnaissance", "Herkenningsdetails"),
        { details = false }, "traffic-sign-details-sheet") { TrafficSignDetailsContent(controller) }
}

@Composable
private fun RecorderModuleButton(
    label: String,
    status: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        shape = RoundedCornerShape(9.dp),
        color = if (selected) Color(0xFF49312D) else Color(0xFF303236),
        contentColor = Color(0xFFF5F5F5),
        border = BorderStroke(1.dp, if (selected) Color(0xFFFFAD96) else Color(0xFF8B8E93)),
    ) {
        Column(Modifier.heightIn(min = 48.dp).padding(horizontal = 5.dp, vertical = 5.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Text(label, color = Color(0xFFF5F5F5), fontWeight = FontWeight.SemiBold,
                style = MaterialTheme.typography.labelMedium, textAlign = TextAlign.Center)
            Text(status, color = Color(0xFFE0E1E3), style = MaterialTheme.typography.labelSmall,
                textAlign = TextAlign.Center)
        }
    }
}

/** Keeps the live surface attached for the recorder session so toggling telemetry does not rebuild CameraX. */
@Composable
internal fun RecorderPreviewWorkspace(
    controller: ConsumerSessionController,
    modifier: Modifier = Modifier,
    visible: Boolean,
    attached: Boolean = true,
    onDismiss: (() -> Unit)? = null,
) {
    if (!attached) return
    val context = LocalContext.current
    val preview = remember(context) {
        PreviewView(context).apply {
            // Like AVCaptureVideoPreviewLayer on iPhone, use a separately
            // composed camera surface when available. CameraX owns rotation,
            // mirroring, crop and the TextureView fallback for device quirks.
            implementationMode = PreviewView.ImplementationMode.PERFORMANCE
            scaleType = PreviewView.ScaleType.FILL_CENTER
            clipToOutline = true
            outlineProvider = object : ViewOutlineProvider() {
                override fun getOutline(view: View, outline: Outline) {
                    outline.setRoundRect(0, 0, view.width, view.height, 16f * resources.displayMetrics.density)
                }
            }
        }
    }
    DisposableEffect(controller, preview) {
        controller.setDriveRecorderPreviewSurfaceProvider(preview.surfaceProvider)
        onDispose { controller.setDriveRecorderPreviewSurfaceProvider(null) }
    }
    Box(
        modifier
            .alpha(if (visible) 1f else 0f)
            .zIndex(if (visible) 1f else -1f)
            .clip(RoundedCornerShape(16.dp))
            .background(Color.Black)
            .testTag("recorder-camera-preview"),
    ) {
        AndroidView(
            factory = { preview },
            modifier = Modifier.fillMaxSize(),
            update = { view ->
                // Keep VISIBLE and attached: hiding must not destroy a surface
                // or rebuild the active recording graph. Our API 34 minimum
                // supports SurfaceView alpha as well as the TextureView fallback.
                val targetAlpha = if (visible) 1f else 0f
                if (view.alpha != targetAlpha) {
                    view.alpha = targetAlpha
                    view.parent?.requestTransparentRegion(view)
                }
                view.importantForAccessibility = if (visible) {
                    View.IMPORTANT_FOR_ACCESSIBILITY_AUTO
                } else {
                    View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
                }
            },
        )
        if (visible && onDismiss != null) TextButton(onClick = onDismiss,
            modifier = Modifier.align(Alignment.TopEnd).testTag("recorder-hide-preview")) {
            Text(doneLabel(), color = Color.White)
        }
    }
}

@Composable
private fun ParitySection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(colors = CardDefaults.cardColors(containerColor = Color.White)) {
        Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, fontWeight = FontWeight.Bold, color = Color.Black)
            content()
        }
    }
}

@Composable
private fun ParityToggle(label: String, checked: Boolean, enabled: Boolean = true, tag: String? = null, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f), color = Color.Black)
        Switch(checked, onChange, enabled = enabled, modifier = tag?.let { Modifier.testTag(it) } ?: Modifier)
    }
}

@Composable
private fun ParitySlider(label: String, value: Double, range: ClosedFloatingPointRange<Float>, steps: Int, unit: String,
    onChange: (Double) -> Unit) {
    Column {
        Text("$label · ${value.roundToInt()} $unit", color = Color.Black)
        Slider(value.toFloat().coerceIn(range), { onChange(it.toDouble()) }, valueRange = range, steps = steps)
    }
}

@Composable
internal fun RecorderParitySettings(controller: ConsumerSessionController) {
    val ui = controller.uiState
    var details by remember { mutableStateOf(false) }
    val active = ui.driveRecorderState in setOf(DriveRecorderState.PREPARING, DriveRecorderState.RECORDING, DriveRecorderState.STOPPING)
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        ParitySection(parityText("Drive recorder", "Fahrtaufnahme", "Enregistrement du trajet", "Ritopname")) {
            ParityToggle(parityText("Traffic-sign recognition", "Verkehrszeichenerkennung", "Reconnaissance des panneaux", "Verkeersbordherkenning"),
                ui.trafficSignRecognitionEnabled, !active, "traffic-sign-recognition-toggle", controller::setTrafficSignRecognitionEnabled)
            ParityToggle(parityText("Show other traffic signs", "Andere Verkehrszeichen anzeigen", "Afficher les autres panneaux", "Andere verkeersborden tonen"),
                ui.otherTrafficSignDisplayEnabled, tag = "other-traffic-sign-display-toggle", onChange = controller::setOtherTrafficSignDisplayEnabled)
            Text(parityText("The included model does not recognize town-entry signs reliably.",
                "Das enthaltene Modell erkennt Ortseingangsschilder nicht zuverlässig.",
                "Le modèle intégré ne reconnaît pas fiablement les panneaux d’entrée d’agglomération.",
                "Het meegeleverde model herkent bebouwdekomborden niet betrouwbaar."), style = MaterialTheme.typography.bodySmall)
            ParityToggle(parityText("Recognize signs without recording", "Schilder ohne Aufnahme erkennen", "Reconnaître sans enregistrer", "Borden herkennen zonder opname"),
                ui.trafficSignRecognitionIndependentEnabled, ui.trafficSignRecognitionEnabled, "traffic-sign-independent-toggle",
                controller::setTrafficSignRecognitionIndependentEnabled)
            Text(parityText("Android asks for camera/video permission when the camera is first started. This option recognizes signs without saving video.",
                "Android fragt beim ersten Start der Kamera nach der Kamera-/Videoberechtigung. Diese Option erkennt Schilder, ohne ein Video zu speichern.",
                "Android demande l’autorisation caméra/vidéo au premier démarrage de la caméra. Cette option reconnaît les panneaux sans enregistrer de vidéo.",
                "Android vraagt bij de eerste start van de camera om camera-/videotoestemming. Deze optie herkent borden zonder video op te slaan."),
                style = MaterialTheme.typography.bodySmall)
            Text(parityText("Recognition feedback", "Rückmeldung bei Erkennung", "Retour de reconnaissance", "Herkenningsmelding"), fontWeight = FontWeight.SemiBold)
            TrafficSignFeedbackMode.entries.forEach { mode ->
                val label = when (mode) {
                    TrafficSignFeedbackMode.SPOKEN_SPEED -> parityText("Speak the speed", "Geschwindigkeit ansagen", "Annoncer la vitesse", "Snelheid uitspreken")
                    TrafficSignFeedbackMode.SOUND -> parityText("Sound", "Ton", "Son", "Geluid")
                    TrafficSignFeedbackMode.SILENT -> parityText("Silent", "Lautlos", "Silencieux", "Stil")
                }
                Row(Modifier.fillMaxWidth().clickable(enabled = ui.trafficSignRecognitionEnabled) { controller.setTrafficSignFeedbackMode(mode) },
                    verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(ui.trafficSignFeedbackMode == mode, { controller.setTrafficSignFeedbackMode(mode) }, enabled = ui.trafficSignRecognitionEnabled)
                    Text(label)
                }
            }
            TextButton(onClick = { details = true }, modifier = Modifier.testTag("traffic-sign-details-button")) {
                Text(parityText("Recognition details", "Erkennungsdetails", "Détails de reconnaissance", "Herkenningsdetails"))
            }
            ParityToggle(parityText("Capture Panoramax photos", "Panoramax-Fotos aufnehmen", "Prendre des photos Panoramax", "Panoramax-foto’s maken"),
                ui.panoramaxCaptureEnabled, !active, "panoramax-settings-toggle", controller::setPanoramaxCaptureEnabled)
            Text(parityText("Camera modules share one camera. Photos remain local until you review and upload them after recording.",
                "Die Module nutzen eine Kamera. Fotos bleiben lokal, bis du sie nach der Aufnahme prüfst und hochlädst.",
                "Les modules partagent une caméra. Les photos restent locales jusqu’à leur vérification et envoi après l’enregistrement.",
                "De modules delen één camera. Foto’s blijven lokaal totdat je ze na de opname controleert en uploadt."), style = MaterialTheme.typography.bodySmall)
            if (active) Text(parityText("Change active modules using the recorder controls.", "Aktive Module über die Aufnahmesteuerung ändern.",
                "Modifiez les modules actifs avec les commandes d’enregistrement.", "Wijzig actieve modules via de opnameknoppen."), style = MaterialTheme.typography.bodySmall)
        }
        ParitySection(parityText("Panoramax storage and capture", "Panoramax-Speicher und Aufnahme", "Stockage et capture Panoramax", "Panoramax-opslag en opname")) {
            if (ui.panoramaxCaptureEnabled) {
                Text("${ui.panoramaxCaptureCount} " + parityText("saved photos", "gespeicherte Fotos", "photos enregistrées", "opgeslagen foto’s"))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PanoramaxCaptureTriggerMode.entries.forEach { mode ->
                        FilterChip(ui.panoramaxTriggerMode == mode, { controller.setPanoramaxTriggerMode(mode) }, label = { Text(
                            if (mode == PanoramaxCaptureTriggerMode.DISTANCE) parityText("Distance", "Abstand", "Distance", "Afstand")
                            else parityText("Time", "Zeit", "Temps", "Tijd")) })
                    }
                }
                ParitySlider(parityText("Minimum distance", "Mindestabstand", "Distance minimale", "Minimumafstand"), ui.panoramaxMinimumDistanceMeters,
                    3f..100f, 96, "m", controller::setPanoramaxMinimumDistanceMeters)
                ParitySlider(parityText("Minimum interval", "Mindestintervall", "Intervalle minimal", "Minimuminterval"), ui.panoramaxMinimumIntervalSeconds,
                    1f..60f, 58, "s", controller::setPanoramaxMinimumIntervalSeconds)
                Text(parityText("GPS accuracy also limits capture spacing; stationary duplicates are skipped.",
                    "Auch die GPS-Genauigkeit begrenzt den Fotoabstand; doppelte Bilder im Stand werden ausgelassen.",
                    "La précision GPS limite aussi l’espacement ; les doublons à l’arrêt sont ignorés.",
                    "GPS-nauwkeurigheid beperkt ook de fotoafstand; duplicaten bij stilstand worden overgeslagen."), style = MaterialTheme.typography.bodySmall)
                ParityToggle(parityText("Unlimited storage", "Unbegrenzter Speicher", "Stockage illimité", "Onbeperkte opslag"), ui.panoramaxUnlimitedStorage,
                    onChange = controller::setPanoramaxUnlimitedStorage)
                if (!ui.panoramaxUnlimitedStorage) {
                    ParitySlider(parityText("Storage limit", "Speicherlimit", "Limite de stockage", "Opslaglimiet"), ui.panoramaxStorageLimitMB,
                        100f..10_000f, 98, "MB", controller::setPanoramaxStorageLimitMB)
                    Text(parityText("Older unprotected photos are removed first. Favorites are preserved.",
                        "Ältere ungeschützte Fotos werden zuerst entfernt. Favoriten bleiben erhalten.",
                        "Les anciennes photos non protégées sont supprimées en premier. Les favoris sont conservés.",
                        "Oudere onbeschermde foto’s worden eerst verwijderd. Favorieten blijven bewaard."), style = MaterialTheme.typography.bodySmall)
                }
            }
            ParityToggle(parityText("Delete uploaded photos", "Hochgeladene Fotos löschen", "Supprimer les photos envoyées", "Geüploade foto’s verwijderen"),
                ui.panoramaxDeleteUploadedImages, onChange = controller::setPanoramaxDeleteUploadedImages)
            Text(parityText("Remove local uploaded pictures only after Panoramax confirms processing of the complete upload.",
                "Lokale hochgeladene Bilder erst entfernen, nachdem Panoramax die Verarbeitung des vollständigen Uploads bestätigt.",
                "Supprimer les photos locales envoyées uniquement après confirmation du traitement de l’envoi complet par Panoramax.",
                "Lokale geüploade foto’s pas verwijderen nadat Panoramax de verwerking van de volledige upload bevestigt."), style = MaterialTheme.typography.bodySmall)
            ui.panoramaxMaintenanceIssue?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        }
        ParitySection(parityText("Panoramax account", "Panoramax-Konto", "Compte Panoramax", "Panoramax-account")) {
            Text(ui.panoramaxAccountStatus.ifBlank { if (ui.panoramaxAccountConnected)
                parityText("Connected", "Verbunden", "Connecté", "Verbonden") else parityText("Not connected", "Nicht verbunden", "Non connecté", "Niet verbonden") })
            if (ui.panoramaxAccountBusy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (ui.panoramaxAccountHasToken) {
                OutlinedButton(onClick = controller::validatePanoramaxAccount, enabled = !ui.panoramaxAccountBusy) { Text(parityText("Check connection", "Verbindung prüfen", "Vérifier la connexion", "Verbinding controleren")) }
                TextButton(onClick = controller::disconnectPanoramaxAccount, enabled = !ui.panoramaxAccountBusy) { Text(parityText("Disconnect account", "Konto trennen", "Déconnecter le compte", "Account loskoppelen")) }
            } else Button(onClick = controller::connectPanoramaxAccount, enabled = !ui.panoramaxAccountBusy) { Text(parityText("Connect account", "Konto verbinden", "Connecter le compte", "Account verbinden")) }
        }
    }
    if (details) SheetScaffold(parityText("Recognition details", "Erkennungsdetails", "Détails de reconnaissance", "Herkenningsdetails"),
        { details = false }, "traffic-sign-details-sheet") { TrafficSignDetailsContent(controller) }
}

@Composable
private fun GalleryActionBar(content: @Composable RowScope.() -> Unit) {
    Surface(tonalElevation = 3.dp) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            content = content,
        )
    }
}

@Composable
private fun GalleryAction(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Column(
        Modifier.width(76.dp).clickable(enabled = enabled, onClick = onClick).padding(vertical = 2.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(icon, contentDescription = label, tint = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f))
        Text(label, style = MaterialTheme.typography.labelSmall, maxLines = 1,
            color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f))
    }
}

@Composable
internal fun DashcamLibraryContent(controller: ConsumerSessionController) {
    val recordings = controller.uiState.dashcamRecordings
    val context = LocalContext.current
    var selected by remember { mutableStateOf(emptySet<String>()) }
    var deleteConfirmation by remember { mutableStateOf(false) }
    var playing by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(recordings) { selected = selected.intersect(recordings.map { it.path }.toSet()) }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(parityText("Movies are stored on this device. Select a recording to play, share or delete it.",
            "Videos liegen auf diesem Gerät. Wähle eine Aufnahme zum Abspielen, Teilen oder Löschen.",
            "Les vidéos sont stockées sur cet appareil. Sélectionnez un enregistrement à lire, partager ou supprimer.",
            "Video’s staan op dit apparaat. Selecteer een opname om af te spelen, te delen of te verwijderen."))
        if (recordings.isEmpty()) Text(parityText("No recordings yet.", "Noch keine Aufnahmen.", "Aucun enregistrement.", "Nog geen opnamen."))
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(recordings, key = { it.path }) { recording ->
                Card {
                    Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Checkbox(recording.path in selected, { checked -> selected = if (checked) selected + recording.path else selected - recording.path })
                        Icon(Icons.Default.VideoLibrary, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Column(Modifier.weight(1f).clickable { playing = recording.path }) {
                            Text(dateText(recording.createdAt), fontWeight = FontWeight.SemiBold)
                            Text(android.text.format.Formatter.formatFileSize(context, recording.bytes), style = MaterialTheme.typography.bodySmall)
                        }
                        IconButton(onClick = { controller.shareDashcamRecording(recording.path) },
                            enabled = controller.uiState.driveRecorderState == DriveRecorderState.DISABLED) {
                            Icon(Icons.Default.Share, contentDescription = parityText("Share", "Teilen", "Partager", "Delen"))
                        }
                    }
                }
            }
        }
        if (recordings.isNotEmpty()) {
            GalleryActionBar {
                GalleryAction(
                    icon = Icons.Default.CheckCircle,
                    label = parityText("Select all", "Alle auswählen", "Tout sélectionner", "Alles selecteren"),
                    enabled = selected.size != recordings.size,
                    onClick = { selected = recordings.map { it.path }.toSet() },
                )
                GalleryAction(
                    icon = Icons.Default.RadioButtonUnchecked,
                    label = parityText("Select none", "Auswahl aufheben", "Tout désélectionner", "Niets selecteren"),
                    enabled = selected.isNotEmpty(),
                    onClick = { selected = emptySet() },
                )
                GalleryAction(
                    icon = Icons.Default.Delete,
                    label = "${deleteLabel()} (${selected.size})",
                    enabled = selected.isNotEmpty() && controller.uiState.driveRecorderState !in
                        setOf(DriveRecorderState.PREPARING, DriveRecorderState.RECORDING, DriveRecorderState.STOPPING),
                    onClick = { deleteConfirmation = true },
                )
            }
        }
    }
    if (deleteConfirmation) ParityDeleteConfirmation(selected.size, { deleteConfirmation = false }) {
        controller.deleteDashcamRecordings(selected); selected = emptySet(); deleteConfirmation = false
    }
    playing?.let { path ->
        SheetScaffold(parityText("Recording", "Aufnahme", "Enregistrement", "Opname"), { playing = null }, "dashcam-playback-sheet") {
            AndroidView(factory = { ctx -> VideoView(ctx).apply {
                setVideoPath(path)
                setMediaController(MediaController(ctx).also { it.setAnchorView(this) })
                setOnPreparedListener { start() }
            } }, modifier = Modifier.fillMaxSize(), onRelease = { it.stopPlayback() })
        }
    }
}

@Composable
private fun ParityDeleteConfirmation(count: Int, onDismiss: () -> Unit, onDelete: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss, title = { Text("${deleteLabel()} ($count)?") },
        text = { Text(parityText("The selected local files will be permanently deleted.", "Die ausgewählten lokalen Dateien werden endgültig gelöscht.",
            "Les fichiers locaux sélectionnés seront définitivement supprimés.", "De geselecteerde lokale bestanden worden definitief verwijderd.")) },
        confirmButton = { TextButton(onClick = onDelete) { Text(deleteLabel()) } }, dismissButton = { TextButton(onClick = onDismiss) { Text(cancelLabel()) } })
}

@Composable
internal fun PanoramaxGalleryContent(controller: ConsumerSessionController) {
    val ui = controller.uiState
    var selected by remember { mutableStateOf(emptyMap<String, Set<String>>()) }
    var deleteConfirmation by remember { mutableStateOf(false) }
    var uploadConfirmation by remember { mutableStateOf(false) }
    var focused by remember { mutableStateOf<Pair<String, String>?>(null) }
    val count = selected.values.sumOf { it.size }
    LaunchedEffect(ui.panoramaxBatches) {
        selected = selected.mapNotNull { (batchId, ids) ->
            val available = ui.panoramaxBatches.firstOrNull { it.batchId == batchId }?.items?.map { it.itemId }?.toSet().orEmpty()
            ids.intersect(available).takeIf { it.isNotEmpty() }?.let { batchId to it }
        }.toMap()
    }
    fun select(batch: String, item: String, value: Boolean) {
        val current = selected[batch].orEmpty()
        val updated = if (value) current + item else current - item
        selected = if (updated.isEmpty()) selected - batch else selected + (batch to updated)
    }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(parityText("Review photos before upload. Open a photo to inspect it; protect favorites from automatic cleanup.",
            "Fotos vor dem Hochladen prüfen. Ein Foto zum Prüfen öffnen; Favoriten vor automatischer Bereinigung schützen.",
            "Vérifiez les photos avant l’envoi. Ouvrez-les pour les inspecter ; les favoris sont protégés du nettoyage automatique.",
            "Controleer foto’s vóór het uploaden. Open een foto om die te bekijken; favorieten zijn beschermd tegen automatisch opruimen."))
        if (!controller.canProcessPanoramaxUploads()) Text(parityText("Uploads are available after recording has finished.",
            "Uploads sind nach Abschluss der Aufnahme verfügbar.", "Les envois sont disponibles après la fin de l’enregistrement.",
            "Uploaden kan nadat de opname is voltooid."), style = MaterialTheme.typography.bodySmall)
        if (ui.panoramaxActiveUploadBatchIds.isNotEmpty()) OutlinedButton(onClick = controller::stopPanoramaxUploads) {
            Text(parityText("Stop uploads", "Uploads stoppen", "Arrêter les envois", "Uploads stoppen"))
        }
        if (ui.panoramaxMaintenanceInProgress) LinearProgressIndicator(Modifier.fillMaxWidth())
        ui.panoramaxMaintenanceIssue?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (ui.panoramaxBatches.all { it.items.isEmpty() }) Text(parityText("No photos yet.", "Noch keine Fotos.", "Aucune photo.", "Nog geen foto’s."))
        LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            ui.panoramaxBatches.forEach { batch ->
                item(key = "header-${batch.batchId}") {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text(dateText(batch.createdAt), fontWeight = FontWeight.Bold)
                        ui.panoramaxUploadStatusByBatch[batch.batchId]?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                        ui.panoramaxUploadProgressByBatch[batch.batchId]?.let { progress ->
                            LinearProgressIndicator(progress = progress.fractionCompleted.toFloat(), modifier = Modifier.fillMaxWidth())
                            Text("${progress.completedItems} / ${progress.totalItems}", style = MaterialTheme.typography.bodySmall)
                        }
                        if (batch.remoteUploadSetId != null && batch.state != PanoramaxBatchState.COMPLETE && batch.batchId !in ui.panoramaxActiveUploadBatchIds) {
                            TextButton(onClick = { controller.resumePanoramaxUpload(batch.batchId) }, enabled = controller.canProcessPanoramaxUploads() && ui.panoramaxAccountConnected) {
                                Text(parityText("Resume upload", "Upload fortsetzen", "Reprendre l’envoi", "Upload hervatten"))
                            }
                        }
                    }
                }
                items(batch.items, key = { "${batch.batchId}/${it.itemId}" }) { item ->
                    val editable = controller.canProcessPanoramaxUploads() && batch.batchId !in ui.panoramaxActiveUploadBatchIds && batch.state != PanoramaxBatchState.CAPTURING
                    Card {
                        Column(Modifier.fillMaxWidth().padding(10.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Checkbox(item.itemId in selected[batch.batchId].orEmpty(), { select(batch.batchId, item.itemId, it) }, enabled = editable)
                                LocalPhoto(controller.panoramaxThumbnailFile(item), Modifier.size(92.dp).clip(RoundedCornerShape(8.dp)).clickable { focused = batch.batchId to item.itemId }, 256,
                                    fallbackFile = controller.panoramaxOriginalFile(item))
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    Text(dateText(item.metadata.capturedAt), style = MaterialTheme.typography.bodySmall)
                                    Text(itemStateLabel(item.state), style = MaterialTheme.typography.bodySmall)
                                    item.metadata.trafficSignAnnotations.orEmpty().firstOrNull()?.speedLimitKmh?.let { Text("$it km/h", fontWeight = FontWeight.Bold) }
                                }
                            }
                            Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
                                IconButton(onClick = { controller.setPanoramaxItemFavorite(batch.batchId, item.itemId, !item.isFavorite) }) {
                                    Icon(
                                        if (item.isFavorite) Icons.Default.Star else Icons.Default.StarBorder,
                                        contentDescription = if (item.isFavorite) parityText("Remove favorite", "Favorit entfernen", "Retirer des favoris", "Favoriet verwijderen")
                                        else parityText("Add favorite", "Als Favorit markieren", "Ajouter aux favoris", "Favoriet maken"),
                                        tint = if (item.isFavorite) Color(0xFFFFC107) else MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                                if (item.state in setOf(PanoramaxItemState.CAPTURED, PanoramaxItemState.INCLUDED, PanoramaxItemState.EXCLUDED, PanoramaxItemState.RETRYABLE_ERROR)) {
                                    IconButton(onClick = { controller.setPanoramaxItemIncluded(batch.batchId, item.itemId, item.state == PanoramaxItemState.EXCLUDED) }, enabled = editable) {
                                        Icon(
                                            Icons.Default.CheckCircle,
                                            contentDescription = if (item.state == PanoramaxItemState.EXCLUDED) parityText("Include", "Einbeziehen", "Inclure", "Opnemen")
                                            else parityText("Exclude", "Ausschließen", "Exclure", "Uitsluiten"),
                                            tint = if (item.state == PanoramaxItemState.EXCLUDED) MaterialTheme.colorScheme.onSurfaceVariant else Color(0xFF43A047),
                                        )
                                    }
                                }
                                IconButton(onClick = { focused = batch.batchId to item.itemId }) {
                                    Icon(Icons.Default.PhotoLibrary, contentDescription = parityText("Open", "Öffnen", "Ouvrir", "Openen"))
                                }
                            }
                        }
                    }
                }
            }
        }
        GalleryActionBar {
            GalleryAction(
                icon = Icons.Default.CheckCircle,
                label = parityText("Select all", "Alle auswählen", "Tout sélectionner", "Alles selecteren"),
                enabled = ui.panoramaxBatches.any { it.batchId !in ui.panoramaxActiveUploadBatchIds && it.state != PanoramaxBatchState.CAPTURING },
                onClick = {
                    selected = ui.panoramaxBatches.filter { it.batchId !in ui.panoramaxActiveUploadBatchIds && it.state != PanoramaxBatchState.CAPTURING }
                        .associate { batch -> batch.batchId to batch.items.map { it.itemId }.toSet() }
                },
            )
            GalleryAction(
                icon = Icons.Default.RadioButtonUnchecked,
                label = parityText("Select none", "Auswahl aufheben", "Tout désélectionner", "Niets selecteren"),
                enabled = count > 0,
                onClick = { selected = emptyMap() },
            )
            GalleryAction(
                icon = Icons.Default.Delete,
                label = "${deleteLabel()} ($count)",
                enabled = count > 0 && controller.canProcessPanoramaxUploads() &&
                    selected.keys.none { it in ui.panoramaxActiveUploadBatchIds },
                onClick = { deleteConfirmation = true },
            )
            Spacer(Modifier.weight(1f))
            if (ui.panoramaxActiveUploadBatchIds.isEmpty()) {
                GalleryAction(
                    icon = Icons.Default.Upload,
                    label = "${parityText("Upload", "Hochladen", "Envoyer", "Uploaden")} ($count)",
                    enabled = count > 0 && controller.canProcessPanoramaxUploads() && ui.panoramaxAccountConnected,
                    onClick = { uploadConfirmation = true },
                )
            } else {
                GalleryAction(
                    icon = Icons.Default.Stop,
                    label = parityText("Stop", "Stopp", "Arrêter", "Stoppen"),
                    enabled = true,
                    onClick = controller::stopPanoramaxUploads,
                )
            }
        }
    }
    if (deleteConfirmation) ParityDeleteConfirmation(count, { deleteConfirmation = false }) {
        controller.deletePanoramaxItems(selected); selected = emptyMap(); deleteConfirmation = false
    }
    if (uploadConfirmation) AlertDialog(onDismissRequest = { uploadConfirmation = false },
        title = { Text(parityText("Upload selected photos?", "Ausgewählte Fotos hochladen?", "Envoyer les photos sélectionnées ?", "Geselecteerde foto’s uploaden?")) },
        text = { Text(parityText("The selected photos and their GPS locations will be sent to Panoramax for publication.",
            "Die ausgewählten Fotos und ihre GPS-Positionen werden zur Veröffentlichung an Panoramax gesendet.",
            "Les photos sélectionnées et leurs positions GPS seront envoyées à Panoramax pour publication.",
            "De geselecteerde foto’s en hun GPS-locaties worden naar Panoramax verzonden voor publicatie.")) },
        confirmButton = { TextButton(onClick = { controller.uploadPanoramaxSelections(selected); uploadConfirmation = false }) {
            Text(parityText("Upload", "Hochladen", "Envoyer", "Uploaden")) } }, dismissButton = { TextButton(onClick = { uploadConfirmation = false }) { Text(cancelLabel()) } })
    focused?.let { (batchId, itemId) ->
        ui.panoramaxBatches.firstOrNull { it.batchId == batchId }?.items?.firstOrNull { it.itemId == itemId }?.let { item ->
            SheetScaffold(dateText(item.metadata.capturedAt), { focused = null }, "panoramax-original-sheet") {
                var scale by remember(itemId) { mutableStateOf(1f) }
                var offset by remember(itemId) { mutableStateOf(Offset.Zero) }
                Box(Modifier.fillMaxSize().clip(RoundedCornerShape(8.dp)).background(Color.Black).pointerInput(itemId) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scale = (scale * zoom).coerceIn(1f, 8f)
                        offset = if (scale == 1f) Offset.Zero else offset + pan
                    }
                }) {
                    LocalPhoto(controller.panoramaxOriginalFile(item), Modifier.fillMaxSize().graphicsLayer {
                        scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y
                    }, 4096, ContentScale.Fit)
                }
            }
        }
    }
}

private fun itemStateLabel(state: PanoramaxItemState): String = when (state) {
    PanoramaxItemState.CAPTURED -> parityText("Awaiting review", "Zur Prüfung", "À vérifier", "Te controleren")
    PanoramaxItemState.INCLUDED -> parityText("Included", "Einbezogen", "Incluse", "Opgenomen")
    PanoramaxItemState.EXCLUDED -> parityText("Excluded", "Ausgeschlossen", "Exclue", "Uitgesloten")
    PanoramaxItemState.QUEUED -> parityText("Queued", "Wartend", "En attente", "In wachtrij")
    PanoramaxItemState.UPLOADING -> parityText("Uploading", "Wird hochgeladen", "Envoi en cours", "Uploaden")
    PanoramaxItemState.UPLOADED -> parityText("Processing", "Wird verarbeitet", "Traitement", "Verwerken")
    PanoramaxItemState.ACCEPTED -> parityText("Accepted", "Angenommen", "Acceptée", "Geaccepteerd")
    PanoramaxItemState.DUPLICATE -> parityText("Duplicate", "Duplikat", "Doublon", "Duplicaat")
    PanoramaxItemState.REJECTED -> parityText("Rejected", "Abgelehnt", "Rejetée", "Afgewezen")
    PanoramaxItemState.RETRYABLE_ERROR -> parityText("Retry available", "Erneut versuchen", "Nouvel essai possible", "Opnieuw proberen")
    PanoramaxItemState.PERMANENT_ERROR -> parityText("Upload failed", "Upload fehlgeschlagen", "Échec de l’envoi", "Upload mislukt")
    PanoramaxItemState.ABANDONED -> parityText("Stopped", "Gestoppt", "Arrêtée", "Gestopt")
}

@Composable
private fun LocalPhoto(file: File, modifier: Modifier, maximumDimension: Int, contentScale: ContentScale = ContentScale.Crop, fallbackFile: File? = null) {
    val bitmap by produceState<Bitmap?>(null, file.absolutePath, fallbackFile?.absolutePath, maximumDimension) {
        value = withContext(Dispatchers.IO) {
            runCatching { loadPhoto(file, maximumDimension) }.getOrNull()
                ?: fallbackFile?.let { runCatching { loadPhoto(it, maximumDimension) }.getOrNull() }
        }
    }
    if (bitmap != null) Image(requireNotNull(bitmap).asImageBitmap(), parityText("Captured photo", "Aufgenommenes Foto", "Photo capturée", "Gemaakte foto"), modifier, contentScale = contentScale)
    else Box(modifier.background(Color.DarkGray), contentAlignment = Alignment.Center) {
        Text(parityText("Photo unavailable", "Foto nicht verfügbar", "Photo indisponible", "Foto niet beschikbaar"), color = Color.White)
    }
}

private fun loadPhoto(file: File, maximumDimension: Int): Bitmap? {
    if (!file.isFile) return null
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.absolutePath, bounds)
    var sample = 1
    while (max(bounds.outWidth, bounds.outHeight) / sample > maximumDimension) sample *= 2
    val source = BitmapFactory.decodeFile(file.absolutePath, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
    val orientation = ExifInterface(file).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
    val matrix = Matrix().apply {
        when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> postRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> postRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> postRotate(270f)
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> postScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> postScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { postScale(-1f, 1f); postRotate(90f) }
            ExifInterface.ORIENTATION_TRANSVERSE -> { postScale(-1f, 1f); postRotate(270f) }
        }
    }
    if (matrix.isIdentity) return source
    return Bitmap.createBitmap(source, 0, 0, source.width, source.height, matrix, true).also { if (it !== source) source.recycle() }
}

@Composable
internal fun TrafficSignDetailsContent(controller: ConsumerSessionController) {
    val ui = controller.uiState
    val event = ui.trafficSignLastEvent
    val candidate = event?.candidate
    val status = when {
        !ui.trafficSignRecognitionEnabled -> parityText("Disabled", "Ausgeschaltet", "Désactivée", "Uitgeschakeld")
        ui.trafficSignRecognitionUnavailable -> parityText("Unavailable", "Nicht verfügbar", "Indisponible", "Niet beschikbaar")
        event?.state == TrafficSignRecognitionState.PROVISIONAL -> parityText("Provisional", "Vorläufig", "Provisoire", "Voorlopig")
        event?.state == TrafficSignRecognitionState.CONFIRMED -> parityText("Confirmed", "Bestätigt", "Confirmée", "Bevestigd")
        event?.state == TrafficSignRecognitionState.UNKNOWN -> parityText("Unknown sign", "Unbekanntes Schild", "Panneau inconnu", "Onbekend bord")
        else -> parityText("No recognition", "Keine Erkennung", "Aucune reconnaissance", "Geen herkenning")
    }
    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { ParitySection(parityText("Camera recognition", "Kameraerkennung", "Reconnaissance par caméra", "Cameraherkenning")) {
            Text(status, fontWeight = FontWeight.SemiBold)
            if (ui.trafficSignRecognitionEnabled && !ui.trafficSignRecognitionUnavailable &&
                event?.state in setOf(TrafficSignRecognitionState.PROVISIONAL, TrafficSignRecognitionState.CONFIRMED)) {
                candidate?.semantic?.value?.let { Text("$it km/h", style = MaterialTheme.typography.headlineMedium) }
            }
            Text(parityText("A visible sign is provisional until its passage is confirmed. Always observe the road signs.",
                "Ein sichtbares Schild ist vorläufig, bis die Vorbeifahrt bestätigt ist. Beachte immer die Verkehrszeichen.",
                "Un panneau visible reste provisoire jusqu’à confirmation du passage. Respectez toujours les panneaux routiers.",
                "Een zichtbaar bord is voorlopig totdat het passeren is bevestigd. Volg altijd de verkeersborden."))
            if (ui.trafficSignRecognitionUnavailable) Text(ui.trafficSignCameraRuntimeDetail, color = MaterialTheme.colorScheme.error)
        } }
        if (event != null) item { ParitySection(parityText("Recognition context", "Erkennungskontext", "Contexte de reconnaissance", "Herkenningscontext")) {
            Text(parityText("Model: ", "Modell: ", "Modèle : ", "Model: ") + event.packId)
            event.roadContext?.let { road ->
                Text(parityText("Road: ", "Straße: ", "Route : ", "Weg: ") + (road.wayId ?: "—"))
                Text(String.format(Locale.getDefault(), "%.5f, %.5f · %.0f°", road.latitude, road.longitude, road.headingDegrees))
            }
            candidate?.let {
                if (it.calibratedConfidence != null) Text(parityText("Confidence: ", "Konfidenz: ", "Confiance : ", "Betrouwbaarheid: ") +
                    String.format(Locale.getDefault(), "%.1f%%", it.calibratedConfidence * 100))
                else Text(parityText("Raw score: ", "Rohwert: ", "Score brut : ", "Ruwe score: ") + String.format(Locale.getDefault(), "%.3f", it.rawScore))
                Text(parityText("Evidence frames: ", "Belegbilder: ", "Images de preuve : ", "Bewijsbeelden: ") + it.evidenceFrames)
            }
            Text(if (ui.cameraSpeedLimitEvidence) parityText("Camera limit is active.", "Kameralimit ist aktiv.", "La limite caméra est active.", "Cameralimiet is actief.")
                else parityText("The database or a local correction supplies the speed limit.", "Datenbank oder lokale Korrektur liefert das Tempolimit.",
                    "La carte ou une correction locale fournit la limite de vitesse.", "De kaart of een lokale correctie levert de snelheidslimiet."))
        } }
    }
}
