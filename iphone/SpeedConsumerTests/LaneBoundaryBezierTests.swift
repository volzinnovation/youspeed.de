import XCTest
@testable import SpeedConsumer

final class LaneBoundaryBezierTests: XCTestCase {
    private func checkBound(_ points: [LanePoint], _ curves: [LaneBezierSegment]) {
        for curve in curves {
            XCTAssertTrue(points.contains(curve.start)); XCTAssertTrue(points.contains(curve.end))
            let covered = points.filter { $0.y >= curve.start.y && $0.y <= curve.end.y }
            let lo = covered.map(\.x).min()!, hi = covered.map(\.x).max()!
            for p in [curve.control1,curve.control2] {
                XCTAssertTrue((lo...hi).contains(p.x)); XCTAssertTrue((curve.start.y...curve.end.y).contains(p.y))
            }
            for step in 0...200 {
                let p = curve.point(at:Double(step)/200)
                let index = max(1, points.firstIndex { $0.y >= p.y } ?? points.count-1)
                let a = points[index-1], b = points[index]
                let raw = a.x+(b.x-a.x)*(p.y-a.y)/(b.y-a.y)
                XCTAssertLessThanOrEqual(abs(p.x-raw),LaneBoundaryBezier.maximumDeviation+1e-10)
            }
        }
    }

    func testNoisyStraightBoundarySimplifiesToOneCurveWithoutMovingEndpoints() {
        let points = (0...11).map { i -> LanePoint in
            let t = Double(i)/11
            return LanePoint(x:0.3+0.18*t+(i==0 || i==11 ? 0 : (i%2==0 ? 0.002 : -0.002)),y:0.45+0.5*t)
        }
        let before = points, curves = LaneBoundaryBezier.fit(points)
        XCTAssertEqual(curves.count,1); XCTAssertEqual(curves.first?.start,points.first); XCTAssertEqual(curves.last?.end,points.last)
        XCTAssertEqual(points,before)
        XCTAssertGreaterThan(abs(curves[0].point(at:5.0/11).x-points[5].x),0.001)
        checkBound(points,curves)
    }

    func testBendAndInflectionKeepCurvatureWithinTheObservedExtent() {
        let points = (0...12).map { i -> LanePoint in
            let t = Double(i)/12
            return LanePoint(x:0.22+0.34*t-0.25*t*t+0.2*t*t*t,y:0.4+0.55*t)
        }
        let curves = LaneBoundaryBezier.fit(points)
        XCTAssertEqual(curves.count,1); checkBound(points,curves)
        XCTAssertEqual(curves[0].point(at:0.5).x,0.3525,accuracy:1e-10)
    }

    func testSharpGeometrySplitsInsteadOfOvershootingOrErasingIt() {
        let points = (0...10).map { i -> LanePoint in
            let offset = 0.025*Double(i)
            return LanePoint(x:i<5 ? 0.25+offset : 0.55-offset,y:0.4+0.05*Double(i))
        }
        let curves = LaneBoundaryBezier.fit(points)
        XCTAssertGreaterThan(curves.count,1); XCTAssertLessThanOrEqual(curves.count,points.count-1)
        XCTAssertEqual(curves.first?.start,points.first); XCTAssertEqual(curves.last?.end,points.last); checkBound(points,curves)
    }

    func testMissingIntervalsAndInvalidPointsNeverBecomeConnectingCurves() {
        let points = [LanePoint(x:0.3,y:0.4),LanePoint(x:0.31,y:0.45),LanePoint(x:0.32,y:0.5),
                      LanePoint(x:0.4,y:0.75),LanePoint(x:0.41,y:0.8),LanePoint(x:0.42,y:0.85)]
        let curves = LaneBoundaryBezier.fit(points)
        XCTAssertEqual(curves.count,2); XCTAssertEqual(curves[0].end,points[2]); XCTAssertEqual(curves[1].start,points[3])
        let invalid = Array(points.prefix(3))+[LanePoint(x:.nan,y:0.6)]+Array(points.suffix(3))
        XCTAssertEqual(LaneBoundaryBezier.fit(invalid),curves)
        XCTAssertTrue(LaneBoundaryBezier.fit([]).isEmpty)
        XCTAssertTrue(LaneBoundaryBezier.fit(Array(repeating:points[0],count:65)).isEmpty)
    }

    func testManyIrregularInputsKeepTheWholePolylineErrorBound() {
        for phase in 0..<20 {
            let points = (0...15).map { i -> LanePoint in
                let trend = 0.2+Double(i)*0.025
                let noise = sin(Double(i*7+phase))*0.018
                return LanePoint(x:trend+noise,y:0.35+Double(i)*0.04)
            }
            let curves = LaneBoundaryBezier.fit(points)
            XCTAssertFalse(curves.isEmpty); checkBound(points,curves)
        }
    }
}
