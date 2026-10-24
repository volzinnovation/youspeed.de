import XCTest
import ImageIO
import Vision
import CoreImage
import UIKit
import CryptoKit
@testable import SpeedConsumer

final class TrafficSignPlateRegressionTests: XCTestCase {
    func testSame32NativeCropsWithRealVision() throws {
        let root = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "tsr-ocr-32", withExtension: nil))
        let rows = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("manifest.json"))) as? [[String: Any]])
        XCTAssertEqual(rows.count, 32)
        TrafficSignOCRLanguageContext.configure(countryCode: "DE")
        let legacy = VNRecognizeTextRequest()
        legacy.recognitionLevel = .fast; legacy.recognitionLanguages = ["de-DE"]
        legacy.automaticallyDetectsLanguage = true; legacy.usesLanguageCorrection = false
        legacy.minimumTextHeight = 0; legacy.regionOfInterest = CGRect(x: 0,y: 0,width: 1,height: 0.5)
        var results = [[String: Any]]()
        for row in rows {
            let id = row["crop_id"] as! String
            let expected = row["expected"] as! [String: Any]
            let source = try XCTUnwrap(CGImageSourceCreateWithURL(root.appendingPathComponent(id + ".png") as CFURL, nil))
            let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
            let started = ProcessInfo.processInfo.systemUptime
            let read = try TrafficSignSupplementaryOCR.shared.read(in: image)
            let negative = expected["kind"] as? String != "text" || expected["small_ambiguous"] as? Bool == true
            if id == "7444ffc9-d750-5b2b-bf8e-a39951ad9f6a" { XCTAssertEqual(read.readStatus, .noText, "Clipped clause must not be presented") }
            if negative { XCTAssertEqual(read.readStatus, .noText, id) }
            if read.readStatus == .read {
                XCTAssertEqual(TrafficSignOCRQuality.comparison(read.rawText ?? ""),
                               TrafficSignOCRQuality.comparison(expected["expected_text"] as? String ?? ""), id)
            }
            if ["de47d0de-884f-5638-a31d-ea0dede1b643", "fabf2a14-f2c3-539f-9bd4-3385c40f0c0d"].contains(id) {
                XCTAssertEqual(read.readStatus, .read, id)
                XCTAssertEqual(read.window?.displayText, "22–6 h", id)
            }
            let elapsed = (ProcessInfo.processInfo.systemUptime-started)*1000
            let baselineStarted = ProcessInfo.processInfo.systemUptime
            try VNImageRequestHandler(cgImage: image, options: [:]).perform([legacy])
            let baseline = (legacy.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
            results.append(["baseline_text": baseline, "baseline_ms": (ProcessInfo.processInfo.systemUptime-baselineStarted)*1000,"crop_id": id, "raw_text": read.rawText as Any? ?? NSNull(), "status": read.readStatus.rawValue,
                "decision": read.decision, "plate": read.plateRect.map { [$0.x,$0.y,$0.width,$0.height] } as Any? ?? NSNull(),
                "passes": read.passes.map { ["text": $0.text,"confidence":$0.confidence,"scale":$0.scale,"uncovered_ink":$0.uncoveredInk] as [String:Any] },
                "milliseconds": elapsed])
        }
        XCTAssertGreaterThanOrEqual(results.filter { $0["status"] as? String == "read" }.count, 18, "Retain broad coverage while abstaining on uncertainty")
        let data = try JSONSerialization.data(withJSONObject: results, options: [.prettyPrinted,.sortedKeys])
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json"); attachment.name = "ocr-32-results"; attachment.lifetime = .keepAlways; add(attachment)
        try data.write(to: FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0].appendingPathComponent("ocr-32-results.json"))
    }
    func testActualNativeNightPlateProvidesCompleteLiveAssemblyProof() throws {
        let root = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "tsr-ocr-32", withExtension: nil))
        let source = try XCTUnwrap(CGImageSourceCreateWithURL(root.appendingPathComponent("fbc95839-71fc-540c-ae6b-041df195e07d.png") as CFURL,nil))
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source,0,nil))
        let box = TrafficSignNormalizedRect(x:10.0/177,y:10.0/326,width:151.0/177,height:150.0/326)
        let rect = try XCTUnwrap(TrafficSignSupplementaryOCRGeometry.cropRect(primaryBox:box,imageWidth:image.width,imageHeight:image.height))
        let crop = try XCTUnwrap(image.cropping(to:rect))
        TrafficSignOCRLanguageContext.configure(countryCode:"DE")
        let read = try TrafficSignSupplementaryOCR.shared.read(in:crop)
        let scan = try XCTUnwrap(read.scan)
        XCTAssertEqual(scan.status,.complete,"\(scan) / \(read)")
        XCTAssertEqual(read.readStatus,.read,"\(read)")
        XCTAssertEqual(read.window?.displayText,"22–6 h")
        let at = Date(timeIntervalSince1970:1792785600)
        var tracker = ConditionalOCRInterpretation.LiveTracker()
        for index in 0...1 {
            // Real native pixels prove the per-frame geometry/OCR path. These
            // fixture frame identities exercise agreement, not real capture timing.
            let frame = "real-crop-test-\(index)", captured = at.addingTimeInterval(Double(index)*0.3)
            let annotation = TrafficSignSupplementaryOCRAnnotation(primaryClassID:"maxspeed:30",primarySpeedKmh:30,
                physicalSignID:"fixture-parent",frameID:frame,sourceObservedAt:captured,observedAt:captured,firstSeenAt:at,
                rawText:read.rawText,window:read.window,readStatus:read.readStatus,primaryBoundingBox:box,ocrBoundingBox:nil,
                engine:"apple_vision",modelVersion:read.modelVersion,
                assemblyEvidence:.init(sourceWidth:image.width,sourceHeight:image.height,sourceFrameID:frame,capturedAt:captured,
                    physicalSignID:"fixture-parent",primaryBox:box,
                    contextRect:.init(x:Int(rect.minX),y:Int(rect.minY),width:Int(rect.width),height:Int(rect.height)),
                    otherPrimaryBoxes:[],scan:scan,qualityDecision:read.decision,passes:read.passes))
            guard case .conditional = ConditionalOCRInterpretation.assess(annotation) else { XCTFail("Actual complete OCR pixels rejected: \(read)"); return }
            let result = tracker.consume(annotation,originAt:at,originDistanceM:0,country:"DE",scopeID:"road:101",generation:0,
                pipelineID:"fixture",modelHash:String(repeating:"a",count:64))
            XCTAssertEqual(result.verification,index == 0 ? .candidate:.verified)
        }
    }
    @MainActor func testActualFullSceneCoreMLDetectorNativeOCRAndCompleteProof() throws {
        let root = try XCTUnwrap(Bundle(for:Self.self).url(forResource:"tsr-ocr-32",withExtension:nil))
        let directory = try DriveSessionViewModel.trafficSignModelPackDirectoryURL(bundle:.main)
        let pack = try TrafficSignModelPackDirectoryLoader.load(from:directory,
            runtimeVersion:UIDevice.current.systemVersion,appVersion:"1.5",countryCode:"DE")
        let backend = try TrafficSignVisionTwoStageCoreMLBackend(verifiedPack:pack,computeUnits:.cpuOnly)
        let context = CIContext(options:[.cacheIntermediates:false])
        let originals = [
            ("baa81e7c-8bfc-49d0-bca5-f39c1dfe21cc","d82de8d0af882633d586459dac74e4ddaa284986a5951fce40fba5115734f7ad"),
            ("0c6575e7-36c3-4468-a6d0-e709485176df","425c9479a9411cf54e162e62971c25227ec9155d1a7a5c98e7d4aee901165112")]
        var rows = [[String:Any]](), verified = 0
        TrafficSignOCRLanguageContext.configure(countryCode:"DE")
        for (id,sha) in originals {
            let data = try Data(contentsOf:root.appendingPathComponent("source-scenes/\(id).jpg"))
            XCTAssertEqual(SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined(),sha)
            let image = try XCTUnwrap(UIImage(data:data)?.cgImage)
            XCTAssertEqual(image.width,4224);XCTAssertEqual(image.height,2376)
            let source = CIImage(cgImage:image)
            let window = try TrafficSignDetectorInput(source:source,orientation:.up,context:context)
            let detections = try backend.detections(in:window.image,orientation:.up)
            let selected = detections.filter { $0.rawClassId == "maxspeed:30" && $0.rawScore >= max($0.classThreshold,pack.manifest.thresholds.confirmed) }
                .max { $0.rawScore < $1.rawScore }
            guard let parent = selected else {
                rows.append(["picture_id":id,"sha256":sha,"stage":"no_confirmed_30_parent",
                    "detections":detections.map { ["class":$0.rawClassId,"score":$0.rawScore,"box":[$0.boundingBox.x,$0.boundingBox.y,$0.boundingBox.width,$0.boundingBox.height]] }]);continue
            }
            let native = TrafficSignDetectorInput.nativeWindow(source:source,orientation:.up)
            let size = Int(native.extent.height), box = parent.boundingBox
            guard let rect = TrafficSignSupplementaryOCRGeometry.cropRect(primaryBox:box,imageWidth:size,imageHeight:size),
                  let crop = context.createCGImage(native,from:CGRect(x:rect.minX,y:native.extent.maxY-rect.maxY,width:rect.width,height:rect.height)) else {
                rows.append(["picture_id":id,"sha256":sha,"stage":"native_context_unavailable"]);continue
            }
            let read = try TrafficSignSupplementaryOCR.shared.read(in:crop)
            guard let scan = read.scan else { XCTFail("Actual pixel scan missing");continue }
            let at = Date(timeIntervalSince1970:1792785600)
            var tracker = ConditionalOCRInterpretation.LiveTracker(), last:ConditionalOCRInterpretation.LiveResult?
            var assessment = "unresolved"
            for index in 0...1 {
                // Original full-scene detector/plate/OCR pixels are real. Frame
                // identities/times are controlled agreement inputs, not a road recording.
                let frame="full-scene-\(id)-\(index)",captured=at.addingTimeInterval(Double(index)*0.4)
                let annotation=TrafficSignSupplementaryOCRAnnotation(primaryClassID:parent.rawClassId,primarySpeedKmh:30,
                    physicalSignID:"full-scene-parent-\(id)",frameID:frame,sourceObservedAt:captured,observedAt:captured,firstSeenAt:at,
                    rawText:read.rawText,window:read.window,readStatus:read.readStatus,primaryBoundingBox:box,ocrBoundingBox:nil,
                    engine:"apple_vision",modelVersion:read.modelVersion,
                    assemblyEvidence:.init(sourceWidth:size,sourceHeight:size,sourceFrameID:frame,capturedAt:captured,
                        physicalSignID:"full-scene-parent-\(id)",primaryBox:box,
                        contextRect:.init(x:Int(rect.minX),y:Int(rect.minY),width:Int(rect.width),height:Int(rect.height)),
                        otherPrimaryBoxes:detections.map(\.boundingBox).filter { $0 != box },scan:scan,
                        qualityDecision:read.decision,passes:read.passes,nativeContentRect:.init(x:0,y:0,width:size,height:size)))
                if case .conditional = ConditionalOCRInterpretation.assess(annotation) { assessment="conditional" }
                last=tracker.consume(annotation,originAt:at,originDistanceM:0,country:"DE",scopeID:"controlled-road",generation:0,
                    pipelineID:pack.manifest.packId,modelHash:pack.detectorArtifact.sha256)
            }
            if last?.verification == .verified { verified += 1 }
            rows.append(["picture_id":id,"sha256":sha,"stage":"actual_detector_native_ocr",
                "parent_box":[box.x,box.y,box.width,box.height],"parent_score":parent.rawScore,
                "native_context":[Int(rect.minX),Int(rect.minY),Int(rect.width),Int(rect.height)],"scan_status":scan.status.rawValue,
                "scan_reason":scan.decision,"paper_components":scan.components.map { [$0.x,$0.y,$0.width,$0.height] },
                "raw_text":read.rawText as Any? ?? NSNull(),"ocr_decision":read.decision,
                "passes":read.passes.map { ["text":$0.text,"confidence":$0.confidence,"scale":$0.scale,"uncovered_ink":$0.uncoveredInk] },
                "assessment":assessment,"verification":last?.verification.rawValue ?? "missing","reason":last?.reason ?? "missing"])
        }
        let report = try JSONSerialization.data(withJSONObject:["source":"unmodified_shared_full_scene_originals","controlled_frame_identities":true,
            "server_annotations_used_for_authority":false,"verified_scene_count":verified,"cases":rows],options:[.prettyPrinted,.sortedKeys])
        let attachment=XCTAttachment(data:report,uniformTypeIdentifier:"public.json");attachment.name="full-scene-coreml-ocr-proof";attachment.lifetime = .keepAlways;add(attachment)
        try report.write(to:FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("full-scene-coreml-ocr-proof.json"))
        print(String(data:report,encoding:.utf8)!)
        XCTAssertGreaterThanOrEqual(verified,1,"At least one unmodified original must pass the actual canonical CoreML detector, native OCR and strict complete proof")
    }
    func testHourRangeWithoutUnitRemainsPresentationEvidence() {
        XCTAssertEqual(TrafficSignOCRQuality.decision(passes: [.init(text: "22-6",confidence: 0.5,scale: 1),.init(text: "22–6",confidence: 0.5,scale: 2)],nativeWidth: 120), "accepted")
        XCTAssertNotEqual(TrafficSignOCRQuality.decision(passes: [.init(text: "30",confidence: 1,scale: 1),.init(text: "30",confidence: 1,scale: 2)],nativeWidth: 120), "accepted")
    }
    func testRejectedRawTextRemainsEvidenceWithoutParsedWindow() {
        let read = TrafficSignSupplementaryOCRRead(rawText: "22-6 h", modelVersion: "test", readStatus: .noText)
        XCTAssertEqual(read.rawText, "22-6 h"); XCTAssertNil(read.window)
        XCTAssertEqual(TrafficSignOCRQuality.decision(passes: [.init(text: "22-6h", confidence: 1, scale: 1), .init(text: "22-8h", confidence: 1, scale: 2)], nativeWidth: 120), "numeric_disagreement")
        let native = TrafficSignOCRPass(text: "Lärmschutz", confidence: 0.75, scale: 1)
        XCTAssertEqual(TrafficSignOCRQuality.selected([native,.init(text: "Larmschutz",confidence: 0.76,scale: 2)]), native)
        XCTAssertEqual(TrafficSignOCRQuality.decision(passes: [.init(text: "Unfall",confidence: 0.9,scale: 2,uncoveredInk: true)],nativeWidth: 180), "incomplete_plate")
        XCTAssertNotEqual(TrafficSignOCRQuality.decision(passes: [.init(text: "r>", confidence: 1, scale: 2)], nativeWidth: 100), "accepted")
    }
}
