import XCTest
import ImageIO
import AVFoundation
import UIKit
@testable import SpeedConsumer

final class TrafficSignSupplementaryOCRTests: XCTestCase {
    func testNativePrimaryZoneProofRejectsInformationPanelsAndMismatchedLimits() throws {
        for (number, label) in [("30", "ZONE"), ("20", "ZONE"), ("40", "Kurort"), ("70", "GEFAHR")] {
            let format = UIGraphicsImageRendererFormat(); format.scale = 1
            let image = UIGraphicsImageRenderer(size: CGSize(width: 400, height: 400), format: format).image { context in
                UIColor.white.setFill(); context.fill(CGRect(x: 0, y: 0, width: 400, height: 400))
                let style = NSMutableParagraphStyle(); style.alignment = .center
                let attributes: [NSAttributedString.Key: Any] = [.font: UIFont.boldSystemFont(ofSize: 70),
                    .foregroundColor: UIColor.black, .paragraphStyle: style]
                (number as NSString).draw(in: CGRect(x: 0, y: 70, width: 400, height: 100), withAttributes: attributes)
                (label as NSString).draw(in: CGRect(x: 0, y: 200, width: 400, height: 100), withAttributes: attributes)
            }
            XCTAssertEqual(TrafficSignSupplementaryOCR.verifiesZone(in: try XCTUnwrap(image.cgImage), speed: 30),
                           number == "30" && label == "ZONE", "\(number) \(label)")
        }
    }
    func testRawOCRDiagnosticEscapesRecordSeparatorsAndKeepsUnknownClauses() throws {
        let raw = "Mo-Fr\n6:30-17:30h\naußer \\\"Anlieger\\\"\r\ntimestamp=forged\u{0}\tbei Nässe"
        let read = TrafficSignSupplementaryOCRRead(rawText: raw, modelVersion: "revision-3", readStatus: .read)
        let line = TrafficSignSupplementaryOCRDiagnostics.attempt(read: read, classID: "hazard:school", frameID: "frame",
            width: 384, height: 377, number: 2, durationMilliseconds: 12.5)
        XCTAssertFalse(line.contains("\n")); XCTAssertFalse(line.contains("\r")); XCTAssertFalse(line.contains("\u{0}"))
        let data = try XCTUnwrap(line.dropFirst("ocr_attempt_v1=".count).data(using: .utf8))
        let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(decoded["raw_text"] as? String, raw)
        XCTAssertEqual(decoded["raw_characters"] as? Int, raw.count)
    }

    func testRawOCRDiagnosticPreservesFullContractLengthAndExplicitNoText() throws {
        let tail = "\nbei Nässe; außer Anlieger \\\"A\\\""
        let raw = String(repeating: "x", count: 4096 - tail.unicodeScalars.count) + tail
        for text in [raw, nil] {
            let read = TrafficSignSupplementaryOCRRead(rawText: text, modelVersion: "revision-3", readStatus: text == nil ? .noText : .read)
            let line = TrafficSignSupplementaryOCRDiagnostics.attempt(read: read, classID: "maxspeed:30", frameID: "frame",
                width: 384, height: 377, number: 2, durationMilliseconds: 12.5)
            let data = try XCTUnwrap(line.dropFirst("ocr_attempt_v1=".count).data(using: .utf8))
            let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            if let text { XCTAssertEqual(text.unicodeScalars.count, 4096); XCTAssertEqual(decoded["raw_text"] as? String, text) }
            else { XCTAssertTrue(decoded["raw_text"] is NSNull) }
        }
    }
    private let now = Date(timeIntervalSince1970: 20_000)
    private let night = TrafficSignSupplementaryTimeWindow(startMinutes: 22 * 60, endMinutes: 6 * 60)!

    private func primary(x: Double = 0.3, classID: String = "maxspeed:30", speed: Int? = 30, track: String? = "physical-1") -> TrafficSignSupplementaryTextTracker.Primary {
        .init(classID: classID, speedKmh: speed,
              box: .init(x: x, y: 0.2, width: 0.15, height: 0.15), physicalSignID: track)
    }

    func testTimeParserNormalizesHoursMinutesAndOvernightWindow() throws {
        for raw in ["22-6h", "22 – 6 h", "22—06 Uhr", "22−6", " 22-6h\n"] {
            let value = try XCTUnwrap(TrafficSignSupplementaryTimeWindow.parse(raw), raw)
            XCTAssertEqual(value, night)
            XCTAssertEqual(value.displayText, "22–6 h")
            XCTAssertTrue(value.crossesMidnight)
        }
        let minutes = try XCTUnwrap(TrafficSignSupplementaryTimeWindow.parse("06:15 - 22:30 h"))
        XCTAssertEqual(minutes.startMinutes, 375)
        XCTAssertEqual(minutes.endMinutes, 1350)
        XCTAssertEqual(minutes.displayText, "6:15–22:30 h")
        XCTAssertFalse(minutes.crossesMidnight)
    }

    func testTimeParserRejectsMalformedAmbiguousAndUnrelatedText() {
        for raw in ["", "30", "30 km/h", "22-6 km", "Mo-Fr 22-6h", "nur 22-6h", "22-6h extra",
                    "24-6h", "22-25h", "22:60-6h", "22:7-6h", "22--6h", "6-6h", "22/6h",
                    "22-6h\n8-10h", "2O-6h", "-1-6h", "123-6h"] {
            XCTAssertNil(TrafficSignSupplementaryTimeWindow.parse(raw), raw)
        }
    }

    func testMultipleOCRLinesCannotDropWeekdaysExceptionsOrConflictingTimes() {
        XCTAssertEqual(TrafficSignSupplementaryTimeWindow.parseRecognizedLines(["22-6h"]), night)
        for lines in [["Mo-Fr", "22-6h"], ["22-6h", "bei Nässe"], ["22-6h", "ausgenommen Anwohner"],
                      ["22-6h", "8-10h"], ["22-6h", "22-6h"], ["22-6h", "30"], []] {
            XCTAssertNil(TrafficSignSupplementaryTimeWindow.parseRecognizedLines(lines), "\(lines)")
        }
    }

    func testNativeCropUsesOneSignHeightBelowAndNeverResizes() throws {
        let rect = try XCTUnwrap(TrafficSignSupplementaryOCRGeometry.cropRect(
            primaryBox: .init(x: 0.25, y: 0.2, width: 0.1, height: 0.1), imageWidth: 2000, imageHeight: 1000))
        XCTAssertEqual(rect, CGRect(x: 500, y: 200, width: 200, height: 200))
        XCTAssertNil(TrafficSignSupplementaryOCRGeometry.cropRect(
            primaryBox: .init(x: 0.25, y: 0.85, width: 0.1, height: 0.1), imageWidth: 2000, imageHeight: 1000))
    }

    private func observe(_ tracker: inout TrafficSignSupplementaryTextTracker,
                         primary: TrafficSignSupplementaryTextTracker.Primary?, frame: Int, at seconds: Double,
                         confirmed: Bool, frames: Int, reads: inout Int,
                         raw: String? = "22-6h", status: TrafficSignSupplementaryOCRReadStatus = .read,
                         roi: CGSize? = CGSize(width: 100, height: 100), canRead: Bool = true)
        -> TrafficSignSupplementaryOCRAnnotation? {
        switch tracker.begin(primary: primary, frameID: "frame-\(frame)", at: now.addingTimeInterval(seconds),
                             confirmed: confirmed, evidenceFrames: frames, nativeROISize: roi, canRead: canRead) {
        case .notRequired: return nil
        case .cached(let value): return value
        case .perform(let attempt):
            reads += 1
            return tracker.finish(attempt, read: .init(rawText: raw, modelVersion: "revision3", readStatus: status),
                                  ocrBoundingBox: nil)
        }
    }

    func testFirstProvisionalDoesNotReadAndConfirmedGetsTwoDistinctInspections() throws {
        var tracker = TrafficSignSupplementaryTextTracker()
        var reads = 0
        XCTAssertNil(observe(&tracker, primary: primary(), frame: 1, at: 0, confirmed: false, frames: 1, reads: &reads))
        XCTAssertEqual(reads, 0)
        let confirmed = try XCTUnwrap(observe(&tracker, primary: primary(), frame: 2, at: 0.201,
            confirmed: true, frames: 2, reads: &reads))
        XCTAssertEqual(reads, 1)
        XCTAssertEqual(confirmed.text, "22–6 h")
        XCTAssertEqual(confirmed.firstSeenAt, now)
        for frame in 3...20 {
            XCTAssertNotNil(observe(&tracker, primary: primary(), frame: frame, at: Double(frame) * 0.2,
                confirmed: true, frames: frame, reads: &reads))
        }
        XCTAssertEqual(reads, 2, "Two source inspections permit authority; subsequent same-size frames do not reread")
    }

    func testPictogramUsesTwoDistinctAcceptedFramesWithoutSpeedFusion() throws {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        let sign = primary(classID: "hazard:school", speed: nil, track: nil)
        XCTAssertNil(observe(&tracker, primary: sign, frame: 1, at: 0, confirmed: false, frames: 1, reads: &reads))
        XCTAssertNil(observe(&tracker, primary: sign, frame: 1, at: 0.1, confirmed: false, frames: 1, reads: &reads))
        XCTAssertEqual(reads, 0, "Repeated callbacks from one frame cannot confirm a pictogram")
        let value = try XCTUnwrap(observe(&tracker, primary: sign, frame: 2, at: 0.3,
            confirmed: false, frames: 1, reads: &reads, raw: "Schule"))
        XCTAssertNil(value.primarySpeedKmh)
        XCTAssertEqual(value.text, "Schule")
        XCTAssertEqual(reads, 1)
    }

    func testNumericStillRequiresExistingConfirmationAndTwoEvidenceFrames() {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        XCTAssertNil(observe(&tracker, primary: primary(), frame: 1, at: 0,
            confirmed: true, frames: 1, reads: &reads))
        XCTAssertNil(observe(&tracker, primary: primary(), frame: 2, at: 0.2,
            confirmed: false, frames: 3, reads: &reads))
        XCTAssertEqual(reads, 0)
    }

    func testTinyAndThermallyDeferredViewsDoNotConsumeAttempts() throws {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        for frame in 1...8 {
            XCTAssertNil(observe(&tracker, primary: primary(), frame: frame, at: Double(frame) * 0.2,
                confirmed: true, frames: frame + 1, reads: &reads,
                roi: frame < 5 ? CGSize(width: 47, height: 31) : CGSize(width: 48, height: 32), canRead: frame < 5))
        }
        XCTAssertEqual(reads, 0)
        XCTAssertNotNil(observe(&tracker, primary: primary(), frame: 9, at: 1.9,
            confirmed: true, frames: 10, reads: &reads, roi: CGSize(width: 48, height: 32)))
        XCTAssertEqual(reads, 1)
    }

    func testNewPhysicalSignAndScopeResetAllowOneNewAttemptEach() throws {
        var tracker = TrafficSignSupplementaryTextTracker()
        var reads = 0
        let first = try XCTUnwrap(observe(&tracker, primary: primary(), frame: 1, at: 0,
            confirmed: true, frames: 2, reads: &reads))
        let replacement = try XCTUnwrap(observe(&tracker, primary: primary(track: "physical-2"), frame: 2, at: 0.2,
            confirmed: true, frames: 2, reads: &reads))
        XCTAssertEqual(reads, 2)
        XCTAssertGreaterThan(replacement.firstSeenAt, first.firstSeenAt)
        tracker.reset()
        XCTAssertNotNil(observe(&tracker, primary: primary(track: "physical-2"), frame: 3, at: 0.4,
            confirmed: true, frames: 2, reads: &reads))
        XCTAssertEqual(reads, 3)
    }

    func testUnreadableAgreementRetryThenRequiresLargerPixelsAndCadence() throws {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        let failed = observe(&tracker, primary: primary(), frame: 1, at: 0,
            confirmed: true, frames: 2, reads: &reads, raw: nil, status: .noText)
        XCTAssertEqual(failed?.readStatus, .noText)
        _ = observe(&tracker, primary: primary(), frame: 2, at: 0.2,
            confirmed: true, frames: 3, reads: &reads, roi: CGSize(width: 200, height: 200))
        _ = observe(&tracker, primary: primary(), frame: 3, at: 0.4,
            confirmed: true, frames: 4, reads: &reads, roi: CGSize(width: 130, height: 130))
        XCTAssertEqual(reads, 2, "The second distinct frame inspection is allowed without growth")
        let clearer = try XCTUnwrap(observe(&tracker, primary: primary(), frame: 4, at: 0.8,
            confirmed: true, frames: 5, reads: &reads, raw: "Mo–Fr 6:30–17:30 h", roi: CGSize(width: 180, height: 180)))
        XCTAssertEqual(reads, 3)
        XCTAssertEqual(clearer.text, "Mo–Fr 6:30–17:30 h")
        _ = observe(&tracker, primary: primary(), frame: 5, at: 1.2,
            confirmed: true, frames: 6, reads: &reads, raw: nil, status: .failed, roi: CGSize(width: 250, height: 250))
        XCTAssertEqual(reads, 4)
        XCTAssertEqual(tracker.presentationAnnotation(at: now.addingTimeInterval(1))?.text, clearer.text,
            "A later failure is collected without erasing the useful read")
    }

    func testRetryBudgetStopsAtSixAndStablePhysicalIdentitySurvivesApproach() {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        for frame in 1...10 {
            let side = 50 * pow(1.5, Double(frame - 1))
            let sign = TrafficSignSupplementaryTextTracker.Primary(classID: "maxspeed:30", speedKmh: 30,
                box: .init(x: frame % 2 == 0 ? 0.7 : 0.1, y: 0.1, width: 0.1, height: 0.1), physicalSignID: "stable")
            _ = observe(&tracker, primary: sign, frame: frame, at: Double(frame) * 0.4,
                confirmed: true, frames: frame + 1, reads: &reads, raw: nil, status: .noText,
                roi: CGSize(width: side, height: side))
        }
        XCTAssertEqual(reads, 6)
    }

    func testExecutionDeferralRestoresTheReadBudget() throws {
        var tracker = TrafficSignSupplementaryTextTracker()
        guard case .perform(let attempt) = tracker.begin(primary: primary(), frameID: "a", at: now,
            confirmed: true, evidenceFrames: 2, nativeROISize: CGSize(width: 100, height: 100)) else { return XCTFail("Expected admission") }
        tracker.deferAttempt(attempt)
        guard case .perform(let retried) = tracker.begin(primary: primary(), frameID: "b", at: now.addingTimeInterval(0.1),
            confirmed: true, evidenceFrames: 3, nativeROISize: CGSize(width: 100, height: 100)) else { return XCTFail("Deferral must permit same pixels") }
        XCTAssertEqual(retried.number, 1)
    }

    func testRawConditionsArePreservedWithoutBeingReducedToATimeWindow() throws {
        var tracker = TrafficSignSupplementaryTextTracker()
        var reads = 0
        let raw = "Mo-Fr\n22-6h\nbei Nässe"
        let value = try XCTUnwrap(observe(&tracker, primary: primary(), frame: 1, at: 0,
            confirmed: true, frames: 2, reads: &reads, raw: raw))
        XCTAssertEqual(value.rawText, raw)
        XCTAssertEqual(value.text, "Mo-Fr 22-6h bei Nässe")
        XCTAssertNil(value.window)
        XCTAssertNil(value.supplementaryText)
    }

    func testCachedAnnotationKeepsSourceIdentityAndRefreshesOnlyPresentationTimestamp() throws {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        _ = observe(&tracker, primary: primary(), frame: 1, at: 0, confirmed:true,frames:2,reads:&reads)
        let source = try XCTUnwrap(observe(&tracker,primary:primary(),frame:2,at:0.4,confirmed:true,frames:3,reads:&reads))
        let cached = try XCTUnwrap(observe(&tracker,primary:primary(),frame:3,at:1,confirmed:true,frames:4,reads:&reads))
        XCTAssertEqual(cached.frameID,source.frameID)
        XCTAssertEqual(cached.sourceObservedAt,source.sourceObservedAt)
        XCTAssertEqual(cached.firstSeenAt,source.firstSeenAt)
        XCTAssertEqual(cached.primaryBoundingBox,source.primaryBoundingBox)
        XCTAssertEqual(cached.observedAt,now.addingTimeInterval(1))
        XCTAssertEqual(reads,2,"Only the first two independent inspections may run without pixel growth")
    }
    func testLossCannotAttachOldTextToAReplacementOrAnUnmatchedFrame() throws {
        var tracker = TrafficSignSupplementaryTextTracker(), reads = 0
        XCTAssertNotNil(observe(&tracker,primary:primary(),frame:1,at:0,confirmed:true,frames:2,reads:&reads))
        XCTAssertNil(observe(&tracker,primary:nil,frame:2,at:0.2,confirmed:true,frames:3,reads:&reads))
        let fresh = try XCTUnwrap(observe(&tracker,primary:primary(),frame:3,at:3,confirmed:true,frames:4,reads:&reads))
        XCTAssertEqual(fresh.frameID,"frame-3")
        XCTAssertEqual(fresh.sourceObservedAt,now.addingTimeInterval(3))
        XCTAssertEqual(fresh.firstSeenAt,now.addingTimeInterval(3),"Reacquisition gets actual new pixels, never cached old provenance")
        XCTAssertEqual(reads,2)
    }

    #if os(iOS)
    func testRuntimeDeliversConfirmedPrimaryThenAuxiliaryCompletionWithoutReprocessingFrame() throws {
        try assertRuntimeOCRDelivery(thermal: .nominal)
    }

    func testRuntimeReadsAtSeriousThermalInsteadOfPermanentlyCachingFailure() throws {
        try assertRuntimeOCRDelivery(thermal: .serious)
    }

    func testClearerRuntimeRetryUsesAuxiliaryCompletionWithoutReplayingPrimary() throws {
        try assertRuntimeOCRDelivery(thermal: .nominal, retry: true)
    }

    func testRuntimeReadsSupplementaryPlateForAnAcceptedPictogram() throws {
        try assertRuntimeOCRDelivery(thermal: .nominal, pictogram: true)
    }

    func testSavedVisualCalibrationPreservesNativeOCRSourceWithMobileDetectorWindow() throws {
        try assertRuntimeOCRDelivery(thermal: .nominal, calibrated: true)
    }

    private func assertRuntimeOCRDelivery(thermal: TrafficSignThermalState, retry: Bool = false, pictogram: Bool = false, calibrated: Bool = false) throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "DE.panoramax-bootstrap", withExtension: "tsrmodelpack", subdirectory: "TSRModelPacks"))
        let manifest = try TrafficSignPackJSON.decoder().decode(TrafficSignModelPackManifest.self,
            from: Data(contentsOf: url.appendingPathComponent("manifest.json")))
        let artifact = try XCTUnwrap(manifest.detector.artifacts.first { $0.platform == .ios })
        let verified = TrafficSignVerifiedModelPack(directoryURL: url, manifest: manifest,
            detectorArtifact: artifact, detectorArtifactURL: url.appendingPathComponent(artifact.path))
        let context = TrafficSignDetectionContext(wayId: "123", latitude: 49.0069, longitude: 8.4037,
            headingDegrees: 82, travelDirection: .forward,
            sourceSignature: .init(osmRevision: "ordering-test", localCorrectionRevision: nil))
        let snapshot = TrafficSignFrameSnapshot(context: context,
            conditions: .init(speedKmh: 50, candidateRecentlySeen: false, lowPowerMode: false,
                              thermalState: thermal, appIsActive: true), captureSessionId: "ordering-test")
        let detection = TrafficSignDetection(rawClassId: pictogram ? "hazard:school" : "maxspeed:30", rawLabel: pictogram ? "hazard:school" : "30",
            semantic: .init(kind: pictogram ? .unknown : .maximumSpeed, value: pictogram ? nil : 30,
                            unit: pictogram ? nil : "km/h"), rawScore: 0.99,
            calibratedConfidence: nil, boundingBox: .init(x: 0.02, y: 0.02,
                width: retry ? 0.55 : 0.95, height: retry ? 0.35 : 0.48), classThreshold: 0.7)
        let larger = TrafficSignDetection(rawClassId: "maxspeed:30", rawLabel: "30",
            semantic: .init(kind: .maximumSpeed, value: 30, unit: "km/h"), rawScore: 0.99,
            calibratedConfidence: nil, boundingBox: .init(x: 0.02, y: 0.02, width: 0.95, height: 0.48), classThreshold: 0.7)
        var pixel: CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault, 136, 230, kCVPixelFormatType_32BGRA,
            [kCVPixelBufferCGImageCompatibilityKey: true, kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary, &pixel), kCVReturnSuccess)
        let image = try XCTUnwrap(pixel)
        CVPixelBufferLockBaseAddress(image, [])
        memset(try XCTUnwrap(CVPixelBufferGetBaseAddress(image)), 255, CVPixelBufferGetBytesPerRow(image) * CVPixelBufferGetHeight(image))
        CVPixelBufferUnlockBaseAddress(image, [])
        var format: CMVideoFormatDescription?
        XCTAssertEqual(CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault,
            imageBuffer: image, formatDescriptionOut: &format), noErr)
        var timing = CMSampleTimingInfo(duration: .invalid, presentationTimeStamp: .zero, decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        XCTAssertEqual(CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: image,
            formatDescription: try XCTUnwrap(format), sampleTiming: &timing, sampleBufferOut: &sample), noErr)
        let buffer = try XCTUnwrap(sample)
        let store = SupplementaryOCREmissionStore()
        let done = expectation(description: "provisional primary, confirmed primary, auxiliary completion")
        done.expectedFulfillmentCount = retry ? 5 : 3
        let runtime = TrafficSignRuntime(verifiedPack: verified,
            backend: SupplementaryOCRTestBackend(retry ? [detection, detection, larger] : [detection]),
            snapshotProvider: { snapshot }, callbackQueue: DispatchQueue(label: "ocr-ordering-test"),
            eventHandler: { store.append($0); done.fulfill() },
            visualCalibrationProvider: {
                guard calibrated else { return nil }
                var calibration = VisualRoadCalibration.defaults(width: 136, height: 230, orientationKey: "rear:exif:1")
                calibration.leftTopX = 0.37
                return calibration
            })
        defer { runtime.stop() }
        runtime.consumeVideoFrame(buffer, orientation: .up)
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.6) { runtime.consumeVideoFrame(buffer, orientation: .up) }
        if retry {
            DispatchQueue.global().asyncAfter(deadline: .now() + 1.2) { runtime.consumeVideoFrame(buffer, orientation: .up) }
        }
        wait(for: [done], timeout: 7)
        let values = store.snapshot()
        guard values.count == (retry ? 5 : 3) else { XCTFail("Unexpected callback count \(values.count)"); return }
        XCTAssertEqual(Array(values.prefix(3)).map(\.ocrPhase), pictogram
            ? [.notRequired, .notRequired, .completed] : [.notRequired, .pending, .completed])
        XCTAssertEqual(Array(values.prefix(3)).map(\.event.state), pictogram
            ? [.unknown, .unknown, .unknown] : [.provisional, .confirmed, .confirmed])
        XCTAssertEqual(values[1].event.frameId, values[2].event.frameId)
        XCTAssertNil(values[1].ocrAnnotation)
        XCTAssertNotNil(values[2].ocrAnnotation)
        XCTAssertEqual(values[2].ocrAttemptAnnotation?.readStatus, .noText)
        let diagnostic = try XCTUnwrap(values[2].ocrDiagnostic)
        let diagnosticData = try XCTUnwrap(diagnostic.dropFirst("ocr_attempt_v1=".count).data(using: .utf8))
        let diagnosticFields = try XCTUnwrap(JSONSerialization.jsonObject(with: diagnosticData) as? [String: Any])
        XCTAssertEqual(diagnosticFields["status"] as? String, "no_text")
        XCTAssertLessThanOrEqual(try XCTUnwrap(diagnosticFields["native_roi_width"] as? Int),230,"OCR keeps native captured pixels despite the detector's1024 input window")
        XCTAssertEqual(values[2].ocrAttemptAnnotation?.assemblyEvidence?.sourceWidth,230)
        XCTAssertEqual(values[2].ocrAttemptAnnotation?.assemblyEvidence?.nativeContentRect?.width,136)
        XCTAssertTrue(diagnosticFields["raw_text"] is NSNull)
        XCTAssertTrue(values[2].supplementaryOCROnly, "Every OCR completion refines evidence without replaying the primary")
        XCTAssertTrue(values.filter { !$0.supplementaryOCROnly }.allSatisfy { $0.ocrAnnotation == nil && $0.ocrAttemptAnnotation == nil },
            "Cached OCR never becomes fresh evidence on a normal primary emission")
        if pictogram {
            XCTAssertNil(values[2].ocrAttemptAnnotation?.primarySpeedKmh)
            XCTAssertEqual(values[2].ocrAttemptAnnotation?.primaryClassID, "hazard:school")
        }
        if retry {
            XCTAssertEqual(values[3].event.frameId, values[4].event.frameId)
            XCTAssertFalse(values[3].supplementaryOCROnly)
            XCTAssertEqual(values[3].ocrPhase,.pending)
            XCTAssertTrue(values[4].supplementaryOCROnly)
            XCTAssertNotNil(values[4].ocrAttemptAnnotation)
            XCTAssertEqual(runtime.metrics.completedInferences, 3)
        } else { XCTAssertEqual(runtime.metrics.completedInferences, 2) }
    }

    func testStrongerNumericAndWeakerSecondaryPublishIndependentlyFromTheSameFrames() throws {
        let fixture = try blockedRuntimeFixture()
        let speed = blockedDetection(speed:60)
        let school = TrafficSignDetection(rawClassId:"hazard:school",rawLabel:"hazard:school",
            semantic:.init(kind:.unknown,value:nil,unit:nil),rawScore:0.94,calibratedConfidence:nil,
            boundingBox:.init(x:0.65,y:0.15,width:0.2,height:0.3),classThreshold:0.7)
        let store = SupplementaryOCREmissionStore()
        let primaryFrames = expectation(description:"two simultaneous primary and secondary frame results")
        primaryFrames.expectedFulfillmentCount = 2
        let runtime = TrafficSignRuntime(verifiedPack:fixture.verified,
            backend:SupplementaryOCRTestBackend(frames:[[speed,school]]),snapshotProvider:{fixture.snapshot},
            callbackQueue:DispatchQueue(label:"simultaneous-numeric-secondary-test"),eventHandler:{
                store.append($0)
                if !$0.supplementaryOCROnly {primaryFrames.fulfill()}
            },supplementaryOCRReader:{_ in .init(rawText:nil,modelVersion:"simultaneous-test",readStatus:.noText)})
        defer {runtime.stop()}
        runtime.consumeVideoFrame(fixture.buffer,orientation:.up)
        DispatchQueue.global().asyncAfter(deadline:.now()+0.6) {runtime.consumeVideoFrame(fixture.buffer,orientation:.up)}
        wait(for:[primaryFrames],timeout:4)
        let values = store.snapshot().filter {!$0.supplementaryOCROnly}
        XCTAssertEqual(values.count,2)
        for value in values {
            XCTAssertEqual(value.event.candidate?.rawClassId,"maxspeed:60")
            XCTAssertEqual(value.event.candidate?.value,60,"A weaker secondary sign never takes the primary fusion lane")
            XCTAssertEqual(value.displayObservation?.classID,"hazard:school",
                "A stronger numeric sign cannot hide an independently qualified secondary sign")
            XCTAssertEqual(value.displayObservation?.classifierScore,0.94)
            XCTAssertFalse(value.displayObservation?.affectsSpeed ?? true)
            let displayTrack = try XCTUnwrap(value.displayObservation?.applicabilityDecision?.trackId)
            let numericTrack = try XCTUnwrap(value.event.applicabilityDecision?.trackId)
            XCTAssertNotEqual(displayTrack,numericTrack,"Each stream retains the applicability decision for its own sign")
        }
        XCTAssertEqual(values.last?.event.state,.confirmed)
        XCTAssertEqual(runtime.metrics.completedInferences,2)
    }

    func testBlockedOCRAllowsFollowingNumericAndSecondaryDetectionsAndStopRejectsItsCompletion() throws {
        let fixture = try blockedRuntimeFixture()
        let entered = expectation(description: "OCR worker entered")
        let finished = expectation(description: "OCR worker exited")
        let primaries = expectation(description: "all five detector results delivered while OCR is blocked")
        primaries.expectedFulfillmentCount = 5
        let staleAuxiliary = expectation(description: "stopped OCR cannot publish")
        staleAuxiliary.isInverted = true
        let release = DispatchSemaphore(value: 0)
        let store = SupplementaryOCREmissionStore()
        let speed30 = blockedDetection(speed: 30)
        let speed60 = blockedDetection(speed: 60)
        let school = TrafficSignDetection(rawClassId: "hazard:school", rawLabel: "hazard:school",
            semantic: .init(kind: .unknown, value: nil, unit: nil), rawScore: 0.99, calibratedConfidence: nil,
            boundingBox: speed60.boundingBox, classThreshold: 0.7)
        let runtime = TrafficSignRuntime(verifiedPack: fixture.verified,
            backend: SupplementaryOCRTestBackend([speed30,speed30,speed60,speed60,school]),
            snapshotProvider: { fixture.snapshot }, callbackQueue: DispatchQueue(label: "blocked-ocr-primary-test"),
            eventHandler: {
                store.append($0)
                if $0.supplementaryOCROnly { staleAuxiliary.fulfill() } else { primaries.fulfill() }
            }, supplementaryOCRReader: { _ in
                entered.fulfill()
                _ = release.wait(timeout: .now() + 10)
                defer { finished.fulfill() }
                return .init(rawText: "bei Nässe", modelVersion: "blocked-test", readStatus: .read)
            })
        defer { runtime.stop(); release.signal() }
        for index in 0..<5 {
            DispatchQueue.global().asyncAfter(deadline: .now() + Double(index) * 0.6) {
                runtime.consumeVideoFrame(fixture.buffer, orientation: .up)
            }
        }
        wait(for: [entered,primaries], timeout: 7)
        let values = store.snapshot()
        XCTAssertEqual(runtime.metrics.completedInferences,5,"OCR does not occupy the detector's scheduling slot")
        XCTAssertEqual(values.count,5,"The stalled auxiliary job cannot delay or replay a primary result")
        if values.count == 5 {
            XCTAssertEqual(values[1].event.state,.confirmed)
            XCTAssertEqual(values[1].event.candidate?.value,30)
            XCTAssertEqual(values[3].event.state,.confirmed)
            XCTAssertEqual(values[3].event.candidate?.value,60)
            XCTAssertEqual(values[4].displayObservation?.classID,"hazard:school",
                "Secondary signs continue updating while lower-priority OCR is blocked")
        }
        runtime.stop()
        release.signal()
        wait(for: [finished,staleAuxiliary], timeout: 0.5)
        XCTAssertEqual(store.snapshot().count,5)
    }

    func testGenerationChangeRejectsBlockedOCRCompletionWithoutReplayingOldPrimary() throws {
        let fixture = try blockedRuntimeFixture()
        let state = TrafficSignAtomicFrameState(value:fixture.snapshot)
        let entered = expectation(description: "OCR worker entered")
        let finished = expectation(description: "OCR worker exited")
        let primaries = expectation(description: "two original-generation detector results")
        primaries.expectedFulfillmentCount = 2
        let staleAuxiliary = expectation(description: "previous-generation OCR cannot publish")
        staleAuxiliary.isInverted = true
        let release = DispatchSemaphore(value:0)
        let store = SupplementaryOCREmissionStore()
        let runtime = TrafficSignRuntime(verifiedPack:fixture.verified,
            backend:SupplementaryOCRTestBackend([blockedDetection(speed:60)]),
            snapshotProvider:{state.snapshot()},callbackQueue:DispatchQueue(label:"blocked-ocr-generation-test"),
            eventHandler:{
                store.append($0)
                if $0.supplementaryOCROnly {staleAuxiliary.fulfill()} else {primaries.fulfill()}
            },supplementaryOCRReader:{_ in
                entered.fulfill()
                _ = release.wait(timeout:.now()+10)
                defer {finished.fulfill()}
                return .init(rawText:"bei Nässe",modelVersion:"blocked-test",readStatus:.read)
            })
        defer {runtime.stop();release.signal()}
        runtime.consumeVideoFrame(fixture.buffer,orientation:.up)
        DispatchQueue.global().asyncAfter(deadline:.now()+0.6) {runtime.consumeVideoFrame(fixture.buffer,orientation:.up)}
        wait(for:[entered,primaries],timeout:4)
        state.update(.init(context:fixture.snapshot.context,conditions:fixture.snapshot.conditions,
            sessionGeneration:fixture.snapshot.sessionGeneration+1,contextGeneration:fixture.snapshot.contextGeneration+1,
            captureSessionId:"replacement-session"))
        release.signal()
        wait(for:[finished,staleAuxiliary],timeout:0.5)
        XCTAssertEqual(store.snapshot().count,2)
        XCTAssertEqual(runtime.metrics.completedInferences,2)
    }

    private func blockedDetection(speed:Int) -> TrafficSignDetection {
        .init(rawClassId:"maxspeed:\(speed)",rawLabel:String(speed),
            semantic:.init(kind:.maximumSpeed,value:speed,unit:"km/h"),rawScore:0.99,calibratedConfidence:nil,
            boundingBox:.init(x:0.02,y:0.02,width:0.95,height:0.48),classThreshold:0.7)
    }

    private func blockedRuntimeFixture() throws -> (verified:TrafficSignVerifiedModelPack,snapshot:TrafficSignFrameSnapshot,buffer:CMSampleBuffer) {
        let url = try XCTUnwrap(Bundle.main.url(forResource:"DE.panoramax-bootstrap",withExtension:"tsrmodelpack",subdirectory:"TSRModelPacks"))
        let manifest = try TrafficSignPackJSON.decoder().decode(TrafficSignModelPackManifest.self,
            from:Data(contentsOf:url.appendingPathComponent("manifest.json")))
        let artifact = try XCTUnwrap(manifest.detector.artifacts.first {$0.platform == .ios})
        let verified = TrafficSignVerifiedModelPack(directoryURL:url,manifest:manifest,
            detectorArtifact:artifact,detectorArtifactURL:url.appendingPathComponent(artifact.path))
        let context = TrafficSignDetectionContext(wayId:"123",latitude:49.0069,longitude:8.4037,
            headingDegrees:82,travelDirection:.forward,sourceSignature:.init(osmRevision:"blocked-test",localCorrectionRevision:nil))
        let snapshot = TrafficSignFrameSnapshot(context:context,
            conditions:.init(speedKmh:50,candidateRecentlySeen:false,lowPowerMode:false,thermalState:.nominal,appIsActive:true),
            captureSessionId:"blocked-test")
        var pixel:CVPixelBuffer?
        XCTAssertEqual(CVPixelBufferCreate(kCFAllocatorDefault,136,230,kCVPixelFormatType_32BGRA,
            [kCVPixelBufferCGImageCompatibilityKey:true,kCVPixelBufferCGBitmapContextCompatibilityKey:true] as CFDictionary,&pixel),kCVReturnSuccess)
        let image = try XCTUnwrap(pixel)
        CVPixelBufferLockBaseAddress(image,[])
        memset(try XCTUnwrap(CVPixelBufferGetBaseAddress(image)),255,CVPixelBufferGetBytesPerRow(image)*CVPixelBufferGetHeight(image))
        CVPixelBufferUnlockBaseAddress(image,[])
        var format:CMVideoFormatDescription?
        XCTAssertEqual(CMVideoFormatDescriptionCreateForImageBuffer(allocator:kCFAllocatorDefault,
            imageBuffer:image,formatDescriptionOut:&format),noErr)
        var timing = CMSampleTimingInfo(duration:.invalid,presentationTimeStamp:.zero,decodeTimeStamp:.invalid)
        var sample:CMSampleBuffer?
        XCTAssertEqual(CMSampleBufferCreateReadyWithImageBuffer(allocator:kCFAllocatorDefault,imageBuffer:image,
            formatDescription:try XCTUnwrap(format),sampleTiming:&timing,sampleBufferOut:&sample),noErr)
        return (verified,snapshot,try XCTUnwrap(sample))
    }
    #endif

    /// Private pixels stay outside the repository and production app. For a
    /// simulator set YOUSPEED_SUPPLEMENTARY_OCR_FIXTURE to the external PNG, or
    /// inject it into the isolated TestHost's Documents with devicectl.
    func testRealCropBottomHalfWhenExternalFixtureIsProvided() throws {
        let external = ProcessInfo.processInfo.environment["YOUSPEED_SUPPLEMENTARY_OCR_FIXTURE"].map {
            URL(fileURLWithPath: $0)
        }
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("supplementary-ocr-fixture.png")
        let url = external ?? documents
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw XCTSkip("Provide the private crop externally; no pixels are bundled.")
        }
        let source = try XCTUnwrap(CGImageSourceCreateWithURL(url as CFURL, nil))
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertEqual(image.width, 136)
        XCTAssertEqual(image.height, 230)
        TrafficSignSupplementaryOCR.warmUp()
        let result = try TrafficSignSupplementaryOCR.shared.recognizeTimeWindow(in: image)
        XCTAssertEqual(result, night)
    }
}

#if os(iOS)
private final class SupplementaryOCRTestBackend: TrafficSignInferenceBackend, @unchecked Sendable {
    let frames: [[TrafficSignDetection]]
    private var index = 0
    init(_ values: [TrafficSignDetection]) { frames = values.map {[$0]} }
    init(frames: [[TrafficSignDetection]]) { self.frames = frames }
    private func next() -> [TrafficSignDetection] {
        defer { index += 1 }
        return frames[min(index,frames.count-1)]
    }
    func detections(in pixelBuffer: CVPixelBuffer, orientation: CGImagePropertyOrientation) throws -> [TrafficSignDetection] {
        XCTAssertEqual(CVPixelBufferGetWidth(pixelBuffer), 136); XCTAssertEqual(CVPixelBufferGetHeight(pixelBuffer), 230)
        return next()
    }
    func detections(in cgImage: CGImage, orientation: CGImagePropertyOrientation) throws -> [TrafficSignDetection] {
        XCTAssertEqual(cgImage.width, 1024); XCTAssertEqual(cgImage.height, 1024)
        return next()
    }
}

private final class SupplementaryOCREmissionStore: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [TrafficSignRuntimeEmission] = []
    func append(_ value: TrafficSignRuntimeEmission) { lock.lock(); values.append(value); lock.unlock() }
    func snapshot() -> [TrafficSignRuntimeEmission] { lock.lock(); defer { lock.unlock() }; return values }
}
#endif
