import XCTest
@testable import SpeedConsumer

final class TrafficSignApplicabilityTests: XCTestCase {
    func testZoneTextRequiresBothTheWordAndTheExactNumber() {
        for text in ["30 ZONE", "ZONE\n30", "30 zona"] { XCTAssertTrue(TSRLiveSignAdmission.verifiesZoneText(text, speed: 30), text) }
        for text in ["40 Kurort", "70 GEFAHR", "20 ZONE", "ZONE", "30", "30 ZONE 70", "30 OZONEN"] {
            XCTAssertFalse(TSRLiveSignAdmission.verifiesZoneText(text, speed: 30), text)
        }
    }
    private func zoneBatches(x: Double = 0.45, calibrated: Bool = false, variant: String = "") throws -> [TSRFrameCandidateBatch] {
        let source = try XCTUnwrap(try scenarios().first { $0.id == "ego_right" })
        return try source.batches.map { batch in
            var wire = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(batch)) as? [String: Any])
            var candidates = try XCTUnwrap(wire["candidates"] as? [[String: Any]])
            candidates[0]["semanticKey"] = variant == "end" ? "speed_limit_end:70:km/h" : variant == "side" ? "maximum_speed:30:km/h" : "zone_start:30:km/h"
            var box = try XCTUnwrap(candidates[0]["box"] as? [String: Any]); box["x"] = x
            candidates[0]["box"] = box; wire["candidates"] = candidates
            var road = try XCTUnwrap(wire["road"] as? [String: Any])
            if !calibrated { road["cameraHorizontalFovDeg"] = NSNull(); road["cameraYawDeg"] = NSNull() }
            if variant == "stale" { road["capturedAtMs"] = batch.capturedAtMs - 2000 }
            if variant == "unstable" { road["matchedStable"] = false }
            if variant == "turning" { road["courseDeg"] = 90 }
            if variant == "side" {
                let heading = x < 0.2 ? 270.0 : 90.0
                road["branches"] = [["wayId": "side", "headingDeg": heading, "distanceM": 15,
                    "roadClass": "residential", "endpointLinked": true, "turnAngleDeg": heading]]
            }
            if variant == "turned" {
                var scope = try XCTUnwrap(wire["scope"] as? [String: Any]); scope["traversalEpoch"] = 2
                wire["scope"] = scope; road["scope"] = scope
                road["wayId"] = "side"; road["courseDeg"] = 90; road["localTangentDeg"] = 90
            }
            wire["road"] = variant == "missing" ? NSNull() : road as Any
            if variant == "truncated" { wire["truncated"] = true }
            return try JSONDecoder().decode(TSRFrameCandidateBatch.self, from: JSONSerialization.data(withJSONObject: wire))
        }
    }
    func testVerifiedZoneNeedsAnEgoApproachButInformationPanelsNeverGainAuthority() throws {
        for calibrated in [false, true] {
            var session = TSRApplicabilitySession(), unverified = TSRApplicabilitySession()
            for (index, batch) in try zoneBatches(calibrated: calibrated).enumerated() {
                let rejected = unverified.evaluate(batch)
                XCTAssertEqual(unverified.liveWithheldCandidateIDs, Set(batch.candidates.map(\.candidateId)))
                let decision = try XCTUnwrap(rejected.decisions.first)
                for sink in ["display", "immediate", "passage"] {
                    XCTAssertFalse(TSRApplicabilityAuthority.allows(decision, scope: batch.scope, frameId: batch.frameId, trackId: decision.trackId, sink: sink, mode: "shadow"))
                }
                let admitted = session.evaluate(batch, verifiedZones: Set(batch.candidates.map(\.candidateId)))
                XCTAssertEqual(!session.liveWithheldCandidateIDs.isEmpty, index == 0)
                XCTAssertEqual(admitted.batch.candidates, batch.candidates)
            }
        }
    }
    func testFarLeftZoneAndStaleRoadAreWithheldWhileLeftEndSignsRemainEligible() throws {
        var session = TSRApplicabilitySession()
        for batch in try zoneBatches(x: 0.015) {
            _ = session.evaluate(batch, verifiedZones: Set(batch.candidates.map(\.candidateId)))
            XCTAssertFalse(session.liveWithheldCandidateIDs.isEmpty)
        }
        for variant in ["stale", "missing", "truncated", "unstable", "turning"] {
            var guarded = TSRApplicabilitySession()
            for batch in try zoneBatches(variant: variant) {
                _ = guarded.evaluate(batch, verifiedZones: Set(batch.candidates.map(\.candidateId)))
                XCTAssertFalse(guarded.liveWithheldCandidateIDs.isEmpty, variant)
            }
        }
        var ends = TSRApplicabilitySession()
        for batch in try zoneBatches(x: 0.015, variant: "end") {
            _ = ends.evaluate(batch)
            XCTAssertTrue(ends.liveWithheldCandidateIDs.isEmpty)
        }
    }
    func testUncalibratedPeripheralSpeedAndActualTurnOntoSideRoad() throws {
        for x in [0.015, 0.85, 0.45] {
            var session = TSRApplicabilitySession()
            for batch in try zoneBatches(x: x, variant: "side") {
                _ = session.evaluate(batch)
                XCTAssertEqual(!session.liveWithheldCandidateIDs.isEmpty, x != 0.45)
            }
        }
        var turned = TSRApplicabilitySession()
        for (index, batch) in try zoneBatches(variant: "turned").enumerated() {
            _ = turned.evaluate(batch, verifiedZones: Set(batch.candidates.map(\.candidateId)))
            XCTAssertEqual(!turned.liveWithheldCandidateIDs.isEmpty, index == 0)
        }
    }
    func testLateUntrackedZoneCannotBypassAdmission() throws {
        let batches = try zoneBatches()
        var session = TSRApplicabilitySession()
        for batch in batches { _ = session.evaluate(batch, verifiedZones: Set(batch.candidates.map(\.candidateId))) }
        var wire = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(batches[0])) as? [String: Any])
        wire["frameId"] = "late-frame"
        var candidates = try XCTUnwrap(wire["candidates"] as? [[String: Any]])
        candidates[0]["candidateId"] = "late-frame:0"; wire["candidates"] = candidates
        let old = try JSONDecoder().decode(TSRFrameCandidateBatch.self, from: JSONSerialization.data(withJSONObject: wire))
        _ = session.evaluate(old, verifiedZones: ["late-frame:0"])
        XCTAssertEqual(session.liveWithheldCandidateIDs, ["late-frame:0"])
    }
    func testKnownSideRoadIsVetoedEvenInShadow() throws {
        let scenario = try XCTUnwrap(try scenarios().first { $0.id == "weak_ego_strong_branch" })
        var session = TSRApplicabilitySession()
        let output = try XCTUnwrap(scenario.batches.map { session.evaluate($0) }.last)
        let branch = try XCTUnwrap(output.decisions.first { $0.classification == "LIKELY_BRANCH" })
        XCTAssertTrue(TSRLiveSignAdmission.blocks(branch))
        for sink in ["display", "immediate", "passage"] {
            XCTAssertFalse(TSRApplicabilityAuthority.allows(branch, scope: output.batch.scope, frameId: output.batch.frameId, trackId: branch.trackId, sink: sink, mode: "shadow"))
        }
        let ego = try XCTUnwrap(output.decisions.first { $0.classification == "LIKELY_EGO_CORRIDOR" })
        XCTAssertTrue(TSRApplicabilityAuthority.allows(ego, scope: output.batch.scope, frameId: output.batch.frameId, trackId: ego.trackId, sink: "immediate", mode: "shadow"))
    }
    func testSecondarySignLogMetadataRoundTripAndLegacyDecode() throws {
        let legacy = try XCTUnwrap(try scenarios().first?.batches.first)
        XCTAssertNil(legacy.country)
        XCTAssertNil(legacy.candidates.first?.rawClassId)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(legacy)) as? [String: Any])
        var candidates = try XCTUnwrap(object["candidates"] as? [[String: Any]])
        candidates[0]["rawClassId"] = "AB4"
        candidates[0]["detectorRawScore"] = 0.3
        candidates[0]["classifierRawScore"] = 0.99
        candidates[0]["semanticKey"] = "unknown::"
        object["candidates"] = candidates
        object["country"] = "FR"
        let batch = try JSONDecoder().decode(TSRFrameCandidateBatch.self, from: JSONSerialization.data(withJSONObject: object))
        var session = TSRApplicabilitySession()
        let diagnostic = session.evaluate(batch)
        let decoded = try JSONDecoder().decode(TSRApplicabilityDiagnostic.self, from: JSONEncoder().encode(diagnostic))
        XCTAssertEqual(decoded.batch.country, "FR")
        XCTAssertEqual(decoded.batch.candidates.first?.detectorRawScore, 0.3)
        XCTAssertEqual(decoded.batch.candidates.first?.classifierRawScore, 0.99)
        XCTAssertEqual(decoded.batch.candidates.first?.rawClassId, "AB4")
        XCTAssertEqual(decoded.batch.candidates.first?.semanticKey, "unknown::")
        XCTAssertEqual(decoded.tracks.first?.samples.first?.candidate.rawClassId, "AB4")
    }
    struct Vectors: Decodable { let scenarios: [Scenario] }
    struct Scenario: Decodable { let id: String; let expectedFinalClass: String?; let batches: [TSRFrameCandidateBatch]; let expectedWithheldCount: Int?; let expectedAccessWithheldCounts: [Int]? }

    func testAccessRoadConflictAndLegitimateMainlineChanges() throws {
        for scenario in try scenarios() {
            guard let counts = scenario.expectedAccessWithheldCounts else { continue }
            var session = TSRApplicabilitySession()
            for (index, batch) in scenario.batches.enumerated() {
                let output = session.evaluate(batch)
                XCTAssertEqual(session.accessRoadWithheldCandidateIDs.count, counts[index], scenario.id + " frame " + String(index))
                if counts[index] > 0 {
                    XCTAssertTrue(session.canConsumePassage(activeTrackId: "previous-main-road-sign", selectedTrackId: nil, mode: "shadow"))
                }
                for decision in output.decisions where decision.reasons.contains(TSRAccessRoadPolicy.reason) {
                    for sink in ["display", "immediate", "passage"] {
                        XCTAssertFalse(TSRApplicabilityAuthority.allows(decision, scope: batch.scope, frameId: batch.frameId, trackId: decision.trackId, sink: sink, mode: "shadow"))
                    }
                }
            }
            session.reset()
            _ = session.evaluate(scenario.batches[2])
            XCTAssertTrue(session.accessRoadWithheldCandidateIDs.isEmpty, "Reset must clear main-road history")
        }
    }
    func testExitGuardOperatesInShadowAndKeepsActualRampAndMainlineRepeats() throws {
        for scenario in try scenarios() {
            guard let count = scenario.expectedWithheldCount else { continue }
            var session = TSRApplicabilitySession()
            for batch in scenario.batches {
                XCTAssertEqual(TSRMotorwayExitPolicy.withheldCandidates(batch).count, count, scenario.id)
                let output = session.evaluate(batch)
                for decision in output.decisions where decision.reasons.contains(TSRMotorwayExitPolicy.reason) {
                    for sink in ["display", "immediate", "passage"] {
                        XCTAssertFalse(TSRApplicabilityAuthority.allows(decision, scope: batch.scope, frameId: batch.frameId,
                            trackId: decision.trackId, sink: sink, mode: "shadow"), scenario.id)
                    }
                    XCTAssertFalse(session.canConsumePassage(activeTrackId: decision.trackId, selectedTrackId: nil, mode: "shadow"))
                }
            }
        }
    }
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
