import XCTest
@testable import SpeedConsumer

final class TrafficSignCameraReferenceOfferTests: XCTestCase {
    private func runtime() throws -> SpeedReferenceRuntime {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("shared/speed-limit-reference")
        let model = try SpeedLimitReferenceModel.load { try Data(contentsOf: root.appendingPathComponent($0)) }
        return SpeedReferenceRuntime(model: model, now: { 0 })
    }
    private func immediate(_ speed: Int, enclosing: Bool = false, id: String? = "new-sign", presented: Int? = nil) -> TrafficSignCameraReferenceOffer? {
        TrafficSignCameraReferenceOffer.select(presentationReason: "camera_confirmed_frames", presentedSpeedKmh: presented ?? speed,
            immediateTrackID: id, immediateSpeedKmh: speed, passageTrackID: "old-passage", resolverTrackID: "old-resolver", resolverEnclosing: enclosing)
    }
    func testFreshImmediate80Replaces70UsingItsOwnEvidenceIdentity() throws {
        let reference = try runtime()
        reference.camera(id: "old-resolver", value: .init(kind: "numeric", kmh: 70))
        let offer = try XCTUnwrap(immediate(80))
        reference.camera(id: offer.evidenceID, value: .init(kind: "numeric", kmh: 80), enclosing: offer.enclosing)
        XCTAssertEqual(reference.output?.evidenceID, "new-sign")
        XCTAssertEqual(reference.output?.baselineKmh, 80)
    }
    func testOrdinaryImmediate30DoesNotBorrowAnExistingZonesEnclosingType() throws {
        let reference = try runtime()
        reference.camera(id: "old-road", value: .init(kind: "numeric", kmh: 70))
        reference.camera(id: "old-resolver:enclosing", value: .init(kind: "numeric", kmh: 30), enclosing: true)
        let offer = try XCTUnwrap(immediate(30, enclosing: true))
        reference.camera(id: offer.evidenceID, value: .init(kind: "numeric", kmh: 30), enclosing: offer.enclosing)
        XCTAssertFalse(offer.enclosing)
        XCTAssertEqual(reference.output?.evidenceID, "new-sign")
        XCTAssertEqual(reference.output?.baselineKmh, 30)
    }
    func testUnmatchedImmediateValueCannotBorrowAnOlderAssertionsIdentity() {
        XCTAssertNil(immediate(80, presented: 70))
        XCTAssertNil(immediate(80, id: nil))
        XCTAssertNil(immediate(80, id: " "))
        XCTAssertNil(TrafficSignCameraReferenceOffer.select(presentationReason: "camera_confirmed_frames", presentedSpeedKmh: nil,
            immediateTrackID: "new-sign", immediateSpeedKmh: 80, passageTrackID: "old-passage", resolverTrackID: "old-resolver", resolverEnclosing: false))
    }
    func testFinalizedPassageAndResolverKeepTheirExistingIdentityAndType() {
        let passage = TrafficSignCameraReferenceOffer.select(presentationReason: "camera_zone_start", presentedSpeedKmh: 30,
            immediateTrackID: "immediate", immediateSpeedKmh: 80, passageTrackID: "zone-passage", resolverTrackID: "resolver", resolverEnclosing: true)
        XCTAssertEqual(passage, .init(trackID: "zone-passage", enclosing: true, provenance: "passage"))
        let resolver = TrafficSignCameraReferenceOffer.select(presentationReason: "camera_posted_maximum", presentedSpeedKmh: 70,
            immediateTrackID: "immediate", immediateSpeedKmh: 80, passageTrackID: nil, resolverTrackID: "resolver", resolverEnclosing: false)
        XCTAssertEqual(resolver, .init(trackID: "resolver", enclosing: false, provenance: "resolver"))
    }

    func testRecognizedZoneKeepsNumericPreviewUntilItsFinalizedEnclosingPassage() throws {
        var now = 0.0
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("shared/speed-limit-reference")
        let model = try SpeedLimitReferenceModel.load { try Data(contentsOf: root.appendingPathComponent($0)) }
        let reference = SpeedReferenceRuntime(model: model, now: { now })
        let preview = try XCTUnwrap(immediate(30, id: "zone-sign"))
        XCTAssertFalse(preview.enclosing)
        XCTAssertEqual(reference.camera(id: preview.evidenceID, value: .init(kind: "numeric", kmh: 30), enclosing: preview.enclosing)?.offeredKind, "camera")
        let passage = try XCTUnwrap(TrafficSignCameraReferenceOffer.select(presentationReason: "camera_zone_start", presentedSpeedKmh: 30,
            immediateTrackID: "zone-sign", immediateSpeedKmh: 30, passageTrackID: "zone-sign", resolverTrackID: "zone-sign", resolverEnclosing: true))
        let receipt = try XCTUnwrap(reference.camera(id: passage.evidenceID, value: .init(kind: "numeric", kmh: 30), enclosing: passage.enclosing))
        XCTAssertEqual(receipt.offeredKind, "camera_context")
        XCTAssertEqual(receipt.after.transition, "T12")
        XCTAssertEqual(reference.output?.evidenceID, "zone-sign")
        // Existing policy priority and expiry remain intact: the enclosing claim survives the preview.
        now = 301
        reference.tick()
        XCTAssertEqual(reference.output?.evidenceID, "zone-sign:enclosing")
        XCTAssertEqual(reference.output?.baselineKmh, 30)
    }

    func testChangedConfirmedPreviewIsSelectedOverOlderResolverCameraValue() throws {
        let old = EffectiveSpeedLimitState(value: .numeric(70), source: .camera,
            presentationReason: "camera_posted_maximum", hasCameraEvidenceMarker: true)
        let selected = TrafficSignCameraReferenceOffer.presentationForChangedOverride(old, overrideChanged: true,
            speedKmh: 80, trackID: "new-sign")
        XCTAssertEqual(selected.value, .numeric(80))
        XCTAssertEqual(selected.presentationReason, "camera_confirmed_frames")
        let reference = try runtime()
        reference.camera(id: "old-resolver", value: .init(kind: "numeric", kmh: 70))
        let offer = try XCTUnwrap(TrafficSignCameraReferenceOffer.select(presentationReason: selected.presentationReason,
            presentedSpeedKmh: selected.value.speedKmh, immediateTrackID: "new-sign", immediateSpeedKmh: 80,
            passageTrackID: nil, resolverTrackID: "old-resolver", resolverEnclosing: false))
        reference.camera(id: offer.evidenceID, value: .init(kind: "numeric", kmh: 80), enclosing: offer.enclosing)
        XCTAssertEqual(reference.output?.evidenceID, "new-sign")
        XCTAssertEqual(reference.output?.baselineKmh, 80)
    }

    func testUnchangedOrStalePreviewCannotReplaceResolverSelection() {
        let resolved = EffectiveSpeedLimitState(value: .numeric(70), source: .camera,
            presentationReason: "camera_posted_maximum", hasCameraEvidenceMarker: true)
        XCTAssertEqual(TrafficSignCameraReferenceOffer.presentationForChangedOverride(resolved, overrideChanged: false,
            speedKmh: 80, trackID: "stale-sign"), resolved)
        XCTAssertEqual(TrafficSignCameraReferenceOffer.presentationForChangedOverride(resolved, overrideChanged: true,
            speedKmh: nil, trackID: nil), resolved)
        let correction = EffectiveSpeedLimitState(value: .numeric(50), source: .localCorrection,
            presentationReason: "local_correction_numeric", hasCameraEvidenceMarker: false, isUserCorrection: true)
        XCTAssertEqual(TrafficSignCameraReferenceOffer.presentationForChangedOverride(correction, overrideChanged: true,
            speedKmh: 80, trackID: "new-sign"), correction)
    }
}
