import XCTest
import CoreImage
import ImageIO
import UIKit
import CoreML
@testable import SpeedConsumer

final class TrafficSignDetectorInputTests: XCTestCase {
    private let context = CIContext(options: [.cacheIntermediates: false])

    @MainActor
    func testBundledCoreMLRunsAt1024AndClassifiesReferenceWindows() throws {
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
            let window = try TrafficSignDetectorInput(source: CIImage(cgImage: image), orientation: .up, context: context)
            let detections = try backend.detections(in: window.image, orientation: .up)
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

    func testRightmostWindowPreservesFullHeightForEveryEXIFOrientation() throws {
        // At 4K, the retained original columns are 1680..<3840.
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
            XCTAssertEqual(input.geometry.scaledWidth, 1820.4444444444443, accuracy: 1e-9)
            assertPixel(input.image, x: 100, y: 500, rgb: [0, 255, 0])
            assertPixel(input.image, x: 900, y: 500, rgb: [0, 0, 255])
            assertPixel(input.image, x: 100, y: 1000, rgb: [255, 255, 0])
            assertPixel(input.image, x: 100, y: 0, rgb: [0, 255, 0])
        }
    }

    func testPortraitIsRightAlignedAndPaddedWithoutStretching() throws {
        let source = CIImage(color: CIColor(red: 0, green: 1, blue: 0))
            .cropped(to: CGRect(x: 0, y: 0, width: 640, height: 1280))
        let input = try TrafficSignDetectorInput(source: source, orientation: .up, context: context)
        assertPixel(input.image, x: 100, y: 500, rgb: [114, 114, 114])
        assertPixel(input.image, x: 600, y: 500, rgb: [0, 255, 0])
        XCTAssertEqual(input.geometry.left, -512)
    }

    func testResolutionIndependentGeometryAndUpscaling() {
        for (width, height) in [(3840, 2160), (1920, 1080), (1280, 720), (640, 360)] {
            let geometry = TrafficSignDetectorGeometry(sourceWidth: width, sourceHeight: height)
            XCTAssertEqual(geometry.scaledWidth, 16384.0 / 9, accuracy: 1e-9)
            XCTAssertEqual(geometry.left, 7168.0 / 9, accuracy: 1e-9)
        }
        XCTAssertEqual(TrafficSignDetectorGeometry(sourceWidth: 1024, sourceHeight: 1024).left, 0)
    }

    func testUploadWindowKeepsNativePixelsWithoutScaling() throws {
        let background = CIImage(color: CIColor(red: 0, green: 1, blue: 0))
            .cropped(to: CGRect(x: 0, y: 0, width: 3840, height: 2160))
        let edge = CIImage(color: CIColor(red: 1, green: 0, blue: 0))
            .cropped(to: CGRect(x: 3839, y: 0, width: 1, height: 2160))
        let window = TrafficSignDetectorInput.nativeWindow(source: edge.composited(over: background), orientation: .up)
        let image = try XCTUnwrap(context.createCGImage(window, from: window.extent))
        XCTAssertEqual(image.width, 2160)
        XCTAssertEqual(image.height, 2160)
        assertPixel(image, x: 2158, y: 500, rgb: [0, 255, 0])
        assertPixel(image, x: 2159, y: 500, rgb: [255, 0, 0])
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
