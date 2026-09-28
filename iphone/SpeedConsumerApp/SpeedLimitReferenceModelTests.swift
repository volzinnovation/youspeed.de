import XCTest
@testable import SpeedConsumer

final class SpeedLimitReferenceModelTests: XCTestCase {
    private func read(_ name: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("shared/speed-limit-reference")
        return try Data(contentsOf: root.appendingPathComponent(name))
    }
    func testPackagedPolicyIsTheSharedRuntimePolicy() throws {
        let model = try SpeedLimitReferenceModel.bundled()
        XCTAssertEqual(model.version, "1.1.0")
        XCTAssertEqual(model.policy["priority"] as? [String], ["voice", "camera", "bundle"])
    }
    func testFrozenScenariosThroughNativeInterpreter() throws {
        let model = try SpeedLimitReferenceModel.load(read: read)
        let corpus = try JSONSerialization.jsonObject(with: read("scenarios-v1.1.0.json")) as! [String: Any]
        for scenario in corpus["scenarios"] as! [[String: Any]] {
            let machine = SpeedReferenceMachine(model: model)
            for (index, row) in (scenario["steps"] as! [[String: Any]]).enumerated() {
                let result = machine.step(row["event"] as! [String: Any])
                let actual: [String: Any] = ["state": result.state, "value": result.value?.json ?? NSNull(),
                    "violation_reference_kmh": result.baselineKmh as Any? ?? NSNull(), "penalty_reference_kmh": result.baselineKmh as Any? ?? NSNull(),
                    "display_stale": result.state == "LAST_KNOWN", "current": result.current,
                    "generation": result.generation, "applicability_revision": result.applicabilityRevision,
                    "transition_id": result.transition, "expiry_reasons": result.expiryReasons,
                    "rejection": result.rejection as Any? ?? NSNull()]
                for (key, expected) in row["expect"] as! [String: Any] {
                    XCTAssertEqual(actual[key] as? NSObject, expected as? NSObject, "\(scenario["id"]!) step \(index) \(key)")
                }
            }
        }
    }
    func testRuntimePreservesBriefRampExcursionButExpiresSustainedDeparture() throws {
        var now = 0.0
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
        runtime.context(way: "a8", road: "ref:A8", relations: ["A8"], direction: "forward", stable: true)
        runtime.bundle(id: "map", value: SpeedReferenceValue(kind: "numeric", kmh: 130))
        runtime.voice(id: "speech", value: SpeedReferenceValue(kind: "numeric", kmh: 130))
        now = 137.302
        runtime.context(way: "ramp", road: "ref:A57:ramp", relations: [], direction: "forward", stable: true)
        runtime.tick(distance: 250)
        now = 143.751
        runtime.context(way: "a8-next", road: "ref:A8", relations: ["A8"], direction: "forward", stable: true)
        XCTAssertEqual(runtime.output?.state, "VOICE")
        now = 150
        runtime.context(way: "ramp", road: "ref:A57:ramp", relations: [], direction: "forward", stable: true)
        now = 158
        runtime.context(way: "ramp", road: "ref:A57:ramp", relations: [], direction: "forward", stable: true)
        XCTAssertEqual(runtime.output?.state, "LAST_KNOWN")
        XCTAssertNil(runtime.output?.baselineKmh)
    }
    func testRepeatedCameraWithdrawalDoesNotEraseFreshRoadEvidence() throws {
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { 0 })
        runtime.bundle(id: "map", value: .init(kind: "numeric", kmh: 80))
        runtime.camera(id: "sign", value: .init(kind: "numeric", kmh: 30))
        runtime.pipelineAuthorityWithdrawn(evidenceID: "end-sign")
        XCTAssertEqual(runtime.output?.state, "LAST_KNOWN")
        runtime.bundle(id: "fresh-map", value: .init(kind: "numeric", kmh: 80))
        for _ in 0..<100 { runtime.pipelineAuthorityWithdrawn(evidenceID: "end-sign") }
        XCTAssertEqual(runtime.output?.state, "BUNDLE")
        XCTAssertEqual(runtime.output?.baselineKmh, 80)
        runtime.pipelineAuthorityWithdrawn(evidenceID: "different-end-sign")
        XCTAssertEqual(runtime.output?.state, "LAST_KNOWN")
        XCTAssertNil(runtime.output?.baselineKmh)
    }
    func testDismissalRejectsDelayedEvidenceButAllowsNewSigns() {
        var gate = VisionDismissalGate()
        let now = Date(timeIntervalSince1970: 100)
        gate.dismiss(at: now, tracks: ["active"])
        XCTAssertFalse(gate.permits(track: "active", observedAt: now.addingTimeInterval(1)))
        XCTAssertFalse(gate.permits(track: "queued", observedAt: now.addingTimeInterval(-1)))
        XCTAssertFalse(gate.permits(track: "queued", observedAt: now.addingTimeInterval(2)))
        XCTAssertTrue(gate.permits(track: "new-sign", observedAt: now.addingTimeInterval(3)))
    }
    func testRejectsChangedPolicyAndApprovalLock() throws {
        for changed in ["policy-v1.1.0.json", "approval-lock.json"] {
            XCTAssertThrowsError(try SpeedLimitReferenceModel.load { name in
                var data = try self.read(name); if name == changed { data.append(32) }; return data
            })
        }
        XCTAssertThrowsError(try SpeedLimitReferenceModel.load { _ in throw CocoaError(.fileNoSuchFile) })
    }
}
