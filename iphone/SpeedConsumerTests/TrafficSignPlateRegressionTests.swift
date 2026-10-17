import XCTest
import ImageIO
import Vision
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
