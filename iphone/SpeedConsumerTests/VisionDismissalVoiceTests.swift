import XCTest
@testable import SpeedConsumer

final class VisionDismissalVoiceTests: XCTestCase {
    func testLocalizedWholeCommandsOnly() {
        for (locale, word) in [("de-DE", "Falsch"), ("en-US", "Wrong"), ("fr-FR", "Faux"), ("nl-NL", "Fout")] {
            XCTAssertTrue(VisionDismissalVoiceWindow.matchesCommand(" \(word)! ", language: locale))
            XCTAssertFalse(VisionDismissalVoiceWindow.matchesCommand("not \(word)", language: locale))
            XCTAssertFalse(VisionDismissalVoiceWindow.matchesCommand("\(word) 50", language: locale))
            XCTAssertFalse(VisionDismissalVoiceWindow.matchesCommand("", language: locale))
        }
        XCTAssertFalse(VisionDismissalVoiceWindow.matchesCommand("wrong", language: "de-DE"))
    }

    func testRepeatedFramesAndPassageDoNotExtendOrReopenWindow() throws {
        var gate = VisionDismissalVoiceWindow()
        let first = try XCTUnwrap(gate.offer(evidenceID: "1|track|30", language: "en-US", now: 10))
        XCTAssertTrue(gate.start(token: first.token, now: 10.3))
        XCTAssertNil(gate.offer(evidenceID: "1|track|30", language: "en-US", now: 13))
        XCTAssertTrue(gate.accepts(token: first.token, evidenceID: first.evidenceID, transcript: "wrong", now: 14.29))
        XCTAssertFalse(gate.accepts(token: first.token, evidenceID: first.evidenceID, transcript: "wrong", now: 14.65))
        gate.cancel()
        XCTAssertNil(gate.offer(evidenceID: "1|track|30", language: "en-US", now: 20))
    }

    func testNewEvidenceRejectsOldCallbackAndOldTranscript() throws {
        var gate = VisionDismissalVoiceWindow()
        let old = try XCTUnwrap(gate.offer(evidenceID: "1|track|30", language: "en-US", now: 10))
        XCTAssertTrue(gate.start(token: old.token, now: 10.3))
        let new = try XCTUnwrap(gate.offer(evidenceID: "1|track|50", language: "en-US", now: 11))
        XCTAssertTrue(gate.start(token: new.token, now: 11.3))
        XCTAssertFalse(gate.accepts(token: old.token, evidenceID: new.evidenceID, transcript: "wrong", now: 12))
        XCTAssertFalse(gate.accepts(token: new.token, evidenceID: old.evidenceID, transcript: "wrong", now: 12))
        XCTAssertTrue(gate.accepts(token: new.token, evidenceID: new.evidenceID, transcript: "wrong", now: 12))
    }

    func testGenerationChangeDoesNotReopenSamePhysicalSign() throws {
        var gate = VisionDismissalVoiceWindow()
        XCTAssertNotNil(gate.offer(evidenceID: "1|track|30", deduplicationID: "track|30", language: "en-US", now: 10))
        gate.cancel()
        XCTAssertNil(gate.offer(evidenceID: "2|track|30", deduplicationID: "track|30", language: "en-US", now: 11))
    }

    func testBoundedWaitForSpeechAndLifecycleCancellation() throws {
        var gate = VisionDismissalVoiceWindow()
        let first = try XCTUnwrap(gate.offer(evidenceID: "first", language: "de-DE", now: 10))
        XCTAssertFalse(gate.start(token: first.token, now: 13.01))
        XCTAssertFalse(gate.accepts(token: first.token, evidenceID: first.evidenceID, transcript: "falsch", now: 12))
        gate.cancel()
        XCTAssertFalse(gate.start(token: first.token, now: 12))
        let next = try XCTUnwrap(gate.offer(evidenceID: "next", language: "de-DE", now: 20))
        XCTAssertTrue(gate.start(token: next.token, now: 20.3))
        gate.cancel()
        XCTAssertFalse(gate.accepts(token: next.token, evidenceID: next.evidenceID, transcript: "falsch", now: 21))
    }
}
