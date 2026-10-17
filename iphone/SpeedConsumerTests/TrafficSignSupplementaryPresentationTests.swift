import Foundation
import XCTest
@testable import SpeedConsumer

final class TrafficSignSupplementaryPresentationTests: XCTestCase {
    private let observedAt = Date(timeIntervalSince1970: 1_000)

    func testFreshnessIncludesBothBoundariesAndRejectsFutureStaleAndNonFiniteDates() throws {
        let value = try observation()
        XCTAssertTrue(TrafficSignSupplementaryPresentation.isFresh(value, at: observedAt))
        XCTAssertTrue(TrafficSignSupplementaryPresentation.isFresh(value, at: observedAt.addingTimeInterval(3)))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.isFresh(value, at: observedAt.addingTimeInterval(-0.001)))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.isFresh(value, at: observedAt.addingTimeInterval(3.001)))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.isFresh(value, at: Date(timeIntervalSince1970: .nan)))
        let invalid = try observation(timestamp: Date(timeIntervalSince1970: .nan))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.isFresh(invalid, at: observedAt))
    }

    func testNumericRestrictionRequiresMatchingCameraSpeedAndFreshEvidence() throws {
        let value = try observation(classID: "maxspeed:30", speed: 30)
        XCTAssertTrue(matchesNumeric(value, speed: 30))
        XCTAssertFalse(matchesNumeric(value, speed: 50))
        XCTAssertFalse(matchesNumeric(value, speed: nil))
        XCTAssertFalse(matchesNumeric(value, speed: 30, cameraEvidence: false))
        XCTAssertFalse(matchesNumeric(value, speed: 30, now: observedAt.addingTimeInterval(4)))
        XCTAssertFalse(matchesNumeric(try observation(), speed: 30))
        XCTAssertFalse(matchesNumeric(try observation(classID: "maxspeed:0", speed: 0), speed: 0))
        XCTAssertFalse(matchesNumeric(try observation(classID: "", speed: 30), speed: 30))
    }

    func testPictogramRestrictionRequiresExactClassAndCannotBorrowNumericEvidence() throws {
        let value = try observation()
        XCTAssertTrue(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: "parking", now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: "stop", now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: nil, now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: "", now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: "parking", now: observedAt.addingTimeInterval(4)))
        let numeric = try observation(classID: "maxspeed:30", speed: 30)
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(numeric, classID: "maxspeed:30", now: observedAt))
    }

    func testOvernightSpeechUsesTheFourAppLanguages() throws {
        let window = try XCTUnwrap(TrafficSignSupplementaryTimeWindow(startMinutes: 22 * 60, endMinutes: 6 * 60))
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "de-DE"), "von 22 Uhr bis 6 Uhr")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "en-GB"), "from 10 p.m. to 6 a.m.")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "fr-FR"), "de 22 heures à 6 heures")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "nl-NL"), "van 22 uur tot 6 uur")
    }

    func testSpeechRetainsMinutesInAllFourLanguages() throws {
        let window = try XCTUnwrap(TrafficSignSupplementaryTimeWindow(startMinutes: 22 * 60 + 30, endMinutes: 6 * 60 + 5))
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "DE-de"), "von 22 Uhr 30 bis 6 Uhr 5")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "en-US"), "from 10:30 p.m. to 6:05 a.m.")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "fr"), "de 22 heures 30 à 6 heures 5")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: "nl"), "van 22 uur 30 tot 6 uur 5")
    }

    func testEnglishMidnightAndNoonAndFrenchSingularHour() throws {
        let midnightToNoon = try XCTUnwrap(TrafficSignSupplementaryTimeWindow(startMinutes: 0, endMinutes: 12 * 60))
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: midnightToNoon, languageIdentifier: "en"), "from 12 a.m. to 12 p.m.")
        let oneToTwo = try XCTUnwrap(TrafficSignSupplementaryTimeWindow(startMinutes: 60, endMinutes: 120))
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: oneToTwo, languageIdentifier: "fr-BE"), "de 1 heure à 2 heures")
    }

    func testSpeechKeyIgnoresTrackerFragmentsButSeparatesClassAndInterval() throws {
        let first = try observation(physicalID: "track-1")
        let fragmented = try observation(physicalID: "track-2", timestamp: observedAt.addingTimeInterval(1))
        XCTAssertEqual(TrafficSignSupplementaryPresentation.speechKey(for: first), TrafficSignSupplementaryPresentation.speechKey(for: fragmented))
        let anotherWindow = try observation(endMinutes: 7 * 60)
        XCTAssertNotEqual(TrafficSignSupplementaryPresentation.speechKey(for: first), TrafficSignSupplementaryPresentation.speechKey(for: anotherWindow))
        let anotherClass = try observation(classID: "stop")
        XCTAssertNotEqual(TrafficSignSupplementaryPresentation.speechKey(for: first), TrafficSignSupplementaryPresentation.speechKey(for: anotherClass))
    }

    func testCombinedAnnouncementRecordsRestrictionEvenInsideSecondaryCooldown() {
        var gate = TrafficSignSecondarySpeechGate()
        func time(_ seconds: Double) -> Date { observedAt.addingTimeInterval(seconds) }
        gate.recordSpoken(classID: "restriction-A", observedAt: time(0), now: time(0))
        // Primary feedback may include B before the secondary-only cooldown ends.
        gate.recordSpoken(classID: "restriction-B", observedAt: time(1), now: time(1))
        XCTAssertFalse(gate.shouldEmit(classID: "restriction-B", observedAt: time(3.1), now: time(3.1), canSpeak: true))
        for second in [4.0, 6.0, 9.0] {
            XCTAssertFalse(gate.shouldEmit(classID: "restriction-B", observedAt: time(second), now: time(second), canSpeak: true))
        }
        XCTAssertFalse(gate.shouldEmit(classID: "restriction-B", observedAt: time(16), now: time(16), canSpeak: true))
        XCTAssertTrue(gate.shouldEmit(classID: "restriction-B", observedAt: time(24), now: time(24), canSpeak: true))
    }

    func testRawRestrictionIsPresentedAndSpokenWithoutDiscardingConditions() {
        let value = annotation(rawText: "Mo-Fr\n22-6 h\nbei Nässe")
        XCTAssertNil(value.window)
        XCTAssertEqual(value.text, "Mo-Fr 22-6 h bei Nässe")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: value,
            languageIdentifier: "de-DE"), "Montag bis Freitag von 22 Uhr bis 6 Uhr bei Nässe")
        XCTAssertTrue(TrafficSignSupplementaryPresentation.matchesNumeric(value,
            displayedSpeedKmh: 30, cameraEvidence: true, now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesNumeric(value,
            displayedSpeedKmh: 50, cameraEvidence: true, now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesNumeric(value,
            displayedSpeedKmh: 30, cameraEvidence: false, now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(value,
            classID: "maxspeed:30", now: observedAt))
    }

    func testRawPictogramRestrictionMatchesOnlyItsOwnVisibleClass() {
        let value = TrafficSignSupplementaryOCRAnnotation(primaryClassID: "hazard:school", primarySpeedKmh: nil,
            physicalSignID: "school-1", frameID: "school-frame", sourceObservedAt: observedAt,
            observedAt: observedAt, firstSeenAt: observedAt, rawText: "Schule\nMo–Fr", window: nil,
            readStatus: .read, primaryBoundingBox: .init(x: 0.2, y: 0.2, width: 0.1, height: 0.1),
            ocrBoundingBox: nil, engine: "apple_vision_text_recognition", modelVersion: "revision3")
        XCTAssertTrue(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: "hazard:school", now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesPictogram(value, classID: "parking", now: observedAt))
        XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesNumeric(value, displayedSpeedKmh: 30, cameraEvidence: true, now: observedAt))
        XCTAssertEqual(value.text, "Schule Mo–Fr")
    }

    func testFailedOrEmptyOCRCannotDisplayOrSpeakARestriction() {
        for value in [annotation(rawText: nil, status: .noText),
                      annotation(rawText: nil, status: .failed),
                      annotation(rawText: " \n ")] {
            XCTAssertNil(value.text)
            XCTAssertFalse(TrafficSignSupplementaryPresentation.matchesNumeric(value,
                displayedSpeedKmh: 30, cameraEvidence: true, now: observedAt))
            XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: value,
                languageIdentifier: "de-DE"), "")
        }
    }

    func testPublicPanoramaxWeekdayAndSuperscriptMinutesRetainAllClauses() {
        for raw in ["Mo-Fr\n630_1730 h", "Mo-Fr\n6³⁰–17³⁰ h"] {
            let value = annotation(rawText: raw)
            XCTAssertEqual(value.rawText, raw)
            XCTAssertNil(value.window)
            XCTAssertEqual(value.text, "Mo-Fr 6:30–17:30 h")
            XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: value, languageIdentifier: "de-DE"),
                           "Montag bis Freitag von 6 Uhr 30 bis 17 Uhr 30")
        }
        XCTAssertEqual(TrafficSignOCRTextFormatting.display("1234-5678 h"), "1234-5678 h")
        XCTAssertEqual(TrafficSignOCRTextFormatting.display("630-1730 kg"), "630-1730 kg")
    }

    func testParsedTimeIsFormattedForPresentationWithoutEvaluatingTheClock() throws {
        let window = try XCTUnwrap(TrafficSignSupplementaryTimeWindow.parse("22-6 h"))
        let value = annotation(rawText: "22-6 h", window: window)
        XCTAssertEqual(value.text, "22–6 h")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.spokenPhrase(for: value,
            languageIdentifier: "de-DE"), "von 22 Uhr bis 6 Uhr")
        let refreshed = value.refreshed(at: observedAt.addingTimeInterval(60 * 60 * 12))
        XCTAssertTrue(TrafficSignSupplementaryPresentation.matchesNumeric(refreshed,
            displayedSpeedKmh: 30, cameraEvidence: true, now: refreshed.observedAt))
        XCTAssertEqual(refreshed.frameID, value.frameID)
        XCTAssertEqual(refreshed.sourceObservedAt, value.sourceObservedAt)
    }

    func testMatchingTextlessPrimaryRefreshesSuccessfulTextWithoutChangingOCRSource() throws {
        let value = annotation(rawText: "Mo-Fr\n22-6 h")
        let nextFrame = observedAt.addingTimeInterval(2)
        let retained = try XCTUnwrap(TrafficSignSupplementaryPresentation.retainedAnnotation(
            value, primaryClassID: "maxspeed:30", primarySpeedKmh: 30, physicalSignID: "track-1",
            evidenceAt: nextFrame, now: nextFrame))
        XCTAssertEqual(retained.rawText, value.rawText)
        XCTAssertEqual(retained.observedAt, nextFrame)
        XCTAssertEqual(retained.frameID, value.frameID)
        XCTAssertEqual(retained.sourceObservedAt, value.sourceObservedAt)
        XCTAssertEqual(retained.primaryBoundingBox, value.primaryBoundingBox)
        XCTAssertTrue(TrafficSignSupplementaryPresentation.matchesNumeric(retained,
            displayedSpeedKmh: 30, cameraEvidence: true, now: nextFrame.addingTimeInterval(2)))
    }

    func testTextlessReplacementCannotBorrowTextFromAnotherPhysicalSignClassOrSpeed() {
        let value = annotation(rawText: "Mo-Fr")
        for (classID, speed, physicalID) in [("maxspeed:30", 30, "track-2"),
                                           ("maxspeed:50", 50, "track-1"),
                                           ("maxspeed:30", 50, "track-1")] {
            XCTAssertNil(TrafficSignSupplementaryPresentation.retainedAnnotation(
                value, primaryClassID: classID, primarySpeedKmh: speed, physicalSignID: physicalID,
                evidenceAt: observedAt.addingTimeInterval(1), now: observedAt.addingTimeInterval(1)))
        }
    }

    func testVisualMissKeepsOriginalExpiryButClassAloneCannotBorrowText() {
        let value = annotation(rawText: "Mo-Fr")
        XCTAssertEqual(TrafficSignSupplementaryPresentation.retainedAnnotation(
            value, primaryClassID: nil, primarySpeedKmh: 30, physicalSignID: nil,
            evidenceAt: observedAt.addingTimeInterval(2), now: observedAt.addingTimeInterval(2)), value)
        XCTAssertNil(TrafficSignSupplementaryPresentation.retainedAnnotation(
            value, primaryClassID: "maxspeed:30", primarySpeedKmh: 30, physicalSignID: nil,
            evidenceAt: observedAt.addingTimeInterval(2), now: observedAt.addingTimeInterval(2)))
        XCTAssertNil(TrafficSignSupplementaryPresentation.retainedAnnotation(
            value, primaryClassID: "maxspeed:30", primarySpeedKmh: 30, physicalSignID: "track-1",
            evidenceAt: observedAt.addingTimeInterval(4), now: observedAt.addingTimeInterval(4)))
    }

    func testTextlessPrimaryCannotReviveEmptyFailedOrFutureOCR() {
        for value in [annotation(rawText: nil, status: .noText), annotation(rawText: nil, status: .failed),
                      annotation(rawText: " \n ")] {
            XCTAssertNil(TrafficSignSupplementaryPresentation.retainedAnnotation(
                value, primaryClassID: "maxspeed:30", primarySpeedKmh: 30, physicalSignID: "track-1",
                evidenceAt: observedAt, now: observedAt))
        }
        XCTAssertNil(TrafficSignSupplementaryPresentation.retainedAnnotation(
            annotation(rawText: "Mo-Fr"), primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
            physicalSignID: "track-1", evidenceAt: observedAt, now: observedAt.addingTimeInterval(-1)))
    }

    private func annotation(rawText: String?, status: TrafficSignSupplementaryOCRReadStatus = .read,
                            window: TrafficSignSupplementaryTimeWindow? = nil) -> TrafficSignSupplementaryOCRAnnotation {
        TrafficSignSupplementaryOCRAnnotation(primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
            physicalSignID: "track-1", frameID: "frame-2", sourceObservedAt: observedAt,
            observedAt: observedAt, firstSeenAt: observedAt.addingTimeInterval(-0.5),
            rawText: rawText, window: window, readStatus: status,
            primaryBoundingBox: .init(x: 0.2, y: 0.2, width: 0.1, height: 0.1),
            ocrBoundingBox: .init(x: 0.2, y: 0.3, width: 0.1, height: 0.1),
            engine: "apple_vision_text_recognition", modelVersion: "revision3")
    }

    private func matchesNumeric(
        _ value: TrafficSignSupplementaryTextObservation,
        speed: Int?,
        cameraEvidence: Bool = true,
        now: Date? = nil
    ) -> Bool {
        TrafficSignSupplementaryPresentation.matchesNumeric(value, displayedSpeedKmh: speed,
            cameraEvidence: cameraEvidence, now: now ?? observedAt)
    }

    private func observation(
        classID: String = "parking",
        speed: Int? = nil,
        physicalID: String = "track-1",
        timestamp: Date? = nil,
        endMinutes: Int = 6 * 60
    ) throws -> TrafficSignSupplementaryTextObservation {
        let window = try XCTUnwrap(TrafficSignSupplementaryTimeWindow(startMinutes: 22 * 60, endMinutes: endMinutes))
        return TrafficSignSupplementaryTextObservation(primaryClassID: classID, primarySpeedKmh: speed,
            physicalSignID: physicalID, window: window, observedAt: timestamp ?? observedAt)
    }
}
