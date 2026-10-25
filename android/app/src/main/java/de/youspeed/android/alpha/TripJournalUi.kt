package de.youspeed.android.alpha

import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.widget.MediaController
import android.widget.VideoView
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.customActions
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import kotlin.math.*

private fun jt(en:String,de:String,fr:String,nl:String)=ConsumerUiStrings.text(en,de,fr,nl)
private fun tripDate(t:Double)=DateTimeFormatter.ofLocalizedDateTime(FormatStyle.SHORT).withZone(ZoneId.systemDefault()).format(Instant.ofEpochMilli((t*1000).toLong()))
private fun stateText(trip:JSONObject):String {
    val state=when(trip.optString("state")) {
        "active" -> jt("Running","Läuft","En cours","Actief")
        "finalizing" -> jt("Saving","Wird gespeichert","Enregistrement","Opslaan")
        "interrupted" -> jt("Interrupted","Unterbrochen","Interrompu","Onderbroken")
        else -> jt("Ended","Beendet","Terminée","Beëindigd")
    }
    return state+when { trip.optInt("valid_gps_count",trip.optInt("gps_count"))==0 -> " · "+jt("No GPS","Ohne GPS","Sans GPS","Geen GPS")
        trip.optInt("gap_count")>0 -> " · "+jt("Track gaps","Track mit Lücken","Tracé incomplet","Route met hiaten")
        trip.optDouble("distance")==0.0 -> " · "+jt("No movement","Ohne Bewegung","Sans mouvement","Geen beweging")
        else -> "" }
}

@Composable
internal fun rememberTripJournalRecordingEnabled(journal: TripJournal): Boolean {
    var enabled by remember(journal) { mutableStateOf(journal.enabled) }
    DisposableEffect(journal) {
        val stopObserving = journal.observeEnabled { enabled = it }
        onDispose { stopObserving() }
    }
    return enabled
}

@Composable
internal fun TripJournalRecordingPreferences(journal:TripJournal) {
    var enabled by remember(journal) {mutableStateOf(journal.enabled)}
    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
        Text(jt("Save trips automatically","Fahrten automatisch speichern","Enregistrer les trajets","Ritten automatisch bewaren"),modifier=Modifier.weight(1f),color=Color.Black)
        Switch(enabled,{enabled=it;journal.setEnabled(it)},modifier=Modifier.testTag("trip-journal-recording-toggle"))
    }
    Text(jt("Private local trip journal with GPS and traffic-sign logs. Trips can be deleted; the car odometer is optional. Tax recognition and official logbook compliance are not guaranteed.","Privates lokales Fahrtenjournal mit GPS- und Verkehrszeichen-Protokollen. Fahrten können gelöscht werden; der Fahrzeug-Kilometerstand ist freiwillig. Eine steuerliche Anerkennung und eine behördliche Fahrtenbuchauflage nach § 31a StVZO werden nicht zugesichert.","Journal local privé avec journaux GPS et panneaux. Trajets supprimables et compteur facultatif. Aucune reconnaissance fiscale ni conformité réglementaire garantie.","Privé lokaal rittenboek met GPS- en verkeersbordlogboeken. Ritten zijn verwijderbaar en de kilometerstand is optioneel. Geen fiscale erkenning of wettelijke conformiteit gegarandeerd."),style=MaterialTheme.typography.bodySmall,color=Color.Black,modifier=Modifier.testTag("trip-journal-recording-disclosure"))
    Text(jt("Disabling track storage keeps the measured app counters. Camera, sign contributions and public uploads have separate controls.","Ohne Trackspeicherung laufen die gemessenen App-Zähler weiter. Kamera, Schilderbeiträge und öffentliche Uploads bleiben separat steuerbar.","Sans tracé, les compteurs mesurés restent actifs. Caméra, contributions et publications ont leurs propres réglages.","Zonder routeopslag blijven gemeten tellers actief. Camera, bijdragen en publicaties hebben aparte instellingen."),style=MaterialTheme.typography.bodySmall,color=Color(0xFF555555))
}

/** Optional local storage choice in the existing Driving setup step. */
@Composable
internal fun TripJournalSetupOption(journal:TripJournal) {
    var enabled by remember(journal) {mutableStateOf(journal.enabled)}
    Column(verticalArrangement=Arrangement.spacedBy(8.dp),modifier=Modifier.testTag("onboarding-trip-journal-option")) {
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
            Text(jt("Save trips automatically (optional)","Fahrten automatisch speichern (optional)","Enregistrer les trajets automatiquement (facultatif)","Ritten automatisch bewaren (optioneel)"),color=Color.White,modifier=Modifier.weight(1f))
            Switch(enabled,{enabled=it;journal.setEnabled(it)},modifier=Modifier.testTag("onboarding-trip-journal-toggle"),
                colors=SwitchDefaults.colors(checkedTrackColor=Color(0xFFD21B24),checkedThumbColor=Color.White))
        }
        Text(jt("Saves routes and GPS/traffic-sign logs privately on this phone. Camera recording and public uploads have separate controls. You can change this later in Settings.","Speichert Routen und GPS-/Verkehrszeichen-Protokolle privat auf diesem Telefon. Kameraaufzeichnung und öffentliche Uploads werden separat gesteuert. Später in den Einstellungen änderbar.","Conserve les itinéraires et journaux GPS/panneaux en privé sur ce téléphone. Caméra et publications ont leurs propres réglages. Modifiable plus tard dans les réglages.","Bewaart routes en GPS-/verkeersbordlogs privé op deze telefoon. Cameraopname en openbare uploads hebben aparte instellingen. Later te wijzigen bij Instellingen."),color=Color(0xFFB9B9C0),style=MaterialTheme.typography.bodySmall)
    }
}

private val TRIP_COLUMN_WIDTHS=listOf(160.dp,220.dp,220.dp,110.dp,180.dp)
private val TRIP_TABLE_WIDTH=890.dp
private fun tripDateCell(trip:JSONObject):String {
    val zone=ZoneId.systemDefault();val start=Instant.ofEpochMilli((trip.optDouble("start")*1000).toLong()).atZone(zone)
    val end=Instant.ofEpochMilli((trip.optDouble("end",trip.optDouble("start"))*1000).toLong()).atZone(zone)
    val date=DateTimeFormatter.ofLocalizedDate(FormatStyle.SHORT);val time=DateTimeFormatter.ofLocalizedTime(FormatStyle.SHORT)
    return date.format(start)+"\n"+time.format(start)+" – "+(if(start.toLocalDate()!=end.toLocalDate()) date.format(end)+"\n" else "")+time.format(end)
}
@Composable
private fun TripHistoryCell(text:String,index:Int,tag:String,header:Boolean=false,onClick:(()->Unit)?=null) {
    Text(text,modifier=Modifier.width(TRIP_COLUMN_WIDTHS[index]).then(if(onClick!=null) Modifier.clickable(onClick=onClick) else Modifier).padding(8.dp).testTag(tag),fontWeight=if(header) FontWeight.Bold else FontWeight.Normal,style=MaterialTheme.typography.bodyMedium)
}
@Composable
private fun TripHistoryHeader() {
    Column(Modifier.width(TRIP_TABLE_WIDTH).testTag("trip-journal-table-header")) {
        Row {listOf(jt("Date / time","Datum / Uhrzeit","Date / heure","Datum / tijd"),jt("Start location","Startort","Lieu de départ","Beginlocatie"),jt("End location","Zielort","Lieu d’arrivée","Eindlocatie"),jt("Distance (km)","Distanz (km)","Distance (km)","Afstand (km)"),jt("Car end odometer (km)","Fahrzeug-Endstand (km)","Compteur final (km)","Eindstand voertuig (km)")).forEachIndexed {index,text->TripHistoryCell(text,index,"trip-journal-column-$index",true)}}
        HorizontalDivider()
    }
}
@Composable
private fun TripHistoryRow(trip:JSONObject,enabled:Boolean,onClick:()->Unit,onDetails:()->Unit,onShare:()->Unit,onDelete:()->Unit) {
    val id=trip.getString("id");val unknown=jt("Unknown location","Unbekannter Ort","Lieu inconnu","Onbekende locatie")
    Column(Modifier.width(TRIP_TABLE_WIDTH)) {
        Row(Modifier.width(TRIP_TABLE_WIDTH).testTag("trip-$id"),verticalAlignment=Alignment.Top) {
            listOf(tripDateCell(trip),trip.optString("start_place").ifBlank {unknown},trip.optString("end_place").ifBlank {unknown},TripJournalPresentation.distanceKilometres(trip.optDouble("distance"))).forEachIndexed {index,text->TripHistoryCell(text,index,"trip-$id-cell-$index",onClick=onClick)}
            Column(Modifier.width(TRIP_COLUMN_WIDTHS[4]).padding(8.dp).testTag("trip-$id-cell-4")) {
                Text(if(trip.has("odo_end")) TripJournalPresentation.odometerKilometres(trip.optDouble("odo_end")) else "—",modifier=Modifier.fillMaxWidth().clickable(onClick=onClick).padding(vertical=4.dp))
                Row(Modifier.testTag("trip-$id-actions")) {
                    TextButton(onShare,enabled=enabled,modifier=Modifier.testTag("trip-$id-share")) {Text(jt("Share","Teilen","Partager","Delen"))}
                    TextButton(onDelete,enabled=enabled,modifier=Modifier.testTag("trip-$id-delete")) {Text(jt("Delete","Löschen","Supprimer","Verwijderen"))}
                }
            }
        }
        HorizontalDivider()
    }
}

@Composable
internal fun TripJournalScreen(journal:TripJournal,mediaCleanup:((List<JSONObject>,Boolean)->String)?=null,mapDatabasePath:String?=null,galleryContent:(@Composable (List<JSONObject>,()->Unit)->Unit)?=null,onOpenSettings:()->Unit={},onDismiss:()->Unit) {
    val context=LocalContext.current;val scope=rememberCoroutineScope()
    var trips by remember {mutableStateOf(emptyList<JSONObject>())}
    var recordingEnabled by remember(journal) {mutableStateOf(journal.enabled)}
    var failure by remember {mutableStateOf<String?>(null)};var busy by remember {mutableStateOf(false)}
    var endingTrip by remember {mutableStateOf<String?>(null)};var endingInput by remember {mutableStateOf("")}
    var deletion by remember {mutableStateOf<String?>(null)};var deleteMedia by remember {mutableStateOf(false)}
    var deletionMedia by remember {mutableStateOf(emptyList<JSONObject>())};var cleanupPreview by remember {mutableStateOf("")}
    val tableScroll=rememberScrollState()
    fun share(file:File,type:String) {
        runCatching {
            val uri=FileProvider.getUriForFile(context,"${context.packageName}.fileprovider",file)
            context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { this.type=type;putExtra(Intent.EXTRA_STREAM,uri);addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) },jt("Share","Teilen","Partager","Delen")))
        }.onFailure { failure=it.message }
    }
    fun task(body:suspend ()->Unit) {scope.launch {busy=true;runCatching {body()}.onFailure {failure=it.cause?.message ?: it.message};busy=false}}
    LaunchedEffect(journal) {while(true) {
        withContext(Dispatchers.IO) {runCatching {journal.history()}}.onSuccess {trips=it}.onFailure {failure=it.cause?.message ?: it.message ?: "Unable to read journal"}
        recordingEnabled=journal.enabled
        delay(2000)
    }}
    SheetScaffold(jt("Trip journal","Fahrtenbuch","Carnet de trajets","Rittenboek"),onDismiss,"trip-journal-sheet",containerColor=Color.White) {
        LazyColumn(Modifier.fillMaxSize().testTag("trip-journal-list")) {
            item {Box(Modifier.fillMaxWidth().horizontalScroll(tableScroll)) {TripHistoryHeader()}}
            if(!recordingEnabled) item {
                Column(Modifier.widthIn(max=280.dp).padding(8.dp)) {
                    Text(jt("Trip recording is off. Enable it in Settings to save future trips.","Fahrtenaufzeichnung ist aus. In den Einstellungen aktivieren, um künftige Fahrten zu speichern.","L’enregistrement des trajets est désactivé. Activez-le dans les réglages pour enregistrer les prochains trajets.","Ritten opnemen staat uit. Schakel dit in bij Instellingen om toekomstige ritten op te slaan."),modifier=Modifier.testTag("trip-journal-recording-off"))
                    TextButton(onOpenSettings,modifier=Modifier.testTag("trip-journal-open-settings")) {Text(jt("Recording settings","Aufzeichnungseinstellungen","Réglages d’enregistrement","Opname-instellingen"))}
                }
            }
            items(trips,key={it.getString("id")}) {trip ->
                val id=trip.getString("id")
                Box(Modifier.fillMaxWidth().horizontalScroll(tableScroll)) {
                    TripHistoryRow(trip,!busy,{endingInput="";endingTrip=id},{},{task {val archive=withContext(Dispatchers.IO) {journal.archive(id,TripExportOptions(includeRawLogs=true))};share(archive,"application/zip")}},{task {
                        deletionMedia=withContext(Dispatchers.IO) {TripJournalProjection.media(journal.events(id))};deleteMedia=false
                        cleanupPreview=withContext(Dispatchers.IO) {mediaCleanup?.invoke(deletionMedia,false).orEmpty()};deletion=id
                    }})
                }
            }
            if(trips.isEmpty() && recordingEnabled) item {Text(jt("No saved trips.","Keine gespeicherten Fahrten.","Aucun trajet enregistré.","Geen bewaarde ritten."),modifier=Modifier.padding(8.dp).testTag("trip-journal-empty"))}
            (failure ?: journal.error)?.let {message ->item {Text(message,color=MaterialTheme.colorScheme.error,modifier=Modifier.testTag("trip-journal-error"))}}
        }
    }
    endingTrip?.let {id ->trips.firstOrNull {it.optString("id")==id}?.let {target ->
        val entered=TripJournalPresentation.endingKilometres(endingInput,target.optDouble("odo_start",0.0))
        SheetScaffold(jt("Ending car odometer (km)","Fahrzeug-Endkilometerstand (km)","Compteur final (km)","Eindkilometerstand (km)"),{endingTrip=null},"trip-ending-odometer-sheet",containerColor=Color.White,compact=true) {
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                if(target.has("odo_end")) Text(TripJournalPresentation.odometerKilometres(target.optDouble("odo_end"))+" km",modifier=Modifier.testTag("trip-ending-odometer-saved"))
                else {
                    OutlinedTextField(endingInput,{endingInput=it},label={Text(jt("Ending odometer (km)","Endkilometerstand (km)","Compteur final (km)","Eindkilometerstand (km)"))},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),isError=endingInput.isNotBlank() && entered==null,modifier=Modifier.fillMaxWidth().testTag("trip-ending-odometer-input"))
                    if(endingInput.isNotBlank() && entered==null) Text(jt("Enter a valid value at least as large as the starting odometer.","Gültigen Wert mindestens in Höhe des Startkilometerstands eingeben.","Saisissez une valeur valide au moins égale au compteur de départ.","Vul een geldige stand in die minstens gelijk is aan de beginstand."),color=MaterialTheme.colorScheme.error,modifier=Modifier.testTag("trip-ending-odometer-error"))
                }
                Button({task {if(!target.has("odo_end") && entered!=null) withContext(Dispatchers.IO) {journal.setEndingOdometer(id,entered)};trips=withContext(Dispatchers.IO) {journal.history()};endingTrip=null}},enabled=!busy && (target.has("odo_end") || endingInput.isBlank() || entered!=null),modifier=Modifier.testTag("trip-ending-odometer-save")) {Text(jt("Save","Speichern","Enregistrer","Opslaan"))}
            }
        }
    }}
    deletion?.let { id -> AlertDialog({deletion=null},title={Text(jt("Delete trip?","Fahrt löschen?","Supprimer ce trajet ?","Rit verwijderen?"))},text={Column { Text(jt("GPS/TSR logs, signs, optional odometer, trip media links and temporary exports are deleted. Library files and public copies remain. Lifetime app counters remain; saved-history totals decrease.","GPS-/TSR-Protokolle, Zeichen, optionale Kilometerstände, Medienverknüpfungen und temporäre Exporte werden gelöscht. Bibliotheksdateien und öffentliche Kopien bleiben. App-Gesamtzähler bleiben; die gespeicherte Fahrtsumme sinkt.","Journaux, panneaux, compteur facultatif, liens et exports temporaires supprimés. Fichiers de bibliothèque et copies publiques conservés. Compteurs globaux inchangés ; total conservé réduit.","Logs, borden, optionele standen, koppelingen en tijdelijke exports worden gewist. Bibliotheek en openbare kopieën blijven. Levenslange tellers blijven; bewaarde totalen dalen."));if(mediaCleanup!=null) {Text(cleanupPreview);Row {Checkbox(deleteMedia,{deleteMedia=it});Text(jt("Also delete eligible local media","Löschbare lokale Medien ebenfalls löschen","Supprimer aussi les médias locaux autorisés","Ook verwijderbare lokale media wissen"))}} }},confirmButton={TextButton({task {if(deleteMedia) failure=withContext(Dispatchers.IO) {mediaCleanup?.invoke(deletionMedia,true)};journal.delete(id);trips=withContext(Dispatchers.IO) {journal.history()};deletion=null}}) {Text(jt("Delete","Löschen","Supprimer","Verwijderen"))}},dismissButton={TextButton({deletion=null}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}}) }
}

@Composable
internal fun TripJournalDataManagement(journal:TripJournal) {
    val context=LocalContext.current;val scope=rememberCoroutineScope()
    var expanded by remember {mutableStateOf(false)};var busy by remember {mutableStateOf(false)}
    var failure by remember {mutableStateOf<String?>(null)};var clear by remember {mutableStateOf(false)}
    var backupDialog by remember {mutableStateOf(false)};var passphrase by remember {mutableStateOf("")}
    var restoreFile by remember {mutableStateOf<File?>(null)};var restorePreview by remember {mutableStateOf<JSONObject?>(null)}
    fun share(file:File,type:String) {
        runCatching {
            val uri=FileProvider.getUriForFile(context,"${context.packageName}.fileprovider",file)
            context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { this.type=type;putExtra(Intent.EXTRA_STREAM,uri);addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) },jt("Share","Teilen","Partager","Delen")))
        }.onFailure { failure=it.message }
    }
    fun task(body:suspend ()->Unit) {scope.launch {busy=true;runCatching {body()}.onFailure {failure=it.cause?.message ?: it.message};busy=false}}
    val picker=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if(uri!=null) task {
            val f=withContext(Dispatchers.IO) {
                File(context.cacheDir,"journal-restore-${java.util.UUID.randomUUID()}.json").also { target ->
                    context.contentResolver.openInputStream(uri).use { input -> requireNotNull(input);target.outputStream().use { output ->
                        val buffer=ByteArray(65536);var total=0L
                        while(true) { val n=input.read(buffer);if(n<0) break;total+=n;require(total<=512_000_000) { "Backup too large" };output.write(buffer,0,n) }
                    } }
                }
            };restoreFile=f;backupDialog=true
        }
    }
    TextButton({expanded=!expanded},modifier=Modifier.testTag("trip-journal-data-disclosure")) {Text((if(expanded) "▾ " else "▸ ")+jt("Trip data","Fahrtdaten","Données des trajets","Ritgegevens"))}
    if(expanded) {
        TextButton({passphrase="";restoreFile=null;backupDialog=true},enabled=!busy,modifier=Modifier.testTag("trip-journal-backup")) {Text(jt("Encrypted backup","Verschlüsselte Sicherung","Sauvegarde chiffrée","Versleutelde back-up"))}
        TextButton({picker.launch(arrayOf("application/json","application/octet-stream"))},enabled=!busy,modifier=Modifier.testTag("trip-journal-restore")) {Text(jt("Restore","Wiederherstellen","Restaurer","Herstellen"))}
        TextButton({clear=true},enabled=!busy,modifier=Modifier.testTag("trip-journal-clear")) {Text(jt("Clear all trips and counters","Alle Fahrtdaten und Zähler löschen","Effacer trajets et compteurs","Alle ritten en tellers wissen"))}
        failure?.let {Text(it,color=MaterialTheme.colorScheme.error)}
    }
    if(clear) AlertDialog({clear=false},title={Text(jt("Clear all trips and counters?","Alle Fahrtdaten und Zähler löschen?","Tout effacer ?","Alle ritten en tellers wissen?"))},text={Text(jt("This removes the entire private journal and creates a new zero counter epoch. Library media and already shared files remain.","Das gesamte private Journal wird entfernt und eine neue Zählerepoche bei null beginnt. Bibliotheksmedien und bereits geteilte Dateien bleiben.","Le journal privé est supprimé et les compteurs repartent à zéro. Médias de bibliothèque et fichiers partagés conservés.","Het privélogboek wordt verwijderd en een nieuw teltijdvak begint op nul. Bibliotheekmedia en gedeelde bestanden blijven."))},confirmButton={TextButton({task {withContext(Dispatchers.IO) {journal.clearAll()};clear=false}}) {Text(jt("Clear everything","Alles löschen","Tout effacer","Alles wissen"))}},dismissButton={TextButton({clear=false}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}})
    if(backupDialog) AlertDialog({backupDialog=false;restoreFile?.delete();restoreFile=null;restorePreview=null},title={Text(if(restoreFile==null) jt("Encrypted local backup","Verschlüsselte lokale Sicherung","Sauvegarde locale chiffrée","Versleutelde lokale back-up") else jt("Restore backup","Sicherung wiederherstellen","Restaurer la sauvegarde","Back-up herstellen"))},text={Column {
        Text(jt("AES-256-GCM encrypted. Keep the passphrase: it cannot be recovered. Includes trips, private logs, counters and media references; original media stays in the library.","AES-256-GCM-verschlüsselt. Passwort aufbewahren: Es kann nicht wiederhergestellt werden. Enthält Fahrten, private Protokolle, Zähler und Medienreferenzen; Originalmedien bleiben in der Bibliothek.","Chiffrement AES-256-GCM. Gardez le mot de passe, irrécupérable. Inclut trajets, journaux, compteurs et références ; médias dans la bibliothèque.","AES-256-GCM-versleuteld. Bewaar het wachtwoord: herstel is onmogelijk. Ritten, logs, tellers en mediaverwijzingen inbegrepen; media blijven in bibliotheek."))
        OutlinedTextField(passphrase,{passphrase=it;restorePreview=null},label={Text(jt("Passphrase (8+ characters)","Passwort (mind. 8 Zeichen)","Mot de passe (8 caractères min.)","Wachtwoord (min. 8 tekens)"))},visualTransformation=PasswordVisualTransformation())
        restorePreview?.let { p -> Text(jt("Whole-journal replacement","Ersetzt das gesamte Journal","Remplace tout le journal","Vervangt het hele logboek")+": ${p.optInt("trip_count")} · %.3f km · %.2f h".format(p.getJSONObject("counters").optDouble("distance")/1000,p.getJSONObject("counters").optDouble("usage")/3600)) }
        failure?.let { Text(it,color=MaterialTheme.colorScheme.error) }
    }},confirmButton={TextButton({task { val file=restoreFile
        if(file==null) { val backup=withContext(Dispatchers.IO) {journal.backup(passphrase)};share(backup,"application/json");backupDialog=false;passphrase="" }
        else if(restorePreview==null) { restorePreview=withContext(Dispatchers.IO) {journal.backupPreview(file,passphrase)} }
        else { withContext(Dispatchers.IO) {journal.restore(file,passphrase)};file.delete();restoreFile=null;restorePreview=null;backupDialog=false;passphrase="" }
    }},enabled=passphrase.length>=8 && !busy) {Text(if(restoreFile==null) jt("Create and share","Erstellen und teilen","Créer et partager","Maken en delen") else if(restorePreview==null) jt("Validate and preview","Prüfen und Vorschau","Vérifier et prévisualiser","Controleren en bekijken") else jt("Replace entire journal","Gesamtes Journal ersetzen","Remplacer tout le journal","Heel logboek vervangen"))}},dismissButton={TextButton({backupDialog=false;restoreFile?.delete();restoreFile=null;restorePreview=null;passphrase=""}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}})
}

@Composable
private fun ArchivedTripJournalDetailScreen(journal:TripJournal,mediaCleanup:((List<JSONObject>,Boolean)->String)?=null,mapDatabasePath:String?=null,galleryContent:(@Composable (List<JSONObject>,()->Unit)->Unit)?=null,onDismiss:()->Unit) {
    val context=LocalContext.current;val scope=rememberCoroutineScope()
    var roadContext by remember {mutableStateOf(TripJournalMapContext.Result(emptyList()))}
    var trips by remember { mutableStateOf(emptyList<JSONObject>()) };var counters by remember { mutableStateOf(JSONObject()) }
    var selected by remember { mutableStateOf<String?>(null) };var events by remember { mutableStateOf(emptyList<JSONObject>()) }
    var failure by remember { mutableStateOf<String?>(null) }
    var showFilters by remember {mutableStateOf(false)};var odometerUnit by remember {mutableStateOf("km")}
    var search by remember { mutableStateOf("") };var vehicleFilter by remember { mutableStateOf("") };var signFilter by remember { mutableStateOf("") }
    var dateFrom by remember { mutableStateOf("") };var dateTo by remember { mutableStateOf("") }
    var period by remember { mutableStateOf(0) };var mediaFilter by remember { mutableStateOf("all") };var interruptedOnly by remember { mutableStateOf(false) }
    var eventFilter by remember { mutableStateOf("all") };var selectedTime by remember { mutableStateOf<Double?>(null) };var logLimit by remember { mutableStateOf(100) }
    var reading by remember { mutableStateOf("") };var vehicle by remember { mutableStateOf("") };var deletion by remember { mutableStateOf<String?>(null) }
    var deleteMedia by remember { mutableStateOf(false) };var cleanupPreview by remember { mutableStateOf("") };var deletionMedia by remember {mutableStateOf(emptyList<JSONObject>())}
    var endingTrip by remember {mutableStateOf<String?>(null)};var endingInput by remember {mutableStateOf("")}
    val tableScroll=rememberScrollState()
    var clear by remember { mutableStateOf(false) };var exportOptions by remember { mutableStateOf(false) };var busy by remember { mutableStateOf(false) }
    var selectedMedia by remember { mutableStateOf(emptySet<String>()) };var maskHome by remember { mutableStateOf(false) };var includeOdometer by remember { mutableStateOf(false) }
    var privateShare by remember { mutableStateOf(false) };var maskRadius by remember { mutableStateOf("300") };var logs by remember { mutableStateOf(true) };var includeMedia by remember { mutableStateOf(false) }
    var backupDialog by remember { mutableStateOf(false) };var passphrase by remember { mutableStateOf("") };var restoreFile by remember { mutableStateOf<File?>(null) };var restorePreview by remember { mutableStateOf<JSONObject?>(null) }
    var library by remember {mutableStateOf(false)}
    var playing by remember { mutableStateOf<TripJournalProjection.Seek?>(null) };var photo by remember { mutableStateOf<String?>(null) };var replay by remember { mutableStateOf(false) }
    fun share(file:File,type:String) {
        runCatching {
            val uri=FileProvider.getUriForFile(context,"${context.packageName}.fileprovider",file)
            context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { this.type=type;putExtra(Intent.EXTRA_STREAM,uri);addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) },jt("Share","Teilen","Partager","Delen")))
        }.onFailure { failure=it.message }
    }
    fun task(body:suspend ()->Unit) { scope.launch { busy=true;runCatching { body() }.onFailure { failure=it.cause?.message ?: it.message };busy=false } }
    fun requestDelete(id:String) {task {
        val owned=withContext(Dispatchers.IO) {TripJournalProjection.media(journal.events(id))}
        deletionMedia=owned;deleteMedia=false
        cleanupPreview=withContext(Dispatchers.IO) {mediaCleanup?.invoke(owned,false).orEmpty()};deletion=id
    }}
    fun shareTrip(id:String) {task {val archive=withContext(Dispatchers.IO) {journal.archive(id,TripExportOptions(includeRawLogs=true))};share(archive,"application/zip")}}
    val picker=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if(uri!=null) task {
            val f=withContext(Dispatchers.IO) {
                File(context.cacheDir,"journal-restore-${java.util.UUID.randomUUID()}.json").also { target ->
                    context.contentResolver.openInputStream(uri).use { input -> requireNotNull(input);target.outputStream().use { output ->
                        val buffer=ByteArray(65536);var total=0L
                        while(true) { val n=input.read(buffer);if(n<0) break;total+=n;require(total<=512_000_000) { "Backup too large" };output.write(buffer,0,n) }
                    } }
                }
            };restoreFile=f;backupDialog=true
        }
    }
    LaunchedEffect(selected) { while(true) {
        val loaded=withContext(Dispatchers.IO) { runCatching { journal.snapshot() to (selected?.let { journal.events(it) } ?: emptyList()) } }
        loaded.onSuccess { (snapshot,log) -> trips=snapshot.first;counters=snapshot.second;events=log }
            .onFailure { failure=it.cause?.message ?: it.message ?: "Unable to read journal";events=emptyList() }
        delay(2000)
    } }
    val routeRevision=events.count {it.optString("kind")=="gps"}
    LaunchedEffect(selected,mapDatabasePath,routeRevision) {
        val result=withContext(Dispatchers.IO) {runCatching {TripJournalMapContext.load(mapDatabasePath,events)}}
        roadContext=result.getOrDefault(TripJournalMapContext.Result(emptyList()))
    }
    LaunchedEffect(replay,selected) {
        if(replay) {
            val points=events.filter { it.optString("kind")=="gps" && TripJournalProjection.trackEligible(TripJournalProjection.payload(it)) }
            val start=points.indexOfFirst { it.optDouble("time")>=(selectedTime ?: 0.0) }.coerceAtLeast(0)
            points.drop(start).forEach { selectedTime=it.optDouble("time");delay(250) };replay=false
        }
    }
    val (from,to)=TripJournalPeriod.bounds(LocalDate.now(),ZoneId.systemDefault(),listOf(0,7,30,365)[period],dateFrom,dateTo)
    val validDates=TripJournalPeriod.validCustom(dateFrom,dateTo)
    val filtered=trips.filter { t ->
        t.optDouble("start")>=from && t.optDouble("start")<to && (signFilter.isBlank() || t.optString("sign_classes").contains(signFilter,true)) && (mediaFilter=="all" || t.optInt(if(mediaFilter=="photo") "photo_count" else "video_count")>0) && (!interruptedOnly || t.optString("state")=="interrupted" || t.optInt("gap_count")>0) &&
            (vehicleFilter.isBlank() || t.optString("vehicle").contains(vehicleFilter,true)) &&
            (search.isBlank() || listOf("vehicle","start_place","end_place").any { t.optString(it).contains(search,true) } || tripDate(t.optDouble("start")).contains(search,true))
    }
    val trip=trips.firstOrNull { it.optString("id")==selected }
    val discoveries=remember(events) { TripJournalProjection.discoveries(events) }
    val media=remember(events) { TripJournalProjection.media(events) }
    val visibleEvents=events.filter { e -> (eventFilter=="all" || e.optString("kind")==eventFilter) && (signFilter.isBlank() || TripJournalProjection.payload(e).toString().contains(signFilter,true)) }
    SheetScaffold(jt("Trip journal","Fahrtenbuch","Carnet de trajets","Rittenboek"),onDismiss,"trip-journal-sheet",onBack=if(selected!=null) ({selected=null;selectedTime=null}) else null,containerColor=Color.White) {
        LazyColumn(Modifier.fillMaxSize().testTag("trip-journal-list"),verticalArrangement=Arrangement.spacedBy(12.dp)) {
            item { Text("YouSpeed: %.3f km · %.2f h".format(counters.optDouble("distance",0.0)/1000,counters.optDouble("usage",0.0)/3600),style=MaterialTheme.typography.titleMedium)
                Text(jt("Since ","Seit ","Depuis ","Sinds ")+tripDate(counters.optDouble("origin",0.0))+" · %.1f MB".format(journal.storageBytes()/1_000_000.0),style=MaterialTheme.typography.bodySmall) }
            item { (failure ?: journal.error)?.let { Text(it,color=MaterialTheme.colorScheme.error,modifier=Modifier.testTag("trip-journal-error")) };if(busy) LinearProgressIndicator(Modifier.fillMaxWidth()) }
            if(selected==null) {
                item {TextButton({showFilters=!showFilters},modifier=Modifier.testTag("trip-journal-filters")) {Text(jt("Filters","Filter","Filtres","Filters"))}}
                if(showFilters) {
                item { OutlinedTextField(search,{search=it},label={Text(jt("Search local place/date/vehicle","Ort, Datum, Fahrzeug suchen","Lieu, date, véhicule","Plaats, datum, voertuig"))},modifier=Modifier.fillMaxWidth()) }
                item { Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(8.dp)) { listOf(jt("All","Alle","Tous","Alle"),jt("7 days","7 Tage","7 jours","7 dagen"),jt("30 days","30 Tage","30 jours","30 dagen"),jt("365 days","365 Tage","365 jours","365 dagen")).forEachIndexed { i,label -> FilterChip(period==i,{period=i},label={Text(label)}) } } }
                item { Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {OutlinedTextField(dateFrom,{dateFrom=it},label={Text(jt("From YYYY-MM-DD","Von JJJJ-MM-TT","Du AAAA-MM-JJ","Vanaf JJJJ-MM-DD"))},isError=!validDates,modifier=Modifier.weight(1f));OutlinedTextField(dateTo,{dateTo=it},label={Text(jt("Through YYYY-MM-DD","Bis JJJJ-MM-TT","Au AAAA-MM-JJ","Tot JJJJ-MM-DD"))},isError=!validDates,modifier=Modifier.weight(1f))}
                    if(!validDates) Text(jt("Enter valid From and Through dates, in that order. Clear both to use the selected period.","Gültige Von- und Bis-Daten in dieser Reihenfolge eingeben. Beide Felder leeren, um den gewählten Zeitraum zu verwenden.","Saisissez des dates de début et de fin valides, dans cet ordre. Effacez les deux pour utiliser la période choisie.","Vul geldige begin- en einddatums in, in die volgorde. Wis beide om de gekozen periode te gebruiken."),color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodySmall,modifier=Modifier.testTag("trip-journal-date-error"))
                }
                item {OutlinedTextField(signFilter,{signFilter=it},label={Text(jt("Sign class","Zeichenklasse","Classe de panneau","Bordklasse"))},modifier=Modifier.fillMaxWidth())}
                item { OutlinedTextField(vehicleFilter,{vehicleFilter=it},label={Text(jt("Vehicle filter","Fahrzeugfilter","Filtre véhicule","Voertuigfilter"))},modifier=Modifier.fillMaxWidth()) }
                item {Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(8.dp)) {listOf("all" to jt("All media","Alle Medien","Tous médias","Alle media"),"photo" to jt("Photos","Fotos","Photos","Foto’s"),"video" to jt("Videos","Videos","Vidéos","Video’s")).forEach {(value,label)->FilterChip(mediaFilter==value,{mediaFilter=value},label={Text(label)})}}}
                item { Row { FilterChip(interruptedOnly,{interruptedOnly=!interruptedOnly},label={Text(jt("With gaps","Mit Lücken","Avec lacunes","Met hiaten"))}) } }
                }
                item { Text(jt("Saved trips","Gespeicherte Fahrten","Trajets conservés","Bewaarde ritten")+": ${filtered.size} · %.3f km · %.1f h".format(filtered.sumOf { it.optDouble("distance") }/1000,filtered.sumOf { it.optDouble("duration") }/3600));TripPeriodChart(filtered);TripPeriodChart(filtered,time=true) }
                if(filtered.isEmpty()) item { Text(jt("No saved trips in this period.","Keine gespeicherten Fahrten in diesem Zeitraum.","Aucun trajet conservé sur cette période.","Geen bewaarde ritten in deze periode.")) }
            }
            if(selected==null) {
                item {Box(Modifier.fillMaxWidth().horizontalScroll(tableScroll)) {TripHistoryHeader()}}
                items(filtered,key={it.getString("id")}) { t ->
                    val id=t.getString("id")
                    Box(Modifier.fillMaxWidth().horizontalScroll(tableScroll)) {
                        TripHistoryRow(t,!busy,{endingInput="";endingTrip=id},{selected=id;logLimit=100;selectedTime=null},{shareTrip(id)},{requestDelete(id)})
                    }
                }
            } else if(trip!=null) item {Text(tripDate(trip.optDouble("start"))+" · "+stateText(trip),style=MaterialTheme.typography.titleMedium)}
            if(trip!=null) {
                item { Text(jt("Map and replay","Karte und Wiedergabe","Carte et lecture","Kaart en afspelen"),style=MaterialTheme.typography.titleMedium)
                    TripRoutePlot(events,selectedTime,roadContext.roads) { selectedTime=it }
                    if(roadContext.roads.isNotEmpty()) Text(jt("Installed offline road map","Installierte Offline-Straßenkarte","Carte routière hors ligne installée","Geïnstalleerde offlinewegenkaart"),style=MaterialTheme.typography.bodySmall)
                    else Text(jt("Road context unavailable in the installed bundle; original geographic route remains available.","Straßenkontext im installierten Bundle nicht verfügbar; die geografische Originalroute bleibt nutzbar.","Contexte routier absent du paquet installé ; tracé géographique original disponible.","Wegcontext niet beschikbaar in geïnstalleerde bundel; oorspronkelijke route blijft beschikbaar."),style=MaterialTheme.typography.bodySmall)
                    if(roadContext.limited) Text(jt("Road context simplified for this view; the recorded track is complete.","Straßenkontext für diese Ansicht vereinfacht; der aufgezeichnete Track bleibt vollständig.","Contexte routier simplifié ; tracé enregistré complet.","Wegcontext vereenvoudigd; opgenomen route blijft compleet."),style=MaterialTheme.typography.bodySmall)
                    Text(jt("Offline geographic route; gaps are not connected. N is up. Tap the track or use the accessible timeline below.","Geografische Offline-Route; Lücken werden nicht verbunden. Norden ist oben. Route antippen oder den zugänglichen Zeitverlauf nutzen.","Tracé géographique hors ligne, lacunes séparées. Nord en haut. Utilisez le tracé ou la chronologie accessible.","Geografische offlineroute; hiaten worden niet verbonden. Noord is boven. Tik op de route of gebruik de tijdlijn."),style=MaterialTheme.typography.bodySmall)
                    val gps=events.filter { it.optString("kind")=="gps" && TripJournalProjection.trackEligible(TripJournalProjection.payload(it)) }
                    val first=gps.firstOrNull()?.optDouble("time");val last=gps.lastOrNull()?.optDouble("time")
                    if(first!=null && last!=null && last>first) Slider(((selectedTime ?: first)-first).toFloat(),{selectedTime=first+it},valueRange=0f..(last-first).toFloat(),modifier=Modifier.semantics { contentDescription=jt("Route time","Zeitpunkt der Route","Heure du tracé","Routetijd") })
                    Row { TextButton({replay=!replay}) {Text(if(replay) jt("Pause","Pause","Pause","Pauze") else jt("Replay","Wiedergeben","Lire","Afspelen"))}
                        val seek=selectedTime?.let { TripJournalProjection.seek(events,it) };TextButton({playing=seek},enabled=seek!=null) { Text(jt("Video from here","Video ab hier","Vidéo à partir d’ici","Video vanaf hier")) } }
                    selectedTime?.let { time -> Text(tripDate(time));val fix=gps.minByOrNull { abs(it.optDouble("time")-time) }?.let(TripJournalProjection::payload)
                        fix?.let { p -> Text("%.5f, %.5f".format(p.optDouble("latitude"),p.optDouble("longitude"))+p.optDouble("speed",Double.NaN).takeIf { it.isFinite() }?.let { " · %.1f km/h".format(it*3.6) }.orEmpty()) }
                    }
                    TripSpeedChart(events,selectedTime)
                }
                if(trip.optString("state")=="active") item {
                    Text(jt("Optional details while parked","Optionale Angaben im Stand","Informations facultatives à l’arrêt","Optionele gegevens bij stilstand"))
                    if(trip.optDouble("distance")==0.0 && !trip.has("vehicle")) { OutlinedTextField(vehicle,{vehicle=it},label={Text(jt("Vehicle name","Fahrzeugname","Nom du véhicule","Voertuignaam"))});TextButton({journal.vehicle(trip.getString("id"),vehicle)}) {Text(jt("Use vehicle","Fahrzeug übernehmen","Utiliser le véhicule","Voertuig gebruiken"))} }
                    Row {FilterChip(odometerUnit=="km",{odometerUnit="km"},label={Text("km")});Spacer(Modifier.width(8.dp));FilterChip(odometerUnit=="mi",{odometerUnit="mi"},label={Text("mi")})}
                    OutlinedTextField(reading,{reading=it},label={Text(jt("Optional odometer","Optionaler Kilometerstand","Compteur facultatif","Optionele kilometerstand")+" ($odometerUnit)")})
                    Row { if(!trip.has("odo_start") && trip.optDouble("distance")==0.0) TextButton({val value=reading.replace(',','.').toDoubleOrNull();if(value!=null && value>=0) journal.odometer(trip.getString("id"),value,null,odometerUnit)}) {Text(jt("Start reading","Startwert","Valeur de départ","Beginstand"))}
                        TextButton({val value=reading.replace(',','.').toDoubleOrNull();if(value==null || value*(if(odometerUnit=="mi") 1.609344 else 1.0)>=trip.optDouble("odo_start",0.0)) {journal.odometer(trip.getString("id"),null,value,odometerUnit);journal.stop()} else failure=jt("End reading is below start; omit it to save.","Endwert liegt unter Startwert; zum Speichern weglassen.","Valeur finale inférieure au départ ; omettez-la pour enregistrer.","Eindstand is lager; laat deze leeg om op te slaan.")}) {Text(jt("End trip (reading optional)","Fahrt beenden (Wert optional)","Terminer (valeur facultative)","Rit beëindigen (stand optioneel)"))} }
                }
                item { if(trip.has("odo_start")) Text("${jt("Car odometer start","Fahrzeug-Startstand","Compteur initial","Beginstand voertuig")}: ${trip.optDouble("odo_start")} km");if(trip.has("odo_end")) Text("${jt("Car odometer end","Fahrzeug-Endstand","Compteur final","Eindstand voertuig")}: ${trip.optDouble("odo_end")} km") }
                item { Text("${jt("Signs","Verkehrszeichen","Panneaux","Verkeersborden")}: ${discoveries.size} · GPS: ${events.count { it.optString("kind")=="gps" }} · TSR: ${events.count { it.optString("kind")=="tsr" }}") }
                item { Text(jt("Media · this trip","Medien · diese Fahrt","Médias · ce trajet","Media · deze rit"),style=MaterialTheme.typography.titleMedium) }
                if(galleryContent!=null && media.isNotEmpty()) item {TextButton({library=true}) {Text(jt("Open library · this trip","Bibliothek öffnen · diese Fahrt","Ouvrir la galerie · ce trajet","Bibliotheek openen · deze rit"))}}
                if(media.isEmpty()) item { Text(jt("No recording available","Keine Aufnahme vorhanden","Aucun enregistrement","Geen opname beschikbaar")) }
                media.groupBy { if(it.optString("type")=="video") it.optString("session") else "photos" }.forEach { (session,items) ->
                    item { Text(if(session=="photos") "Panoramax" else jt("Dashcam session","Dashcam-Sitzung","Session dashcam","Dashcamsessie")+" · ${items.size}") }
                    items(items,key={"${it.optString("type")}-${it.optString("id")}-${it.optString("path")}"}) { m ->
                        val path=m.optString("path");val local=m.optString("availability")=="local_original";val remote=path.startsWith("https://")
                        TextButton({selectedTime=m.optDouble("started_at",m.optDouble("time"));when { remote -> runCatching { context.startActivity(Intent(Intent.ACTION_VIEW,Uri.parse(path))) }.onFailure { failure=it.message };m.optString("type")=="video" -> playing=TripJournalProjection.Seek(path,0.0,m.optString("timing_quality")!="presentation_clock");else -> photo=path }},enabled=local || remote) {
                            Text("${tripDate(m.optDouble("started_at",m.optDouble("time")))} · ${if(remote) jt("Open in Panoramax","In Panoramax öffnen","Ouvrir dans Panoramax","Openen in Panoramax") else File(path).name} · ${if(local) jt("Local original","Lokales Original","Original local","Lokaal origineel") else if(remote) jt("Remote link","Remote-Link","Lien distant","Externe link") else jt("Missing/deleted","Fehlt/gelöscht","Absent/supprimé","Ontbreekt/verwijderd")}")
                        }
                    }
                }
                item { Text(jt("Timeline and logs","Zeitverlauf und Protokolle","Chronologie et journaux","Tijdlijn en logboeken"),style=MaterialTheme.typography.titleMedium)
                    Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(8.dp)) { listOf("all","gps","tsr","sign","media","gap").forEach { value -> FilterChip(eventFilter==value,{eventFilter=value;logLimit=100},label={Text(value.uppercase())}) } }
                    OutlinedTextField(signFilter,{signFilter=it;logLimit=100},label={Text(jt("Sign class / event search","Zeichenklasse / Ereignissuche","Classe de panneau / recherche","Bordklasse / gebeurtenis zoeken"))},modifier=Modifier.fillMaxWidth()) }
                items(visibleEvents.take(logLimit),key={"event-${it.optLong("seq")}"}) { e ->
                    val selectedEvent=selectedTime==e.optDouble("time")
                    OutlinedButton({selectedTime=e.optDouble("time")},modifier=Modifier.fillMaxWidth()) { Column {
                        Text("${tripDate(e.optDouble("time"))} · ${e.optString("kind")} #${e.optLong("seq")}${if(selectedEvent) " ✓" else ""}")
                        Text(e.optString("payload"),style=MaterialTheme.typography.bodySmall)
                    } }
                }
                if(visibleEvents.size>logLimit) item { TextButton({logLimit+=100}) {Text(jt("Show more events","Weitere Ereignisse","Plus d’événements","Meer gebeurtenissen"))} }
                item { Row { TextButton({exportOptions=true}) {Text(jt("Export / privately share","Export / privat teilen","Exporter / partager en privé","Exporteren / privé delen"))};TextButton({requestDelete(trip.getString("id"))}) {Text(jt("Delete trip","Fahrt löschen","Supprimer le trajet","Rit verwijderen"))} } }
            }
            item { HorizontalDivider();Row { TextButton({passphrase="";restoreFile=null;backupDialog=true}) {Text(jt("Encrypted backup","Verschlüsselte Sicherung","Sauvegarde chiffrée","Versleutelde back-up"))};TextButton({picker.launch(arrayOf("application/json","application/octet-stream"))}) {Text(jt("Restore","Wiederherstellen","Restaurer","Herstellen"))} }
                TextButton({clear=true}) {Text(jt("Clear all trips and counters","Alle Fahrtdaten und Zähler löschen","Effacer trajets et compteurs","Alle ritten en tellers wissen"))}
                if(trip==null) TextButton({journal.newTrip()}) {Text(jt("New trip","Neue Fahrt","Nouveau trajet","Nieuwe rit"))} }
        }
    }
    endingTrip?.let {id ->
        val target=trips.firstOrNull {it.optString("id")==id}
        if(target!=null) {
            val entered=TripJournalPresentation.endingKilometres(endingInput,target.optDouble("odo_start",0.0))
            SheetScaffold(jt("Ending car odometer","Fahrzeug-Endkilometerstand","Compteur du véhicule à l’arrivée","Eindkilometerstand voertuig"),{endingTrip=null},"trip-ending-odometer-sheet",containerColor=Color.White) {
                Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(16.dp)) {
                    Text(tripDate(target.optDouble("start")))
                    Text(jt("Optional: enter the car’s ending odometer in km. A saved reading cannot be changed and does not change the measured distance.","Optional: Endkilometerstand des Fahrzeugs in km eingeben. Ein gespeicherter Wert ist unveränderlich und verändert die gemessene Distanz nicht.","Facultatif : indiquez le compteur final du véhicule en km. Une valeur enregistrée est définitive et ne modifie pas la distance mesurée.","Optioneel: vul de eindkilometerstand in km in. Een opgeslagen stand is onveranderlijk en wijzigt de gemeten afstand niet."))
                    if(target.has("odo_end")) Text(TripJournalPresentation.odometerKilometres(target.optDouble("odo_end"))+" km",modifier=Modifier.testTag("trip-ending-odometer-saved"))
                    else {
                        OutlinedTextField(endingInput,{endingInput=it},label={Text(jt("Ending odometer (km)","Endkilometerstand (km)","Compteur final (km)","Eindkilometerstand (km)"))},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),isError=endingInput.isNotBlank() && entered==null,modifier=Modifier.fillMaxWidth().testTag("trip-ending-odometer-input"))
                        if(endingInput.isNotBlank() && entered==null) Text(jt("Enter a finite nonnegative value at least as large as the starting odometer.","Einen gültigen, nicht negativen Wert mindestens in Höhe des Startkilometerstands eingeben.","Saisissez une valeur valide positive ou nulle, au moins égale au compteur de départ.","Vul een geldige niet-negatieve stand in die minstens gelijk is aan de beginstand."),color=MaterialTheme.colorScheme.error,modifier=Modifier.testTag("trip-ending-odometer-error"))
                    }
                    Row(Modifier.horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                        Button({task {if(!target.has("odo_end") && entered!=null) withContext(Dispatchers.IO) {journal.setEndingOdometer(id,entered)};trips=withContext(Dispatchers.IO) {journal.snapshot().first};endingTrip=null}},enabled=!busy && (target.has("odo_end") || endingInput.isBlank() || entered!=null),modifier=Modifier.testTag("trip-ending-odometer-save")) {Text(jt("Done","Fertig","Terminer","Gereed"))}
                        TextButton({endingTrip=null;selected=id;logLimit=100;selectedTime=null},modifier=Modifier.testTag("trip-ending-odometer-details")) {Text(jt("Details","Details","Détails","Details"))}
                    }
                }
            }
        }
    }
    deletion?.let { id -> AlertDialog({deletion=null},title={Text(jt("Delete trip?","Fahrt löschen?","Supprimer ce trajet ?","Rit verwijderen?"))},text={Column { Text(jt("GPS/TSR logs, signs, optional odometer, trip media links and temporary exports are deleted. Library files and public copies remain. Lifetime app counters remain; saved-history totals decrease.","GPS-/TSR-Protokolle, Zeichen, optionale Kilometerstände, Medienverknüpfungen und temporäre Exporte werden gelöscht. Bibliotheksdateien und öffentliche Kopien bleiben. App-Gesamtzähler bleiben; die gespeicherte Fahrtsumme sinkt.","Journaux, panneaux, compteur facultatif, liens et exports temporaires supprimés. Fichiers de bibliothèque et copies publiques conservés. Compteurs globaux inchangés ; total conservé réduit.","Logs, borden, optionele standen, koppelingen en tijdelijke exports worden gewist. Bibliotheek en openbare kopieën blijven. Levenslange tellers blijven; bewaarde totalen dalen."));if(mediaCleanup!=null) {Text(cleanupPreview);Row {Checkbox(deleteMedia,{deleteMedia=it});Text(jt("Also delete eligible local media","Löschbare lokale Medien ebenfalls löschen","Supprimer aussi les médias locaux autorisés","Ook verwijderbare lokale media wissen"))}} }},confirmButton={TextButton({task {if(deleteMedia) failure=withContext(Dispatchers.IO) {mediaCleanup?.invoke(deletionMedia,true)};journal.delete(id);selected=null;deletion=null}}) {Text(jt("Delete","Löschen","Supprimer","Verwijderen"))}},dismissButton={TextButton({deletion=null}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}}) }
    if(clear) AlertDialog({clear=false},title={Text(jt("Clear all trips and counters?","Alle Fahrtdaten und Zähler löschen?","Tout effacer ?","Alle ritten en tellers wissen?"))},text={Text(jt("This removes the entire private journal and creates a new zero counter epoch. Library media and already shared files remain.","Das gesamte private Journal wird entfernt und eine neue Zählerepoche bei null beginnt. Bibliotheksmedien und bereits geteilte Dateien bleiben.","Le journal privé est supprimé et les compteurs repartent à zéro. Médias de bibliothèque et fichiers partagés conservés.","Het privélogboek wordt verwijderd en een nieuw teltijdvak begint op nul. Bibliotheekmedia en gedeelde bestanden blijven."))},confirmButton={TextButton({task {withContext(Dispatchers.IO) {journal.clearAll()};selected=null;clear=false}}) {Text(jt("Clear everything","Alles löschen","Tout effacer","Alles wissen"))}},dismissButton={TextButton({clear=false}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}})
    if(exportOptions && trip!=null) AlertDialog({exportOptions=false},title={Text(jt("Export preview","Exportvorschau","Aperçu de l’export","Exportvoorbeeld"))},text={Column(Modifier.heightIn(max=460.dp).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(8.dp)) {
        Text("1 ${jt("trip","Fahrt","trajet","rit")} · ${tripDate(trip.optDouble("start"))} · ${stateText(trip)}")
        Row { Checkbox(privateShare,{privateShare=it;logs=!it;includeMedia=false;selectedMedia=emptySet()});Text(jt("Privately share (hide endpoints)","Privat teilen (Endpunkte ausblenden)","Partager en privé (masquer extrémités)","Privé delen (eindpunten verbergen)")) }
        if(privateShare) OutlinedTextField(maskRadius,{maskRadius=it},label={Text(jt("Endpoint radius, metres","Endpunktradius, Meter","Rayon aux extrémités, mètres","Straal eindpunten, meter"))})
        if(privateShare) Row {Checkbox(maskHome,{maskHome=it},enabled=selectedTime!=null);Text(jt("Also hide selected map location","Ausgewählten Kartenort ebenfalls verbergen","Masquer aussi le point sélectionné","Geselecteerde kaartlocatie ook verbergen"))}
        Row { Checkbox(logs,{logs=it},enabled=!privateShare);Text(jt("GPS/TSR logs","GPS-/TSR-Protokolle","Journaux GPS/TSR","GPS/TSR-logboeken")) }
        Row {Checkbox(includeOdometer,{includeOdometer=it});Text(jt("Disclose optional odometer","Optionale Kilometerstände offenlegen","Inclure le compteur facultatif","Optionele standen delen"))}
        Column(Modifier.heightIn(max=140.dp).verticalScroll(rememberScrollState())) {media.filter {it.optString("availability")=="local_original" && (!privateShare || it.optString("type")=="photo")}.forEach { m ->
            val id=m.optString("id");Row {Checkbox(id in selectedMedia,{checked -> selectedMedia=if(checked) selectedMedia+id else selectedMedia-id});Text("${m.optString("type")} · ${tripDate(m.optDouble("time"))}")}
        }}
        Text(if(privateShare) jt("Hidden fixes, sign pins, raw logs, videos and remote links are excluded. Selected photos outside hidden areas are re-encoded without GPS metadata. Visible image content may still reveal locations. Originals do not change.","Verdeckte Fixes, Zeichen-Pins, Rohprotokolle, Videos und Remote-Links sind ausgeschlossen. Ausgewählte Fotos außerhalb verborgener Bereiche werden ohne GPS-Metadaten neu kodiert. Bildinhalte können Orte verraten. Originale bleiben unverändert.","Positions masquées, panneaux, journaux bruts, vidéos et liens distants exclus. Photos choisies hors zone réencodées sans GPS. Le contenu peut révéler des lieux. Originaux inchangés.","Verborgen posities, borden, ruwe logs, video’s en externe links worden uitgesloten. Gekozen foto’s buiten verborgen gebieden worden zonder GPS opgeslagen. Inhoud kan locaties onthullen. Originelen blijven gelijk.") else jt("Contains private coordinates, optional odometer and media references. No media bytes unless selected. Active trips are in-progress snapshots.","Enthält private Koordinaten, optionale Kilometerstände und Medienreferenzen. Mediendateien nur bei Auswahl. Aktive Fahrten sind Zwischenstände.","Contient coordonnées privées, compteur facultatif et références média. Fichiers seulement sur sélection. Trajets actifs = instantanés.","Bevat privécoördinaten, optionele standen en mediaverwijzingen. Bestanden alleen bij selectie. Actieve ritten zijn momentopnamen."),style=MaterialTheme.typography.bodySmall)
    }},confirmButton={TextButton({ val id=trip.getString("id");val radius=if(privateShare) maskRadius.replace(',','.').toDoubleOrNull()?.coerceIn(100.0,2000.0) ?: 300.0 else 0.0;task { val home=if(maskHome) selectedTime?.let {time -> events.filter {it.optString("kind")=="gps"}.minByOrNull {kotlin.math.abs(it.optDouble("time")-time)}?.let(TripJournalProjection::payload)} else null
                val options=TripExportOptions(privateShare,radius,home?.optDouble("latitude"),home?.optDouble("longitude"),logs && !privateShare,includeOdometer,selectedMedia)
                val file=withContext(Dispatchers.IO) {journal.archive(id,options)};share(file,"application/zip");exportOptions=false } },enabled=!busy) {Text(jt("Create ZIP and share","ZIP erstellen und teilen","Créer et partager le ZIP","ZIP maken en delen"))}},dismissButton={TextButton({exportOptions=false}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}})
    if(backupDialog) AlertDialog({backupDialog=false;restoreFile?.delete();restoreFile=null;restorePreview=null},title={Text(if(restoreFile==null) jt("Encrypted local backup","Verschlüsselte lokale Sicherung","Sauvegarde locale chiffrée","Versleutelde lokale back-up") else jt("Restore backup","Sicherung wiederherstellen","Restaurer la sauvegarde","Back-up herstellen"))},text={Column {
        Text(jt("AES-256-GCM encrypted. Keep the passphrase: it cannot be recovered. Includes trips, private logs, counters and media references; original media stays in the library.","AES-256-GCM-verschlüsselt. Passwort aufbewahren: Es kann nicht wiederhergestellt werden. Enthält Fahrten, private Protokolle, Zähler und Medienreferenzen; Originalmedien bleiben in der Bibliothek.","Chiffrement AES-256-GCM. Gardez le mot de passe, irrécupérable. Inclut trajets, journaux, compteurs et références ; médias dans la bibliothèque.","AES-256-GCM-versleuteld. Bewaar het wachtwoord: herstel is onmogelijk. Ritten, logs, tellers en mediaverwijzingen inbegrepen; media blijven in bibliotheek."))
        OutlinedTextField(passphrase,{passphrase=it;restorePreview=null},label={Text(jt("Passphrase (8+ characters)","Passwort (mind. 8 Zeichen)","Mot de passe (8 caractères min.)","Wachtwoord (min. 8 tekens)"))},visualTransformation=PasswordVisualTransformation())
        restorePreview?.let { p -> Text(jt("Whole-journal replacement","Ersetzt das gesamte Journal","Remplace tout le journal","Vervangt het hele logboek")+": ${p.optInt("trip_count")} · %.3f km · %.2f h".format(p.getJSONObject("counters").optDouble("distance")/1000,p.getJSONObject("counters").optDouble("usage")/3600)) }
        failure?.let { Text(it,color=MaterialTheme.colorScheme.error) }
    }},confirmButton={TextButton({task { val file=restoreFile
        if(file==null) { val backup=withContext(Dispatchers.IO) {journal.backup(passphrase)};share(backup,"application/json");backupDialog=false;passphrase="" }
        else if(restorePreview==null) { restorePreview=withContext(Dispatchers.IO) {journal.backupPreview(file,passphrase)} }
        else { withContext(Dispatchers.IO) {journal.restore(file,passphrase)};file.delete();restoreFile=null;restorePreview=null;backupDialog=false;selected=null;passphrase="" }
    }},enabled=passphrase.length>=8 && !busy) {Text(if(restoreFile==null) jt("Create and share","Erstellen und teilen","Créer et partager","Maken en delen") else if(restorePreview==null) jt("Validate and preview","Prüfen und Vorschau","Vérifier et prévisualiser","Controleren en bekijken") else jt("Replace entire journal","Gesamtes Journal ersetzen","Remplacer tout le journal","Heel logboek vervangen"))}},dismissButton={TextButton({backupDialog=false;restoreFile?.delete();restoreFile=null;restorePreview=null;passphrase=""}) {Text(jt("Cancel","Abbrechen","Annuler","Annuleren"))}})
    if(library && galleryContent!=null) galleryContent(media) {library=false}
    playing?.let { seek -> SheetScaffold(jt("Dashcam playback","Dashcam-Wiedergabe","Lecture dashcam","Dashcam afspelen"),{playing=null},"trip-video-sheet") { Column {
        if(seek.approximate) Text(jt("Approximate capture-clock alignment (up to 2 s)","Ungefähre Aufnahmezeit-Zuordnung (bis 2 s)","Alignement approximatif (jusqu’à 2 s)","Geschatte klokuitlijning (tot 2 s)"))
        AndroidView(factory={ ctx -> VideoView(ctx).apply {setVideoPath(seek.path);setMediaController(MediaController(ctx).also {it.setAnchorView(this)});setOnPreparedListener {seekTo((seek.seconds*1000).toInt());start()} }},modifier=Modifier.fillMaxSize(),onRelease={it.stopPlayback()})
    } } }
    photo?.let { path -> SheetScaffold(jt("Photo · this trip","Foto · diese Fahrt","Photo · ce trajet","Foto · deze rit"),{photo=null},"trip-photo-sheet") {
        val bitmap=remember(path) { BitmapFactory.decodeFile(path) };DisposableEffect(bitmap) {onDispose {bitmap?.recycle()}}
        bitmap?.let {Image(it.asImageBitmap(),contentDescription=jt("Captured photo","Aufgenommenes Foto","Photo capturée","Gemaakte foto"),modifier=Modifier.fillMaxSize())}
    } }
}

@Composable
private fun TripRoutePlot(events:List<JSONObject>,selectedTime:Double?,roads:List<TripJournalMapContext.Road>,onSelect:(Double)->Unit) {
    val points=remember(events) { events.filter { it.optString("kind")=="gps" && TripJournalProjection.trackEligible(TripJournalProjection.payload(it)) }.map { it to TripJournalProjection.payload(it) } }
    val pins=remember(events) { events.filter { it.optString("kind") in listOf("sign","media") }.map { it to TripJournalProjection.payload(it) }.filter { !it.second.isNull("latitude") && !it.second.isNull("longitude") } }
    val line=MaterialTheme.colorScheme.primary;val secondary=MaterialTheme.colorScheme.tertiary;val muted=MaterialTheme.colorScheme.outlineVariant
    if(points.isEmpty()) { Text(jt("No distance measurement / no GPS track","Keine Distanzmessung / kein GPS-Track","Aucune mesure de distance / tracé GPS","Geen afstandsmeting / GPS-route"));return }
    val minX=points.minOf { it.second.getDouble("longitude") };val maxX=points.maxOf { it.second.getDouble("longitude") }
    val minY=points.minOf { it.second.getDouble("latitude") };val maxY=points.maxOf { it.second.getDouble("latitude") }
    val middle=(maxY+minY)/2;val widthM=maxOf((maxX-minX)*111320*cos(Math.toRadians(middle)),10.0);val heightM=maxOf((maxY-minY)*111320,10.0)
    var canvasWidth by remember { mutableStateOf(1f) };var canvasHeight by remember { mutableStateOf(1f) }
    fun position(p:JSONObject,w:Float,h:Float):Offset {
        val scale=min((w-32)/widthM,(h-32)/heightM)
        return Offset((w/2+(p.getDouble("longitude")-(maxX+minX)/2)*111320*cos(Math.toRadians(middle))*scale).toFloat(),(h/2-(p.getDouble("latitude")-middle)*111320*scale).toFloat())
    }
    Canvas(Modifier.fillMaxWidth().height(230.dp).testTag("trip-route-map").background(MaterialTheme.colorScheme.surfaceVariant).semantics {contentDescription=jt("Geographic route map; timeline is the accessible alternative","Geografische Routenkarte; Zeitverlauf als zugängliche Alternative","Carte du trajet ; chronologie accessible disponible","Geografische routekaart; tijdlijn is toegankelijk alternatief")}.pointerInput(points) {detectTapGestures { tap ->
        points.minByOrNull { (position(it.second,canvasWidth,canvasHeight)-tap).getDistance() }?.let { onSelect(it.first.optDouble("time")) }
    }}) {
        canvasWidth=size.width;canvasHeight=size.height
        for(i in 1..3) {drawLine(muted,Offset(size.width*i/4,0f),Offset(size.width*i/4,size.height));drawLine(muted,Offset(0f,size.height*i/4),Offset(size.width,size.height*i/4))}
        val roadLabelPaint=android.graphics.Paint().apply {color=android.graphics.Color.DKGRAY;textSize=20f;isAntiAlias=true}
        roads.forEach { road ->
            val shape=Path();road.points.forEachIndexed {index,(lat,lon) ->val p=position(JSONObject().put("latitude",lat).put("longitude",lon),size.width,size.height);if(index==0)shape.moveTo(p.x,p.y)else shape.lineTo(p.x,p.y)}
            drawPath(shape,Color(0xFFB7B9B5),style=Stroke(if(road.highway in listOf("motorway","trunk","primary")) 7f else 3f))
        }
        roads.filter {it.name.isNotBlank()}.distinctBy {it.name}.take(14).forEach {road ->val (lat,lon)=road.points[road.points.size/2];val p=position(JSONObject().put("latitude",lat).put("longitude",lon),size.width,size.height)
            if(p.x in 12f..(size.width-70) && p.y in 24f..(size.height-30)) drawContext.canvas.nativeCanvas.drawText(road.name.take(32),p.x,p.y,roadLabelPaint)
        }
        val path=Path();var priorTime:Double?=null
        points.forEachIndexed { i,(e,p) -> val point=position(p,size.width,size.height);val time=e.optDouble("time")
            if(i==0 || p.optString("reason") in listOf("segment_start","sampling_gap") || priorTime?.let {time-it>15}==true) path.moveTo(point.x,point.y) else path.lineTo(point.x,point.y)
            priorTime=time
        };drawPath(path,line,style=Stroke(4f))
        pins.forEach { (_,p) -> drawCircle(secondary,6f,position(p,size.width,size.height)) }
        selectedTime?.let { time -> points.minByOrNull { abs(it.first.optDouble("time")-time) }?.let {drawCircle(line,9f,position(it.second,size.width,size.height))} }
        drawContext.canvas.nativeCanvas.drawText("N ↑   %.5f°, %.5f°   %.0f × %.0f m".format(middle,(maxX+minX)/2,widthM,heightM),12f,size.height-10,android.graphics.Paint().apply {color=android.graphics.Color.DKGRAY;textSize=22f})
    }
}

@Composable
private fun TripSpeedChart(events:List<JSONObject>,time:Double?) {
    val points=events.filter { it.optString("kind")=="gps" }.map { it to TripJournalProjection.payload(it) }.filter { it.second.optBoolean("valid") && it.second.optDouble("speed",-1.0)>=0 }
    if(points.size<2) return
    val min=points.first().first.optDouble("time");val max=points.last().first.optDouble("time");if(max<=min)return
    Text(jt("Recorded speed (km/h)","Aufgezeichnete Geschwindigkeit (km/h)","Vitesse enregistrée (km/h)","Opgenomen snelheid (km/h)"),style=MaterialTheme.typography.bodySmall)
    val color=MaterialTheme.colorScheme.primary
    Canvas(Modifier.fillMaxWidth().height(72.dp).semantics { contentDescription=jt("Speed chart; each GPS fix is available in the timeline","Geschwindigkeitsdiagramm; alle GPS-Fixes im Zeitverlauf","Vitesse ; chaque position est disponible dans la chronologie","Snelheidsdiagram; alle GPS-punten in de tijdlijn") }) {
        val high=points.maxOf { it.second.optDouble("speed") }.coerceAtLeast(1.0);val path=Path();var prior:Double?=null
        points.forEach { (e,p) -> val t=e.optDouble("time");val x=((t-min)/(max-min)*size.width).toFloat();val y=(size.height-p.optDouble("speed")/high*size.height).toFloat()
            if(prior==null || t-prior!!>15) path.moveTo(x,y) else path.lineTo(x,y);prior=t }
        drawPath(path,color,style=Stroke(2f));time?.let { val x=((it-min)/(max-min)*size.width).toFloat();drawLine(color,Offset(x,0f),Offset(x,size.height)) }
    }
}
@Composable
private fun TripPeriodChart(trips:List<JSONObject>,time:Boolean=false) {
    val days=trips.groupBy { Instant.ofEpochMilli((it.optDouble("start")*1000).toLong()).atZone(ZoneId.systemDefault()).toLocalDate() }.toSortedMap().entries.toList()
    if(days.isEmpty())return
    val color=MaterialTheme.colorScheme.primary
    fun value(items:List<JSONObject>,key:String)=items.sumOf {it.optDouble(key,0.0)}
    Text(if(time) jt("Saved trip time by day: span / observed","Gespeicherte Fahrtzeit je Tag: Dauer / aufgezeichnet","Durée conservée par jour : totale / observée","Bewaarde rittijd per dag: totale / opgenomen") else jt("Saved distance by day","Gespeicherte Distanz je Tag","Distance conservée par jour","Bewaarde afstand per dag"),style=MaterialTheme.typography.bodySmall)
    Canvas(Modifier.fillMaxWidth().height(80.dp).semantics {contentDescription=days.joinToString {if(time) "${it.key}: %.1f / %.1f min".format(value(it.value,"duration")/60,value(it.value,"observed")/60) else "${it.key}: %.3f km".format(value(it.value,"distance")/1000)}}) {
        val high=days.maxOf {value(it.value,if(time) "duration" else "distance")}.coerceAtLeast(1.0)
        val width=size.width/days.size;val bar=min(width-4,32.dp.toPx()).coerceAtLeast(1f)
        days.forEachIndexed { i,entry ->
            val height=(value(entry.value,if(time) "duration" else "distance")/high*size.height).toFloat()
            drawRect(if(time) color.copy(alpha=.35f) else color,Offset(i*width+(width-bar)/2,size.height-height),androidx.compose.ui.geometry.Size(bar,height))
            if(time) {val observed=(value(entry.value,"observed")/high*size.height).toFloat();drawRect(color,Offset(i*width+(width-bar)/2,size.height-observed),androidx.compose.ui.geometry.Size(bar/2,observed))}
        }
    }
    Row(Modifier.fillMaxWidth()) {Text(days.first().key.toString(),style=MaterialTheme.typography.labelSmall);Spacer(Modifier.weight(1f));if(days.size>1) Text(days.last().key.toString(),style=MaterialTheme.typography.labelSmall)}
}

@Composable
internal fun TripJournalLibrary(controller:ConsumerSessionController,media:List<JSONObject>,onDismiss:()->Unit) {
    var videoTab by remember {mutableStateOf(false)}
    val paths=media.map {it.optString("path")}.toSet()
    SheetScaffold(jt("Library · this trip","Bibliothek · diese Fahrt","Galerie · ce trajet","Bibliotheek · deze rit"),onDismiss,"trip-filtered-library",onBack=onDismiss) {
        Column(Modifier.fillMaxSize()) {
            Row {TextButton({videoTab=false}) {Text(jt("Photos","Fotos","Photos","Foto’s"))};TextButton({videoTab=true}) {Text(jt("Videos","Videos","Vidéos","Video’s"))}}
            if(videoTab) DashcamLibraryContent(controller,tripPaths=paths) else PanoramaxGalleryContent(controller,tripPaths=paths)
        }
    }
}

@Composable
internal fun TripStoppedOdometerPrompt(snapshot:TripStopPromptSnapshot,foreground:Color,save:(Int)->Unit,continueTrip:()->Unit) {
    var reading by remember(snapshot.tripID) {mutableStateOf(snapshot.reading)}
    Column(horizontalAlignment=Alignment.CenterHorizontally,modifier=Modifier.fillMaxWidth().testTag("trip-stop-prompt")) {
        Text(jt("Trip stopped · odometer","Fahrt beendet · Kilometerstand","Trajet terminé · compteur","Rit beëindigd · kilometerstand"),color=foreground,fontWeight=FontWeight.SemiBold)
        Row(Modifier.fillMaxWidth().height(76.dp)) {
            repeat(6) {index ->
                val place=listOf(100000,10000,1000,100,10,1)[index]
                val digit=reading/place%10
                val update:(Int)->Unit={value->reading=TripOdometer.replacingDigit(reading,index,(value+10)%10)}
                val latestUpdate by rememberUpdatedState(update)
                val latestDigit by rememberUpdatedState(digit)
                val threshold=with(androidx.compose.ui.platform.LocalDensity.current){22.dp.toPx()}
                Column(horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.Center,
                    modifier=Modifier.weight(1f).fillMaxHeight().testTag("trip-stop-digit-$index")
                        .semantics {
                            contentDescription=jt("Odometer digit","Kilometerstand Ziffer","Chiffre du compteur","Kilometerstand cijfer")+" ${index+1}: $digit"
                            customActions=listOf(
                                androidx.compose.ui.semantics.CustomAccessibilityAction(jt("Increase","Erhöhen","Augmenter","Verhogen")){update(digit+1);true},
                                androidx.compose.ui.semantics.CustomAccessibilityAction(jt("Decrease","Verringern","Diminuer","Verlagen")){update(digit-1);true})
                        }
                        .pointerInput(index,threshold) {
                            var drag=0f
                            detectVerticalDragGestures(onDragStart={drag=0f}) {change,amount->
                                change.consume();drag-=amount
                                var value=latestDigit
                                while(kotlin.math.abs(drag)>=threshold) {
                                    val step=if(drag>0) 1 else -1
                                    value=(value+step+10)%10;latestUpdate(value);drag-=step*threshold
                                }
                            }
                        }) {
                    Text(((digit+9)%10).toString(),color=foreground.copy(alpha=.3f),fontSize=12.sp)
                    Text(digit.toString(),color=foreground,fontSize=32.sp,fontWeight=FontWeight.Bold,fontFamily=androidx.compose.ui.text.font.FontFamily.Monospace)
                    Text(((digit+1)%10).toString(),color=foreground.copy(alpha=.3f),fontSize=12.sp)
                }
            }
        }
        Text(if(snapshot.estimated) jt("Estimated odometer · km","Geschätzter Kilometerstand · km","Compteur estimé · km","Geschatte kilometerstand · km") else jt("Car odometer · km","Fahrzeug-Kilometerstand · km","Compteur du véhicule · km","Kilometerstand auto · km"),color=foreground,fontSize=12.sp)
        Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            TextButton(continueTrip,modifier=Modifier.testTag("trip-stop-continue")) {Text(jt("Later","Später","Plus tard","Later"),color=foreground)}
            TextButton({save(reading)},modifier=Modifier.testTag("trip-stop-save")) {Text(jt("Save odometer","Kilometerstand speichern","Enregistrer le compteur","Kilometerstand opslaan"),color=foreground,fontWeight=FontWeight.Bold)}
        }
    }
}
