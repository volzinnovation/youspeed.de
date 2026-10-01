import XCTest
@testable import SpeedConsumer

final class RoadPathSessionTests: XCTestCase {

    func testPreviewExperimentsCannotChangeTSRPathEvidence() {
        let baseline=RoadPathSession(nowUptime:{1.001})
        let requested=RoadPathSession(detectionOptions:RoadBoundaryDetectionOptions(useSearchBands:true,groupFragments:true),
            fragmentTracking:true,retainTentativeIdentity:true,jointSelection:true,nowUptime:{1.001})
        for i in 0..<8 {
            let frame=paintedFrame(10+Double(i)*0.1,sourceTime:100+Double(i)*0.1)
            let a=baseline.prepare(frame:frame,frameId:"a-\(i)",scope:scope)
            let b=requested.prepare(frame:frame,frameId:"b-\(i)",scope:scope)
            XCTAssertEqual(a.geometry.boundaries,b.geometry.boundaries)
            XCTAssertEqual(a.presentation.visibleBoundaryIndices,b.presentation.visibleBoundaryIndices)
            XCTAssertFalse(b.diagnostics.fragmentTrackingEnabled)
            XCTAssertFalse(b.diagnostics.tentativeIdentityEnabled)
            XCTAssertFalse(b.diagnostics.jointSelectionEnabled)
            XCTAssertEqual(b.diagnostics.detectionVariant,"baseline")
        }
    }

    func testPreparationDiagnosticsIdentifyComponentAndCurrentIntrinsicsWithoutDriftResets() {
        let session=RoadPathSession(previewMode:true,nowUptime:{1.001})
        func input(_ i:Int,cx:Double=0.5,geometry:String="geometry") -> RoadPathCameraFrame {
            let f=paintedFrame(10+Double(i)*0.1,sourceTime:100+Double(i)*0.1)
            return RoadPathCameraFrame(grayscale:f.grayscale,width:f.width,height:f.height,capturedAtSeconds:f.capturedAtSeconds,
                geometryId:geometry,calibration:calibration(cx:cx),clockKnown:true,preprocessingMs:0,startedAt:1,
                rawWidth:128,rawHeight:72,sourceTimestampSeconds:f.sourceTimestampSeconds)
        }
        let first=session.prepare(frame:input(0),frameId:"0",scope:scope)
        XCTAssertEqual(first.diagnostics.resetComponents,["initial"])
        let drift=session.prepare(frame:input(1,cx:0.50001),frameId:"1",scope:scope)
        XCTAssertEqual(drift.diagnostics.calibrationGeneration,first.diagnostics.calibrationGeneration)
        XCTAssertEqual(drift.diagnostics.calibration?.cx,0.50001)
        XCTAssertTrue(drift.diagnostics.resetComponents.isEmpty)
        XCTAssertEqual(Set(drift.diagnostics.stageMs.keys),Set(["luma","queueAndAdmission","filter","prediction","detector","fusion","presentation","total"]))
        let zoom=session.prepare(frame:input(2,cx:0.502),frameId:"2",scope:scope)
        XCTAssertEqual(zoom.diagnostics.resetComponents,["calibration"])
        let crop=session.prepare(frame:input(3,cx:0.502,geometry:"crop"),frameId:"3",scope:scope)
        XCTAssertEqual(crop.diagnostics.resetComponents,["geometry"])
        session.invalidateOverlay()
        let lifecycle=session.prepare(frame:input(4,cx:0.502,geometry:"crop"),frameId:"4",scope:scope)
        XCTAssertEqual(lifecycle.diagnostics.resetComponents,["lifecycle"])
    }
    func testWeakSavedGuidesCannotCropAwayObservedPaintOrMutateSavedCalibration() {
        let session=RoadPathSession(previewMode:true,nowUptime:{1.001})
        let saved=VisualRoadCalibration(horizonY:0.75,leftBottom:LanePoint(x:0.03,y:1),leftTopX:0.03,
            rightBottom:LanePoint(x:0.54,y:1),rightTopX:0.54,revision:"shifted",imageWidth:128,imageHeight:72,orientationKey:"test")
        var input=paintedFrame(10,sourceTime:100); input.visualCalibration=saved; input.orientationKey="test"
        let result=session.prepare(frame:input,frameId:"weak",scope:scope)
        XCTAssertEqual(result.diagnostics.guideTrust.state,"weak")
        XCTAssertEqual(result.diagnostics.guideTrust.reason,"observed_border_conflict")
        XCTAssertEqual(result.diagnostics.guidePriorUsed,"none_independent_audit")
        XCTAssertEqual(result.geometry.boundaries.count,2)
        XCTAssertTrue(result.geometry.boundaries.allSatisfy { $0.points.first!.y < saved.horizonY })
        XCTAssertEqual(result.frame.visualCalibration,saved)
    }
    func testGuideTrustRequiresIndependentBothSideEvidenceAndExpiresOrRejectsConflict() {
        let validator=RoadVisualGuideValidator()
        let saved=VisualRoadCalibration(horizonY:0.42,leftBottom:LanePoint(x:0.23,y:1),leftTopX:0.23,
            rightBottom:LanePoint(x:0.75,y:1),rightTopX:0.75,revision:"saved",imageWidth:128,imageHeight:72,orientationKey:"test")
        func borders(_ shift:Double=0,provenance:RoadBoundaryProvenance = .fresh) -> [RoadBoundaryEvidence] {
            [0.23,0.75].map { RoadBoundaryEvidence(points:[LanePoint(x:$0+shift,y:0.55),LanePoint(x:$0+shift,y:0.9)],
                confidence:0.95,cue:.paint,supportRows:12,provenance:provenance) }
        }
        for i in 0..<5 {
            let t=Double(i)*0.1, plan=validator.begin(saved:saved,compatible:saved,time:t,key:"camera")
            let state=validator.observe(borders(),visual:saved,time:t,plan:plan)
            XCTAssertEqual(state.state,i == 4 ? "trusted" : "weak")
        }
        let expiry=validator.begin(saved:saved,compatible:saved,time:2,key:"camera")
        XCTAssertFalse(expiry.trusted)
        XCTAssertEqual(expiry.reason,"independent_evidence_expired")
        let conflictPlan=RoadVisualGuidePlan(independentAudit:true,trusted:false,reason:"audit")
        XCTAssertEqual(validator.observe(borders(0.15),visual:saved,time:2.1,plan:conflictPlan).reason,"observed_border_conflict")
        for i in 0..<5 {
            let t=3+Double(i)*0.1, plan=validator.begin(saved:saved,compatible:saved,time:t,key:"new-camera")
            XCTAssertEqual(validator.observe(borders(provenance:.tracked),visual:saved,time:t,plan:plan).state,"weak")
        }
        let onlyLeft=validator.observe(Array(borders().prefix(1)),visual:saved,time:4,plan:conflictPlan)
        XCTAssertEqual(onlyLeft.matchedSides,1); XCTAssertEqual(onlyLeft.state,"weak")
    }

    private func calibration(cx: Double = 0.5, fx: Double = 0.8, revision: String = "mount") -> RoadPathCalibration {
        RoadPathCalibration(revision:revision,verified:true,fx:fx,fy:0.8,cx:cx,cy:0.5,
            yawDegrees:0,pitchDegrees:0,rollDegrees:0,heightMeters:1.6,lateralOffsetMeters:-0.08)
    }
    func testPreviewCalibrationIdentityAnchorsDriftAndResetsRealChanges() {
        let identity = RoadPreviewCalibrationIdentity()
        let first = identity.key(calibration())
        for i in 0..<10 { XCTAssertEqual(identity.key(calibration(cx:0.5+Double(i)*0.00001)),first) }
        XCTAssertNotEqual(identity.key(calibration(cx:0.5011)),first)
        let drifted = identity.key(calibration(cx:0.5011))
        XCTAssertNotEqual(identity.key(calibration(cx:0.5011,fx:0.82)),drifted)
        let zoomed = identity.key(calibration(cx:0.5011,fx:0.82))
        XCTAssertNotEqual(identity.key(calibration(cx:0.5011,fx:0.82,revision:"new-mount")),zoomed)
        let mounted = identity.key(calibration(cx:0.5011,fx:0.82,revision:"new-mount"))
        XCTAssertNotEqual(identity.key(nil),mounted)
        let missing = identity.key(nil)
        XCTAssertNotEqual(identity.key(calibration()),missing)
    }
    func testPreviewMaturesWithTinyIntrinsicsDriftAndResetsOnZoomAndCrop() {
        let session = RoadPathSession(previewMode:true,nowUptime:{1.001})
        func prepare(_ i:Int, fx:Double=0.8, geometry:String="geometry") -> RoadPathPreparedFrame {
            let source = paintedFrame(10+Double(i)*0.1,sourceTime:100+Double(i)*0.1)
            let input = RoadPathCameraFrame(grayscale:source.grayscale,width:128,height:72,
                capturedAtSeconds:source.capturedAtSeconds,geometryId:geometry,
                calibration:calibration(cx:0.5+Double(i)*0.00001,fx:fx),clockKnown:true,
                preprocessingMs:0,startedAt:1,rawWidth:128,rawHeight:72,sourceTimestampSeconds:source.sourceTimestampSeconds)
            return session.prepare(frame:input,frameId:"drift-\(i)",scope:scope)
        }
        for i in 0..<10 {
            let result = prepare(i)
            XCTAssertEqual(result.geometry.boundaries.count,2)
            if i >= 4 { XCTAssertEqual(result.presentation.visibleBoundaryIndices.count,2) }
        }
        XCTAssertTrue(prepare(10,fx:0.82).presentation.visibleBoundaryIndices.isEmpty)
        for i in 11..<16 { _ = prepare(i,fx:0.82) }
        XCTAssertEqual(prepare(16,fx:0.82).presentation.visibleBoundaryIndices.count,2)
        XCTAssertTrue(prepare(17,fx:0.82,geometry:"new-crop").presentation.visibleBoundaryIndices.isEmpty)
    }
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
    private func paintedFrame(_ time:Double,sourceTime:Double,startedAt:Double=1) -> RoadPathCameraFrame {
        var gray=[UInt8](repeating:55,count:128*72)
        for y in 0..<72 { for x in [29,30,31,94,95,96] { gray[y*128+x]=230 } }
        return RoadPathCameraFrame(grayscale:gray,width:128,height:72,capturedAtSeconds:time,geometryId:"geometry",
            calibration:camera,clockKnown:true,preprocessingMs:0,startedAt:startedAt,rawWidth:128,rawHeight:72,sourceTimestampSeconds:sourceTime)
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
        let prepared = session.prepare(frame:paintedFrame(10,sourceTime:100),frameId:diagnostic.batch.frameId,scope:scope)
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
        XCTAssertEqual(prepared.geometry.boundaries.count,2)
        XCTAssertEqual((r["boundaries"] as? [[String:Any]])?.count,2)
        XCTAssertTrue(session.overlay()?.boundaries.isEmpty ?? false)
        XCTAssertEqual(prepared.presentation.tentativeCount,2)
        let second=session.prepare(frame:paintedFrame(10.45,sourceTime:100.45,startedAt:clock.value-0.001),frameId:"second",scope:scope)
        XCTAssertEqual(second.geometry.boundaries.count,2)
        XCTAssertEqual(session.overlay()?.boundaries,second.geometry.boundaries)
        XCTAssertEqual(second.presentation.confirmedCount,2)
        session.invalidateOverlay()
        let afterReset=session.prepare(frame:paintedFrame(10.7,sourceTime:100.7,startedAt:clock.value-0.001),frameId:"after-reset",scope:scope)
        XCTAssertEqual(afterReset.geometry.boundaries.count,2)
        XCTAssertTrue(session.overlay()?.boundaries.isEmpty ?? false)
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
    func testPerformanceTargetDoesNotRejectButCumulativeAssociationDeadlineClearsOwnedOverlay() throws {
        let clock = MutableClock(), session = RoadPathSession(nowUptime:{clock.now()})
        clock.value = 1.051
        let diagnostic = diagnostic(10)
        let expired = session.prepare(frame:frame(10),frameId:diagnostic.batch.frameId,scope:scope)
        XCTAssertFalse(expired.geometry.budgetExceeded)
        XCTAssertTrue(expired.performanceTargetExceeded)
        XCTAssertNotNil(session.overlay())
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
    func testSlowPreparationKeepsMatureGeometryAndReportsPerformanceTargetOnly() throws {
        for preview in [false,true] {
            let session=RoadPathSession(previewMode:preview,nowUptime:{0.060})
            for i in 0...10 {
                let prepared=session.prepare(frame:paintedFrame(10+Double(i)*0.1,sourceTime:100+Double(i)*0.1,startedAt:0),frameId:"slow-\(i)",scope:scope)
                XCTAssertFalse(prepared.geometry.budgetExceeded)
                XCTAssertEqual(prepared.geometry.boundaries.count,2)
                XCTAssertTrue(prepared.performanceTargetExceeded)
                XCTAssertTrue(prepared.presentation.accepted)
                if i>=4 { XCTAssertEqual(prepared.presentation.visibleBoundaryIndices.count,2) }
                XCTAssertNotNil(session.overlay())
            }
        }
        let session=RoadPathSession(nowUptime:{1.060})
        let value=try result(session,10)
        XCTAssertEqual(value["geometryDeadlineExceeded"] as? Bool,false)
        XCTAssertEqual(value["preparationPerformanceTargetExceeded"] as? Bool,true)
    }

    func testCrossingPerformanceTargetAfterSelectionNeverInvalidatesGeometryOrPresentation() {
        for preview in [false,true] {
            var calls=0, crossingAt:Int?=nil
            var elapsed=0.050
            let session=RoadPathSession(previewMode:preview,nowUptime:{
                calls += 1
                return crossingAt.map { calls >= $0 } == true ? elapsed : 0.001
            })
            func prepare(_ i:Int) -> RoadPathPreparedFrame {
                calls=0
                return session.prepare(frame:paintedFrame(10+Double(i)*0.1,sourceTime:100+Double(i)*0.1,startedAt:0),frameId:"crossing-\(i)",scope:scope)
            }
            for i in 0...10 { _ = prepare(i) }
            crossingAt=calls // The final preparation clock read, after mature side selection.
            for (offset,time) in [0.050,0.060].enumerated() {
                elapsed=time
                let prepared=prepare(11+offset)
                XCTAssertEqual(prepared.preparationMs,time*1000,accuracy:0.000001)
                XCTAssertEqual(prepared.performanceTargetExceeded,time>0.050)
                XCTAssertFalse(prepared.geometry.budgetExceeded)
                XCTAssertTrue(prepared.presentation.accepted)
                XCTAssertEqual(prepared.presentation.visibleBoundaryIndices,[0,1])
                // The exact formerly trapping diagnostic lookup must also remain safe.
                XCTAssertEqual(prepared.presentation.visibleBoundaryIndices.map { prepared.geometry.boundaries[$0].points }.count,2)
                XCTAssertEqual(session.overlay()?.boundaries.count,2)
            }
            crossingAt=nil
            let recovered=prepare(13)
            XCTAssertEqual(recovered.presentation.visibleBoundaryIndices.count,2)
            XCTAssertFalse(recovered.performanceTargetExceeded)
        }
    }

    func testRealOperationExhaustionStillRejectsGeometryAndPresentationTogether() {
        for preview in [false,true] {
            let session=RoadPathSession(previewMode:preview,maximumGeometryOperations:100,nowUptime:{1.060})
            let prepared=session.prepare(frame:paintedFrame(10,sourceTime:100),frameId:"operation-limit",scope:scope)
            XCTAssertTrue(prepared.geometry.budgetExceeded)
            XCTAssertTrue(prepared.geometry.boundaries.isEmpty)
            XCTAssertFalse(prepared.presentation.accepted)
            XCTAssertTrue(prepared.presentation.visibleBoundaryIndices.isEmpty)
            XCTAssertEqual(prepared.presentation.reason,"geometry_budget")
            XCTAssertEqual(prepared.presentation.rawCount,0)
            XCTAssertNil(session.overlay())
        }
    }

    func testIndependentPreviewDoesNotInheritSignAssociationDeadline() {
        let session=RoadPathSession(previewMode:true,nowUptime:{1.250})
        for i in 0...10 { _ = session.prepare(frame:paintedFrame(10+Double(i)*0.1,sourceTime:100+Double(i)*0.1),frameId:"slow-preview-\(i)",scope:scope) }
        XCTAssertEqual(session.overlay()?.boundaries.count,2)
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
