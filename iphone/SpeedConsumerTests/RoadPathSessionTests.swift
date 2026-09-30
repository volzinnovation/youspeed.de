import XCTest
@testable import SpeedConsumer

final class RoadPathSessionTests: XCTestCase {
    private final class MutableClock {
        var value = 1.001
        var step = 0.0
        func now() -> Double { defer { value += step }; return value }
    }
    private let scope = TSRApplicabilityScope(sessionId: "drive", bundleId: "bundle", cameraGeometryId: "camera", generation: 1, contextGeneration: 1, traversalEpoch: 1)
    private let camera = RoadPathCalibration(revision: "mount", verified: true, fx: 0.8, fy: 0.8, cx: 0.5, cy: 0.5,
        yawDegrees: 0, pitchDegrees: 0, rollDegrees: 0, heightMeters: 1.6, lateralOffsetMeters: -0.08)
    private func frame(_ time: Double, sourceTime: Double? = nil) -> RoadPathCameraFrame {
        RoadPathCameraFrame(grayscale: [UInt8](repeating: 0, count: 128*72), width: 128, height: 72,
            capturedAtSeconds: time, geometryId: "geometry", calibration: camera, clockKnown: true,
            preprocessingMs: 0, startedAt: 1, rawWidth: 128, rawHeight: 72, sourceTimestampSeconds: sourceTime)
    }
    private func diagnostic(_ time: Double) -> TSRApplicabilityDiagnostic {
        let forward = 30-(time-10)*10
        let x = 0.5+0.8*3.08/forward, y = 0.5+0.8*(1.6-2)/forward
        let candidate = TSRApplicabilityCandidate(candidateId: "candidate-\(time)", semanticKey: "maximum_speed:50:",
            box: TSRApplicabilityBox(x: x-0.01, y: y-0.01, width: 0.02, height: 0.02), rawScore: 0.99,
            recognitionEligible: true, assemblyId: nil)
        let batch = TSRFrameCandidateBatch(schemaVersion: 1, frameId: "frame-\(time)", capturedAtMs: time*1000, scope: scope,
            status: "analyzed", candidates: [candidate], truncated: false, rawCandidateCount: 1, modelId: "model", preprocessingId: "preprocess", road: nil)
        let sample = TSRTrackSample(frameId: batch.frameId, capturedAtMs: time*1000, candidate: candidate)
        return TSRApplicabilityDiagnostic(schemaVersion: 1, batch: batch, tracks: [TSRPhysicalTrackSnapshot(trackId: "physical-sign",
            scope: scope, samples: [sample], visibility: "observed", associationAmbiguous: false)], decisions: [])
    }
    private func record(_ session: RoadPathSession, _ time: Double) {
        session.recordLocation(time: time, latitude: 48+(time-10)*10/6_371_000*180 / .pi,
            longitude: 8, course: 0, speed: 10, accuracy: 0.02, courseAccuracy: 0.02)
    }
    private func result(_ session: RoadPathSession, _ time: Double, sourceTime: Double? = nil) throws -> [String:Any] {
        let json = try XCTUnwrap(session.evaluate(frame: frame(time, sourceTime: sourceTime), diagnostic: diagnostic(time)))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String:Any])
    }
    private func decoded(_ json: String?) throws -> [String:Any] {
        let json = try XCTUnwrap(json)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String:Any])
    }
    func testDiagnosticPreservesAllVisualGuidesAndActualUprightPixelCrop() throws {
        let session = RoadPathSession(nowUptime: { 1.001 })
        let visual = VisualRoadCalibration(horizonY: 0.37,
            leftBottom: LanePoint(x: 0.11, y: 0.93), leftTopX: 0.413,
            rightBottom: LanePoint(x: 0.88, y: 0.91), rightTopX: 0.59,
            revision: "saved-calibration-test", imageWidth: 1280, imageHeight: 720,
            orientationKey: "rear:exif:6")
        var input = frame(10, sourceTime: 100)
        // Rotated sensor dimensions differ from both upright source and small analysis image.
        input.rawWidth = 720; input.rawHeight = 1280; input.rotationDegrees = 90
        input.orientationKey = visual.orientationKey; input.visualCalibration = visual
        let value = try decoded(session.evaluate(frame: input, diagnostic: diagnostic(10)))
        let logged = try XCTUnwrap(value["visualCalibration"] as? [String:Any])
        let recovered = try JSONDecoder().decode(VisualRoadCalibration.self,
            from: JSONSerialization.data(withJSONObject: logged))
        XCTAssertEqual(recovered, visual) // All seven coordinates, geometry, schema and revision.
        XCTAssertEqual(value["visualCalibrationRevision"] as? String, visual.revision)
        XCTAssertEqual(value["imageWidth"] as? Int, 1280)
        XCTAssertEqual(value["imageHeight"] as? Int, 720)
        XCTAssertEqual(value["tsrInputRegion"] as? [String:Int],
            ["leftPixels": 528, "topPixels": 0, "rightPixels": 1280, "bottomPixels": 720])
    }
    func testUncalibratedDiagnosticDoesNotInventSavedGuidesOrCrop() throws {
        let value = try result(RoadPathSession(nowUptime: { 1.001 }), 10)
        XCTAssertNil(value["visualCalibration"])
        XCTAssertNil(value["visualCalibrationRevision"])
        XCTAssertNil(value["tsrInputRegion"])
    }
    func testPreparedGeometryPublishesBeforeTsrAndInferenceTimeIsExcludedWithoutRefreshingExposure() throws {
        let clock = MutableClock(), session = RoadPathSession(nowUptime: { clock.now() })
        record(session,10)
        let diagnostic = diagnostic(10)
        let prepared = session.prepare(frame:frame(10,sourceTime:100),frameId:diagnostic.batch.frameId,scope:scope)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,10)
        XCTAssertFalse(prepared.geometry.budgetExceeded)
        XCTAssertEqual(prepared.publicationDetails["overlayPublicationPhase"] as? String,"before_tsr")
        clock.value = 101 // Long model/wait interval must not be charged or refresh old image evidence.
        let r = try decoded(session.evaluate(prepared:prepared,diagnostic:diagnostic,tsrStartedAtUptime:1.002))
        XCTAssertEqual(r["lanePreparedBeforeTsr"] as? Bool,true)
        XCTAssertEqual(r["geometryReusedAfterTsr"] as? Bool,true)
        XCTAssertEqual(r["geometryDeadlineExceeded"] as? Bool,false)
        XCTAssertEqual(r["deadlineExceeded"] as? Bool,false)
        XCTAssertEqual(try XCTUnwrap(r["totalAddedProcessingMs"] as? Double),1,accuracy:0.001)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,10)
        XCTAssertEqual(session.overlay()?.boundaries,prepared.geometry.boundaries)
    }
    func testPreparedFrameMismatchAndScopeMismatchCannotEnterAssociationHistory() throws {
        let session = RoadPathSession(nowUptime:{1.001}), diagnostic = diagnostic(10)
        let prepared = session.prepare(frame:frame(10),frameId:"different-frame",scope:scope)
        XCTAssertEqual(try decoded(session.evaluate(prepared:prepared,diagnostic:diagnostic))["reason"] as? String,"prepared_frame_mismatch")
        let changed = TSRApplicabilityScope(sessionId:"other",bundleId:scope.bundleId,cameraGeometryId:scope.cameraGeometryId,
            generation:scope.generation,contextGeneration:scope.contextGeneration,traversalEpoch:scope.traversalEpoch)
        let wrongScope = session.prepare(frame:frame(10),frameId:diagnostic.batch.frameId,scope:changed)
        XCTAssertEqual(try decoded(session.evaluate(prepared:wrongScope,diagnostic:diagnostic))["reason"] as? String,"prepared_frame_mismatch")
    }
    func testPreparedLocationSnapshotIgnoresFixArrivingDuringTsr() throws {
        let session = RoadPathSession(nowUptime:{1.001})
        record(session,10)
        let diagnostic = diagnostic(11)
        let prepared = session.prepare(frame:frame(11),frameId:diagnostic.batch.frameId,scope:scope)
        record(session,11)
        let r = try decoded(session.evaluate(prepared:prepared,diagnostic:diagnostic))
        XCTAssertEqual(r["trajectorySamples"] as? Int,1)
        XCTAssertEqual((r["trajectory"] as? [[String:Double]])?.last?["timeSeconds"],10)
    }
    func testPreparationOrderingNeverComparesCameraSecondsWithUtc() {
        let session = RoadPathSession(nowUptime:{1.001})
        _ = session.prepare(frame:frame(10,sourceTime:100),frameId:"raw-clock",scope:scope)
        _ = session.prepare(frame:frame(11),frameId:"utc-fallback",scope:scope)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,11)
        _ = session.prepare(frame:frame(12,sourceTime:101),frameId:"raw-clock-restored",scope:scope)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,12)
        _ = session.prepare(frame:frame(12.1,sourceTime:101),frameId:"raw-duplicate",scope:scope)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,12)
    }
    func testPreparedInvalidationAndRejectedAdmissionNeverResurrectOverlay() throws {
        let session = RoadPathSession(nowUptime:{1.001}), diagnostic = diagnostic(10)
        let rejected = session.prepare(frame:frame(10),frameId:diagnostic.batch.frameId,scope:scope,shouldPublish:{false})
        XCTAssertNil(session.overlay())
        XCTAssertEqual(rejected.publicationDetails["overlayPublicationSuppressionReason"] as? String,"admission_changed")
        let prepared = session.prepare(frame:frame(10),frameId:diagnostic.batch.frameId,scope:scope)
        XCTAssertNotNil(session.overlay())
        session.invalidateOverlay()
        XCTAssertEqual(try decoded(session.evaluate(prepared:prepared,diagnostic:diagnostic))["reason"] as? String,"overlay_invalidated")
        XCTAssertNil(session.overlay())
    }
    func testGeometryAndCumulativeAddedDeadlinesClearOnlyOwnedOverlay() throws {
        let clock = MutableClock(), session = RoadPathSession(nowUptime:{clock.now()})
        clock.value = 1.051
        let diagnostic = diagnostic(10)
        let expired = session.prepare(frame:frame(10),frameId:diagnostic.batch.frameId,scope:scope)
        XCTAssertTrue(expired.geometry.budgetExceeded)
        XCTAssertTrue(expired.geometry.boundaries.isEmpty)
        XCTAssertNil(session.overlay())
        clock.value = 1.001
        let valid = session.prepare(frame:frame(11),frameId:"frame-11.0",scope:scope)
        XCTAssertNotNil(session.overlay())
        session.invalidatePreparedOverlay(frameId:diagnostic.batch.frameId)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,11)
        clock.value = 100; clock.step = 0.05
        let r = try decoded(session.evaluate(prepared:valid,diagnostic:self.diagnostic(11)))
        XCTAssertEqual(r["reason"] as? String,"added_processing_deadline")
        XCTAssertNil(session.overlay())
    }
    func testDualProviderDuplicateAndOlderFixesPreserveThreeObservationTriangulation() throws {
        let session = RoadPathSession(nowUptime: { 1.001 })
        for (index,time) in [10.0,11,12].enumerated() {
            record(session,time)
            session.recordLocation(time: time, latitude: 49, longitude: 9, course: 90, speed: 20, accuracy: 0.01, courseAccuracy: 0.01)
            session.recordLocation(time: time-0.2, latitude: 49, longitude: 9, course: 90, speed: 20, accuracy: 0.01, courseAccuracy: 0.01)
            let r = try result(session,time), origin = try XCTUnwrap(r["localOrigin"] as? [String:Double])
            XCTAssertEqual(r["trajectorySamples"] as? Int,index+1)
            XCTAssertEqual(origin["latitude"],48)
            let ingestion = try XCTUnwrap(r["locationIngestion"] as? [String:Int])
            XCTAssertEqual(ingestion["duplicateFixesDropped"],index+1)
            XCTAssertEqual(ingestion["outOfOrderFixesDropped"],index+1)
            XCTAssertEqual(ingestion["resetCount"],0)
            let a = try XCTUnwrap((r["associations"] as? [[String:Any]])?.first)
            XCTAssertEqual((a["observations"] as? [Any])?.count,index+1)
            if index == 2 {
                XCTAssertEqual(a["supportingObservations"] as? Int,3)
                XCTAssertEqual(a["reason"] as? String,"current_path_unavailable")
                XCTAssertEqual(try XCTUnwrap(a["eastMeters"] as? Double),3,accuracy: 1e-6)
                XCTAssertEqual(try XCTUnwrap(a["northMeters"] as? Double),30,accuracy: 1e-6)
                XCTAssertEqual(a["classification"] as? String,"unknown")
                XCTAssertEqual(a["shadowOnly"] as? Bool,true)
            }
        }
    }
    func testExplicitResetStartsNewOriginAndObservationHistory() throws {
        let session = RoadPathSession(nowUptime: { 1.001 })
        record(session,10); _ = try result(session,10)
        record(session,11); _ = try result(session,11)
        session.resetTrajectory()
        XCTAssertNil(session.overlay())
        session.recordLocation(time: 11.2, latitude: 49, longitude: 9, course: 0, speed: 10, accuracy: 0.02, courseAccuracy: 0.02)
        let r = try result(session,11.2)
        XCTAssertEqual(r["trajectorySamples"] as? Int,1)
        XCTAssertEqual((r["localOrigin"] as? [String:Double])?["latitude"],49)
        XCTAssertEqual((r["locationIngestion"] as? [String:Int])?["resetCount"],1)
        XCTAssertEqual(((r["associations"] as? [[String:Any]])?.first?["observations"] as? [Any])?.count,1)
        session.resetTrajectory(); record(session,5)
        let next = try result(session,5)
        XCTAssertEqual((next["trajectory"] as? [[String:Double]])?.first?["timeSeconds"],5)
        XCTAssertEqual((next["locationIngestion"] as? [String:Int])?["resetCount"],2)
    }
    func testDuplicateAndOlderFramesPublishNoEvidenceAndPreserveTrackHistoryAndOverlay() throws {
        let session = RoadPathSession(nowUptime: { 1.001 })
        record(session,10); _ = try result(session,10)
        record(session,11); _ = try result(session,11)
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,11)
        for (time,reason) in [(11.0,"duplicate_frame"),(10.5,"out_of_order_frame")] {
            let skipped = try result(session,time)
            XCTAssertEqual(skipped["reason"] as? String,reason)
            XCTAssertEqual((skipped["associations"] as? [Any])?.count,0)
            XCTAssertNil(skipped["boundaries"])
            XCTAssertEqual(session.overlay()?.capturedAtSeconds,11)
        }
        record(session,12)
        let r = try result(session,12)
        let a = try XCTUnwrap((r["associations"] as? [[String:Any]])?.first)
        let observations = try XCTUnwrap(a["observations"] as? [[String:Any]])
        XCTAssertEqual(observations.compactMap { $0["timeSeconds"] as? Double },[10,11,12])
        XCTAssertEqual(a["supportingObservations"] as? Int,3)
    }
    func testChangedScopeAcceptsEarlierExposureWithoutReusingHistory() throws {
        let session = RoadPathSession(nowUptime: { 1.001 })
        record(session,10); _ = try result(session,10)
        let next = diagnostic(9), batch = next.batch
        let changedScope = TSRApplicabilityScope(sessionId: scope.sessionId, bundleId: scope.bundleId, cameraGeometryId: scope.cameraGeometryId,
            generation: 2, contextGeneration: scope.contextGeneration, traversalEpoch: scope.traversalEpoch)
        let changed = TSRFrameCandidateBatch(schemaVersion: batch.schemaVersion, frameId: batch.frameId, capturedAtMs: batch.capturedAtMs,
            scope: changedScope, status: batch.status, candidates: batch.candidates, truncated: batch.truncated, rawCandidateCount: batch.rawCandidateCount,
            modelId: batch.modelId, preprocessingId: batch.preprocessingId, road: batch.road)
        let json = try XCTUnwrap(session.evaluate(frame: frame(9), diagnostic: TSRApplicabilityDiagnostic(schemaVersion: 1,
            batch: changed, tracks: next.tracks, decisions: [])))
        let r = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String:Any])
        XCTAssertNil(r["reason"])
        XCTAssertEqual(((r["associations"] as? [[String:Any]])?.first?["observations"] as? [Any])?.count,1)
    }
    func testRawExposureOrderingRejectsRedeliveryDespiteNewerMappedUtc() throws {
        let session = RoadPathSession(nowUptime: { 1.001 })
        record(session,10); _ = try result(session,10,sourceTime: 100)
        record(session,11); _ = try result(session,11,sourceTime: 101)
        let duplicate = try result(session,11.1,sourceTime: 101)
        let older = try result(session,11.2,sourceTime: 100.5)
        XCTAssertEqual(duplicate["reason"] as? String,"duplicate_frame")
        XCTAssertEqual(older["reason"] as? String,"out_of_order_frame")
        for skipped in [duplicate,older] {
            XCTAssertEqual(skipped["frameOrderingClock"] as? String,"source_exposure")
            XCTAssertEqual((skipped["associations"] as? [Any])?.count,0)
        }
        XCTAssertEqual(session.overlay()?.capturedAtSeconds,11)
        record(session,12)
        let r = try result(session,12,sourceTime: 102)
        let a = try XCTUnwrap((r["associations"] as? [[String:Any]])?.first)
        let observations = try XCTUnwrap(a["observations"] as? [[String:Any]])
        XCTAssertEqual(observations.compactMap { $0["timeSeconds"] as? Double },[10,11,12])
        XCTAssertEqual(a["supportingObservations"] as? Int,3)
        session.resetTrajectory(); record(session,5)
        let reset = try result(session,5,sourceTime: 1)
        XCTAssertNil(reset["reason"])
        XCTAssertEqual(((reset["associations"] as? [[String:Any]])?.first?["observations"] as? [Any])?.count,1)
    }
    private final class PausedClock: @unchecked Sendable {
        let entered = DispatchSemaphore(value: 0), resume = DispatchSemaphore(value: 0)
        private let lock = NSLock()
        private var first = true
        func now() -> Double {
            lock.lock(); let pause = first; first = false; lock.unlock()
            if pause {
                entered.signal()
                precondition(resume.wait(timeout: .now()+5) == .success,"Test evaluator was not resumed")
            }
            return 1.001
        }
    }
    private final class ResultBox: @unchecked Sendable {
        var json: String?
    }
    private func concurrentEvaluation(reset: Bool) throws {
        let clock = PausedClock()
        // Use a fresh clock-controlled session so analysis pauses after taking its location snapshot.
        let pausedSession = RoadPathSession(nowUptime: clock.now)
        record(pausedSession,10)
        let done = DispatchSemaphore(value: 0), box = ResultBox()
        let inputFrame = frame(10), inputDiagnostic = diagnostic(10)
        DispatchQueue(label: "RoadPathSessionTests.evaluate").async {
            box.json = pausedSession.evaluate(frame: inputFrame, diagnostic: inputDiagnostic); done.signal()
        }
        defer { clock.resume.signal() }
        XCTAssertEqual(clock.entered.wait(timeout: .now()+2),.success)
        let callbackDone = DispatchSemaphore(value: 0)
        DispatchQueue(label: "RoadPathSessionTests.callback").async {
            if reset { pausedSession.resetTrajectory() }
            else {
                pausedSession.recordLocation(time: 10, latitude: 49, longitude: 9, course: 90, speed: 20, accuracy: 0.01, courseAccuracy: 0.01)
                pausedSession.recordLocation(time: 9, latitude: 49, longitude: 9, course: 90, speed: 20, accuracy: 0.01, courseAccuracy: 0.01)
            }
            callbackDone.signal()
        }
        XCTAssertEqual(callbackDone.wait(timeout: .now()+2),.success)
        clock.resume.signal()
        XCTAssertEqual(done.wait(timeout: .now()+2),.success)
        let json = try XCTUnwrap(box.json)
        let r = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String:Any])
        if reset {
            XCTAssertEqual(r["reason"] as? String,"trajectory_reset")
            XCTAssertEqual((r["associations"] as? [Any])?.count,0)
            XCTAssertNil(pausedSession.overlay())
        } else {
            XCTAssertNil(r["reason"])
            XCTAssertEqual(r["trajectorySamples"] as? Int,1)
            XCTAssertNotNil(pausedSession.overlay())
            let next = try result(pausedSession,10.1)
            let ingestion = try XCTUnwrap(next["locationIngestion"] as? [String:Int])
            XCTAssertEqual(ingestion["duplicateFixesDropped"],1)
            XCTAssertEqual(ingestion["outOfOrderFixesDropped"],1)
            XCTAssertEqual(ingestion["resetCount"],0)
        }
    }
    func testDuplicateAndOlderCallbacksDoNotInvalidateInFlightEvaluation() throws { try concurrentEvaluation(reset: false) }
    func testExplicitResetDiscardsInFlightEvaluation() throws { try concurrentEvaluation(reset: true) }
}
