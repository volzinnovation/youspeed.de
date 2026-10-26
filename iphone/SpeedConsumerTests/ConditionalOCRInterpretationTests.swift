import XCTest
@testable import SpeedConsumer

final class ConditionalOCRInterpretationTests: XCTestCase {
    @MainActor func testControllerWithdrawsPositivePlateButEmptyReadRetainsNumericMapVoiceAndUnrelatedCamera() {
        let model = DriveSessionViewModel()
        let at = Date()
        let box = TrafficSignNormalizedRect(x: 0.2, y: 0.2, width: 0.1, height: 0.1)
        let candidate = TrafficSignRecognitionCandidate(rawClassId: "maxspeed:30", rawLabel: "30",
            semanticKind: TrafficSignSemanticKind.maximumSpeed.rawValue, value: 30, unit: "km/h",
            rawScore: 0.99, calibratedConfidence: nil, boundingBox: box, trackId: "conditional-parent", evidenceFrames: 2)
        let event = TrafficSignRecognitionEvent(schemaVersion: 1, packId: "test", artifactSha256: String(repeating: "a", count: 64),
            preprocessingVersion: "test", frameId: "first", driveSessionId: "test", analysisEligible: true,
            source: .liveFrame, frameTimestampUtc: at, state: .confirmed, candidate: candidate, roadContext: nil,
            latencyMs: 0, thermalState: "nominal")
        let annotation = TrafficSignSupplementaryOCRAnnotation(primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
            physicalSignID: "conditional-parent", frameID: "first", sourceObservedAt: at, observedAt: at, firstSeenAt: at,
            rawText: "bei Nässe", window: nil, readStatus: .read, primaryBoundingBox: box, ocrBoundingBox: box,
            engine: "test", modelVersion: "test")
        let emission = TrafficSignRuntimeEmission(event: event, frameContext: nil, ocrAnnotation: annotation, supplementaryOCROnly: true)
        model.testSeedConditionalOCRReference(cameraID: "conditional-parent")
        XCTAssertEqual(model.speedLimitKmh, 30)
        model.testMaskConditionalOCRParent(emission)
        XCTAssertEqual(model.speedLimitKmh, 80)
        XCTAssertEqual(model.effectiveSpeedLimitState.source, .bundle)
        for status in [TrafficSignSupplementaryOCRReadStatus.noText, .failed] {
            let unreadModel = DriveSessionViewModel()
            unreadModel.testSeedConditionalOCRReference(cameraID: "conditional-parent")
            let unread = TrafficSignSupplementaryOCRAnnotation(primaryClassID: "maxspeed:30", primarySpeedKmh: 30,
                physicalSignID: "conditional-parent", frameID: "first", sourceObservedAt: at, observedAt: at, firstSeenAt: at,
                rawText: nil, window: nil, readStatus: status, primaryBoundingBox: box, ocrBoundingBox: box,
                engine: "test", modelVersion: "test")
            unreadModel.testMaskConditionalOCRParent(TrafficSignRuntimeEmission(event: event, frameContext: nil,
                ocrAttemptAnnotation: unread, supplementaryOCROnly: true))
            XCTAssertEqual(unreadModel.speedLimitKmh, 30, "A failed/empty read without positive plate evidence cannot block its recognized parent")
            XCTAssertEqual(unreadModel.effectiveSpeedLimitState.source, .camera)
            XCTAssertFalse(unreadModel.testConditionalOCRParentIsBlocked("conditional-parent"))
        }
        model.testSeedConditionalOCRReference(cameraID: "conditional-parent", ownCorrection: 70)
        model.testMaskConditionalOCRParent(emission)
        XCTAssertEqual(model.speedLimitKmh, 70)
        XCTAssertEqual(model.effectiveSpeedLimitState.source, .localCorrection)
        model.testSeedConditionalOCRReference(cameraID: "independent-camera")
        model.testMaskConditionalOCRParent(emission)
        XCTAssertEqual(model.speedLimitKmh, 30)
        XCTAssertEqual(model.effectiveSpeedLimitState.source, .camera)
    }

    @MainActor func testControllerLatchesKnownDeferredPlateWithoutBlockingUnrelatedBareSign() {
        let model = DriveSessionViewModel(), at = Date()
        func emission(_ id: String, condition: TrafficSignConditionState) -> TrafficSignRuntimeEmission {
            let candidate = TrafficSignRecognitionCandidate(rawClassId: "maxspeed:30", rawLabel: "30",
                semanticKind: TrafficSignSemanticKind.maximumSpeed.rawValue, value: 30, unit: "km/h", rawScore: 0.99,
                calibratedConfidence: nil, boundingBox: .init(x: 0.2, y: 0.2, width: 0.1, height: 0.1),
                trackId: id, evidenceFrames: 2, conditionState: condition)
            let event = TrafficSignRecognitionEvent(schemaVersion: 1, packId: "test", artifactSha256: String(repeating: "a", count: 64),
                preprocessingVersion: "test", source: .liveFrame, frameTimestampUtc: at, state: .confirmed,
                candidate: candidate, latencyMs: 0, thermalState: "critical")
            return TrafficSignRuntimeEmission(event: event, frameContext: nil, ocrPhase: .notRequired)
        }
        model.testSeedConditionalOCRReference(cameraID: "deferred-parent")
        model.testMaskConditionalOCRParent(emission("deferred-parent", condition: .unresolved))
        XCTAssertEqual(model.speedLimitKmh, 80)
        model.testMaskConditionalOCRParent(emission("deferred-parent", condition: .none))
        XCTAssertEqual(model.speedLimitKmh, 80, "Deferred plate evidence cannot expire into an unconditional parent")
        model.testSeedConditionalOCRReference(cameraID: "unrelated-bare")
        model.testMaskConditionalOCRParent(emission("unrelated-bare", condition: .none))
        XCTAssertEqual(model.speedLimitKmh, 30, "A separate numeric parent must not wait for negative plate proof")
        XCTAssertEqual(model.effectiveSpeedLimitState.source, .camera)
    }
    func testUnverifiedPlateCannotRenewNumericParentAndIsScopedToPhysicalGeneration() {
        var gate = ConditionalOCRInterpretation.AuthorityGate()
        for text in ["Mo-Fr 6-17h", "bei Nässe", "Lärmschu", "Lärmschutz"] {
            XCTAssertTrue(gate.observe(parentID: text, primaryClassID: "maxspeed:30", speedKmh: 30, rawText: text, scope: "1:1"))
            XCTAssertTrue(gate.blocks(text, scope: "1:1"))
            XCTAssertFalse(gate.observe(parentID: text, primaryClassID: "maxspeed:30", speedKmh: 30, rawText: nil, scope: "1:1"))
            XCTAssertTrue(gate.blocks(text, scope: "1:1"), "A later unread frame must not renew the numeric parent")
        }
        XCTAssertFalse(gate.blocks("unrelated", scope: "1:1"))
        for text in [nil, "", " \n\t"] as [String?] {
            XCTAssertFalse(gate.observe(parentID: "unread-first", primaryClassID: "maxspeed:30", speedKmh: 30, rawText: text, scope: "1:1"))
            XCTAssertFalse(gate.blocks("unread-first", scope: "1:1"), "Missing OCR is independent of primary speed admission")
        }
        XCTAssertTrue(gate.observe(parentID: "known-unread", primaryClassID: "maxspeed:60", speedKmh: 60, rawText: nil, scope: "1:1", knownPlate: true))
        XCTAssertTrue(gate.blocks("known-unread", scope: "1:1"), "An observed unread plate remains restrictive")
        XCTAssertFalse(gate.blocks("bei Nässe", scope: "1:2"))
        XCTAssertFalse(gate.observe(parentID: "secondary", primaryClassID: "warning:children", speedKmh: nil, rawText: "Schule", scope: "1:2"))
    }
    private let now=Date(timeIntervalSince1970:1792749600)
    private func observation(_ raw:String="Mo-Fr / 630-1730h",at:Date?=nil,frame:String="first",offset:Double=0) -> ConditionalOCRInterpretation.Observation {
        .init(physicalSignID:"physical",parentID:"parent",primaryClassID:"maxspeed:30",primarySpeedKmh:30,plateIDs:["plate"],frameID:frame,
            rawText:raw,capturedAt:(at ?? now).addingTimeInterval(offset),evidenceOriginAt:at ?? now,evidenceOriginDistanceM:100,countryCode:"DE",scopeID:"road:10:forward",
            scopeGeneration:1,pipelineID:"plate-ocr-v1",modelHash:String(repeating:"a",count:64),completeAssembly:true,exactAssociation:true,qualityAccepted:true)
    }
    private func verified(_ raw:String,at:Date?=nil) -> ConditionalOCRInterpretation.Record {
        var tracker=ConditionalOCRInterpretation.Tracker();let first=observation(raw,at:at)
        _=tracker.consume(first)
        let second=observation(raw,at:at,frame:"second",offset:0.2)
        return tracker.consume(second)
    }
    func testSharedTemplatesNeverDiscardResidualOrTruncatedText() throws {
        let root=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let bundled=Bundle(for:Self.self).url(forResource:"templates-v1",withExtension:"json",subdirectory:"conditional-ocr")
        let data=try Data(contentsOf:bundled ?? root.appendingPathComponent("shared/conditional-ocr/templates-v1.json"))
        let corpus=try XCTUnwrap(JSONSerialization.jsonObject(with:data) as? [String:Any])
        for item in try XCTUnwrap(corpus["cases"] as? [[String:Any]]) {
            let raw=try XCTUnwrap(item["raw"] as? String),parsed=ConditionalOCRInterpretation.parse(raw)
            guard let kind=item["kind"] as? String else { XCTAssertNil(parsed,raw);continue }
            switch kind {
            case "wet":XCTAssertEqual(parsed?.condition,.wet,raw)
            case "informational":XCTAssertEqual(parsed?.condition,.informational,raw)
            default:XCTAssertEqual(parsed?.condition,.schedule(weekdays:item["weekdays"] as? [Int] ?? [],startMinute:item["start_minute"] as? Int ?? -1,endMinute:item["end_minute"] as? Int ?? -1),raw)
            }
        }
    }
    func testAdmissionRequiresCompleteAssemblyAndTwoDistinctFramesAndHonorsSourceProhibition() {
        var tracker=ConditionalOCRInterpretation.Tracker(),first=observation()
        first.completeAssembly=false
        XCTAssertEqual(tracker.consume(first).verification,.candidate)
        first.completeAssembly=true
        XCTAssertEqual(tracker.consume(first).verification,.candidate)
        let same=observation(frame:"first",offset:0.2)
        XCTAssertEqual(tracker.consume(same).verification,.candidate)
        let second=observation(frame:"second",offset:0.4)
        let admitted=tracker.consume(second)
        XCTAssertEqual(admitted.verification,.verified)
        XCTAssertEqual(admitted.supportingFrameIDs,["first","second"])
        XCTAssertEqual(admitted.originalEvidenceAt,now)
        first.sourceEvaluationEnabled=false
        XCTAssertEqual(tracker.consume(first).reason,"source_evaluation_disabled")
    }
    func testWetnessRemainsUnknownAndEvidenceCannotOutliveScopeTimeOrDistance() {
        let record=verified("bei Nässe")
        XCTAssertEqual(record.verdict(at:now.addingTimeInterval(1),distanceM:101,scopeID:"road:10:forward",generation:1),.unresolved)
        XCTAssertEqual(record.verdict(at:now.addingTimeInterval(1),distanceM:101,scopeID:"road:10:forward",generation:1,roadSurfaceWet:true),.applicable)
        XCTAssertEqual(record.verdict(at:now.addingTimeInterval(1),distanceM:101,scopeID:"road:10:forward",generation:1,roadSurfaceWet:false),.inapplicable)
        XCTAssertEqual(record.verdict(at:now.addingTimeInterval(301),distanceM:101,scopeID:"road:10:forward",generation:1,roadSurfaceWet:true),.unresolved)
        XCTAssertEqual(record.verdict(at:now.addingTimeInterval(1),distanceM:5101,scopeID:"road:10:forward",generation:1,roadSurfaceWet:true),.unresolved)
        XCTAssertEqual(record.verdict(at:now.addingTimeInterval(1),distanceM:101,scopeID:"road:10:forward",generation:2,roadSurfaceWet:true),.unresolved)
    }
}

extension ConditionalOCRInterpretationTests {
    private var context: TrafficSignDetectionContext {
        .init(wayId:"101",latitude:48,longitude:8,headingDegrees:0,travelDirection:.forward,
            sourceSignature:.init(osmRevision:"fixture",localCorrectionRevision:nil,bundleSHA256:String(repeating:"a",count:64)),
            matchedWayStable:true)
    }
    private func pixelAnnotation(frame:String, at:Date, parent:String="live", raw:String?="12-13h", plain:Bool=false,
                                 wrongFrame:Bool=false, componentCount:Int=1) -> TrafficSignSupplementaryOCRAnnotation {
        let box=TrafficSignNormalizedRect(x:0.25,y:0.1,width:0.4,height:0.3)
        let sourceText=plain ? nil:raw
        let scan=TrafficSignPlateScan(status:plain ? .plain : .complete,
            union:plain ? nil : .init(x:10,y:135,width:140,height:60),
            components:plain ? [] : (0..<componentCount).map { .init(x:10,y:135+$0*65,width:140,height:60) },
            decision:plain ? "quiet_lower_context" : "bounded_complete_panels",lowerMinimum:plain ? 180:nil,lowerMaximum:plain ? 180:nil)
        let passes=sourceText.map { [TrafficSignOCRPass(text:$0,confidence:0.99,scale:1),.init(text:$0,confidence:0.99,scale:2)] } ?? []
        return .init(primaryClassID:"maxspeed:30",primarySpeedKmh:30,physicalSignID:parent,frameID:frame,
            sourceObservedAt:at,observedAt:at,firstSeenAt:at,rawText:sourceText,window:nil,readStatus:sourceText == nil ? .noText:.read,
            primaryBoundingBox:box,ocrBoundingBox:nil,engine:"fixture",modelVersion:"fixture",
            assemblyEvidence:.init(sourceWidth:400,sourceHeight:400,sourceFrameID:wrongFrame ? "other":frame,capturedAt:at,
                physicalSignID:parent,primaryBox:box,contextRect:.init(x:100,y:40,width:160,height:240),otherPrimaryBoxes:[],
                scan:scan,qualityDecision:"accepted",passes:passes))
    }
    private func liveEmission(_ annotation:TrafficSignSupplementaryOCRAnnotation, eventParent:String?=nil,
                              eventSpeed:Int=30, decision:TSRApplicabilityDecision?=nil,
                              condition:TrafficSignConditionState = .none,includeDecision:Bool=true,
                              eventFrame:String?=nil,eventAt:Date?=nil) -> TrafficSignRuntimeEmission {
        var event=TrafficSignRecognitionEvent(schemaVersion:1,packId:"fixture",artifactSha256:String(repeating:"a",count:64),
            preprocessingVersion:"fixture",frameId:eventFrame ?? annotation.frameID,driveSessionId:"fixture",analysisEligible:true,
            source:.liveFrame,frameTimestampUtc:eventAt ?? annotation.sourceObservedAt,state:.confirmed,
            candidate:.init(rawClassId:"maxspeed:\(eventSpeed)",rawLabel:String(eventSpeed),semanticKind:"maximum_speed",value:eventSpeed,
                unit:"km/h",rawScore:0.99,calibratedConfidence:nil,boundingBox:annotation.primaryBoundingBox,
                trackId:eventParent ?? annotation.physicalSignID,evidenceFrames:2,conditionState:condition),roadContext:context,latencyMs:0,thermalState:"nominal")
        event.applicabilityDecision=decision ?? .init(schemaVersion:1,policyVersion:TSRApplicabilityConfiguration.policyVersion,
            configHash:TSRApplicabilityConfiguration.configHash,frameId:annotation.frameID,
            trackId:eventParent ?? annotation.physicalSignID,
            scope:.init(sessionId:"fixture",bundleId:String(repeating:"a",count:64),cameraGeometryId:"fixture",generation:0,contextGeneration:0,traversalEpoch:0),
            roadSnapshotId:"fixture",classification:"LIKELY_EGO_CORRIDOR",reasons:[],evidence:[],imageSupport:1,
            displayEligible:true,immediateEligible:true,passageEligible:true)
        if !includeDecision { event.applicabilityDecision = nil }
        return .init(event:event,frameContext:context,ocrAttemptAnnotation:annotation,supplementaryOCROnly:true)
    }
    private func iso(_ value:String) -> Date { ISO8601DateFormatter().date(from:value)! }
    @MainActor func testUnmatchedPlateCompletionCannotBlockOrWithdrawNumericParent() {
        let start=iso("2026-10-23T10:00:00Z")
        let annotation=pixelAnnotation(frame:"source",at:start)
        let mismatched:[TrafficSignRuntimeEmission] = [
            liveEmission(annotation,eventParent:"different-parent"),
            liveEmission(annotation,eventSpeed:60),
            liveEmission(annotation,eventFrame:"different-frame"),
            liveEmission(annotation,eventAt:start.addingTimeInterval(0.1))
        ]
        for (index,emission) in mismatched.enumerated() {
            let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
            let id=emission.event.candidate!.trackId!
            model.testOfferIndependentCamera(id:id,speed:60)
            model.testMaskConditionalOCRParent(emission)
            XCTAssertEqual(model.speedLimitKmh,60,"Mismatched evidence \(index) cannot change its event's numeric parent")
            XCTAssertFalse(model.testConditionalOCRParentIsBlocked(id),"Mismatched evidence \(index) cannot latch a restriction")
        }
    }
    @MainActor func testPendingAndUnavailableOCRDoNotWithdrawConfirmedSixty() {
        let start=iso("2026-10-23T10:00:00Z")
        let source=pixelAnnotation(frame:"sixty",at:start)
        let event=liveEmission(source,eventSpeed:60).event
        for phase in [TrafficSignSupplementaryOCRPhase.notRequired,.pending] {
            let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
            model.testOfferIndependentCamera(id:"live",speed:60)
            model.testMaskConditionalOCRParent(.init(event:event,frameContext:context,ocrPhase:phase))
            XCTAssertEqual(model.speedLimitKmh,60,"A confirmed primary stays active while the plate task is \(phase)")
            XCTAssertFalse(model.testConditionalOCRParentIsBlocked("live"))
        }
    }
    @MainActor func testFourSecondOldPlateCompletionCannotWithdrawItsCurrentNumericParent() {
        let start=iso("2026-10-23T10:00:00Z")
        let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
        let source=pixelAnnotation(frame:"stalled-source",at:start)
        model.testMaskConditionalOCRParent(.init(event:liveEmission(source).event,frameContext:context))
        model.testOfferIndependentCamera(id:"live",speed:30)
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(4))
        XCTAssertEqual(model.speedLimitKmh,30)
        model.testMaskConditionalOCRParent(liveEmission(source))
        XCTAssertFalse(model.testConditionalOCRParentIsBlocked("live"),
            "Same-generation OCR must still satisfy the source-frame age limit")
        XCTAssertEqual(model.speedLimitKmh,30,"A stalled old plate task cannot retroactively withdraw its current primary")
    }
    private func dismissalEmission(at:Date,annotation:TrafficSignSupplementaryOCRAnnotation?=nil,
                                  supplementaryOnly:Bool=false) throws -> TrafficSignRuntimeEmission {
        let source=pixelAnnotation(frame:"independent-streams",at:at,parent:"numeric",raw:nil,plain:true)
        let base=liveEmission(source)
        let catalog=try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        var display=TrafficSignDisplayObservation(classID:"hazard:school",classifierScore:0.94,timestamp:at,
            affectsSpeed:false,classifierCheckpointSHA256:catalog.classifierCheckpointSHA256)
        let primaryDecision=try XCTUnwrap(base.event.applicabilityDecision)
        display.applicabilityDecision = .init(schemaVersion:primaryDecision.schemaVersion,
            policyVersion:primaryDecision.policyVersion,configHash:primaryDecision.configHash,
            frameId:primaryDecision.frameId,trackId:"secondary",scope:primaryDecision.scope,
            roadSnapshotId:primaryDecision.roadSnapshotId,classification:primaryDecision.classification,
            reasons:[],evidence:[],imageSupport:1,displayEligible:true,immediateEligible:true,passageEligible:true)
        return .init(event:base.event,frameContext:context,displayObservation:display,
            ocrPhase:annotation == nil ? .pending:.completed,ocrAnnotation:annotation,
            ocrAttemptAnnotation:annotation,supplementaryOCROnly:supplementaryOnly)
    }
    private func dismissalAnnotation(classID:String,speed:Int?,parent:String,at:Date,text:String) -> TrafficSignSupplementaryOCRAnnotation {
        .init(primaryClassID:classID,primarySpeedKmh:speed,physicalSignID:parent,frameID:"independent-streams",
            sourceObservedAt:at,observedAt:at,firstSeenAt:at,rawText:text,window:nil,readStatus:.read,
            primaryBoundingBox:pixelAnnotation(frame:"box",at:at).primaryBoundingBox,ocrBoundingBox:nil,
            engine:"fixture",modelVersion:"fixture")
    }
    @MainActor func testDismissedNumericParentDoesNotBlockNewSecondaryOrItsOwnSupplementaryText() throws {
        let at=Date().addingTimeInterval(-0.5)
        let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:at,context:context)
        let pictograms=model.trafficSignPictogramEnabled
        model.trafficSignPictogramEnabled=true
        defer {model.trafficSignPictogramEnabled=pictograms}
        model.testDismissTrafficSignTracks(["numeric"],at:at.addingTimeInterval(-0.2))
        model.testConsumeAdmittedTrafficSignRuntimeEmission(try dismissalEmission(at:at))
        XCTAssertEqual(model.trafficSignPictogram?.classID,"hazard:school",
            "A dismissed primary must not suppress a separately admitted secondary sign")
        XCTAssertNil(model.trafficSignRecognitionLastEvent,"The dismissed primary is not republished")
        XCTAssertEqual(model.speedLimitKmh,50)
        let secondary=dismissalAnnotation(classID:"hazard:school",speed:nil,parent:"secondary",at:at,text:"Schule")
        model.testConsumeAdmittedTrafficSignRuntimeEmission(try dismissalEmission(at:at,annotation:secondary,supplementaryOnly:true))
        XCTAssertEqual(model.trafficSignSupplementaryText?.physicalSignID,"secondary")
        let numeric=dismissalAnnotation(classID:"maxspeed:30",speed:30,parent:"numeric",at:at,text:"bei Nässe")
        model.testConsumeAdmittedTrafficSignRuntimeEmission(try dismissalEmission(at:at,annotation:numeric,supplementaryOnly:true))
        XCTAssertEqual(model.trafficSignSupplementaryText?.physicalSignID,"secondary",
            "The dismissed numeric parent's delayed text cannot replace independent secondary text")
    }
    @MainActor func testDismissedSecondaryDoesNotBlockPrimaryOrItsOwnSupplementaryText() throws {
        let at=Date().addingTimeInterval(-0.5)
        let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:at,context:context)
        let pictograms=model.trafficSignPictogramEnabled
        model.trafficSignPictogramEnabled=true
        defer {model.trafficSignPictogramEnabled=pictograms}
        model.testDismissTrafficSignTracks(["secondary"],at:at.addingTimeInterval(-0.2))
        model.testConsumeAdmittedTrafficSignRuntimeEmission(try dismissalEmission(at:at))
        XCTAssertEqual(model.trafficSignRecognitionLastEvent?.candidate?.trackId,"numeric")
        XCTAssertNil(model.trafficSignPictogram,"The dismissed secondary's own lane remains suppressed")
        let numeric=dismissalAnnotation(classID:"maxspeed:30",speed:30,parent:"numeric",at:at,text:"bei Nässe")
        model.testConsumeAdmittedTrafficSignRuntimeEmission(try dismissalEmission(at:at,annotation:numeric,supplementaryOnly:true))
        XCTAssertEqual(model.trafficSignSupplementaryText?.physicalSignID,"numeric",
            "Numeric supplementary text uses its own primary applicability and dismissal")
        let secondary=dismissalAnnotation(classID:"hazard:school",speed:nil,parent:"secondary",at:at,text:"Schule")
        model.testConsumeAdmittedTrafficSignRuntimeEmission(try dismissalEmission(at:at,annotation:secondary,supplementaryOnly:true))
        XCTAssertEqual(model.trafficSignSupplementaryText?.physicalSignID,"numeric")
    }
    @MainActor func testOlderParentPlateCompletionCannotWithdrawOrReplaceNewerCamera() {
        let start=iso("2026-10-23T10:00:00Z")
        let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
        let first=pixelAnnotation(frame:"old-first",at:start,parent:"old-parent")
        model.testMaskConditionalOCRParent(.init(event:liveEmission(first).event,frameContext:context))
        model.testOfferIndependentCamera(id:"old-parent",speed:30)
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(0.6))
        model.testOfferIndependentCamera(id:"newer-parent",speed:60)
        for annotation in [first,pixelAnnotation(frame:"old-second",at:start.addingTimeInterval(0.3),parent:"old-parent")] {
            model.testMaskConditionalOCRParent(liveEmission(annotation))
            XCTAssertEqual(model.speedLimitKmh,60,"A delayed older-parent restriction must leave the newer sign authoritative")
        }
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(1))
        XCTAssertEqual(model.speedLimitKmh,60,"Clock reevaluation cannot promote the older completed OCR over the newer parent")
    }
    func testLivePixelProofBindsFrameParentAndPlainAgreementScope() {
        let at=now
        XCTAssertEqual(ConditionalOCRInterpretation.assess(pixelAnnotation(frame:"a",at:at)),.conditional(ConditionalOCRInterpretation.parse("12-13h")!))
        if case .unresolved = ConditionalOCRInterpretation.assess(pixelAnnotation(frame:"a",at:at,wrongFrame:true)) {} else { XCTFail("Copied frame proof admitted") }
        var tracker=ConditionalOCRInterpretation.LiveTracker()
        func consume(_ annotation:TrafficSignSupplementaryOCRAnnotation,scope:String="scope") -> ConditionalOCRInterpretation.LiveResult {
            tracker.consume(annotation,originAt:at,originDistanceM:0,country:"DE",scopeID:scope,generation:0,pipelineID:"fixture",modelHash:"hash")
        }
        XCTAssertFalse(consume(pixelAnnotation(frame:"a",at:at,plain:true)).plain)
        XCTAssertFalse(consume(pixelAnnotation(frame:"b",at:at.addingTimeInterval(0.3),parent:"other",plain:true)).plain)
        XCTAssertFalse(consume(pixelAnnotation(frame:"c",at:at.addingTimeInterval(0.6),parent:"other",plain:true),scope:"new").plain)
        XCTAssertTrue(consume(pixelAnnotation(frame:"d",at:at.addingTimeInterval(0.9),parent:"other",plain:true),scope:"new").plain)
        _=consume(pixelAnnotation(frame:"e",at:at.addingTimeInterval(1),parent:"other"),scope:"new")
        XCTAssertFalse(consume(pixelAnnotation(frame:"f",at:at.addingTimeInterval(1.3),parent:"other",plain:true),scope:"new").plain)
    }
    @MainActor func testLiveControllerScheduleBoundaryUnknownAndNewerCameraSupersession() {
        let start=iso("2026-10-23T09:59:58Z") // Europe/Berlin 11:59:58
        let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
        model.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"a",at:start)))
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(0.3))
        model.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"b",at:start.addingTimeInterval(0.3))))
        XCTAssertEqual(model.speedLimitKmh,50,"Outside schedule keeps independent baseline")
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(2))
        XCTAssertEqual(model.speedLimitKmh,30,"Exact start activates verified camera: \(model.testConditionalOCRDiagnostics)")
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(300))
        XCTAssertEqual(model.speedLimitKmh,50,"Clock reevaluation must not renew original evidence")
        let newer=DriveSessionViewModel();newer.testConfigureLiveConditionalOCR(at:start,context:context)
        newer.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"c",at:start)))
        newer.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(0.3))
        newer.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"d",at:start.addingTimeInterval(0.3))))
        newer.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(1))
        newer.testOfferIndependentCamera(id:"newer-plain",speed:80)
        newer.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(2))
        XCTAssertEqual(newer.speedLimitKmh,80,"Older initially inactive condition cannot override a newer sign")
        let wrong=DriveSessionViewModel();wrong.testConfigureLiveConditionalOCR(at:start,context:context)
        for (index,parent,speed) in [(0,"unrelated",30),(1,"live",50)] {
            let at=start.addingTimeInterval(Double(index)*0.3)
            wrong.testReevaluateLiveConditionalOCR(at:at)
            wrong.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"wrong\(index)",at:at),eventParent:parent,eventSpeed:speed))
        }
        wrong.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(2))
        XCTAssertEqual(wrong.speedLimitKmh,50,"Wrong parent/class annotation never grants authority")
    }
    func testFramedBlankPixelsAndConflictingReadsNeverBecomePlain() {
        let width=160,height=240
        var bytes=[UInt8](repeating:90,count:width*height*4)
        for y in 0..<height { for x in 0..<width {
            let i=(y*width+x)*4; bytes[i+3]=255
            if (10..<150).contains(x) && (145..<210).contains(y) {
                let level:UInt8 = (x<13 || x>=147 || y<148 || y>=207) ? 10:230
                bytes[i]=level;bytes[i+1]=level;bytes[i+2]=level
            }
        } }
        let scan=TrafficSignPlateDetector.scan(width:width,height:height,rgba:bytes)
        XCTAssertEqual(scan.status,.unresolved)
        XCTAssertFalse(scan.components.isEmpty,"An empty framed plate must remain observed, never turn into plate absence")
        for y in 170..<185 { for x in 40..<100 { let i=(y*width+x)*4;bytes[i]=10;bytes[i+1]=10;bytes[i+2]=10 } }
        for y in 237..<240 { for x in 10..<150 { let i=(y*width+x)*4;bytes[i]=230;bytes[i+1]=230;bytes[i+2]=230 } }
        XCTAssertEqual(TrafficSignPlateDetector.scan(width:width,height:height,rgba:bytes).status,.unresolved,
            "A readable first panel must not hide a tiny clipped second panel")
        var tracker=ConditionalOCRInterpretation.LiveTracker()
        func consume(_ raw:String,_ frame:String,_ offset:Double) -> ConditionalOCRInterpretation.LiveResult {
            tracker.consume(pixelAnnotation(frame:frame,at:now.addingTimeInterval(offset),raw:raw),originAt:now,
                originDistanceM:0,country:"DE",scopeID:"scope",generation:0,pipelineID:"fixture",modelHash:"hash")
        }
        XCTAssertEqual(consume("12-13h","same",0).verification,.candidate)
        XCTAssertEqual(consume("12-13h","same",0.3).verification,.candidate,"Native/scaled OCR passes are not two captured frames")
        XCTAssertEqual(consume("13-14h","different",0.6).verification,.candidate,"Conflicting complete reads restart agreement")
    }
    @MainActor func testLiveControllerRejectsOppositeLaneAndDeferredKnownPlateCannotBecomeBare() {
        let start=iso("2026-10-23T10:00:00Z")
        let rejected=TSRApplicabilityDecision(schemaVersion:1,policyVersion:TSRApplicabilityConfiguration.policyVersion,
            configHash:TSRApplicabilityConfiguration.configHash,frameId:"a",trackId:"live",
            scope:.init(sessionId:"fixture",bundleId:String(repeating:"a",count:64),cameraGeometryId:"fixture",generation:0,contextGeneration:0,traversalEpoch:0),
            roadSnapshotId:"fixture",classification:"LIKELY_BRANCH",reasons:["side_road_ambiguous_sign"],evidence:[],imageSupport:1,
            displayEligible:false,immediateEligible:false,passageEligible:false)
        let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
        model.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"a",at:start),decision:rejected))
        model.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(0.3))
        model.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"b",at:start.addingTimeInterval(0.3)),decision:rejected))
        XCTAssertEqual(model.speedLimitKmh,50)
        let withdrawn=DriveSessionViewModel();withdrawn.testConfigureLiveConditionalOCR(at:start,context:context)
        for index in 0...1 {
            let at=start.addingTimeInterval(Double(index)*0.3)
            withdrawn.testReevaluateLiveConditionalOCR(at:at)
            withdrawn.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"good\(index)",at:at)))
        }
        XCTAssertEqual(withdrawn.speedLimitKmh,30)
        withdrawn.testReevaluateLiveConditionalOCR(at:start.addingTimeInterval(0.6))
        withdrawn.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"a",at:start.addingTimeInterval(0.6),raw:nil),decision:rejected))
        XCTAssertEqual(withdrawn.speedLimitKmh,50)
        let bareEvent=liveEmission(pixelAnnotation(frame:"after",at:start.addingTimeInterval(0.9))).event
        withdrawn.testMaskConditionalOCRParent(.init(event:bareEvent,frameContext:context))
        XCTAssertEqual(withdrawn.speedLimitKmh,50,"A later bare callback cannot revive the condition invalidated by an actual unread frame")
        let known=DriveSessionViewModel();known.testConfigureLiveConditionalOCR(at:start,context:context)
        let sample=pixelAnnotation(frame:"known",at:start)
        let event=liveEmission(sample,condition:.unresolved).event
        known.testMaskConditionalOCRParent(.init(event:event,frameContext:context))
        for index in 1...2 {
            let at=start.addingTimeInterval(Double(index)*0.3)
            known.testReevaluateLiveConditionalOCR(at:at)
            known.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"bare\(index)",at:at,plain:true)))
        }
        XCTAssertEqual(known.speedLimitKmh,50,"A known unread/deferred plate cannot be replaced by bare frames")
        let priorPlain=DriveSessionViewModel();priorPlain.testConfigureLiveConditionalOCR(at:start,context:context)
        for index in 0...1 {
            let at=start.addingTimeInterval(Double(index)*0.3)
            priorPlain.testReevaluateLiveConditionalOCR(at:at)
            priorPlain.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"plain\(index)",at:at,plain:true)))
        }
        priorPlain.testOfferIndependentCamera(id:"live",speed:30)
        XCTAssertEqual(priorPlain.speedLimitKmh,30)
        priorPlain.testMaskConditionalOCRParent(.init(event:event,frameContext:context))
        XCTAssertEqual(priorPlain.speedLimitKmh,50,"A newly observed deferred plate immediately invalidates prior plain admission")
    }
    func testFirstClearReadAfterGrowthGetsOneBoundedAgreementFollowup() throws {
        var tracker=TrafficSignSupplementaryTextTracker()
        let primary=TrafficSignSupplementaryTextTracker.Primary(classID:"maxspeed:30",speedKmh:30,
            box:pixelAnnotation(frame:"a",at:now).primaryBoundingBox,physicalSignID:"live")
        for index in 0...2 {
            let frame="attempt\(index)",at=now.addingTimeInterval(Double(index)*0.4)
            guard case .perform(let attempt)=tracker.begin(primary:primary,frameID:frame,at:at,confirmed:true,evidenceFrames:2,
                nativeROISize:.init(width:index<2 ? 100:180,height:index<2 ? 100:180)) else { XCTFail("Expected bounded attempt");return }
            let proof=pixelAnnotation(frame:frame,at:at)
            _=tracker.finish(attempt,read:.init(rawText:index<2 ? nil:"12-13h",modelVersion:"fixture",readStatus:index<2 ? .noText:.read),
                ocrBoundingBox:nil,assemblyEvidence:index<2 ? nil:proof.assemblyEvidence)
        }
        guard case .perform(let followup)=tracker.begin(primary:primary,frameID:"agreement",at:now.addingTimeInterval(1.2),
            confirmed:true,evidenceFrames:2,nativeROISize:.init(width:180,height:180)) else { XCTFail("Clearer first supported read needs one same-size confirmation");return }
        let proof=pixelAnnotation(frame:"agreement",at:now.addingTimeInterval(1.2))
        _=tracker.finish(followup,read:.init(rawText:"12-13h",modelVersion:"fixture",readStatus:.read),ocrBoundingBox:nil,assemblyEvidence:proof.assemblyEvidence)
        if case .perform = tracker.begin(primary:primary,frameID:"extra",at:now.addingTimeInterval(1.6),
            confirmed:true,evidenceFrames:2,nativeROISize:.init(width:180,height:180)) { XCTFail("Agreement must not create unbounded periodic reads") }
    }
    @MainActor func testPlainKeepsLegacyShadowEligibilityWhileConditionalRequiresPositiveDecision() {
        let start=iso("2026-10-23T10:00:00Z")
        for plain in [true,false] {
            let model=DriveSessionViewModel();model.testConfigureLiveConditionalOCR(at:start,context:context)
            for index in 0...1 {
                let at=start.addingTimeInterval(Double(index)*0.3)
                model.testReevaluateLiveConditionalOCR(at:at)
                model.testMaskConditionalOCRParent(liveEmission(pixelAnnotation(frame:"source\(index)",at:at,plain:plain),includeDecision:false))
            }
            XCTAssertEqual(model.testConditionalOCRParentIsBlocked("live"),!plain)
            XCTAssertEqual(model.speedLimitKmh,50,"Conditional without ego decision cannot use direct authority")
        }
        var annotation=pixelAnnotation(frame:"padding",at:start,plain:true)
        annotation.assemblyEvidence?.nativeContentRect = .init(x:150,y:0,width:250,height:400)
        if case .unresolved = ConditionalOCRInterpretation.assess(annotation) {} else { XCTFail("Padded pixels are not native absence evidence") }
        annotation.assemblyEvidence?.nativeContentRect = .init(x:100,y:0,width:300,height:400)
        if case .unresolved = ConditionalOCRInterpretation.assess(annotation) {} else { XCTFail("A primary touching the actual content border lacks its2px margin") }
        annotation.assemblyEvidence?.nativeContentRect = .init(x:0,y:0,width:400,height:280)
        if case .unresolved = ConditionalOCRInterpretation.assess(annotation) {} else { XCTFail("A context touching the actual content bottom lacks its2px margin") }
    }
    func testRepeatedConditionalChangesPreserveIndependentZoneOriginalExpiryAndVoice() throws {
        var clock=0.0
        let reference=SpeedReferenceRuntime(now:{clock})
        reference.context(way:"101",road:nil,relations:[],direction:"forward",stable:true)
        reference.bundle(id:"map",value:.init(kind:"numeric",kmh:50),applicability:["status":"applicable","context_revision":0,
            "conditions":["producer":"osm_bundle_conditional","rule_set":["version":1]]])
        reference.camera(id:"zone",value:.init(kind:"numeric",kmh:30),enclosing:true)
        reference.preserveObservedCameraOrigin(id:"conditional",elapsed:0,distance:0)
        for value:Int? in [10,nil,10,nil] {
            clock+=1
            _=reference.reevaluateObservedCamera(parentID:"conditional",value:value.map{.init(kind:"numeric",kmh:$0)},observedElapsedSeconds:0,observedDistanceMeters:0)
            XCTAssertEqual(reference.output?.baselineKmh,value ?? 30)
            XCTAssertEqual(reference.testBundleApplicability?["context_revision"] as? Int,reference.output?.applicabilityRevision)
            XCTAssertEqual((reference.testBundleApplicability?["conditions"] as? [String:Any])?["producer"] as? String,"osm_bundle_conditional")
        }
        clock=299
        _=reference.reevaluateObservedCamera(parentID:"conditional",value:.init(kind:"numeric",kmh:10),observedElapsedSeconds:0,observedDistanceMeters:0)
        clock=300;reference.tick()
        XCTAssertEqual(reference.output?.baselineKmh,30,"Expiry remains anchored at original sighting")
        reference.voice(id:"own",value:.init(kind:"numeric",kmh:70))
        XCTAssertNil(reference.reevaluateObservedCamera(parentID:"conditional",value:.init(kind:"numeric",kmh:10),observedElapsedSeconds:0,observedDistanceMeters:0))
        XCTAssertEqual(reference.output?.baselineKmh,70)
        clock=601;reference.tick()
        XCTAssertEqual(reference.output?.baselineKmh,50,"Voice expiry must not resurrect discarded cameras")
    }
    func testScheduleWeekdayOvernightExactEndAndDSTUseGermanWallClock() {
        let origin=iso("2026-10-23T19:59:59Z")
        let overnight=verified("Fr 22-6h",at:origin)
        XCTAssertEqual(overnight.verdict(at:origin,distanceM:100,scopeID:"road:10:forward",generation:1),.inapplicable)
        XCTAssertEqual(overnight.verdict(at:origin.addingTimeInterval(1),distanceM:100,scopeID:"road:10:forward",generation:1),.applicable)
        for (stamp,expected) in [("2026-10-24T04:00:00Z",ConditionalOCRInterpretation.Verdict.inapplicable),("2026-10-24T03:59:00Z",.applicable),
                                 ("2026-10-25T00:30:00Z",.applicable),("2026-10-25T01:30:00Z",.applicable)] {
            let at=iso(stamp),record=verified("22-6h",at:at)
            XCTAssertEqual(record.verdict(at:at,distanceM:100,scopeID:"road:10:forward",generation:1),expected)
        }
    }
}

final class TrafficSignNaturalBackgroundTests: XCTestCase {
    func testTexturedVegetationAllowsBareInspectionButPanelsAndDarknessDoNot() {
        let width=160,height=256
        var pixels=[UInt8](repeating:255,count:width*height*4)
        for y in 0..<height {for x in 0..<width {let i=(y*width+x)*4
            pixels[i]=UInt8(40+(x*13+y*17)%70);pixels[i+1]=UInt8(120+(x*11+y*7)%90);pixels[i+2]=UInt8(20+(x*5+y*23)%30)
        }}
        XCTAssertTrue(TrafficSignPlateDetector.naturalBackground(width:width,height:height,rgba:pixels))
        XCTAssertEqual(TrafficSignPlateDetector.scan(width:width,height:height,rgba:pixels).status,.plain)
        for y in 155..<195 {for x in 30..<130 {let i=(y*width+x)*4
            pixels[i]=230;pixels[i+1]=230;pixels[i+2]=230
        }}
        XCTAssertFalse(TrafficSignPlateDetector.naturalBackground(width:width,height:height,rgba:pixels),"An unread panel must not become a bare sign")
        XCTAssertNotEqual(TrafficSignPlateDetector.scan(width:width,height:height,rgba:pixels).status,.plain)
        XCTAssertFalse(TrafficSignPlateDetector.naturalBackground(width:width,height:height,rgba:[UInt8](repeating:0,count:width*height*4)))
        XCTAssertFalse(TrafficSignPlateDetector.naturalBackground(width:40,height:64,rgba:[UInt8](repeating:120,count:40*64*4)))
    }
}
