import XCTest
@testable import SpeedConsumer

final class RoadBoundaryDetectorTests: XCTestCase {
    private let detector = RoadBoundaryDetector()

    // Same deterministic fixtures and assertions as RoadBoundaryDetectorTests.kt.
    private func scene(_ kind: String, width: Int = 384, height: Int = 216) -> [UInt8] {
        var image = [UInt8](repeating: 55, count: width * height)
        for y in 0..<height {
            let ny = Double(y) / Double(height - 1)
            if ny < 0.49 || ny > 0.96 { continue }
            let t = (ny - 0.50) / 0.44
            let bend = kind == "curve" ? 0.18 * (1 - t) * (1 - t) : 0.0
            let targets: [Double]
            if kind == "fork" { targets = [0.38 - 0.24 * t, 0.50, 0.62 + 0.24 * t] }
            else if kind == "facade" { targets = (1...10).map { Double($0) / 11 } }
            else { targets = [0.42 - 0.28 * t + bend, 0.58 + 0.28 * t + bend] }
            for x in 0..<width {
                let nx = Double(x) / Double(width - 1)
                let value: Int
                if kind == "edge" { value = nx > 0.42 - 0.28 * t && nx < 0.58 + 0.28 * t ? 190 : 55 }
                else if kind == "clutter" { value = (x * 37 + y * 17 + x * y * 13) % 256 }
                else { value = targets.contains { abs(nx - $0) < 0.0065 } ? 230 : 55 }
                image[y * width + x] = UInt8(value)
            }
        }
        return image
    }

    func testStraightPaintProducesUnassignedObservedCorridor() {
        let frame = detector.detect(grayscale: scene("straight"), width: 384, height: 216, timestampSeconds: 1)
        XCTAssertFalse(frame.budgetExceeded)
        XCTAssertEqual(frame.boundaries.count, 2)
        XCTAssertEqual(frame.corridors.count, 1)
        for (index, boundary) in frame.boundaries.enumerated() {
            XCTAssertEqual(boundary.cue, .paint)
            XCTAssertEqual(boundary.supportRows, 24)
            XCTAssertGreaterThanOrEqual(boundary.confidence, 0.90)
            for point in boundary.points {
                let t = (point.y - 0.50) / 0.44
                XCTAssertEqual(point.x, index == 0 ? 0.42 - 0.28 * t : 0.58 + 0.28 * t, accuracy: 0.008)
                XCTAssertTrue((0.50...0.95).contains(point.y))
            }
        }
        XCTAssertEqual(frame.operationCount, 127904)
        XCTAssertEqual(frame.boundaries.first?.points.first?.x ?? -1, 0.4177545691906005, accuracy: 1e-12)
    }

    func testCurvedMarkingsPreserveLocalShapeInsteadOfStraightFit() {
        let frame = detector.detect(grayscale: scene("curve"), width: 384, height: 216, timestampSeconds: 2)
        XCTAssertEqual(frame.boundaries.count, 2)
        XCTAssertEqual(frame.corridors.count, 1)
        for (index, boundary) in frame.boundaries.enumerated() {
            for point in boundary.points {
                let t = (point.y - 0.50) / 0.44
                let expected = (index == 0 ? 0.42 - 0.28 * t : 0.58 + 0.28 * t) + 0.18 * (1 - t) * (1 - t)
                XCTAssertEqual(point.x, expected, accuracy: 0.009)
            }
        }
    }

    func testCompetingCorridorsRemainSeparateWithoutChoosingEgo() {
        let frame = detector.detect(grayscale: scene("fork"), width: 384, height: 216, timestampSeconds: 3)
        XCTAssertEqual(frame.boundaries.count, 3)
        XCTAssertEqual(frame.corridors.map { $0.leftBoundaryIndex }, [0, 1])
        XCTAssertEqual(frame.corridors.map { $0.rightBoundaryIndex }, [1, 2])
    }

    func testNoPaintAndFacadeEdgesCannotInventDrivableCorridor() {
        let blank = detector.detect(grayscale: [UInt8](repeating: 55, count: 384 * 216), width: 384, height: 216, timestampSeconds: 4)
        XCTAssertTrue(blank.boundaries.isEmpty)
        XCTAssertTrue(blank.corridors.isEmpty)
        let edges = detector.detect(grayscale: scene("edge"), width: 384, height: 216, timestampSeconds: 4.1)
        XCTAssertEqual(edges.boundaries.count, 2)
        XCTAssertTrue(edges.boundaries.allSatisfy { $0.cue == .edge && $0.confidence <= 0.40 })
        XCTAssertTrue(edges.corridors.isEmpty)
        XCTAssertTrue(detector.detect(grayscale: scene("facade"), width: 384, height: 216, timestampSeconds: 4.2).corridors.isEmpty)
    }

    func testPortraitAndClutterRemainBounded() {
        let portrait = detector.detect(grayscale: scene("straight", width: 122), width: 122, height: 216, timestampSeconds: 5)
        XCTAssertFalse(portrait.budgetExceeded)
        XCTAssertEqual(portrait.boundaries.count, 2)
        let clutter = detector.detect(grayscale: scene("clutter"), width: 384, height: 216, timestampSeconds: 5.1)
        XCTAssertFalse(clutter.budgetExceeded)
        XCTAssertLessThanOrEqual(clutter.boundaries.count, 6)
        XCTAssertLessThanOrEqual(clutter.corridors.count, 2)
        XCTAssertLessThanOrEqual(clutter.operationCount, 250_000)
    }

    func testInvalidDimensionsBufferAndTimestampReturnEmpty() {
        for (width, height) in [(0, 216), (385, 216), (384, 217), (Int.max, Int.max)] {
            let result = detector.detect(grayscale: [], width: width, height: height, timestampSeconds: 1)
            XCTAssertTrue(result.boundaries.isEmpty)
            XCTAssertFalse(result.budgetExceeded)
        }
        XCTAssertTrue(detector.detect(grayscale: [55], width: 384, height: 216, timestampSeconds: 1).boundaries.isEmpty)
        XCTAssertTrue(detector.detect(grayscale: scene("straight"), width: 384, height: 216, timestampSeconds: .nan).boundaries.isEmpty)
    }

    func testDeadlinesAndOperationBudgetDiscardAllPartialGeometry() {
        let pixels = scene("straight")
        var checks = 0
        let cancelled = detector.detect(grayscale: pixels, width: 384, height: 216, timestampSeconds: 6) {
            checks += 1
            return checks < 75
        }
        XCTAssertTrue(cancelled.budgetExceeded)
        XCTAssertTrue(cancelled.boundaries.isEmpty)
        XCTAssertTrue(cancelled.corridors.isEmpty)
        XCTAssertEqual(checks, 75)
        let exhausted = detector.detect(grayscale: pixels, width: 384, height: 216, timestampSeconds: 6.1, maximumOperations: 100)
        XCTAssertTrue(exhausted.budgetExceeded)
        XCTAssertTrue(exhausted.boundaries.isEmpty)
        let fresh = detector.detect(grayscale: pixels, width: 384, height: 216, timestampSeconds: 6.2)
        XCTAssertEqual(fresh.boundaries.count, 2)
        XCTAssertFalse(fresh.budgetExceeded)
    }
}
