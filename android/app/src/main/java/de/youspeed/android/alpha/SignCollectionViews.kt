package de.youspeed.android.alpha

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.util.Locale

internal object SignCollectionText {
    fun text(en: String, de: String) = if (Locale.getDefault().language == "de") de else en
    val title get() = text("Share detected signs", "Erkannte Verkehrszeichen teilen")
    val disclosure get() = text(
        "With your permission, YouSpeed sends detected sign classes, model scores, observation times and your vehicle's GPS position to our servers to build a global traffic sign database and improve maps. Submissions use a random installation ID, without an account. Detected sign photos are sent automatically with each observation. You can withdraw permission and request deletion in Settings. Camera recognition works with either choice.",
        "Mit deiner Zustimmung sendet YouSpeed erkannte Zeichenklassen, Modellbewertungen, Beobachtungszeiten und die GPS-Position deines Fahrzeugs an unsere Server. Damit bauen wir eine weltweite Verkehrszeichen-Datenbank auf und verbessern Karten. Beiträge verwenden eine zufällige Installations-ID, ohne Benutzerkonto. Fotos erkannter Zeichen werden automatisch mit der Beobachtung gesendet. Du kannst die Zustimmung in den Einstellungen widerrufen und die Löschung anfordern. Die Kameraerkennung funktioniert bei beiden Entscheidungen.")
    val cropTitle get() = text("Upload sign photos automatically", "Zeichenfotos automatisch hochladen")
    val cropDisclosure get() = text("YouSpeed automatically sends cropped photos of detected signs to our private sign database, together with the observation time and location. No review or manual entry is needed. Uploads also use mobile data. Offline photos wait on your phone for up to 7 days. This does not publish photos to Panoramax or send them to an external AI service.", "YouSpeed sendet Fotos erkannter Zeichen automatisch als Bildausschnitte an unsere private Zeichendatenbank, zusammen mit Beobachtungszeit und Standort. Du musst nichts prüfen oder manuell eintragen. Uploads nutzen auch mobile Daten. Offline bleiben Fotos bis zu 7 Tage auf deinem Telefon. Fotos werden dabei weder auf Panoramax veröffentlicht noch an einen externen KI-Dienst gesendet.")

}
@Composable internal fun SignCollectionConsentDialog(collection: SignCollectionCoordinator) {
    if (!collection.consentPresented) return
    var remember by remember { mutableStateOf(false) }
    fun decide(granted: Boolean) { collection.decide(granted, remember) }
    fun dismiss() { collection.dismissConsent() }
    AlertDialog(onDismissRequest = ::dismiss, title = { Text(SignCollectionText.title) }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(SignCollectionText.disclosure,
                modifier = Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = remember, onCheckedChange = { remember = it })
                Text(SignCollectionText.text("Don't ask again", "Nicht erneut fragen"), modifier = Modifier.weight(1f))
            }
        }
    }, confirmButton = { TextButton(onClick = { decide(true) }) { Text(SignCollectionText.text("Allow contributions", "Beiträge erlauben")) } },
        dismissButton = { TextButton(onClick = { decide(false) }) { Text(SignCollectionText.text("Decline", "Ablehnen")) } })
}
@Composable internal fun SignCollectionSettings(collection: SignCollectionCoordinator) {
    var confirm by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (collection.status in listOf("local_operation_failed", "storage_unavailable")) Text(SignCollectionText.text("The local operation could not be saved. Please retry your choice or deletion request.", "Der lokale Vorgang konnte nicht gespeichert werden. Bitte die Entscheidung oder Löschanforderung erneut versuchen."), color = MaterialTheme.colorScheme.error)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(SignCollectionText.title, modifier = Modifier.weight(1f))
            Switch(checked = collection.enabled, onCheckedChange = collection::updateEnabled)
        }
        Text(if (collection.authorized) SignCollectionText.text("Detected signs are shared automatically.", "Erkannte Zeichen werden automatisch geteilt.")
            else SignCollectionText.text("Allow sharing when the camera asks for permission.", "Erlaube das Teilen, wenn die Kamera nach deiner Zustimmung fragt."))
        Text(SignCollectionText.text("Observations are buffered offline and sent automatically whenever internet is available, including during camera use and over mobile data.", "Beobachtungen werden offline gepuffert und bei verfügbarer Internetverbindung automatisch gesendet, auch während der Kameranutzung und über mobile Daten."))
        Text(SignCollectionText.cropDisclosure)
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
