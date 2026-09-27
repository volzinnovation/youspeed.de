import Foundation
import XCTest
@testable import SpeedConsumer

/// Both native finalizers execute these exact frame sequences and expected states.
/// Completed prefixes establish map scope before loss. Android's raw finalizer
/// precedes its activation resolver, while iPhone checks that scope before commit.
final class PassageParityTests: XCTestCase {
    private struct Corpus: Decodable {
        let schemaVersion: Int
        let prefixes: [String: [Frame]]
        let scenarios: [Scenario]
    }
    private struct Scenario: Decodable { let id: String; let prefix: String; let frames: [Frame] }
    private struct Frame: Decodable {
        let atMs: Int
        let track: String?
        let position: [Double]?
        let expectActive: Bool
        let expectCommit: Int?
    }

    func testSharedPassageSuppressionCorpus() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "suppression-v1", withExtension: "json"))
        let corpus = try JSONDecoder().decode(Corpus.self, from: Data(contentsOf: url))
        XCTAssertEqual(corpus.schemaVersion, 1)
        XCTAssertFalse(corpus.scenarios.isEmpty)
        for scenario in corpus.scenarios {
            var finalizer = TrafficSignPassageFinalizer()
            let prefix = try XCTUnwrap(corpus.prefixes[scenario.prefix])
            for frame in prefix + scenario.frames {
                let result = finalizer.ingest(event(frame), sessionGeneration: 1, contextGeneration: 1,
                                              frameSpeedKmh: 50, calibratedActivationEligible: true)
                let label = "\(scenario.id) at \(frame.atMs)ms"
                XCTAssertEqual(finalizer.activePhysicalTrackID != nil, frame.expectActive, label)
                if let expected = frame.expectCommit {
                    guard case .committed(let passage) = result else { XCTFail("\(label): expected commit, got \(result)"); continue }
                    XCTAssertEqual(passage.action, .postedMaximum(expected), label)
                } else if case .committed = result {
                    XCTFail("\(label): unexpected commit")
                }
            }
        }
    }

    func testEntirelyUnmatchedVisibleTrackCannotActivateAfterContextReturnsAtLoss() {
        var finalizer = TrafficSignPassageFinalizer()
        for offset in [0, 100] {
            _ = finalizer.ingest(event(Frame(atMs: offset, track: "track-30", position: nil,
                                             expectActive: true, expectCommit: nil)),
                                 sessionGeneration: 1, contextGeneration: 1,
                                 frameSpeedKmh: 50, calibratedActivationEligible: true)
        }
        _ = finalizer.ingest(event(Frame(atMs: 200, track: nil, position: [0, 0],
                                         expectActive: true, expectCommit: nil)),
                             sessionGeneration: 1, contextGeneration: 1,
                             frameSpeedKmh: 50, calibratedActivationEligible: true)
        let result = finalizer.ingest(event(Frame(atMs: 300, track: nil, position: [0, 0],
                                                  expectActive: false, expectCommit: nil)),
                                      sessionGeneration: 1, contextGeneration: 1,
                                      frameSpeedKmh: 50, calibratedActivationEligible: true)
        XCTAssertEqual(result, .discarded(reason: "passage_missing_recognition_origin"))
        XCTAssertNil(finalizer.activePhysicalTrackID)
    }

    private func event(_ frame: Frame) -> TrafficSignRecognitionEvent {
        let sha = String(repeating: "a", count: 64)
        let context = frame.position.map { point in
            TrafficSignDetectionContext(wayId: "100", latitude: point[0], longitude: point[1],
                headingDegrees: 90, travelDirection: .forward,
                sourceSignature: .init(osmRevision: "bundle:test|way:100", localCorrectionRevision: nil, bundleSHA256: sha),
                routeContinuityAvailable: true,
                routeRelationMemberships: [.init(groupID: 1, sourceRelationID: 1001)],
                traversalEpoch: 1, matchedWayStable: true)
        }
        let candidate = frame.track.map { track in
            TrafficSignRecognitionCandidate(rawClassId: "speed_limit_30", rawLabel: "30",
                semanticKind: TrafficSignSemanticKind.maximumSpeed.rawValue, value: 30, unit: "km/h",
                rawScore: 0.95, calibratedConfidence: 0.95,
                boundingBox: .init(x: 0.7, y: 0.1, width: 0.1, height: 0.2), trackId: track, evidenceFrames: 2,
                assemblyId: "assembly-\(track)")
        }
        return TrafficSignRecognitionEvent(schemaVersion: 1, packId: "parity-pack", artifactSha256: sha,
            preprocessingVersion: "rgb-v1",
            modelComponents: [.init(role: "direct_detector", artifactSHA256: sha, preprocessingVersion: "rgb-v1", calibrationID: "test")],
            frameId: "frame-\(frame.atMs)", driveSessionId: "parity-drive", source: .liveFrame,
            frameTimestampUtc: Date(timeIntervalSince1970: 1_788_279_200).addingTimeInterval(Double(frame.atMs) / 1000),
            state: candidate == nil ? .noRecognition : .confirmed, candidate: candidate, roadContext: context,
            latencyMs: 1, thermalState: nil)
    }
}
