import XCTest
@testable import SpeedConsumer

final class RoadBoundaryDetectorTests: XCTestCase {
    private let detector = RoadBoundaryDetector()

    func testTopHat5MatchesUnsignedFloorSaturationAndBorderContract() throws {
        // Five-pixel horizontal opening: isolated peaks open to10; 1.5× gain rounds down.
        XCTAssertEqual(RoadBoundaryPreprocessor.topHat5(grayscale:[10,10,11,10,10],width:5,height:1),[10,10,12,10,10])
        XCTAssertEqual(RoadBoundaryPreprocessor.topHat5(grayscale:[101,10,10,10,10],width:5,height:1),[237,10,10,10,10])
        XCTAssertEqual(RoadBoundaryPreprocessor.topHat5(grayscale:[10,10,10,10,101],width:5,height:1),[10,10,10,10,237])
        XCTAssertEqual(RoadBoundaryPreprocessor.topHat5(grayscale:[10,10,255,10,10],width:5,height:1),[10,10,255,10,10])
        XCTAssertEqual(RoadBoundaryPreprocessor.topHat5(grayscale:[128,128,128,128,128],width:5,height:1),[128,128,128,128,128])
        XCTAssertEqual(RoadBoundaryPreprocessor.topHat5(grayscale:[200,20],width:1,height:2),[200,20])
    }

    func testTopHat5CancellationAndInvalidBuffersNeverReturnPartialPixels() {
        XCTAssertNil(RoadBoundaryPreprocessor.topHat5(grayscale:[1],width:0,height:1))
        XCTAssertNil(RoadBoundaryPreprocessor.topHat5(grayscale:[1],width:2,height:1))
        var calls = 0
        XCTAssertNil(RoadBoundaryPreprocessor.topHat5(grayscale:[UInt8](repeating:100,count:384*216),width:384,height:216,
            shouldContinue:{ calls += 1; return calls<30 }))
        XCTAssertEqual(calls,30)
        // Cancel during dilation as well as erosion.
        calls = 0
        XCTAssertNil(RoadBoundaryPreprocessor.topHat5(grayscale:[10,10,20,10,10],width:5,height:1,
            shouldContinue:{ calls += 1; return calls<5 }))
        XCTAssertEqual(calls,5)
    }

    func testSparseFilterPreservesAllDetectorReadsAndGeometryWithCalibration() throws {
        for (w,h) in [(64,64),(288,216),(384,216),(161,91)] {
            let input: [UInt8]=(0..<(w*h)).map { (index: Int) -> UInt8 in
                let value: Int = index*37 + index/7
                return UInt8(value%256)
            }
            let full=try XCTUnwrap(RoadBoundaryPreprocessor.topHat5(grayscale:input,width:w,height:h))
            for horizon: Double? in [nil,.nan,-1,0.05,0.37,0.8,2] {
                let sparse=try XCTUnwrap(RoadBoundaryPreprocessor.topHat5ForDetector(grayscale:input,width:w,height:h,horizonY:horizon))
                let rows=Set(RoadBoundarySamplingRows.support(height:h,horizonY:horizon))
                XCTAssertLessThanOrEqual(rows.count,72)
                for y in 0..<h { for x in 0..<w {
                    XCTAssertEqual(sparse[y*w+x],rows.contains(y) ? full[y*w+x] : 0)
                } }
                let guidance=RoadBoundarySearchGuidance(horizonY:horizon)
                XCTAssertEqual(detector.detect(grayscale:full,width:w,height:h,timestampSeconds:1,guidance:guidance),
                    detector.detect(grayscale:sparse,width:w,height:h,timestampSeconds:1,guidance:guidance))
            }
        }
        XCTAssertNil(RoadBoundaryPreprocessor.topHat5ForDetector(grayscale:[UInt8](repeating:0,count:64*64),width:64,height:64,shouldContinue:{ false }))
    }

    func testCachedCameraSamplingPreservesPixelCentersAndStrideChanges() throws {
        let sampler=RoadPathLumaSampler()
        for (rawW,rawH) in [(1279,721),(1920,1440),(65,67)] {
            for rotation in [0,90,180,270] { for pixelStride in [1,2] {
                let stride=rawW*pixelStride+13
                let bytes: [UInt8]=(0..<(stride*rawH+20)).map { (index: Int) -> UInt8 in
                    let value: Int = index*31 + index/19
                    return UInt8(value%256)
                }
                let uprightW=rotation%180==0 ? rawW : rawH, uprightH=rotation%180==0 ? rawH : rawW
                let scale=min(384.0/Double(uprightW),216.0/Double(uprightH),1)
                let w=Int(Double(uprightW)*scale), h=Int(Double(uprightH)*scale)
                for base in [0,7,0] {
                    var expected=[UInt8](repeating:0,count:w*h)
                    for y in 0..<h { for x in 0..<w {
                        let u=(Double(x)+0.5)/Double(w), v=(Double(y)+0.5)/Double(h)
                        let rx: Double, ry: Double
                        switch rotation {
                        case 0: rx=u; ry=v
                        case 90: rx=v; ry=1-u
                        case 180: rx=1-u; ry=1-v
                        default: rx=1-v; ry=u
                        }
                        let ix=min(rawW-1,Int(rx*Double(rawW)))
                        let iy=min(rawH-1,Int(ry*Double(rawH)))
                        expected[y*w+x]=bytes[base+iy*stride+ix*pixelStride]
                    } }
                    let actual=bytes.withUnsafeBufferPointer { sampler.copy(base:$0.baseAddress!+base,rawWidth:rawW,rawHeight:rawH,
                        rotation:rotation,rowStride:stride,pixelStride:pixelStride,width:w,height:h) }
                    XCTAssertEqual(actual,expected)
                }
            } }
        }
        let pixel: [UInt8]=[1]
        XCTAssertNil(pixel.withUnsafeBufferPointer { sampler.copy(base:$0.baseAddress!,rawWidth:1,rawHeight:1,
            rotation:0,rowStride:1,width:1,height:1,shouldContinue:{ false }) })
    }

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

    func testDarkNoiseAndBroadShadowTransitionsCannotBecomePaint() {
        let width = 384, height = 216
        let paint = scene("straight",width:width,height:height)
        let lowContrast: [UInt8] = paint.map { $0 > 100 ? 47 : 32 }
        let blackLevel: [UInt8] = paint.map { $0 > 100 ? 30 : 0 }
        let texture: [UInt8] = (0..<(width*height)).map { index in
            UInt8(40+((index%width)*13+(index/width)*7)%15)
        }
        let gradient: [UInt8] = (0..<(width*height)).map { index in UInt8(25+50*(index%width)/width) }
        let shadow: [UInt8] = (0..<(width*height)).map { index in
            let y = Double(index/width)/Double(height-1), x = Double(index%width)/Double(width-1)
            return x > 0.42-0.28*((y-0.50)/0.44) && x < 0.58+0.28*((y-0.50)/0.44) ? 75 : 20
        }
        for image in [lowContrast,blackLevel,texture,gradient,shadow] {
            let frame = detector.detect(grayscale:image,width:width,height:height,timestampSeconds:2.2)
            XCTAssertFalse(frame.budgetExceeded)
            XCTAssertTrue(frame.boundaries.allSatisfy { $0.cue == .edge && $0.confidence <= 0.40 })
            XCTAssertTrue(frame.corridors.isEmpty)
        }
    }

    func testCompetingCorridorsRemainSeparateWithoutChoosingEgo() {
        let frame = detector.detect(grayscale: scene("fork"), width: 384, height: 216, timestampSeconds: 3)
        XCTAssertEqual(frame.boundaries.count, 3)
        XCTAssertEqual(frame.corridors.map { $0.leftBoundaryIndex }, [0, 1])
        XCTAssertEqual(frame.corridors.map { $0.rightBoundaryIndex }, [1, 2])
    }

    func testStaleCurvedGuideCannotJoinTwoSeparatelyObservedStripes() {
        // A continuous stripe has two current observations before the old guide bends toward
        // a nearby stripe appearing farther away. The old unbounded guide joined those stripes.
        for width in [192,384] {
            let height = 216
            var image = [UInt8](repeating:55,count:width*height)
            for y in 0..<height {
                let ny = Double(y)/Double(height-1)
                if !(0.49...0.96).contains(ny) { continue }
                for x in 0..<width {
                    let nx = Double(x)/Double(width-1)
                    if abs(nx-0.35)<0.0065 || (ny<0.91 && abs(nx-0.40)<0.0065) { image[y*width+x]=230 }
                }
            }
            let guide = RoadBoundarySearchGuidance(polylines:[[
                LanePoint(x:0.45,y:0.50),LanePoint(x:0.45,y:0.903),LanePoint(x:0.35,y:0.920),LanePoint(x:0.35,y:0.94),
            ]])
            let frame = detector.detect(grayscale:image,width:width,height:height,timestampSeconds:3.1,guidance:guide)
            XCTAssertFalse(frame.budgetExceeded)
            XCTAssertEqual(frame.boundaries.count,2)
            let continuous = frame.boundaries.filter { $0.supportRows==24 }
            XCTAssertEqual(continuous.count,1)
            XCTAssertTrue(continuous.first?.points.allSatisfy { abs($0.x-0.35)<=1/Double(width-1) } ?? false)
            let distant = frame.boundaries.filter { $0.supportRows==22 }
            XCTAssertEqual(distant.count,1)
            XCTAssertTrue(distant.first?.points.allSatisfy { abs($0.x-0.40)<=1/Double(width-1) } ?? false)
        }
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
