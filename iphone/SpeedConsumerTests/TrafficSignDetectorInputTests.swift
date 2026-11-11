import XCTest
import CoreImage
import ImageIO
import UIKit
import CoreML
@testable import SpeedConsumer

final class TrafficSignDetectorInputTests: XCTestCase {
    private let context = CIContext(options: [.cacheIntermediates: false])

    @MainActor
    func testGermanTownFacesRejectPhotographedDirectionSigns() throws {
        struct Case: Decodable { let file: String; let x: Double; let y: Double; let width: Double; let height: Double }
        let directory = try DriveSessionViewModel.trafficSignModelPackDirectoryURL(bundle: .main)
        let baseline = try TrafficSignModelPackDirectoryLoader.load(from: directory,
            runtimeVersion: UIDevice.current.systemVersion, appVersion: "1.5", countryCode: "DE")
        let backend = try TrafficSignRuntimeBootstrap.townTrial(baseline, countryCode: "DE")?.1
            ?? TrafficSignVisionTwoStageCoreMLBackend(verifiedPack: baseline)
        let bundle = Bundle(for: Self.self)
        let manifest = try XCTUnwrap(bundle.url(forResource: "cases", withExtension: "json", subdirectory: "tsr-town-face"))
        for sample in try JSONDecoder().decode([Case].self, from: Data(contentsOf: manifest)) {
            let url = try XCTUnwrap(bundle.url(forResource: sample.file, withExtension: nil, subdirectory: "tsr-town-face"))
            let image = try XCTUnwrap(CIImage(contentsOf: url))
            let box = CGRect(x: sample.x, y: 1 - sample.y - sample.height, width: sample.width, height: sample.height)
            for exit in [false, true] {
                XCTAssertFalse(TrafficSignVisionTwoStageCoreMLBackend.matchesTownFace(
                    source: image, context: context, box: box, townExit: exit), sample.file)
            }
            let result = try backend.shadowInference(source: image, orientation: .up, context: context)
            XCTAssertFalse(result.legacyDetections.contains { ["city:start", "city:end"].contains($0.rawClassId) }, sample.file)
            print("Town direction test \(sample.file): \(result.legacyDetections.map(\.rawClassId))")
        }
        for code in [310, 311] {
            let url = try XCTUnwrap(Bundle.main.url(forResource: "de-\(code)", withExtension: "png",
                                                    subdirectory: "sign-pictograms/png"))
            let image = try XCTUnwrap(CIImage(contentsOf: url))
            let box = CGRect(x: 0, y: 0, width: 1, height: 1)
            XCTAssertTrue(TrafficSignVisionTwoStageCoreMLBackend.matchesTownFace(
                source: image, context: context, box: box, townExit: code == 311))
            XCTAssertFalse(TrafficSignVisionTwoStageCoreMLBackend.matchesTownFace(
                source: image, context: context, box: box, townExit: code != 311))
        }
    }

    func testTownExitCropPreservesStrikeDirectionAndIgnoresWhiteOutsideBox() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "de-311", withExtension: "png",
                                                subdirectory: "sign-pictograms/png"))
        let image = try XCTUnwrap(CIImage(contentsOf: url))
        let w = image.extent.width, h = image.extent.height
        let frame = CGRect(x: 0, y: 0, width: w * 2, height: h * 3)
        let sign = image.transformed(by: CGAffineTransform(translationX: w / 2, y: h * 2))
        let source = sign.composited(over: CIImage(color: CIColor(red: 1, green: 1, blue: 1)).cropped(to: frame))
        let box = CGRect(x: 0.25, y: 2.0 / 3, width: 0.5, height: 1.0 / 3)
        XCTAssertTrue(TrafficSignVisionTwoStageCoreMLBackend.matchesTownFace(
            source: source, context: context, box: box, townExit: true))
        XCTAssertFalse(TrafficSignVisionTwoStageCoreMLBackend.matchesTownFace(
            source: source, context: context, box: box, townExit: false))
    }

    func testTwoEdgeWindowsMapAndMergeOverlappingSourceProposals() throws {
        let windows = TrafficSignDetectorGeometry.twoEdgeWindows(width: 1920, height: 1080)
        XCTAssertEqual(windows.map(\.minX), [0, 840])
        let left = TrafficSignDetectorGeometry(sourceWidth: 1920, sourceHeight: 1080, sourceWindow: windows[0])
        let right = TrafficSignDetectorGeometry(sourceWidth: 1920, sourceHeight: 1080, sourceWindow: windows[1])
        let a = try XCTUnwrap(left.sourceRegion(for: CGRect(x: 900.0 / 1080, y: 0.2, width: 0.05, height: 0.1)))
        let b = try XCTUnwrap(right.sourceRegion(for: CGRect(x: 60.0 / 1080, y: 0.2, width: 0.05, height: 0.1)))
        XCTAssertEqual(a.minX, b.minX, accuracy: 1e-9)
        let merged = TrafficSignVisionTwoStageCoreMLBackend.mergedProposals([(0.9, a), (0.85, b)])
        XCTAssertEqual(merged.count, 1)
        XCTAssertEqual(merged.first?.confidence, 0.9)
        XCTAssertEqual(TrafficSignDetectorGeometry.twoEdgeWindows(width: 1080, height: 1920).count, 1)
        XCTAssertEqual(TrafficSignDetectorGeometry.twoEdgeWindows(width: 3000, height: 1000).count, 3)
    }

    @MainActor
    func testPhysicalIPhoneTownTwoWindowLatency() throws {
#if targetEnvironment(simulator)
        throw XCTSkip("Town detector latency requires the attached iPhone")
#else
        let directory = try DriveSessionViewModel.trafficSignModelPackDirectoryURL(bundle: .main)
        let baseline = try TrafficSignModelPackDirectoryLoader.load(from: directory,
            runtimeVersion: UIDevice.current.systemVersion, appVersion: "1.5", countryCode: "DE")
        let referenceURL = try XCTUnwrap(Bundle(for: Self.self).url(
            forResource: "tsr-panoramax-0906fc23", withExtension: "jpg"))
        let reference = try XCTUnwrap(UIImage(data: Data(contentsOf: referenceURL))?.cgImage)
        let scale = min(1920.0 / Double(reference.width), 1080.0 / Double(reference.height))
        let width = Double(reference.width) * scale, height = Double(reference.height) * scale
        let square = CGRect(x: 0, y: 0, width: 1920, height: 1080)
        let gray = CGFloat(114.0 / 255)
        let background = CIImage(color: CIColor(red: gray, green: gray, blue: gray)).cropped(to: square)
        let pixels = CIImage(cgImage: reference).transformed(by: CGAffineTransform(scaleX: scale, y: scale))
            .transformed(by: CGAffineTransform(translationX: (1920 - width) / 2, y: (1080 - height) / 2))
        let image = try XCTUnwrap(CIContext().createCGImage(pixels.composited(over: background), from: square))
        var measurements: [String: Any] = [:]
        for dual in [false, true] {
            let (_, backend) = try XCTUnwrap(TrafficSignRuntimeBootstrap.townTrial(baseline,
                countryCode: "DE", useTwoDetectorWindows: dual))
            var samples: [[String: Any]] = []
            for iteration in 0..<8 {
                let start = ProcessInfo.processInfo.systemUptime
                let result = try backend.shadowInference(in: image, orientation: .up)
                let elapsed = (ProcessInfo.processInfo.systemUptime - start) * 1000
                XCTAssertTrue(elapsed.isFinite && elapsed > 0)
                if iteration >= 3 {
                    samples.append(["total_ms": elapsed, "detector_ms": result.detectorLatencyMs,
                                    "classifier_ms": result.classifierLatencyMs,
                                    "detections": result.legacyDetections.count])
                }
            }
            measurements[dual ? "dual" : "single"] = samples
        }
        let report: [String: Any] = ["device": UIDevice.current.model, "source_width": image.width,
            "source_height": image.height, "classifier_compute_units": "all",
            "detector_compute_units": "cpuAndNeuralEngine", "measurements": measurements]
        let documents = try XCTUnwrap(FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first)
        try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys, .prettyPrinted])
            .write(to: documents.appendingPathComponent("reviewed142-dual-window-latency.json"), options: .atomic)
#endif
    }

    @MainActor
    func testBundledCoreMLRunsAt1024AndClassifiesFullFrameReferences() throws {
        let directory = try DriveSessionViewModel.trafficSignModelPackDirectoryURL(bundle: .main)
        let pack = try TrafficSignModelPackDirectoryLoader.load(from: directory,
            runtimeVersion: UIDevice.current.systemVersion, appVersion: "1.4", countryCode: "DE")
        let configuration = MLModelConfiguration(); configuration.computeUnits = .cpuOnly
        let model = try MLModel(contentsOf: pack.detectorArtifactURL, configuration: configuration)
        let input = try XCTUnwrap(model.modelDescription.inputDescriptionsByName["image"]?.imageConstraint)
        XCTAssertEqual(input.pixelsWide, 1024); XCTAssertEqual(input.pixelsHigh, 1024)
        let backend = try TrafficSignVisionTwoStageCoreMLBackend(verifiedPack: pack, computeUnits: .cpuOnly)
        for name in ["tsr-panoramax-0906fc23", "tsr-panoramax-49e25e66"] {
            let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "jpg"))
            let image = try XCTUnwrap(UIImage(data: Data(contentsOf: url))?.cgImage)
            let frame = try TrafficSignDetectorInput(source: CIImage(cgImage: image), orientation: .up, context: context)
            let detections = try backend.shadowInference(in: frame).legacyDetections
            print("1024 reference \(name): source=\(image.width)x\(image.height), detections=\(detections.map { "\($0.rawClassId):\($0.rawScore)" })")
            if name == "tsr-panoramax-0906fc23" {
                XCTAssertTrue(detections.contains {
                    $0.semantic.value == 70 && $0.rawScore >= pack.manifest.thresholds.confirmed
                }, name)
            } else {
                // At 1024 the distant fixture is below confirmation, and its
                // top class varies between simulator and physical iPhone.
                // Require the clear reference above; never accept a confident
                // wrong speed on this diagnostic reference.
                XCTAssertFalse(detections.contains {
                    $0.semantic.value != 70 && $0.rawScore >= pack.manifest.thresholds.confirmed
                }, "Distant reference must not confirm an incorrect class: \(name)")
            }
        }
    }

    func testFullFrameFitsForEveryEXIFOrientation() throws {
        let green = CIImage(color: CIColor(red: 0, green: 1, blue: 0))
            .cropped(to: CGRect(x: 1680, y: 0, width: 1080, height: 2160))
        let blue = CIImage(color: CIColor(red: 0, green: 0, blue: 1))
            .cropped(to: CGRect(x: 2760, y: 0, width: 1080, height: 2160))
        let yellow = CIImage(color: CIColor(red: 1, green: 1, blue: 0))
            .cropped(to: CGRect(x: 0, y: 1944, width: 3840, height: 216))
        let red = CIImage(color: CIColor(red: 1, green: 0, blue: 0))
            .cropped(to: CGRect(x: 0, y: 0, width: 3840, height: 2160))
        let upright = yellow.composited(over: blue.composited(over: green.composited(over: red)))
        for value: UInt32 in 1...8 {
            let orientation = try XCTUnwrap(CGImagePropertyOrientation(rawValue: value))
            let inverse = value == 6 ? 8 : value == 8 ? 6 : value
            let source = upright.oriented(forExifOrientation: Int32(inverse))
            let input = try TrafficSignDetectorInput(source: source, orientation: orientation, context: context)
            XCTAssertEqual(input.image.width, 1024)
            XCTAssertEqual(input.image.height, 1024)
            XCTAssertEqual(input.geometry.scaledWidth, 1024, accuracy: 1e-9)
            assertPixel(input.image, x: 100, y: 500, rgb: [255, 0, 0])
            assertPixel(input.image, x: 550, y: 500, rgb: [0, 255, 0])
            assertPixel(input.image, x: 900, y: 500, rgb: [0, 0, 255])
            assertPixel(input.image, x: 100, y: 780, rgb: [255, 255, 0])
            assertPixel(input.image, x: 100, y: 240, rgb: [255, 0, 0])
            assertPixel(input.image, x: 100, y: 1000, rgb: [114, 114, 114])
            assertPixel(input.image, x: 100, y: 0, rgb: [114, 114, 114])
        }
    }

    func testPortraitIsCenteredAndPaddedWithoutStretching() throws {
        let source = CIImage(color: CIColor(red: 0, green: 1, blue: 0))
            .cropped(to: CGRect(x: 0, y: 0, width: 640, height: 1280))
        let input = try TrafficSignDetectorInput(source: source, orientation: .up, context: context)
        assertPixel(input.image, x: 100, y: 500, rgb: [114, 114, 114])
        assertPixel(input.image, x: 600, y: 500, rgb: [0, 255, 0])
        assertPixel(input.image, x: 900, y: 500, rgb: [114, 114, 114])
        XCTAssertEqual(input.geometry.left, 256)
    }

    func testResolutionIndependentGeometryAndUpscaling() {
        for (width, height) in [(3840, 2160), (1920, 1080), (1280, 720), (640, 360)] {
            let geometry = TrafficSignDetectorGeometry(sourceWidth: width, sourceHeight: height)
            XCTAssertEqual(geometry.scaledWidth, 1024, accuracy: 1e-9)
            XCTAssertEqual(geometry.scaledHeight, 576, accuracy: 1e-9)
            XCTAssertEqual(geometry.bottom, 224, accuracy: 1e-9)
        }
        XCTAssertEqual(TrafficSignDetectorGeometry(sourceWidth: 1024, sourceHeight: 1024).left, 0)
    }

    func testNativeSourceKeepsFullResolution() throws {
        let background = CIImage(color: CIColor(red: 0, green: 1, blue: 0))
            .cropped(to: CGRect(x: 0, y: 0, width: 3840, height: 2160))
        let edge = CIImage(color: CIColor(red: 1, green: 0, blue: 0))
            .cropped(to: CGRect(x: 3839, y: 0, width: 1, height: 2160))
        let source = TrafficSignDetectorInput.upright(source: edge.composited(over: background), orientation: .up)
        let image = try XCTUnwrap(context.createCGImage(source, from: source.extent))
        XCTAssertEqual(image.width, 3840)
        XCTAssertEqual(image.height, 2160)
        assertPixel(image, x: 0, y: 500, rgb: [0, 255, 0])
        assertPixel(image, x: 3839, y: 500, rgb: [255, 0, 0])
    }

    func testLetterboxRemapsLeftEdgeAndDiscardsPadding() throws {
        let geometry = TrafficSignDetectorGeometry(sourceWidth: 1920, sourceHeight: 1080)
        let region = try XCTUnwrap(geometry.sourceRegion(for: CGRect(x: 0.05, y: 0.125, width: 0.125, height: 0.25)))
        XCTAssertEqual(region.minX, 0.05, accuracy: 1e-9)
        XCTAssertEqual(region.minY, 0, accuracy: 1e-9)
        XCTAssertEqual(region.width, 0.125, accuracy: 1e-9)
        XCTAssertEqual(region.height, 5.0 / 18, accuracy: 1e-9)
        XCTAssertNil(geometry.sourceRegion(for: CGRect(x: 0.05, y: 0, width: 0.125, height: 0.125)))
    }

    private func assertPixel(_ image: CGImage, x: Int, y: Int, rgb: [UInt8], file: StaticString = #filePath, line: UInt = #line) {
        var pixel = [UInt8](repeating: 0, count: 4)
        context.render(CIImage(cgImage: image), toBitmap: &pixel, rowBytes: 4,
            bounds: CGRect(x: x, y: y, width: 1, height: 1), format: .RGBA8,
            colorSpace: CGColorSpace(name: CGColorSpace.sRGB))
        for index in 0..<3 {
            XCTAssertLessThanOrEqual(abs(Int(pixel[index]) - Int(rgb[index])), 2, file: file, line: line)
        }
    }
}
