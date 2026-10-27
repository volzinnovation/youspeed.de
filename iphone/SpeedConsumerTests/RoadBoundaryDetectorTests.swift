import XCTest
@testable import SpeedConsumer

final class RoadBoundaryDetectorTests: XCTestCase {
    private let detector = RoadBoundaryDetector()

    func testTracePreservesAllDetectionFieldsAndCancellationChecks() throws {
        for kind in ["straight","curve","fork","clutter","edge"] {
            for options in [RoadBoundaryDetectionOptions(),RoadBoundaryDetectionOptions(useSearchBands:true),
                            RoadBoundaryDetectionOptions(groupFragments:true),RoadBoundaryDetectionOptions(useSearchBands:true,groupFragments:true)] {
                let pixels=scene(kind)
                var events: [[String:Any]] = []
                let traced=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:1,options:options,trace:{ events.append($0) })
                XCTAssertEqual(traced,detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:1,options:options))
                XCTAssertEqual(events.first?["stage"] as? String,"configuration")
                XCTAssertEqual(events.last?["status"] as? String,"complete")
                XCTAssertEqual(events.filter { $0["stage"] as? String == "row" }.count,24)
                XCTAssertNoThrow(try JSONSerialization.data(withJSONObject:events))
            }
        }
        let pixels=scene("straight")
        var tracedCalls=0, plainCalls=0
        var events: [[String:Any]] = []
        let traced=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:1,trace:{ events.append($0) },
            shouldContinue:{ tracedCalls += 1; return tracedCalls < 100 })
        let plain=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:1,
            shouldContinue:{ plainCalls += 1; return plainCalls < 100 })
        XCTAssertEqual(traced,plain)
        XCTAssertEqual(tracedCalls,plainCalls)
        XCTAssertTrue(traced.boundaries.isEmpty)
        XCTAssertEqual(events.last?["status"] as? String,"budget_or_cancelled")
    }

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
            let bend = kind == "curve" ? 0.18 * (1 - t) * (1 - t) : (kind == "wave" ? 0.04*sin(2*Double.pi*t) : 0.0)
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
    private func fragmentScene(_ kind: String) -> [UInt8] {
        let width=384, height=216
        var image=[UInt8](repeating:55,count:width*height)
        for y in 0..<height {
            let ny=Double(y)/Double(height-1), t=(ny-0.50)/0.44
            for x in 0..<width {
                let nx=Double(x)/Double(width-1)
                var painted=false
                switch kind {
                case "dashed", "curved_dashed":
                    let bend=kind == "curved_dashed" ? 0.18*(1-t)*(1-t) : 0
                    painted=((0.56...0.63).contains(ny) || (0.76...0.83).contains(ny)) &&
                        [0.42-0.28*t+bend,0.58+0.28*t+bend].contains { abs(nx-$0)<0.0065 }
                case "arrow":
                    painted=((0.81...0.93).contains(ny) && abs(nx-0.5)<0.0065) ||
                        ((0.70...0.81).contains(ny) && abs(abs(nx-0.5)-(0.81-ny)*1.4)<0.0065)
                case "merge":
                    painted=((0.76...0.83).contains(ny) && abs(nx-(0.42-0.28*t))<0.0065) ||
                        ((0.56...0.63).contains(ny) && abs(nx-(0.42-0.28*t+0.10))<0.0065)
                case "guardrail": painted=nx>0.1 && nx<0.9 && (abs(ny-0.62)<0.006 || abs(ny-0.78)<0.006)
                default: break
                }
                if painted { image[y*width+x]=230 }
            }
        }
        return image
    }

    func testFragmentRecoveryPreservesAcceptedContinuousGeometryAndConfidence() {
        // The wave is measured coherently but is not a single quadratic. A global
        // residual/curvature gate previously discarded both valid raw borders.
        for kind in ["straight","curve","wave","fork","edge","facade"] {
            let pixels=scene(kind)
            let baseline=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:6.3)
            XCTAssertFalse(baseline.boundaries.isEmpty)
            for bands in [false,true] {
                let recovered=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:6.3,
                    options:RoadBoundaryDetectionOptions(useSearchBands:bands,groupFragments:true))
                XCTAssertFalse(recovered.budgetExceeded)
                XCTAssertEqual(recovered.boundaries.count,baseline.boundaries.count,"Lost raw support for \(kind)")
                for (original,preserved) in zip(baseline.boundaries,recovered.boundaries) {
                    XCTAssertEqual(preserved.points,original.points)
                    XCTAssertEqual(preserved.confidence,original.confidence)
                    XCTAssertEqual(preserved.cue,original.cue)
                    XCTAssertEqual(preserved.supportRows,original.supportRows)
                    XCTAssertNil(preserved.geometryConfidence)
                    if preserved.cue == .paint {
                        XCTAssertEqual(preserved.observedSegments,[original.points])
                        XCTAssertEqual(preserved.paintOccupancy,1)
                    }
                }
                XCTAssertEqual(recovered.corridors,baseline.corridors)
                XCTAssertNil(recovered.rejectionCounts["fragments_joined"])
                XCTAssertFalse(recovered.rejectionCounts.keys.contains { $0.hasPrefix("fragment_fit_") })
            }
        }
    }

    func testRecoveredDashesCannotDisplaceSixAcceptedRawBorders() {
        let w=384,h=216
        var pixels=[UInt8](repeating:55,count:w*h)
        for y in 0..<h {
            let ny=Double(y)/Double(h-1)
            if !(0.49...0.96).contains(ny) { continue }
            var centers=[0.10,0.25,0.40,0.55,0.70,0.85]
            if (0.56...0.63).contains(ny) || (0.76...0.83).contains(ny) { centers.append(0.475) }
            for x in 0..<w where centers.contains(where:{ abs(Double(x)/Double(w-1)-$0)<0.0065 }) { pixels[y*w+x]=230 }
        }
        let baseline=detector.detect(grayscale:pixels,width:w,height:h,timestampSeconds:6.4)
        let recovered=detector.detect(grayscale:pixels,width:w,height:h,timestampSeconds:6.4,
            options:RoadBoundaryDetectionOptions(groupFragments:true))
        XCTAssertFalse(recovered.budgetExceeded)
        XCTAssertEqual(baseline.boundaries.count,6)
        XCTAssertEqual(recovered.boundaries.map(\.points),baseline.boundaries.map(\.points))
        XCTAssertEqual(recovered.boundaries.map(\.confidence),baseline.boundaries.map(\.confidence))
        XCTAssertEqual(recovered.rejectionCounts["fragment_output_capacity"],1)
    }

    func testFragmentGroupingJoinsConsistentDashesWithoutInventingPaintOrRequiringBottomRow() {
        for kind in ["dashed","curved_dashed"] {
            let pixels=fragmentScene(kind)
            let baseline=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:7)
            XCTAssertTrue(baseline.boundaries.isEmpty)
            let grouped=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:7,
                options:RoadBoundaryDetectionOptions(groupFragments:true))
            XCTAssertFalse(grouped.budgetExceeded)
            XCTAssertEqual(grouped.boundaries.count,2)
            XCTAssertEqual(grouped.rejectionCounts["fragments_joined"],2)
            for boundary in grouped.boundaries {
                XCTAssertEqual(boundary.cue,.paint)
                XCTAssertEqual(boundary.observedSegments.count,2)
                XCTAssertGreaterThan(boundary.confidence,0.40)
                XCTAssertLessThan(boundary.paintOccupancy ?? 1,0.65)
                XCTAssertLessThan(boundary.points.last!.y,0.85)
                for segment in boundary.observedSegments {
                    XCTAssertGreaterThanOrEqual(segment.count,2)
                    XCTAssertTrue(segment.allSatisfy { (0.55...0.64).contains($0.y) || (0.75...0.84).contains($0.y) })
                    XCTAssertLessThan(segment.last!.y-segment.first!.y,0.10)
                }
            }
        }
    }

    func testSearchBandsAreSoftAndDoNotChangeSolidPaintWithoutCapacityPressure() {
        let pixels=scene("straight")
        let baseline=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:8)
        let wrong=RoadBoundarySearchGuidance(polylines:[
            [LanePoint(x:0.05,y:0.5),LanePoint(x:0.05,y:0.94)],
            [LanePoint(x:0.1,y:0.5),LanePoint(x:0.1,y:0.94)]])
        let bands=detector.detect(grayscale:pixels,width:384,height:216,timestampSeconds:8,guidance:wrong,
            options:RoadBoundaryDetectionOptions(useSearchBands:true))
        XCTAssertEqual(bands.boundaries,baseline.boundaries)
        XCTAssertGreaterThan(bands.rejectionCounts["outside_bands_retained"] ?? 0,0)
        XCTAssertEqual(bands.detectionVariant,"bands")
    }

    func testFragmentNegativesDoNotJoinArrowMergeOrHorizontalGuardrail() {
        for kind in ["arrow","merge","guardrail","unmarked"] {
            for bands in [false,true] {
                let result=detector.detect(grayscale:fragmentScene(kind),width:384,height:216,timestampSeconds:9,
                    options:RoadBoundaryDetectionOptions(useSearchBands:bands,groupFragments:true))
                XCTAssertFalse(result.budgetExceeded)
                XCTAssertTrue(result.boundaries.isEmpty,"Unexpected boundary for \(kind)")
                XCTAssertTrue(result.corridors.isEmpty)
                XCTAssertNil(result.rejectionCounts["fragments_joined"])
            }
        }
    }

    func testFragmentVariantKeepsOperationCapAndCancellationAtomic() {
        for options in [RoadBoundaryDetectionOptions(useSearchBands:true),RoadBoundaryDetectionOptions(groupFragments:true),
                        RoadBoundaryDetectionOptions(useSearchBands:true,groupFragments:true)] {
            let exhausted=detector.detect(grayscale:fragmentScene("dashed"),width:384,height:216,timestampSeconds:10,
                maximumOperations:100,options:options)
            XCTAssertTrue(exhausted.budgetExceeded)
            XCTAssertTrue(exhausted.boundaries.isEmpty)
            XCTAssertLessThanOrEqual(exhausted.operationCount,100)
            let clutter=detector.detect(grayscale:scene("clutter"),width:384,height:216,timestampSeconds:10,options:options)
            XCTAssertLessThanOrEqual(clutter.operationCount,250_000)
            XCTAssertLessThanOrEqual(clutter.boundaries.count,6)
        }
    }

}

#if os(iOS)
import CryptoKit
import Darwin

/// Opt-in paced component replay. Does not start a camera, recording, model, UI flow or network.
final class LaneFragmentSustainedReplayTests: XCTestCase {
    private struct Config: Decodable { let runId: String; let secondsPerArm: Double; let variants: [String] }
    private struct Input: Decodable {
        let id: String; let sequenceId: String; let file: String; let rawSha256: String
        let width: Int; let height: Int; let decodedWidth: Int; let decodedHeight: Int; let time: Double
        let calibration: RoadPathCalibration?; let visualCalibration: VisualRoadCalibration?; let orientationKey: String?
    }
    private struct Manifest: Decodable { let frames: [Input] }
    private func sha(_ data: Data) -> String { SHA256.hash(data:data).map { String(format:"%02x",$0) }.joined() }
    private func rss() -> UInt64? {
        var info=mach_task_basic_info(); var count=mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size/MemoryLayout<natural_t>.size)
        let result=withUnsafeMutablePointer(to:&info) { pointer in pointer.withMemoryRebound(to:integer_t.self,capacity:Int(count)) {
            task_info(mach_task_self_,task_flavor_t(MACH_TASK_BASIC_INFO),$0,&count)
        } }
        return result == KERN_SUCCESS ? info.resident_size : nil
    }
    private func distribution(_ values:[Double]) -> [String:Any] {
        let sorted=values.sorted(); guard !sorted.isEmpty else { return ["count":0] }
        func q(_ p:Double)->Double { sorted[min(sorted.count-1,max(0,Int(ceil(p*Double(sorted.count)))-1))] }
        return ["count":sorted.count,"p50":q(0.5),"p95":q(0.95),"p99":q(0.99),"max":sorted.last!]
    }
    private func boundaries(_ values:[RoadBoundaryEvidence]) -> [[String:Any]] {
        values.map { b in ["points":b.points.map { [$0.x,$0.y] },"observedSegments":b.observedSegments.map { $0.map { [$0.x,$0.y] } },
            "confidence":b.confidence,"cue":b.cue.rawValue,"supportRows":b.supportRows,"provenance":b.provenance.rawValue,
            "evidenceAgeSeconds":b.evidenceAgeSeconds,"geometryConfidence":b.geometryConfidence as Any? ?? NSNull(),
            "paintOccupancy":b.paintOccupancy as Any? ?? NSNull()] }
    }

    func testPacedRecordedAblationsAndTracking() throws {
        executionTimeAllowance=2100
        let root=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].appendingPathComponent("LaneFragmentReplay",isDirectory:true)
        let configURL=root.appendingPathComponent("config.json")
        let explicitRunID=ProcessInfo.processInfo.environment["LANE_FRAGMENT_RUN_ID"]
        try XCTSkipUnless(explicitRunID != nil,"Explicit LANE_FRAGMENT_RUN_ID required")
        try XCTSkipUnless(FileManager.default.fileExists(atPath:configURL.path),"Explicit private replay config required")
        let decoder=JSONDecoder(), config=try decoder.decode(Config.self,from:Data(contentsOf:configURL))
        let runId=config.runId, seconds=config.secondsPerArm
        guard explicitRunID==runId else { throw NSError(domain:"ReplayRunIDMismatch",code:1) }
        let allowed=Set(["baseline","bands","fragments","bands_fragments","fragments_tracking","bands_fragments_tracking"])
        guard runId.range(of:"^[A-Za-z0-9_-]+$",options:.regularExpression) != nil,
              (1...300).contains(seconds), !config.variants.isEmpty, Set(config.variants).count==config.variants.count,
              config.variants.allSatisfy({ allowed.contains($0) }) else { throw NSError(domain:"ReplayConfig",code:1) }
        let manifestData=try Data(contentsOf:root.appendingPathComponent("input.json"))
        let rows=try decoder.decode(Manifest.self,from:manifestData).frames
        guard (1...5000).contains(rows.count) else { throw NSError(domain:"ReplayFrames",code:1) }
        let outputURL=root.appendingPathComponent(runId+".ndjson"), reportURL=root.appendingPathComponent(runId+".json")
        guard !FileManager.default.fileExists(atPath:outputURL.path), !FileManager.default.fileExists(atPath:reportURL.path) else {
            throw NSError(domain:"ReplayOutputExists",code:1)
        }
        XCTAssertTrue(FileManager.default.createFile(atPath:outputURL.path,contents:nil))
        let writer=try FileHandle(forWritingTo:outputURL); defer { try? writer.close() }
        var summaries:[String:Any]=[:]
        for arm in config.variants {
            let options=RoadBoundaryDetectionOptions(useSearchBands:arm.contains("bands"),groupFragments:arm.contains("fragments"))
            func newSession()->RoadPathSession { RoadPathSession(previewMode:true,detectionOptions:options,fragmentTracking:arm.hasSuffix("tracking")) }
            var session=newSession(), previousSequence="", previousTime = -Double.infinity
            var latencies:[Double]=[], filterTimes:[Double]=[], geometryTimes:[Double]=[]
            var maxRss:UInt64=0, memorySamples=0, operationRejects=0, targetMisses=0, invalidSelected=0
            var identityChanges=0, previousIDs:[Int64]?, loops=0, thermalPauseSeconds=0.0
            var thermalCounts:[String:Int]=[:]
            let start=ProcessInfo.processInfo.systemUptime
            var next=start, index=0, lastTick=start, wasPaused=false
            while ProcessInfo.processInfo.systemUptime-start<seconds {
                let delay=next-ProcessInfo.processInfo.systemUptime
                if delay>0 { Thread.sleep(forTimeInterval:delay) }
                let tick=ProcessInfo.processInfo.systemUptime
                if tick-start>=seconds { break }
                if wasPaused { thermalPauseSeconds+=tick-lastTick }
                lastTick=tick
                try autoreleasepool {
                    let thermal=ProcessInfo.processInfo.thermalState
                    thermalCounts[String(thermal.rawValue),default:0]+=1
                    let paused=thermal == .serious || thermal == .critical
                    let row=rows[index%rows.count]
                    if index>0 && index%rows.count==0 { loops+=1 }
                    var record:[String:Any]=["schemaVersion":1,"runId":runId,"arm":arm,"index":index,"wallSeconds":tick-start,
                        "id":row.id,"sequenceId":row.sequenceId,"sourcePtsSeconds":row.time,"thermalStatus":thermal.rawValue,"thermalPaused":paused]
                    if index%10==0 {
                        memorySamples+=1
                        if let resident=rss() { maxRss=max(maxRss,resident); record["residentBytes"]=resident }
                        else { record["residentBytes"]=NSNull() }
                    }
                    if !paused {
                        if wasPaused || row.sequenceId != previousSequence || row.time<=previousTime { session=newSession(); previousIDs=nil }
                        previousSequence=row.sequenceId; previousTime=row.time
                        guard URL(fileURLWithPath:row.file).lastPathComponent==row.file,
                              (64...384).contains(row.width),(64...216).contains(row.height) else { throw NSError(domain:"ReplayInput",code:1) }
                        let loadStart=ProcessInfo.processInfo.systemUptime
                        let data=try Data(contentsOf:root.appendingPathComponent(row.file))
                        let digest=sha(data)
                        XCTAssertEqual(data.count,row.width*row.height); XCTAssertEqual(digest,row.rawSha256)
                        guard data.count==row.width*row.height,digest==row.rawSha256 else { throw NSError(domain:"ReplayIntegrity",code:1) }
                        record["loadAndIntegrityMs"]=(ProcessInfo.processInfo.systemUptime-loadStart)*1000
                        let started=ProcessInfo.processInfo.systemUptime
                        let pixels=Array(data), copyMs=(ProcessInfo.processInfo.systemUptime-started)*1000
                        let geometryID="encoded:\(row.sequenceId):\(row.decodedWidth)x\(row.decodedHeight)"
                        let frame=RoadPathCameraFrame(grayscale:pixels,width:row.width,height:row.height,capturedAtSeconds:row.time,
                            geometryId:geometryID,calibration:row.calibration,clockKnown:true,preprocessingMs:copyMs,startedAt:started,
                            rawWidth:row.decodedWidth,rawHeight:row.decodedHeight,sourceTimestampSeconds:row.time,
                            visualCalibration:row.visualCalibration,orientationKey:row.orientationKey ?? "")
                        let scope=TSRApplicabilityScope(sessionId:row.sequenceId,bundleId:"component-replay",cameraGeometryId:geometryID,
                            generation:1,contextGeneration:1,traversalEpoch:1)
                        let prepared=session.prepare(frame:frame,frameId:row.id,scope:scope)
                        let elapsed=(ProcessInfo.processInfo.systemUptime-started)*1000
                        let selected=prepared.presentation.visibleBoundaryIndices
                        invalidSelected+=selected.filter { !prepared.geometry.boundaries.indices.contains($0) }.count
                        let ids=selected.map { selectedIndex -> Int64 in prepared.presentation.items.first { $0.boundaryIndex==selectedIndex }?.trackId ?? -1 }
                        invalidSelected+=ids.filter { $0<0 }.count
                        let identitySet=ids.sorted()
                        if let previousIDs,previousIDs != identitySet { identityChanges+=1 }
                        previousIDs=identitySet
                        latencies.append(elapsed); filterTimes.append(prepared.filterMs); geometryTimes.append(prepared.geometryMs)
                        if prepared.geometry.budgetExceeded { operationRejects+=1 }
                        if elapsed>50 { targetMisses+=1 }
                        record["componentMs"]=elapsed; record["filterMs"]=prepared.filterMs; record["geometryMs"]=prepared.geometryMs
                        record["performanceTargetExceeded50Ms"]=elapsed>50; record["operationBudgetExceeded"]=prepared.geometry.budgetExceeded
                        record["operationCount"]=prepared.geometry.operationCount; record["temporalOperationCount"]=prepared.geometry.temporalOperationCount
                        record["selectedIndices"]=selected; record["visibleIds"]=ids; record["boundaries"]=boundaries(prepared.geometry.boundaries)
                        record["selectedBoundaries"]=boundaries(selected.compactMap { prepared.geometry.boundaries.indices.contains($0) ? prepared.geometry.boundaries[$0] : nil })
                        record["lanePresentation"]=prepared.presentation.diagnosticFields
                        record["lanePreparationDiagnostics"]=prepared.diagnostics.diagnosticFields
                    } else { record["rejectionReason"]="thermal_paused" }
                    var line=try JSONSerialization.data(withJSONObject:record,options:[.sortedKeys]); line.append(10)
                    try writer.write(contentsOf:line)
                    if index%10==0 { try writer.synchronize() }
                    wasPaused=paused
                }
                index+=1; next+=0.1
                // A stall drops cadence slots; never burst work to catch up.
                if next<ProcessInfo.processInfo.systemUptime { next=ProcessInfo.processInfo.systemUptime+0.1 }
            }
            if wasPaused { thermalPauseSeconds+=ProcessInfo.processInfo.systemUptime-lastTick }
            summaries[arm]=["admissions":index,"processedFrames":latencies.count,"loops":loops,
                "wallSeconds":ProcessInfo.processInfo.systemUptime-start,"componentMs":distribution(latencies),
                "filterMs":distribution(filterTimes),"geometryMs":distribution(geometryTimes),"performanceTargetExceeded50Ms":targetMisses,
                "operationBudgetExceeded":operationRejects,"identitySetChangesWithinSequences":identityChanges,"invalidSelectedIndices":invalidSelected,
                "peakSampledResidentBytes":maxRss,"memorySamples":memorySamples,"thermalPausedSeconds":thermalPauseSeconds,"thermalSamples":thermalCounts]
            XCTAssertEqual(invalidSelected,0,"Selected boundary indices must be valid")
        }
        let report:[String:Any]=["schemaVersion":1,"runId":runId,"completed":true,"platform":"iOS",
            "osVersion":ProcessInfo.processInfo.operatingSystemVersionString,"manifestSha256":sha(manifestData),
            "secondsPerArm":seconds,"sustained":seconds>=180,"fpsTarget":10,"arms":summaries,
            "scope":"Paced lane component replay; no camera, TSR, recorder, rendering or GNSS injection. Includes luma copy/filter/detection/tracking/presentation; excludes disk/integrity/JSON. Repeated exposures reset per sequence/loop. Thermal pause is this harness's serious-or-critical gate. RSS sampled once per second is process RSS, not exact peak, jetsam limit or physical footprint. Identity counts are diagnostics, not manually labelled accuracy."]
        try JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]).write(to:reportURL,options:.atomic)
        let attachment=XCTAttachment(contentsOfFile:reportURL); attachment.lifetime = .keepAlways; add(attachment)
    }
}
#endif
