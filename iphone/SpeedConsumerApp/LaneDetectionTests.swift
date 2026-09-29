import XCTest
@testable import SpeedConsumer

final class LaneDetectionTests: XCTestCase {
    private let detector = LaneDetector()

    private func road(left: Bool = true, right: Bool = true, width: Int = 384, height: Int = 216) -> [UInt8] {
        var image = [UInt8](repeating: 55, count: width * height)
        for y in 0..<height {
            let normalizedY = Double(y) / Double(height - 1)
            guard (0.52...0.96).contains(normalizedY) else { continue }
            let offset = (normalizedY - 0.52) * 0.30 / 0.44
            for x in 0..<width {
                let normalizedX = Double(x) / Double(width - 1)
                if (left && abs(normalizedX - (0.42 - offset)) < 0.0065)
                    || (right && abs(normalizedX - (0.58 + offset)) < 0.0065) {
                    image[y * width + x] = 230
                }
            }
        }
        return image
    }

    func testPairNeedsTwoFramesAndNeverInventsMissingBoundary() {
        var tracker = LaneTracker()
        let first = detector.detect(grayscale: road(), width: 384, height: 216, timestampSeconds: 1)
        XCTAssertTrue(first.hasReliablePair)
        XCTAssertEqual(tracker.update(first).state, .uncertain)
        XCTAssertTrue(tracker.update(detector.detect(grayscale: road(), width: 384, height: 216, timestampSeconds: 1.2)).hasReliablePair)
        let single = tracker.update(detector.detect(grayscale: road(right: false), width: 384, height: 216, timestampSeconds: 1.4))
        XCTAssertEqual(single.state, .uncertain)
        XCTAssertNotNil(single.left)
        XCTAssertNil(single.right)
        let blank = tracker.update(detector.detect(grayscale: [UInt8](repeating: 55, count: 384 * 216), width: 384, height: 216, timestampSeconds: 1.6))
        XCTAssertEqual(blank.state, .unavailable)
        XCTAssertNil(blank.left)
        XCTAssertNil(blank.right)
    }

    func testBackwardClockGapsAndExplicitResetRequireFreshConfirmation() {
        var tracker = LaneTracker()
        func estimate(_ timestamp: Double) -> LaneDetectionEstimate {
            detector.detect(grayscale: road(), width: 384, height: 216, timestampSeconds: timestamp)
        }
        _ = tracker.update(estimate(1))
        XCTAssertTrue(tracker.update(estimate(1.2)).hasReliablePair)
        XCTAssertEqual(tracker.update(estimate(2.0)).state, .uncertain)
        XCTAssertTrue(tracker.update(estimate(2.2)).hasReliablePair)
        XCTAssertEqual(tracker.update(estimate(2.1)).state, .uncertain)
        tracker.reset()
        XCTAssertEqual(tracker.update(estimate(2.3)).state, .uncertain)
    }

    func testInvalidInputAndNonFiniteTimestampAreUnavailable() {
        for (width, height, pixels) in [(0, 216, [UInt8]()), (641, 216, [UInt8]()), (384, 216, [55])] {
            XCTAssertEqual(detector.detect(grayscale: pixels, width: width, height: height, timestampSeconds: 1).state, .unavailable)
        }
        XCTAssertEqual(detector.detect(grayscale: road(), width: 384, height: 216, timestampSeconds: .nan).state, .unavailable)
        var tracker = LaneTracker()
        let invalid = LaneDetectionEstimate(left: nil, right: nil, timestampSeconds: .infinity, state: .reliable)
        XCTAssertEqual(tracker.update(invalid).state, .unavailable)
    }

    func testFitStaysOnObservedMarkings() throws {
        let estimate = detector.detect(grayscale: road(), width: 384, height: 216, timestampSeconds: 1)
        for (boundary, isLeft) in [(try XCTUnwrap(estimate.left), true), (try XCTUnwrap(estimate.right), false)] {
            XCTAssertGreaterThanOrEqual(boundary.confidence, 0.62)
            for point in boundary.points {
                XCTAssertTrue((0.52...0.96).contains(point.y))
                let offset = (point.y - 0.52) * 0.30 / 0.44
                XCTAssertEqual(point.x, isLeft ? 0.42 - offset : 0.58 + offset, accuracy: 0.008)
            }
        }
    }

    func testCorridorFillUsesOnlySharedObservedExtent() {
        let left = LaneBoundary(points: [LanePoint(x: 0.4, y: 0.5), LanePoint(x: 0.1, y: 0.9)], confidence: 0.9)
        let right = LaneBoundary(points: [LanePoint(x: 0.6, y: 0.6), LanePoint(x: 0.8, y: 0.8)], confidence: 0.9)
        let estimate = LaneDetectionEstimate(left: left, right: right, timestampSeconds: 1, state: .reliable)
        XCTAssertEqual(estimate.corridorPoints.count, 4)
        XCTAssertTrue(estimate.corridorPoints.allSatisfy { (0.6...0.8).contains($0.y) })
        XCTAssertEqual(estimate.corridorPoints[0].x, 0.325, accuracy: 1e-9)
        XCTAssertEqual(estimate.corridorPoints[1].x, 0.175, accuracy: 1e-9)
        XCTAssertTrue(LaneDetectionEstimate(left: left, right: right, timestampSeconds: 1, state: .uncertain).corridorPoints.isEmpty)
        XCTAssertTrue(LaneDetectionEstimate(left: left, right: nil, timestampSeconds: 1, state: .reliable).corridorPoints.isEmpty)
    }
}
