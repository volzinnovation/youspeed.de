import Foundation

/// Host proof calls the complete production fusion implementation. It does not
/// reproduce its selection or qualify a crop, road, applicability or live policy.
private struct Corpus: Decodable {
    let schema_version: Int
    let cases: [Fixture]
}

private struct Fixture: Decodable {
    let id: String
    let runtime_output: String
    let unknown_threshold: Double
    let candidates: [Candidate]
    let withheld_indices: [Int]
    let expected_candidate_id: String?
}

private struct Candidate: Decodable {
    let id: String
    let semantic_kind: String
    let value: Int?
    let raw_score: Double
    let calibrated_confidence: Double?
    let box: [Double]
    let class_threshold: Double

    func detection() throws -> TrafficSignDetection {
        guard box.count == 4,
              let kind = TrafficSignSemanticKind(rawValue: semantic_kind),
              kind == .maximumSpeed || kind == .unknown || kind == .restrictionEnd else {
            throw Failure.invalid("candidate \(id)")
        }
        return TrafficSignDetection(
            rawClassId: id, rawLabel: id,
            semantic: TrafficSignSemantic(kind: kind, value: value, unit: kind == .maximumSpeed && value != nil ? "km/h" : nil),
            rawScore: raw_score, calibratedConfidence: calibrated_confidence,
            boundingBox: TrafficSignNormalizedRect(x: box[0], y: box[1], width: box[2], height: box[3]),
            classThreshold: class_threshold
        )
    }
}

private enum Failure: Error {
    case invalid(String)
    case mismatch(String)
}

@main private struct ShadowSelection {
    static func main() throws {
        guard CommandLine.arguments.count == 2 else { throw Failure.invalid("fixture path required") }
        let corpus = try JSONDecoder().decode(Corpus.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        guard corpus.schema_version == 1, !corpus.cases.isEmpty,
              Set(corpus.cases.map(\.id)).count == corpus.cases.count else {
            throw Failure.invalid("corpus")
        }
        var rows: [[String: Any]] = []
        for fixture in corpus.cases {
            guard let runtimeOutput = TrafficSignModelPackManifest.Calibration.RuntimeOutput(rawValue: fixture.runtime_output),
                  Set(fixture.withheld_indices).count == fixture.withheld_indices.count,
                  fixture.withheld_indices.allSatisfy({ fixture.candidates.indices.contains($0) }) else {
                throw Failure.invalid(fixture.id)
            }
            let detections = try fixture.candidates.map { try $0.detection() }
            let withheld = Set(fixture.withheld_indices)
            let survivors = detections.enumerated().filter { !withheld.contains($0.offset) }.map(\.element)
            func ingest(_ input: [TrafficSignDetection]) -> TrafficSignRecognitionEvent {
                var engine = TrafficSignFusionEngine(
                    packId: "shadow-selection-fixture-v1",
                    artifactSha256: String(repeating: "0", count: 64),
                    preprocessingVersion: "fixture-v1",
                    thresholds: TrafficSignModelPackManifest.Thresholds(
                        provisional: 0.6, confirmed: 0.8, unknown: fixture.unknown_threshold,
                        confirmationFrames: 2, confirmationWindowMs: 1_500, minimumTrackIou: 0.2
                    ), runtimeOutput: runtimeOutput
                )
                return engine.ingest(
                    detections: input, source: .liveFrame,
                    timestamp: Date(timeIntervalSince1970: 1_000), roadContext: nil,
                    latencyMs: 0, thermalState: nil, frameID: fixture.id,
                    driveSessionID: "fixture-session", physicalTrackID: "fixture-track"
                )
            }
            // Separate fresh engines: filtering must not inherit the blocked
            // candidate's confirmation, and fixtures are not repeated frames.
            let raw = ingest(detections)
            let selected = ingest(survivors)
            guard selected.candidate?.rawClassId == fixture.expected_candidate_id,
                  selected.state != .confirmed,
                  selected.candidate.map({ $0.evidenceFrames == 1 }) ?? true else {
                throw Failure.mismatch(fixture.id)
            }
            rows.append([
                "id": fixture.id,
                "baseline_candidate_id": raw.candidate?.rawClassId as Any? ?? NSNull(),
                "survivor_ids": survivors.map(\.rawClassId),
                "candidate_id": selected.candidate?.rawClassId as Any? ?? NSNull(),
                "expected_candidate_id": fixture.expected_candidate_id as Any? ?? NSNull(),
                "state": selected.state.rawValue,
                "evidence_frames": selected.candidate?.evidenceFrames as Any? ?? NSNull(),
                "passed": true
            ])
        }
        let output: [String: Any] = ["schema_version": 1, "platform": "swift-production-fusion-host",
                                     "cases": rows, "passed": true,
                                     "scope": "Fresh first-frame fusion of externally specified surviving candidates; no applicability or device claim"]
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys, .prettyPrinted]))
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
}
