import Foundation

@main struct Replay {
    struct Scenario: Decodable { let id: String; let batches: [TSRFrameCandidateBatch] }
    struct Vectors: Decodable { let scenarios: [Scenario] }
    struct Output: Encodable { let id: String; let frames: [TSRApplicabilityDiagnostic]; let liveMapFixSnapshots: [TrafficSignMapContextSnapshot] }
    static func main() throws {
        let vectors = try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let outputs = vectors.scenarios.map { scenario in
            var session = TSRApplicabilitySession()
            // Exercise the production map-only adapter separately from calibrated
            // synthetic policy inputs. It must never manufacture mount calibration.
            let snapshots = scenario.batches.compactMap { batch -> TrafficSignMapContextSnapshot? in
                guard let road = batch.road else { return nil }
                let geometry = TSRMapGeometry(wayId: road.wayId, localTangentDeg: road.localTangentDeg,
                    roadClass: road.roadClass, hypotheses: road.hypotheses, branches: road.branches,
                    capabilities: road.capabilities, postedSpeedKmh: road.postedSpeedKmh)
                return TSRMapFix(geometry: geometry, timestampMs: road.capturedAtMs,
                    accuracyM: road.horizontalAccuracyM, courseDeg: road.courseDeg,
                    courseAccuracyDeg: road.courseAccuracyDeg, stable: road.matchedStable).snapshot(scope: batch.scope)
            }
            return Output(id: scenario.id, frames: scenario.batches.map { session.evaluate($0) }, liveMapFixSnapshots: snapshots)
        }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        FileHandle.standardOutput.write(try encoder.encode(outputs))
    }
}
