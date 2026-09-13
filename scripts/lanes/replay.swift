import Foundation

@main
struct LaneReplay {
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            throw NSError(domain: "LaneReplay", code: 64, userInfo: [NSLocalizedDescriptionKey: "Expected fixture manifest TSV"])
        }
        let manifest = try String(contentsOfFile: CommandLine.arguments[1], encoding: .utf8)
        let detector = LaneDetector()
        var output: [[String: Any]] = []
        for row in manifest.split(separator: "\n") {
            let fields = row.split(separator: "\t").map(String.init)
            guard fields.count == 4, let width = Int(fields[1]), let height = Int(fields[2]) else {
                throw NSError(domain: "LaneReplay", code: 65)
            }
            let pixels = [UInt8](try Data(contentsOf: URL(fileURLWithPath: fields[3])))
            var tracker = LaneTracker()
            for frame in 0..<3 {
                let detection = detector.detect(grayscale: pixels, width: width, height: height, timestampSeconds: Double(frame) * 0.2)
                let estimate = tracker.update(detection)
                func boundary(_ value: LaneBoundary?) -> Any {
                    guard let value else { return NSNull() }
                    return ["confidence": value.confidence, "points": value.points.map { [$0.x, $0.y] }] as [String: Any]
                }
                output.append([
                    "case": fields[0], "frame": frame,
                    "state": estimate.state.rawValue.lowercased(),
                    "timestamp_seconds": estimate.timestampSeconds,
                    "corridor_points": estimate.corridorPoints.map { [$0.x, $0.y] },
                    "left": boundary(estimate.left), "right": boundary(estimate.right)
                ])
            }
        }
        let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
    }
}
