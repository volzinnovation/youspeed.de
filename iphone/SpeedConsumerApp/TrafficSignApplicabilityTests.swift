import XCTest
@testable import SpeedConsumer

final class TrafficSignApplicabilityTests: XCTestCase {
    struct Vectors: Decodable { let scenarios: [Scenario] }
    struct Scenario: Decodable { let id: String; let expectedFinalClass: String?; let batches: [TSRFrameCandidateBatch] }
    func scenarios() throws -> [Scenario] {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "golden-vectors-v1", withExtension: "json"))
        return try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: url)).scenarios
    }
    func testSharedGoldenDecisionsAndNoNonEgoAuthority() throws {
        for scenario in try scenarios() {
            var session = TSRApplicabilitySession()
            let outputs = scenario.batches.map { session.evaluate($0) }
            if let expected = scenario.expectedFinalClass {
                XCTAssertTrue(outputs.last!.decisions.contains { $0.classification == expected }, scenario.id)
            }
            for output in outputs {
                XCTAssertLessThanOrEqual(output.tracks.count, 24)
                for decision in output.decisions {
                    for sink in ["display", "immediate", "passage"] {
                        let allowed = TSRApplicabilityAuthority.allows(decision, scope: output.batch.scope,
                            frameId: output.batch.frameId, trackId: decision.trackId, sink: sink, mode: "enforce")
                        XCTAssertEqual(allowed, decision.classification == "LIKELY_EGO_CORRIDOR", scenario.id)
                    }
                }
            }
        }
    }
    func testPhysicalIdentityDuplicateAndWeakerEgoEvidence() throws {
        for scenario in try scenarios() where ["simultaneous_equal_signs", "weak_ego_strong_branch", "duplicate_frame"].contains(scenario.id) {
            var session = TSRApplicabilitySession()
            let outputs = scenario.batches.map { session.evaluate($0) }
            let last = outputs.last!
            if scenario.id == "simultaneous_equal_signs" {
                XCTAssertEqual(last.tracks.count, 2)
                XCTAssertEqual(last.tracks.map { $0.samples.count }, [3, 3])
            } else if scenario.id == "weak_ego_strong_branch" {
                XCTAssertEqual(Set(last.decisions.map(\.classification)), ["LIKELY_EGO_CORRIDOR", "LIKELY_BRANCH"])
            } else { XCTAssertEqual(last.tracks.first?.samples.count, 3) }
        }
    }
    func testRejectedVisibleAndFailedFrameNeverAuthorizeLoss() throws {
        for scenario in try scenarios() where ["failed_frame", "proposal_cap", "parallel_road", "camera_remount"].contains(scenario.id) {
            var session = TSRApplicabilitySession()
            for batch in scenario.batches { _ = session.evaluate(batch) }
            XCTAssertFalse(session.canConsumePassage(activeTrackId: "track-1", selectedTrackId: nil, mode: "enforce"), scenario.id)
        }
        var session = TSRApplicabilitySession()
        let dropout = try XCTUnwrap(try scenarios().first { $0.id == "detector_dropout" })
        for batch in dropout.batches { _ = session.evaluate(batch) }
        XCTAssertTrue(session.canConsumePassage(activeTrackId: "track-1", selectedTrackId: nil, mode: "enforce"))
    }
    func testLegacyAndStaleAuthorityFailClosed() throws {
        let scenario = try XCTUnwrap(try scenarios().first { $0.id == "ego_right" })
        var session = TSRApplicabilitySession()
        let output = scenario.batches.map { session.evaluate($0) }.last!
        let decision = try XCTUnwrap(output.decisions.first)
        var unknownVersion = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(decision)) as? [String: Any])
        unknownVersion["schemaVersion"] = 2
        let futureDecision = try JSONDecoder().decode(TSRApplicabilityDecision.self, from: JSONSerialization.data(withJSONObject: unknownVersion))
        XCTAssertFalse(TSRApplicabilityAuthority.allows(futureDecision, scope: output.batch.scope, frameId: decision.frameId, trackId: decision.trackId, sink: "immediate", mode: "enforce"))
        XCTAssertFalse(TSRApplicabilityAuthority.allows(nil, scope: output.batch.scope, frameId: decision.frameId, trackId: decision.trackId, sink: "immediate", mode: "enforce"))
        XCTAssertFalse(TSRApplicabilityAuthority.allows(decision, scope: output.batch.scope, frameId: "later-frame", trackId: decision.trackId, sink: "immediate", mode: "enforce"))
        XCTAssertFalse(TSRApplicabilityAuthority.allows(decision, scope: output.batch.scope, frameId: decision.frameId, trackId: "other-sign", sink: "immediate", mode: "disabled"))
    }
    func testImmediateEnforcementPreservesOlderAssertionForUnknownAndEndSigns() throws {
        let scenario = try XCTUnwrap(try scenarios().first { $0.id == "ego_right" })
        var session = TSRApplicabilitySession()
        let output = scenario.batches.map { session.evaluate($0) }.last!
        let decision = try XCTUnwrap(output.decisions.first)
        let context = TrafficSignDetectionContext(wayId: "1", latitude: 50, longitude: 5, headingDegrees: 0,
            travelDirection: .forward, sourceSignature: TrafficSignRuntimeSourceSignature(osmRevision: "fixture", localCorrectionRevision: nil,
                bundleSHA256: decision.scope.bundleId), traversalEpoch: decision.scope.traversalEpoch, matchedWayStable: true)
        func event(kind: String, speed: Int, at: Double, evidence: TSRApplicabilityDecision?) -> TrafficSignRecognitionEvent {
            let candidate = TrafficSignRecognitionCandidate(rawClassId: "speed-\(speed)", rawLabel: "speed", semanticKind: kind,
                value: speed, unit: "km/h", rawScore: 0.97, calibratedConfidence: nil,
                boundingBox: TrafficSignNormalizedRect(x: 0.6, y: 0.3, width: 0.1, height: 0.1), trackId: decision.trackId, evidenceFrames: 3)
            var event = TrafficSignRecognitionEvent(schemaVersion: 1, packId: "fixture", artifactSha256: String(repeating: "a", count: 64),
                preprocessingVersion: "fixture", frameId: decision.frameId, driveSessionId: decision.scope.sessionId,
                source: .liveFrame, frameTimestampUtc: Date(timeIntervalSince1970: at), state: .confirmed,
                candidate: candidate, roadContext: context, latencyMs: 1, thermalState: nil)
            event.applicabilityDecision = evidence
            return event
        }
        var policy = TrafficSignTransientOverridePolicy()
        XCTAssertTrue(policy.ingestConfirmedDetection(event(kind: "maximum_speed", speed: 50, at: 2, evidence: decision),
            currentSourceSignature: context.sourceSignature, applicabilityMode: "enforce"))
        let previous = policy.activeOverride
        for classification in ["UNKNOWN", "LIKELY_BRANCH", "LIKELY_OTHER_LANE", "LIKELY_OPPOSITE_DIRECTION"] {
            var wire = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(decision)) as? [String: Any])
            wire["classification"] = classification
            for key in ["displayEligible", "immediateEligible", "passageEligible"] { wire[key] = false }
            let rejected = try JSONDecoder().decode(TSRApplicabilityDecision.self, from: JSONSerialization.data(withJSONObject: wire))
            let raw = event(kind: "maximum_speed", speed: 30, at: 3, evidence: rejected)
            let withheld = event(kind: "restriction_end", speed: 30, at: 3, evidence: nil)
            let emission = TrafficSignRuntimeEmission(event: withheld, frameContext: context, annotationEvent: raw)
            let annotation = try XCTUnwrap(PanoramaxTrafficSignAnnotationDraft(emission: emission))
            XCTAssertEqual(annotation.applicabilityStatus, classification)
            XCTAssertEqual(annotation.speedLimitKmh, 30)
            XCTAssertFalse(emission.event.permitsApplicability("immediate", mode: "enforce"))
            for kind in ["maximum_speed", "zone_start", "city_entry", "restriction_end", "zone_end"] {
                XCTAssertFalse(policy.ingestConfirmedDetection(event(kind: kind, speed: 30, at: 3, evidence: rejected),
                    currentSourceSignature: context.sourceSignature, applicabilityMode: "enforce"))
                XCTAssertEqual(policy.activeOverride, previous)
            }
        }
        XCTAssertFalse(policy.ingestConfirmedDetection(event(kind: "restriction_end", speed: 30, at: 4, evidence: nil),
            currentSourceSignature: context.sourceSignature, applicabilityMode: "enforce"))
        XCTAssertEqual(policy.activeOverride, previous)
    }

}
