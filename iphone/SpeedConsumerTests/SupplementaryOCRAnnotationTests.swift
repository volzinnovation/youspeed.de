import Foundation
import XCTest
@testable import SpeedConsumer

final class SupplementaryOCRAnnotationTests: XCTestCase {
    func testFullContractLengthRawTextKeepsEveryClauseAndEscapesNewlinesInConsentedRecords() throws {
        let tail = "\nbei Nässe; außer \\\"Anlieger\\\"\r\nunknown clause"
        let raw = String(repeating: "x", count: 4096 - tail.unicodeScalars.count) + tail
        let value = try annotation(rawText: raw)
        let encoded = try SignCollectionJSON.canonical(value.wire)
        XCTAssertFalse(encoded.contains("\n")); XCTAssertFalse(encoded.contains("\r"))
        let decoded = try XCTUnwrap(SignCollectionJSON.parse(encoded) as? [String: Any])
        XCTAssertEqual((decoded["raw_text"] as? String)?.unicodeScalars.count, 4096)
        XCTAssertEqual(decoded["raw_text"] as? String, raw)
    }
    private let at = Date(timeIntervalSince1970: 1_000)
    private var contractRoot: URL {
        Bundle.main.url(forResource: "collection-contract-v1", withExtension: nil)
            ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("shared/tsr/collection-contract-v1")
    }
    private func annotation(rawText: String? = "Mo–Fr\n22–6 h\nbei Nässe", status: SupplementaryOCRAnnotation.Status = .read) throws -> SupplementaryOCRAnnotation {
        try XCTUnwrap(SupplementaryOCRAnnotation(primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
            physicalSignID: "physical-1", frameID: "ocr-frame-2", observedAt: at.addingTimeInterval(0.2), firstSeenAt: at,
            rawText: rawText, status: status, primaryBox: .init(x: 0.1, y: 0.1, width: 0.2, height: 0.2),
            ocrBox: .init(x: 0.1, y: 0.3, width: 0.2, height: 0.2), engine: "vision-fast",
            modelVersion: "revision-3", parsedTimeWindow: nil))
    }
    private func gate() throws -> SignCollectionContractGate {
        try SignCollectionContractGate { try Data(contentsOf: contractRoot.appendingPathComponent($0)) }
    }
    private func fixture() throws -> [String: Any] {
        let batch = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/sighting-batch-v1.json"), encoding: .utf8)) as! [String: Any]
        return (batch["events"] as! [[String: Any]])[0]
    }

    func testUnparsedRawTextSurvivesSightingAndCropContractWithoutChangingClassification() throws {
        let annotation = try annotation(), gate = try gate()
        var sighting = try fixture()
        let originalClassification = try SignCollectionJSON.canonical(sighting["classification"]!)
        sighting["supplementary_ocr"] = annotation.wire
        try gate.validate(sighting, model: "sighting")
        XCTAssertEqual(try SignCollectionJSON.canonical(sighting["classification"]!), originalClassification)
        let roundTrip = try SignCollectionJSON.parse(SignCollectionJSON.canonical(sighting)) as! [String: Any]
        let saved = try XCTUnwrap(roundTrip["supplementary_ocr"] as? [String: Any])
        XCTAssertEqual(saved["raw_text"] as? String, "Mo–Fr\n22–6 h\nbei Nässe")
        XCTAssertTrue(saved["parsed_time_window"] is NSNull)
        var crop = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/crop-v1.json"), encoding: .utf8)) as! [String: Any]
        crop["supplementary_ocr"] = annotation.wire
        try gate.validate(crop, model: "crop")
        XCTAssertEqual((crop["supplementary_ocr"] as? [String: Any])?["frame_id"] as? String, "ocr-frame-2")
    }

    func testRejectedRawReadSurvivesConsentContractWithoutATimeWindow() throws {
        let value = try annotation(rawText: "Mo-Fr\n6:30-17:20 h", status: .noText)
        var sighting = try fixture(); sighting["supplementary_ocr"] = value.wire
        try gate().validate(sighting, model: "sighting")
        XCTAssertEqual(value.wire["raw_text"] as? String, "Mo-Fr\n6:30-17:20 h")
        XCTAssertTrue(value.wire["parsed_time_window"] is NSNull)
    }

    func testNoTextAndFailureAreRecordedWithoutInventingRestrictionText() throws {
        for status in [SupplementaryOCRAnnotation.Status.noText, .failed] {
            let annotation = try annotation(rawText: nil, status: status)
            var sighting = try fixture(); sighting["supplementary_ocr"] = annotation.wire
            try gate().validate(sighting, model: "sighting")
            XCTAssertTrue(annotation.wire["raw_text"] is NSNull)
            XCTAssertEqual(annotation.wire["status"] as? String, status.rawValue)
        }
        XCTAssertNil(SupplementaryOCRAnnotation(primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
            physicalSignID: "physical", frameID: "frame", observedAt: at, firstSeenAt: at,
            rawText: nil, status: .read, primaryBox: .init(x: 0, y: 0, width: 1, height: 1),
            ocrBox: nil, engine: "vision", modelVersion: "3", parsedTimeWindow: nil))
    }

    func testMatchingDoesNotBorrowAnotherClassSpeedOrPhysicalLocation() throws {
        let value = try annotation()
        XCTAssertTrue(value.matches(modelLabel: "maxspeed:30", speedKmh: 30, box: [0.1, 0.1, 0.2, 0.2]))
        XCTAssertFalse(value.matches(modelLabel: "maxspeed:50", speedKmh: 30, box: [0.1, 0.1, 0.2, 0.2]))
        XCTAssertFalse(value.matches(modelLabel: "maxspeed:30", speedKmh: 50, box: [0.1, 0.1, 0.2, 0.2]))
        XCTAssertFalse(value.matches(modelLabel: "maxspeed:30", speedKmh: 30, box: [0.7, 0.7, 0.2, 0.2]))
    }

    func testSecondFrameCommitsAnnotationAndLaterCropsRetainOriginalOCRProvenance() throws {
        let observer = SignCollectionObserver(), annotation = try annotation(), payload = try fixture()
        let first = SignCollectionObserver.Detection(key: "maxspeed:30", box: [0.1, 0.1, 0.2, 0.2], payload: payload, presentationTrack: "primary")
        var second = first; second.supplementaryOCR = annotation
        var sightings = [[String: Any]](), candidates = [SignCollectionObserver.CropCandidate]()
        let capture: (SignCollectionObserver.CropCandidate) -> SignCollectionObserver.CropCaptureResult = { candidates.append($0); return .stored }
        try observer.observe(at: at, detections: [first], captureCrop: capture) { sightings.append($0) }
        XCTAssertTrue(sightings.isEmpty)
        try observer.observe(at: at.addingTimeInterval(0.2), detections: [second], captureCrop: capture) { sightings.append($0) }
        try observer.observe(at: at.addingTimeInterval(0.8), detections: [first], captureCrop: capture) { sightings.append($0) }
        XCTAssertEqual(sightings.count, 1); XCTAssertEqual(candidates.count, 2)
        let saved = try XCTUnwrap(sightings[0]["supplementary_ocr"] as? [String: Any])
        XCTAssertEqual(saved["raw_text"] as? String, annotation.rawText)
        for crop in candidates {
            XCTAssertEqual(crop.supplementaryOCR?.frameID, "ocr-frame-2")
            XCTAssertEqual(crop.supplementaryOCR?.observedAt, at.addingTimeInterval(0.2))
        }
        XCTAssertEqual(candidates[1].frameAt, at.addingTimeInterval(0.8))
        XCTAssertEqual(candidates[0].observationID, candidates[1].observationID)
    }

    func testTinyConfirmedSightingCollectsBeforeOCRAndLateAttemptsAreImmutableAndDeduplicated() throws {
        let observer = SignCollectionObserver()
        var payload = try fixture(), classification = (try fixture())["classification"] as! [String: Any]
        classification["model_label"] = "maxspeed:30"; classification["value"] = 30; payload["classification"] = classification
        let detection = SignCollectionObserver.Detection(key: "numeric", box: [0.1, 0.1, 0.2, 0.2], payload: payload, presentationTrack: "primary")
        var sightings = [[String: Any]](), events = [[String: Any]](), crops = [SignCollectionObserver.CropCandidate]()
        let capture: (SignCollectionObserver.CropCandidate) -> SignCollectionObserver.CropCaptureResult = { crops.append($0); return .stored }
        try observer.observe(at: at, detections: [detection], frameID: "frame-1") { sightings.append($0) }
        try observer.observe(at: at.addingTimeInterval(0.2), detections: [detection], frameID: "ocr-frame-2", captureCrop: capture) { sightings.append($0) }
        XCTAssertEqual(sightings.count, 1); XCTAssertNil(sightings[0]["supplementary_ocr"])
        let original = try SignCollectionJSON.canonical(sightings[0])
        let first = try annotation(rawText: nil, status: .noText)
        try observer.recordSupplementaryOCR(first, at: at.addingTimeInterval(0.3)) { events.append($0) }
        try observer.recordSupplementaryOCR(first, at: at.addingTimeInterval(0.4)) { events.append($0) }
        try observer.observe(at: at.addingTimeInterval(0.8), detections: [detection], frameID: "clear-frame-3") { sightings.append($0) }
        let clearer = try XCTUnwrap(SupplementaryOCRAnnotation(primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
            physicalSignID: "physical-1", frameID: "clear-frame-3", observedAt: at.addingTimeInterval(0.8), firstSeenAt: at,
            rawText: "22–6 h", status: .read, primaryBox: first.primaryBox, ocrBox: first.ocrBox,
            engine: first.engine, modelVersion: first.modelVersion, parsedTimeWindow: nil))
        try observer.recordSupplementaryOCR(clearer, at: at.addingTimeInterval(0.9)) { events.append($0) }
        try observer.observe(at: at.addingTimeInterval(1.4), detections: [detection], frameID: "frame-4", captureCrop: capture) { sightings.append($0) }
        XCTAssertEqual(events.count, 2); XCTAssertEqual(sightings.count, 1)
        XCTAssertEqual(try SignCollectionJSON.canonical(sightings[0]), original)
        XCTAssertEqual((sightings[0]["evidence"] as? [String: Any])?["analyzed_frames"] as? Int, 2)
        for event in events {
            try gate().validate(event, model: "media-status")
            XCTAssertEqual(event["association_status"] as? String, "exact")
            XCTAssertEqual(event["observation_id"] as? String, sightings[0]["event_id"] as? String)
            XCTAssertTrue(event["crop_id"] is NSNull)
        }
        XCTAssertNotEqual(events[0]["ocr_attempt_id"] as? String, events[1]["ocr_attempt_id"] as? String)
        XCTAssertEqual(crops.last?.supplementaryOCR?.frameID, "clear-frame-3")
        XCTAssertEqual(crops.last?.supplementaryOCR?.rawText, "22–6 h")
    }

    func testUnmatchedAttemptIsExplicitlyUnresolvedAndResetClearsAssociationAndDedup() throws {
        let observer = SignCollectionObserver(), annotation = try annotation()
        var events = [[String: Any]]()
        try observer.recordSupplementaryOCR(annotation, at: at.addingTimeInterval(1)) { events.append($0) }
        try gate().validate(events[0], model: "media-status")
        XCTAssertTrue(events[0]["observation_id"] is NSNull)
        XCTAssertEqual(events[0]["association_status"] as? String, "unresolved")
        observer.reset()
        try observer.recordSupplementaryOCR(annotation, at: at.addingTimeInterval(1)) { events.append($0) }
        XCTAssertEqual(events.count, 2)
        XCTAssertEqual(events[0]["ocr_attempt_id"] as? String, events[1]["ocr_attempt_id"] as? String)
        XCTAssertNotEqual(events[0]["event_id"] as? String, events[1]["event_id"] as? String)
        var invalid = events[0]; invalid["association_status"] = "exact"
        XCTAssertThrowsError(try gate().validate(invalid, model: "media-status"))
        invalid = events[0]; invalid["created_at"] = SignCollectionJSON.utc(at)
        XCTAssertThrowsError(try gate().validate(invalid, model: "media-status"))
        invalid = events[0]; invalid["status"] = "expired"
        XCTAssertThrowsError(try gate().validate(invalid, model: "media-status"))
    }

    func testPictogramNullableSpeedContractPreservesRawTextAndClassGeometryMatching() throws {
        let source = try annotation()
        let pictogram = try XCTUnwrap(SupplementaryOCRAnnotation(primaryClassID: "hazard:school", primarySpeedKmh: nil,
            physicalSignID: source.physicalSignID, frameID: source.frameID, observedAt: source.observedAt,
            firstSeenAt: source.firstSeenAt, rawText: "Schule", status: .read, primaryBox: source.primaryBox,
            ocrBox: source.ocrBox, engine: source.engine, modelVersion: source.modelVersion, parsedTimeWindow: nil))
        XCTAssertTrue(pictogram.wire["primary_speed_kmh"] is NSNull)
        XCTAssertTrue(pictogram.matches(modelLabel: "hazard:school", speedKmh: 100, box: [0.1, 0.1, 0.2, 0.2]))
        XCTAssertFalse(pictogram.matches(modelLabel: "hazard:children", speedKmh: nil, box: [0.1, 0.1, 0.2, 0.2]))
        var sighting = try fixture(); sighting["supplementary_ocr"] = pictogram.wire
        try gate().validate(sighting, model: "sighting")
    }
}
