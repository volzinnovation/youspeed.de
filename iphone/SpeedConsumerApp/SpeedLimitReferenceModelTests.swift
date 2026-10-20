import XCTest
@testable import SpeedConsumer

final class SpeedLimitReferenceModelTests: XCTestCase {
    private func read(_ name: String) throws -> Data {
        if let url = Bundle.main.url(forResource: name, withExtension: nil, subdirectory: SpeedLimitReferenceModel.directory) {
            return try Data(contentsOf: url)
        }
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

    func testPendingRoadConfirmsAfterEightSecondsAcrossOppositeWayOrientations() throws {
        for relationOnly in [false, true] {
            var now = 0.0
            let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
            runtime.context(way: "old", road: "ref:old", relations: [], direction: "forward", stable: true)
            runtime.bundle(id: "old-map", value: .init(kind: "numeric", kmh: 70))
            let road: String? = relationOnly ? nil : "ref:L562"
            let relations: Set<String> = relationOnly ? ["562"] : []
            // The recorded L562 drive crosses ways digitized in both directions.
            for (at, way, direction) in [(1.0, "242667444", "forward"), (3.0, "242667445", "reverse"),
                                         (4.0, "242667443", "forward"), (7.0, "31266734", "reverse"),
                                         (8.999, "733915457", "forward")] {
                now = at
                runtime.context(way: way, road: road, relations: relations, direction: direction, stable: true)
                runtime.bundle(id: "new-map", value: .init(kind: "numeric", kmh: 50))
                XCTAssertEqual(runtime.output?.state, "LAST_KNOWN")
                XCTAssertEqual(runtime.output?.generation, 0)
                XCTAssertNil(runtime.output?.baselineKmh)
            }
            XCTAssertTrue(try XCTUnwrap(runtime.camera(id: "pending-sign", value: .init(kind: "numeric", kmh: 30))).pendingContextAfter)
            now = 9
            runtime.context(way: "733915457", road: road, relations: relations, direction: "forward", stable: true)
            XCTAssertEqual(runtime.output?.generation, 1)
            runtime.bundle(id: "current-map", value: .init(kind: "numeric", kmh: 50))
            XCTAssertEqual(runtime.output?.state, "BUNDLE")
            XCTAssertEqual(runtime.output?.baselineKmh, 50)
            XCTAssertEqual(runtime.camera(id: "fresh-sign", value: .init(kind: "numeric", kmh: 30))?.after.state, "CAMERA")
        }
    }

    func testPendingSameWayReversalRestartsAndUnknownDoesNotEraseDirection() throws {
        var now = 0.0
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
        runtime.context(way: "old", road: "ref:old", relations: [], direction: "forward", stable: true)
        runtime.bundle(id: "old-map", value: .init(kind: "numeric", kmh: 70))
        for (at, direction) in [(1.0, "forward"), (3.0, "unknown"), (4.0, "reverse"), (9.0, "reverse"), (11.999, "unknown")] {
            now = at
            runtime.context(way: "new", road: "ref:new", relations: [], direction: direction, stable: true)
            XCTAssertEqual(runtime.output?.generation, 0)
        }
        now = 12
        runtime.context(way: "new", road: "ref:new", relations: [], direction: "unknown", stable: true)
        XCTAssertEqual(runtime.output?.generation, 1)
        runtime.bundle(id: "new-map", value: .init(kind: "numeric", kmh: 50))
        now = 13
        runtime.context(way: "new", road: "ref:new", relations: [], direction: "forward", stable: true)
        XCTAssertEqual(runtime.output?.state, "LAST_KNOWN", "Confirmation must retain the last reliable same-way reverse direction")
        now = 21
        runtime.context(way: "new", road: "ref:new", relations: [], direction: "forward", stable: true)
        XCTAssertEqual(runtime.output?.generation, 2)
    }

    func testUnrelatedPendingRoadRestartsConfirmation() throws {
        var now = 0.0
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
        runtime.context(way: "old", road: "ref:old", relations: ["old"], direction: "forward", stable: true)
        runtime.bundle(id: "old-map", value: .init(kind: "numeric", kmh: 70))
        now = 1
        runtime.context(way: "b", road: "ref:B", relations: ["B"], direction: "forward", stable: true)
        now = 4
        runtime.context(way: "c", road: "ref:C", relations: ["C"], direction: "forward", stable: true)
        now = 9
        runtime.context(way: "c", road: "ref:C", relations: ["C"], direction: "forward", stable: true)
        XCTAssertEqual(runtime.output?.generation, 0)
        now = 12
        runtime.context(way: "c", road: "ref:C", relations: ["C"], direction: "forward", stable: false)
        XCTAssertEqual(runtime.output?.generation, 0)
        runtime.context(way: "c", road: "ref:C", relations: ["C"], direction: "forward", stable: true)
        XCTAssertEqual(runtime.output?.generation, 1)
    }

    func testAcceptedDirectionSurvivesUnknownButRealReversalStillWaitsEightSeconds() throws {
        var now = 0.0
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "forward", stable: true)
        runtime.bundle(id: "map", value: .init(kind: "numeric", kmh: 70))
        now = 1
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "unknown", stable: true)
        XCTAssertEqual(runtime.output?.state, "BUNDLE")
        now = 2
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "reverse", stable: true)
        XCTAssertEqual(runtime.output?.state, "LAST_KNOWN")
        now = 9.999
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "unknown", stable: true)
        XCTAssertEqual(runtime.output?.generation, 0)
        now = 10
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "reverse", stable: true)
        XCTAssertEqual(runtime.output?.generation, 1)
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

    func testCameraReceiptReportsAcceptedAndDuplicateOffersWithoutChangingDeduplication() throws {
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { 0 })
        runtime.camera(id: "old", value: .init(kind: "numeric", kmh: 70))
        let accepted = try XCTUnwrap(runtime.camera(id: "new", value: .init(kind: "numeric", kmh: 80)))
        XCTAssertEqual(accepted.offeredID, "new")
        XCTAssertEqual(accepted.offeredKind, "camera")
        XCTAssertEqual(accepted.before.value?.kmh, 70)
        XCTAssertEqual(accepted.after.transition, "T03")
        XCTAssertEqual(accepted.after.value?.kmh, 80)
        XCTAssertEqual(accepted.after.evidenceID, "new")
        let repeated = try XCTUnwrap(runtime.camera(id: "new", value: .init(kind: "numeric", kmh: 30)))
        XCTAssertEqual(repeated.offeredValue.kmh, 30)
        XCTAssertEqual(repeated.after.transition, "T11")
        XCTAssertEqual(repeated.after.value?.kmh, 80)
        XCTAssertEqual(runtime.output?.baselineKmh, 80)
    }

    func testCameraReceiptExposesPendingGateAndPreservesWithheldEvidenceBehavior() throws {
        var now = 0.0
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "forward", stable: true)
        runtime.camera(id: "old", value: .init(kind: "numeric", kmh: 70))
        now = 1
        runtime.context(way: "ramp", road: "ref:B", relations: [], direction: "forward", stable: false)
        let withheld = try XCTUnwrap(runtime.camera(id: "new", value: .init(kind: "numeric", kmh: 80)))
        XCTAssertTrue(withheld.pendingContextBefore)
        XCTAssertTrue(withheld.pendingContextAfter)
        XCTAssertEqual(withheld.after.transition, "T11")
        XCTAssertEqual(withheld.after.value?.kmh, 70)
        now = 2
        runtime.context(way: "road", road: "ref:A", relations: [], direction: "forward", stable: true)
        let repeated = try XCTUnwrap(runtime.camera(id: "new", value: .init(kind: "numeric", kmh: 80)))
        XCTAssertFalse(repeated.pendingContextBefore)
        XCTAssertEqual(repeated.after.transition, "T11")
        XCTAssertEqual(repeated.after.value?.kmh, 70)
        XCTAssertTrue(repeated.diagnosticFields["gapBefore"] is NSNull)
        XCTAssertTrue(repeated.diagnosticFields["seenBefore"] is NSNull)
        XCTAssertEqual(repeated.diagnosticFields["gateDiagnosticAvailability"] as? String, "pending_context_only")
        XCTAssertTrue(JSONSerialization.isValidJSONObject(repeated.diagnosticFields))
    }

    func testCameraReceiptDistinguishesAcceptedEnclosingOfferFromSelectedOrdinaryValue() throws {
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { 0 })
        runtime.camera(id: "posted", value: .init(kind: "numeric", kmh: 70))
        let receipt = try XCTUnwrap(runtime.camera(id: "zone", value: .init(kind: "numeric", kmh: 30), enclosing: true))
        XCTAssertEqual(receipt.offeredKind, "camera_context")
        XCTAssertEqual(receipt.after.transition, "T12")
        XCTAssertEqual(receipt.after.evidenceID, "posted")
        XCTAssertEqual(receipt.after.value?.kmh, 70)
    }

    func testCameraReceiptKeepsExpiryOriginsAndReportsActualRejection() throws {
        var now = 0.0
        let runtime = SpeedReferenceRuntime(model: try SpeedLimitReferenceModel.load(read: read), now: { now })
        runtime.camera(id: "sign", value: .init(kind: "numeric", kmh: 70))
        now = 300
        let expired = try XCTUnwrap(runtime.camera(id: "sign", value: .init(kind: "numeric", kmh: 70)))
        XCTAssertEqual(expired.before.state, "LAST_KNOWN")
        XCTAssertEqual(expired.after.transition, "T11")
        XCTAssertFalse(expired.after.current)
        let rejected = try XCTUnwrap(runtime.camera(id: "invalid", value: .init(kind: "numeric", kmh: 0)))
        XCTAssertEqual(rejected.after.transition, "REJECT")
        XCTAssertEqual(rejected.after.rejection, "invalid_value")
        XCTAssertEqual(rejected.after.evidenceID, "sign")
        let fields = try XCTUnwrap(rejected.diagnosticFields["after"] as? [String: Any])
        XCTAssertEqual(fields["rejection"] as? String, "invalid_value")
        XCTAssertNil(SpeedReferenceRuntime(model: nil, now: { 0 }).camera(id: "sign", value: .init(kind: "numeric", kmh: 70)))
    }
}
