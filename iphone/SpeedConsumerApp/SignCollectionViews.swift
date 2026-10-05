import SwiftUI
import UIKit

enum SignCollectionText {
    static func text(_ en: String, _ de: String) -> String { Locale.current.language.languageCode?.identifier == "de" ? de : en }
    static var title: String { text("Share detected signs", "Erkannte Verkehrszeichen teilen") }
    static var disclosure: String { text(
        "With your permission, YouSpeed sends detected sign classes, model scores, observation times and your vehicle's GPS position to our servers to build a global traffic sign database and improve maps. Submissions use a random installation ID, without an account. Detected sign photos are sent automatically with each observation. You can withdraw permission and request deletion in Settings. Camera recognition works with either choice.",
        "Mit deiner Zustimmung sendet YouSpeed erkannte Zeichenklassen, Modellbewertungen, Beobachtungszeiten und die GPS-Position deines Fahrzeugs an unsere Server. Damit bauen wir eine weltweite Verkehrszeichen-Datenbank auf und verbessern Karten. Beiträge verwenden eine zufällige Installations-ID, ohne Benutzerkonto. Fotos erkannter Zeichen werden automatisch mit der Beobachtung gesendet. Du kannst die Zustimmung in den Einstellungen widerrufen und die Löschung anfordern. Die Kameraerkennung funktioniert bei beiden Entscheidungen.") }
}
extension SignCollectionText {
    static var cropTitle: String { text("Upload sign photos automatically", "Zeichenfotos automatisch hochladen") }
    static var cropDisclosure: String { text("YouSpeed automatically sends cropped photos of detected signs to our private sign database, together with the observation time and location. No review or manual entry is needed. Uploads also use mobile data. Offline photos wait on your phone for up to 7 days. This does not publish photos to Panoramax or send them to an external AI service.", "YouSpeed sendet Fotos erkannter Zeichen automatisch als Bildausschnitte an unsere private Zeichendatenbank, zusammen mit Beobachtungszeit und Standort. Du musst nichts prüfen oder manuell eintragen. Uploads nutzen auch mobile Daten. Offline bleiben Fotos bis zu 7 Tage auf deinem Telefon. Fotos werden dabei weder auf Panoramax veröffentlicht noch an einen externen KI-Dienst gesendet.") }
}
struct SignCollectionConsentModifier: ViewModifier {
    @ObservedObject var collection: SignCollectionCoordinator
    @State private var remember = false
    private func decide(_ granted: Bool) {
        collection.decide(granted: granted, dontAskAgain: remember)
    }
    private func dismiss() { collection.dismissConsent() }
    func body(content: Content) -> some View {
        content.sheet(isPresented: Binding(get: { collection.consentPresented }, set: { if !$0 { dismiss() } })) {
            NavigationStack {
                Form {
                    Text(SignCollectionText.disclosure)
                    Toggle(SignCollectionText.text("Don't ask again", "Nicht erneut fragen"), isOn: $remember)
                    Button(SignCollectionText.text("Allow contributions", "Beiträge erlauben")) { decide(true) }
                    Button(SignCollectionText.text("Decline", "Ablehnen")) { decide(false) }
                }.navigationTitle(SignCollectionText.title)
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button(SignCollectionText.text("Close", "Schließen")) { dismiss() } } }
            }.onAppear { remember = false }
        }
    }
}
struct SignCollectionSettingsSection: View {
    @ObservedObject var collection: SignCollectionCoordinator
    @State private var confirmDeletion = false
    var body: some View {
        Section(SignCollectionText.title) {
            Toggle(SignCollectionText.title, isOn: Binding(get: { collection.enabled }, set: collection.setEnabled))
            if ["local_operation_failed", "storage_unavailable"].contains(collection.status) {
                Text(SignCollectionText.text("The local operation could not be saved. Please retry your choice or deletion request.", "Der lokale Vorgang konnte nicht gespeichert werden. Bitte die Entscheidung oder Löschanforderung erneut versuchen.")).foregroundStyle(.red)
            }
            Text(collection.authorized ? SignCollectionText.text("Detected signs are shared automatically.", "Erkannte Zeichen werden automatisch geteilt.") : SignCollectionText.text("Allow sharing when the camera asks for permission.", "Erlaube das Teilen, wenn die Kamera nach deiner Zustimmung fragt."))
                .font(.footnote).foregroundStyle(.secondary)
            Text(SignCollectionText.text("Observations are buffered offline and sent automatically whenever internet is available, including during camera use and over mobile data.", "Beobachtungen werden offline gepuffert und bei verfügbarer Internetverbindung automatisch gesendet, auch während der Kameranutzung und über mobile Daten."))
                .font(.footnote).foregroundStyle(.secondary)
            Text(SignCollectionText.cropDisclosure).font(.footnote).foregroundStyle(.secondary)
            Button(SignCollectionText.text("Delete my observations", "Meine Beobachtungen löschen"), role: .destructive) { confirmDeletion = true }
            ForEach(Array(collection.deletions.enumerated()), id: \.offset) { index, phases in
                Text(index == collection.deletions.count - 1 ? SignCollectionText.text("Latest deletion request", "Letzte Löschanforderung") : SignCollectionText.text("Earlier deletion request", "Frühere Löschanforderung")).fontWeight(.semibold)
                Label(SignCollectionText.text("Active data removed", "Aktive Daten gelöscht"), systemImage: phases["active_data_removed"] == true ? "checkmark.circle" : "clock")
                Label(SignCollectionText.text("Archives purged", "Archive bereinigt"), systemImage: phases["archives_purged"] == true ? "checkmark.circle" : "clock")
                Label(SignCollectionText.text("Backup retention complete", "Backup-Aufbewahrung beendet"), systemImage: phases["backup_expiry_complete"] == true ? "checkmark.circle" : "clock")
            }.font(.footnote)
        }.confirmationDialog(SignCollectionText.text("Delete all observations from this installation?", "Alle Beobachtungen dieser Installation löschen?"), isPresented: $confirmDeletion, titleVisibility: .visible) {
            Button(SignCollectionText.text("Delete my observations", "Meine Beobachtungen löschen"), role: .destructive) { collection.deleteObservations() }
        } message: { Text(SignCollectionText.text("Pending observations are cleared immediately. Server deletion resumes when connected; archives and backups may finish later.", "Ausstehende Beobachtungen werden sofort entfernt. Die Serverlöschung läuft bei bestehender Verbindung weiter; Archive und Backups können später abgeschlossen werden.")) }
    }
}
