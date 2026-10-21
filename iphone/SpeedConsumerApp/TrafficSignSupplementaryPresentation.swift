import Foundation

/// Matches OCR evidence to the currently visible sign. These checks only admit
/// presentation and speech; they never determine whether a road rule applies.
enum TrafficSignSupplementaryPresentation {
    /// Display memory is independent of fresh OCR used for speech and captures.
    /// A miss, a textless result, or a fragmented track of the same class keeps it.
    static func retainedForDisplay(_ current: TrafficSignSupplementaryOCRAnnotation?,
                                   primaryClassID: String?,
                                   read: TrafficSignSupplementaryOCRAnnotation? = nil,
                                   now: Date) -> TrafficSignSupplementaryOCRAnnotation? {
        if let read, read.readStatus == .read, read.text != nil,
           isFresh(read, at: now), primaryClassID == nil || read.primaryClassID == primaryClassID {
            return read
        }
        guard primaryClassID == nil || primaryClassID == current?.primaryClassID else { return nil }
        return current
    }

    /// A newer primary result need not contain another OCR read. Keep the last
    /// successful text for the same sign, without changing its source provenance.
    static func retainedAnnotation(
        _ current: TrafficSignSupplementaryOCRAnnotation?,
        primaryClassID: String?, primarySpeedKmh: Int?, physicalSignID: String?,
        evidenceAt: Date, now: Date
    ) -> TrafficSignSupplementaryOCRAnnotation? {
        guard let current, current.readStatus == .read, current.text != nil,
              isFresh(current, at: now) else { return nil }
        // A visual miss may finalize a passage. Its original expiry still runs.
        guard let primaryClassID else { return current }
        guard primaryClassID == current.primaryClassID,
              primarySpeedKmh == current.primarySpeedKmh else { return nil }
        // Class alone cannot distinguish two nearby pictograms of the same
        // kind. The runtime supplies cached OCR for its matching association.
        guard let physicalSignID else { return nil }
        guard physicalSignID == current.physicalSignID else { return nil }
        let age = now.timeIntervalSince(evidenceAt)
        guard evidenceAt >= current.observedAt, age.isFinite, (0...3).contains(age) else { return current }
        return current.refreshed(at: evidenceAt)
    }

    static func isFresh(_ annotation: TrafficSignSupplementaryOCRAnnotation, at now: Date) -> Bool {
        let age = now.timeIntervalSince(annotation.observedAt)
        return age.isFinite && (0...3).contains(age)
    }

    static func matchesNumeric(_ annotation: TrafficSignSupplementaryOCRAnnotation,
                              displayedSpeedKmh: Int?, cameraEvidence: Bool, now: Date) -> Bool {
        cameraEvidence && !annotation.primaryClassID.isEmpty
            && annotation.readStatus == .read && annotation.text != nil
            && isFresh(annotation, at: now) && (annotation.primarySpeedKmh ?? 0) > 0
            && annotation.primarySpeedKmh == displayedSpeedKmh
    }

    static func matchesPictogram(_ annotation: TrafficSignSupplementaryOCRAnnotation,
                                classID: String?, now: Date) -> Bool {
        annotation.primarySpeedKmh == nil && annotation.primaryClassID == classID
            && annotation.readStatus == .read && annotation.text != nil && isFresh(annotation, at: now)
    }

    static func spokenPhrase(for annotation: TrafficSignSupplementaryOCRAnnotation,
                             languageIdentifier: String) -> String {
        if let window = annotation.window {
            return spokenPhrase(for: window, languageIdentifier: languageIdentifier)
        }
        return TrafficSignOCRTextFormatting.speech(annotation.text ?? "", language: languageIdentifier)
    }

    static func speechKey(for annotation: TrafficSignSupplementaryOCRAnnotation) -> String {
        "supplementary:\(annotation.primaryClassID)|\(annotation.text ?? "")"
    }

    static func isFresh(_ observation: TrafficSignSupplementaryTextObservation, at now: Date) -> Bool {
        let age = now.timeIntervalSince(observation.observedAt)
        return age.isFinite && (0...3).contains(age)
    }

    static func matchesNumeric(
        _ observation: TrafficSignSupplementaryTextObservation,
        displayedSpeedKmh: Int?,
        cameraEvidence: Bool,
        now: Date
    ) -> Bool {
        guard cameraEvidence, isFresh(observation, at: now),
              !observation.primaryClassID.isEmpty,
              let observedSpeed = observation.primarySpeedKmh, observedSpeed > 0,
              let displayedSpeedKmh else { return false }
        return observedSpeed == displayedSpeedKmh
    }

    static func matchesPictogram(
        _ observation: TrafficSignSupplementaryTextObservation,
        classID: String?,
        now: Date
    ) -> Bool {
        guard isFresh(observation, at: now), observation.primarySpeedKmh == nil,
              let classID, !classID.isEmpty else { return false }
        return observation.primaryClassID == classID
    }

    static func spokenPhrase(
        for window: TrafficSignSupplementaryTimeWindow,
        languageIdentifier: String
    ) -> String {
        let language = String(languageIdentifier.prefix(2)).lowercased()
        guard ["de", "fr", "nl", "it", "en"].contains(language) else { return window.displayText }
        func time(_ totalMinutes: Int) -> String {
            let hour = totalMinutes / 60
            let minute = totalMinutes % 60
            if language == "en" {
                let twelveHour = hour % 12 == 0 ? 12 : hour % 12
                let clock = minute == 0 ? "\(twelveHour)" : String(format: "%d:%02d", twelveHour, minute)
                return "\(clock) \(hour < 12 ? "a.m." : "p.m.")"
            }
            let unit: String
            switch language {
            case "de": unit = "Uhr"
            case "fr": unit = hour == 1 ? "heure" : "heures"
            case "it": unit = "ore"
            default: unit = "uur"
            }
            return "\(hour) \(unit)" + (minute == 0 ? "" : " \(minute)")
        }
        let start = time(window.startMinutes)
        let end = time(window.endMinutes)
        switch language {
        case "de": return "von \(start) bis \(end)"
        case "fr": return "de \(start) à \(end)"
        case "nl": return "van \(start) tot \(end)"
        case "it": return "dalle \(start) alle \(end)"
        default: return "from \(start) to \(end)"
        }
    }

    /// A fragmented tracker must not reannounce an unchanged class and interval.
    /// The caller's existing visibility-gap gate controls when it can speak again.
    static func speechKey(for observation: TrafficSignSupplementaryTextObservation) -> String {
        "supplementary:\(observation.primaryClassID)|\(observation.window.startMinutes)-\(observation.window.endMinutes)"
    }
}
