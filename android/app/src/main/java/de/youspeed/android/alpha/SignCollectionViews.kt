package de.youspeed.android.alpha

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.graphics.asImageBitmap
import android.graphics.BitmapFactory
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.util.Locale

internal object SignCollectionText {
    fun text(en: String, de: String) = if (Locale.getDefault().language == "de") de else en
    val title get() = text("Contribute traffic signs", "Verkehrszeichen beitragen")
    val disclosure get() = text(
        "With your permission, YouSpeed sends detected sign classes, model scores, observation times and your vehicle's GPS position to our servers to build a global traffic sign database and improve maps. Submissions use a random installation ID, without an account. Photos require separate permission and review. You can withdraw permission and request deletion in Settings. Camera recognition works with either choice.",
        "Mit deiner Zustimmung sendet YouSpeed erkannte Zeichenklassen, Modellbewertungen, Beobachtungszeiten und die GPS-Position deines Fahrzeugs an unsere Server. Damit bauen wir eine weltweite Verkehrszeichen-Datenbank auf und verbessern Karten. Beiträge verwenden eine zufällige Installations-ID, ohne Benutzerkonto. Fotos benötigen eine gesonderte Zustimmung und Prüfung. Du kannst die Zustimmung in den Einstellungen widerrufen und die Löschung anfordern. Die Kameraerkennung funktioniert bei beiden Entscheidungen.")
    val cropTitle get() = text("Optional sign crops", "Optionale Zeichenausschnitte")
    val cropDisclosure get() = text("With separate permission, YouSpeed saves an expanded sign crop locally for your review. Only crops you approve are sent to our servers and stored in our private sign database. This permission does not publish images to Panoramax or authorize an external AI service. Unreviewed crops expire after 7 days.", "Mit gesonderter Zustimmung speichert YouSpeed einen erweiterten Zeichenausschnitt lokal zur Prüfung. Nur freigegebene Ausschnitte werden an unsere Server gesendet und in unserer privaten Zeichendatenbank gespeichert. Diese Zustimmung veröffentlicht keine Bilder auf Panoramax und erlaubt keinen externen KI-Dienst. Ungeprüfte Ausschnitte verfallen nach 7 Tagen.")
    val reviewConfirmation get() = text("I checked: no identifiable people, plates or unrelated private text", "Geprüft: keine erkennbaren Personen, Kennzeichen oder fremden privaten Texte")

}
@Composable internal fun SignCollectionConsentDialog(collection: SignCollectionCoordinator) {
    if (!collection.consentPresented && !collection.cropConsentPresented) return
    val crop = collection.cropConsentPresented && !collection.consentPresented
    var remember by remember(crop) { mutableStateOf(false) }
    fun decide(granted: Boolean) { if (crop) collection.decideCrop(granted, remember) else collection.decide(granted, remember) }
    fun dismiss() { if (crop) collection.dismissCropConsent() else collection.dismissConsent() }
    AlertDialog(onDismissRequest = ::dismiss, title = { Text(if (crop) SignCollectionText.cropTitle else SignCollectionText.title) }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(if (crop) SignCollectionText.cropDisclosure else SignCollectionText.disclosure,
                modifier = Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = remember, onCheckedChange = { remember = it })
                Text(SignCollectionText.text("Don't ask again", "Nicht erneut fragen"), modifier = Modifier.weight(1f))
            }
        }
    }, confirmButton = { TextButton(onClick = { decide(true) }) { Text(SignCollectionText.text("Allow contributions", "Beiträge erlauben")) } },
        dismissButton = { TextButton(onClick = { decide(false) }) { Text(SignCollectionText.text("Decline", "Ablehnen")) } })
}
@Composable internal fun SignCollectionSettings(collection: SignCollectionCoordinator, manualSighting: () -> Unit) {
    var confirm by remember { mutableStateOf(false) }
    var safeCrop by remember(collection.reviewCropId) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (collection.status in listOf("local_operation_failed", "storage_unavailable")) Text(SignCollectionText.text("The local operation could not be saved. Please retry your choice or deletion request.", "Der lokale Vorgang konnte nicht gespeichert werden. Bitte die Entscheidung oder Löschanforderung erneut versuchen."), color = MaterialTheme.colorScheme.error)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(SignCollectionText.title, modifier = Modifier.weight(1f))
            Switch(checked = collection.enabled, onCheckedChange = collection::updateEnabled)
        }
        Text(if (collection.authorized) SignCollectionText.text("Metadata contributions are authorized for this camera session.", "Metadaten-Beiträge sind für diese Kamerasitzung erlaubt.")
            else SignCollectionText.text("Metadata requires your permission when using the camera.", "Metadaten benötigen deine Zustimmung bei der Kameranutzung."))
        Text(SignCollectionText.text("Observations are buffered offline and sent automatically whenever internet is available, including during camera use and over mobile data.", "Beobachtungen werden offline gepuffert und bei verfügbarer Internetverbindung automatisch gesendet, auch während der Kameranutzung und über mobile Daten."))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(SignCollectionText.cropTitle, modifier = Modifier.weight(1f))
            Switch(checked = collection.cropsEnabled, enabled = collection.enabled, onCheckedChange = collection::updateCropsEnabled)
        }
        Text(SignCollectionText.cropDisclosure)
        if (collection.reviewCount > 0) {
            Text(SignCollectionText.text("Crops awaiting review: ", "Ausschnitte zur Prüfung: ") + collection.reviewCount)
            val bytes = collection.reviewCropBytes
            if (bytes != null && collection.canReviewCrops) {
                val bitmap = remember(collection.reviewCropId, bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
                DisposableEffect(bitmap) { onDispose { bitmap?.recycle() } }
                if (bitmap != null) {
                    Image(bitmap.asImageBitmap(), contentDescription = SignCollectionText.cropTitle, modifier = Modifier.fillMaxWidth().heightIn(max = 280.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) { Checkbox(safeCrop, { safeCrop = it }); Text(SignCollectionText.reviewConfirmation) }
                    TextButton(onClick = { collection.reviewCrop(true); safeCrop = false }, enabled = safeCrop) { Text(SignCollectionText.text("Approve this crop for upload", "Diesen Ausschnitt zum Hochladen freigeben")) }
                }
                TextButton(onClick = { collection.reviewCrop(false); safeCrop = false }) { Text(SignCollectionText.text("Discard this crop", "Diesen Ausschnitt verwerfen")) }
            } else Text(SignCollectionText.text("Review crops after the camera stops.", "Ausschnitte nach dem Ende der Kameranutzung prüfen."))
        }
        TextButton(onClick = manualSighting, enabled = collection.authorized) { Text(SignCollectionText.text("Add manual sighting", "Manuelle Beobachtung hinzufügen")) }
        Text(SignCollectionText.text("Records a sign sighting at your current position and time, without a photo or model classification.", "Erfasst eine Zeichenbeobachtung mit aktueller Position und Zeit, ohne Foto oder Modellklassifikation."))
        TextButton(onClick = { confirm = true }) { Text(SignCollectionText.text("Delete my observations", "Meine Beobachtungen löschen")) }
        collection.deletions.forEachIndexed { index, phases ->
            Text(if (index == collection.deletions.lastIndex) SignCollectionText.text("Latest deletion request", "Letzte Löschanforderung") else SignCollectionText.text("Earlier deletion request", "Frühere Löschanforderung"))
            listOf("active_data_removed" to SignCollectionText.text("Active data removed", "Aktive Daten gelöscht"),
                "archives_purged" to SignCollectionText.text("Archives purged", "Archive bereinigt"),
                "backup_expiry_complete" to SignCollectionText.text("Backup retention complete", "Backup-Aufbewahrung beendet")).forEach { (key, label) ->
                Text((if (phases[key] == true) "✓ " else "… ") + label)
            }
        }
    }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false }, title = { Text(SignCollectionText.text("Delete all observations from this installation?", "Alle Beobachtungen dieser Installation löschen?")) },
        text = { Text(SignCollectionText.text("Pending observations are cleared immediately. Server deletion resumes when connected; archives and backups may finish later.", "Ausstehende Beobachtungen werden sofort entfernt. Die Serverlöschung läuft bei bestehender Verbindung weiter; Archive und Backups können später abgeschlossen werden.")) },
        confirmButton = { TextButton(onClick = { confirm = false; collection.deleteObservations() }) { Text(SignCollectionText.text("Delete my observations", "Meine Beobachtungen löschen")) } },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text(SignCollectionText.text("Cancel", "Abbrechen")) } })
}
