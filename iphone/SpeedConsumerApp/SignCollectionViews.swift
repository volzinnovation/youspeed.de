import SwiftUI
import UIKit

enum SignCollectionText {
    static func text(_ en: String, _ de: String) -> String { Locale.current.language.languageCode?.identifier == "de" ? de : en }
    static var title: String { text("Contribute traffic signs", "Verkehrszeichen beitragen") }
    static var disclosure: String { text(
        "With your permission, YouSpeed sends detected sign classes, model scores, observation times and your vehicle's GPS position to our servers to build a global traffic sign database and improve maps. Submissions use a random installation ID, without an account. Photos require separate permission and review. You can withdraw permission and request deletion in Settings. Camera recognition works with either choice.",
        "Mit deiner Zustimmung sendet YouSpeed erkannte Zeichenklassen, Modellbewertungen, Beobachtungszeiten und die GPS-Position deines Fahrzeugs an unsere Server. Damit bauen wir eine weltweite Verkehrszeichen-Datenbank auf und verbessern Karten. Beiträge verwenden eine zufällige Installations-ID, ohne Benutzerkonto. Fotos benötigen eine gesonderte Zustimmung und Prüfung. Du kannst die Zustimmung in den Einstellungen widerrufen und die Löschung anfordern. Die Kameraerkennung funktioniert bei beiden Entscheidungen.") }
}
extension SignCollectionText {
    static var cropTitle: String { text("Optional sign crops", "Optionale Zeichenausschnitte") }
    static var cropDisclosure: String { text("With separate permission, YouSpeed saves an expanded sign crop locally for your review. Only crops you approve are sent to our servers and stored in our private sign database. This permission does not publish images to Panoramax or authorize an external AI service. Unreviewed crops expire after 7 days.", "Mit gesonderter Zustimmung speichert YouSpeed einen erweiterten Zeichenausschnitt lokal zur Prüfung. Nur freigegebene Ausschnitte werden an unsere Server gesendet und in unserer privaten Zeichendatenbank gespeichert. Diese Zustimmung veröffentlicht keine Bilder auf Panoramax und erlaubt keinen externen KI-Dienst. Ungeprüfte Ausschnitte verfallen nach 7 Tagen.") }
    static var reviewConfirmation: String { text("I checked: no identifiable people, plates or unrelated private text", "Geprüft: keine erkennbaren Personen, Kennzeichen oder fremden privaten Texte") }
}
struct SignCollectionConsentModifier: ViewModifier {
    @ObservedObject var collection: SignCollectionCoordinator
    @State private var remember = false
    private var crop: Bool { collection.cropConsentPresented && !collection.consentPresented }
    private func decide(_ granted: Bool) {
        if crop { collection.decideCrop(granted: granted, dontAskAgain: remember) }
        else { collection.decide(granted: granted, dontAskAgain: remember) }
    }
    private func dismiss() { if crop { collection.dismissCropConsent() } else { collection.dismissConsent() } }
    func body(content: Content) -> some View {
        content.sheet(isPresented: Binding(get: { collection.consentPresented || collection.cropConsentPresented }, set: { if !$0 { dismiss() } })) {
            NavigationStack {
                Form {
                    Text(crop ? SignCollectionText.cropDisclosure : SignCollectionText.disclosure)
                    Toggle(SignCollectionText.text("Don't ask again", "Nicht erneut fragen"), isOn: $remember)
                    Button(SignCollectionText.text("Allow contributions", "Beiträge erlauben")) { decide(true) }
                    Button(SignCollectionText.text("Decline", "Ablehnen")) { decide(false) }
                }.navigationTitle(crop ? SignCollectionText.cropTitle : SignCollectionText.title)
                    .toolbar { ToolbarItem(placement: .cancellationAction) { Button(SignCollectionText.text("Close", "Schließen")) { dismiss() } } }
            }.onAppear { remember = false }.onChange(of: crop) { _, _ in remember = false }
        }
    }
}
struct SignCollectionSettingsSection: View {
    @ObservedObject var collection: SignCollectionCoordinator
    let manualSighting: () -> Void
    @State private var confirmDeletion = false
    @State private var safeCrop = false
    var body: some View {
        Section(SignCollectionText.title) {
            Toggle(SignCollectionText.title, isOn: Binding(get: { collection.enabled }, set: collection.setEnabled))
            if ["local_operation_failed", "storage_unavailable"].contains(collection.status) {
                Text(SignCollectionText.text("The local operation could not be saved. Please retry your choice or deletion request.", "Der lokale Vorgang konnte nicht gespeichert werden. Bitte die Entscheidung oder Löschanforderung erneut versuchen.")).foregroundStyle(.red)
            }
            Text(collection.authorized ? SignCollectionText.text("Metadata contributions are authorized for this camera session.", "Metadaten-Beiträge sind für diese Kamerasitzung erlaubt.") : SignCollectionText.text("Metadata requires your permission when using the camera.", "Metadaten benötigen deine Zustimmung bei der Kameranutzung."))
                .font(.footnote).foregroundStyle(.secondary)
            Text(SignCollectionText.text("Observations are buffered offline and sent automatically whenever internet is available, including during camera use and over mobile data.", "Beobachtungen werden offline gepuffert und bei verfügbarer Internetverbindung automatisch gesendet, auch während der Kameranutzung und über mobile Daten."))
                .font(.footnote).foregroundStyle(.secondary)
            Toggle(SignCollectionText.cropTitle, isOn: Binding(get: { collection.cropsEnabled }, set: collection.setCropsEnabled)).disabled(!collection.enabled)
            Text(SignCollectionText.cropDisclosure).font(.footnote).foregroundStyle(.secondary)
            if collection.reviewCount > 0 {
                Text(SignCollectionText.text("Crops awaiting review: ", "Ausschnitte zur Prüfung: ") + String(collection.reviewCount))
                if let bytes = collection.reviewCropBytes, let image = UIImage(data: bytes), collection.canReviewCrops {
                    Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 280)
                    Toggle(SignCollectionText.reviewConfirmation, isOn: $safeCrop)
                    Button(SignCollectionText.text("Approve this crop for upload", "Diesen Ausschnitt zum Hochladen freigeben")) { collection.reviewCrop(approved: true); safeCrop = false }.disabled(!safeCrop)
                    Button(SignCollectionText.text("Discard this crop", "Diesen Ausschnitt verwerfen"), role: .destructive) { collection.reviewCrop(approved: false); safeCrop = false }
                } else { Text(SignCollectionText.text("Review crops after the camera stops.", "Ausschnitte nach dem Ende der Kameranutzung prüfen.")).font(.footnote) }
            }
            Button(SignCollectionText.text("Add manual sighting", "Manuelle Beobachtung hinzufügen"), action: manualSighting).disabled(!collection.authorized)
            Text(SignCollectionText.text("Records a sign sighting at your current position and time, without a photo or model classification.", "Erfasst eine Zeichenbeobachtung mit aktueller Position und Zeit, ohne Foto oder Modellklassifikation."))
                .font(.footnote).foregroundStyle(.secondary)
            Button(SignCollectionText.text("Delete my observations", "Meine Beobachtungen löschen"), role: .destructive) { confirmDeletion = true }
            ForEach(Array(collection.deletions.enumerated()), id: \.offset) { index, phases in
                Text(index == collection.deletions.count - 1 ? SignCollectionText.text("Latest deletion request", "Letzte Löschanforderung") : SignCollectionText.text("Earlier deletion request", "Frühere Löschanforderung")).fontWeight(.semibold)
                Label(SignCollectionText.text("Active data removed", "Aktive Daten gelöscht"), systemImage: phases["active_data_removed"] == true ? "checkmark.circle" : "clock")
                Label(SignCollectionText.text("Archives purged", "Archive bereinigt"), systemImage: phases["archives_purged"] == true ? "checkmark.circle" : "clock")
                Label(SignCollectionText.text("Backup retention complete", "Backup-Aufbewahrung beendet"), systemImage: phases["backup_expiry_complete"] == true ? "checkmark.circle" : "clock")
            }.font(.footnote)
        }.onChange(of: collection.reviewCropID) { _, _ in safeCrop = false }.confirmationDialog(SignCollectionText.text("Delete all observations from this installation?", "Alle Beobachtungen dieser Installation löschen?"), isPresented: $confirmDeletion, titleVisibility: .visible) {
            Button(SignCollectionText.text("Delete my observations", "Meine Beobachtungen löschen"), role: .destructive) { collection.deleteObservations() }
        } message: { Text(SignCollectionText.text("Pending observations are cleared immediately. Server deletion resumes when connected; archives and backups may finish later.", "Ausstehende Beobachtungen werden sofort entfernt. Die Serverlöschung läuft bei bestehender Verbindung weiter; Archive und Backups können später abgeschlossen werden.")) }
    }
}
