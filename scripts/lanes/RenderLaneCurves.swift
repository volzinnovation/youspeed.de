import Foundation

/// Offline presentation review: inputs contain normalized `boundaries[].points` arrays.
/// Compile with the production LaneDetection.swift and LaneBoundaryBezier.swift.
@main struct RenderLaneCurves {
    static func main() throws {
        let arguments = CommandLine.arguments
        guard arguments.count == 3 else {
            throw NSError(domain:"RenderLaneCurves",code:1,userInfo:[NSLocalizedDescriptionKey:"usage: render-lane-curves input.ndjson output.ndjson"])
        }
        let input = URL(fileURLWithPath:arguments[1]), output = URL(fileURLWithPath:arguments[2])
        guard input.standardizedFileURL != output.standardizedFileURL, !FileManager.default.fileExists(atPath:output.path) else {
            throw NSError(domain:"RenderLaneCurves",code:2,userInfo:[NSLocalizedDescriptionKey:"choose a new output file"])
        }
        let contents = try String(contentsOf:input,encoding:.utf8)
        var result = Data()
        for line in contents.split(separator:"\n") {
            var row = try JSONSerialization.jsonObject(with:Data(line.utf8)) as! [String:Any]
            let boundaries = row["boundaries"] as? [[String:Any]] ?? []
            row["renderCurves"] = boundaries.enumerated().map { index,boundary in
                let points = (boundary["points"] as? [[Double]] ?? []).filter { $0.count==2 }.map { LanePoint(x:$0[0],y:$0[1]) }
                let curves = LaneBoundaryBezier.fit(points)
                return ["boundaryIndex":index,"sourcePointCount":points.count,
                        "segments":curves.map { [$0.start,$0.control1,$0.control2,$0.end].map { [$0.x,$0.y] } }] as [String:Any]
            }
            row["renderMaximumDeviation"] = LaneBoundaryBezier.maximumDeviation
            row["renderMaximumGap"] = LaneBoundaryBezier.maximumGap
            result.append(try JSONSerialization.data(withJSONObject:row,options:[.sortedKeys])); result.append(10)
        }
        try result.write(to:output,options:.atomic)
    }
}
