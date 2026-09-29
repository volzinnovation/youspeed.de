import Foundation
import CryptoKit

// Experiment harness only. Link the unchanged production LaneDetection.swift and
// RoadBoundaryDetector.swift. Reads the supplied bytes exactly; performs no resampling,
// normalization, range conversion, masking, or temporal smoothing.
private struct InputFrame: Decodable {
    let id: String
    let sourceFrameId: String?
    let variant: String?
    let source: String?
    let grayPath: String
    let graySha256: String?
    let width: Int
    let height: Int
    let time: Double
}
private struct Manifest: Decodable {
    let schemaVersion: Int
    let frames: [InputFrame]
}
private struct Failure: Error, CustomStringConvertible { let description: String }

@main struct NativeBaseline {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count == 3 else {
            throw Failure(description: "usage: native-baseline manifest.json output.ndjson")
        }
        let manifestURL = URL(fileURLWithPath: args[1]).standardizedFileURL
        let manifest = try JSONDecoder().decode(Manifest.self, from: Data(contentsOf: manifestURL))
        guard manifest.schemaVersion == 1 else { throw Failure(description: "unsupported manifest schema") }
        let destination = URL(fileURLWithPath: args[2]).standardizedFileURL
        guard destination != manifestURL else { throw Failure(description: "output would overwrite input manifest") }
        guard !FileManager.default.fileExists(atPath: destination.path) else {
            throw Failure(description: "output already exists; choose a new filename")
        }
        guard FileManager.default.createFile(atPath: destination.path, contents: nil) else {
            throw Failure(description: "cannot create output")
        }
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        let roadDetector = RoadBoundaryDetector()
        let laneDetector = LaneDetector()
        var seen = Set<String>()
        func points(_ values: [LanePoint]) -> [[Double]] { values.map { [$0.x, $0.y] } }
        func legacyBoundary(_ value: LaneBoundary?) -> Any {
            guard let value else { return NSNull() }
            return ["confidence": value.confidence, "points": points(value.points)] as [String: Any]
        }
        for frame in manifest.frames {
            guard !frame.id.isEmpty, seen.insert(frame.id).inserted,
                  (64...640).contains(frame.width), (64...960).contains(frame.height), frame.time.isFinite else {
                throw Failure(description: "invalid or duplicate manifest frame: \(frame.id)")
            }
            let fileURL = frame.grayPath.hasPrefix("/") ? URL(fileURLWithPath: frame.grayPath) :
                manifestURL.deletingLastPathComponent().appendingPathComponent(frame.grayPath)
            let bytes = [UInt8](try Data(contentsOf: fileURL))
            guard bytes.count == frame.width * frame.height else {
                throw Failure(description: "raw byte length differs from width*height: \(frame.id)")
            }
            let digest = SHA256.hash(data: Data(bytes)).map { String(format: "%02x", $0) }.joined()
            guard frame.graySha256 == nil || frame.graySha256 == digest else {
                throw Failure(description: "input SHA256 differs from manifest: \(frame.id)")
            }
            let roadStart = ProcessInfo.processInfo.systemUptime
            let road = roadDetector.detect(grayscale: bytes, width: frame.width, height: frame.height,
                timestampSeconds: frame.time, shouldContinue: { ProcessInfo.processInfo.systemUptime - roadStart < 0.050 })
            let roadEnd = ProcessInfo.processInfo.systemUptime
            let legacy = laneDetector.detect(grayscale: bytes, width: frame.width, height: frame.height, timestampSeconds: frame.time)
            let legacyEnd = ProcessInfo.processInfo.systemUptime
            let boundaries: [[String: Any]] = road.boundaries.map {
                ["cue": $0.cue.rawValue, "confidence": $0.confidence, "supportRows": $0.supportRows, "points": points($0.points)]
            }
            let corridors: [[String: Any]] = road.corridors.map {
                ["leftBoundaryIndex": $0.leftBoundaryIndex, "rightBoundaryIndex": $0.rightBoundaryIndex,
                 "confidence": $0.confidence, "role": "unknown"]
            }
            let row: [String: Any] = [
                "schemaVersion": 1, "id": frame.id, "sourceFrameId": frame.sourceFrameId as Any? ?? NSNull(),
                "variant": frame.variant as Any? ?? NSNull(), "source": frame.source as Any? ?? NSNull(),
                "time": frame.time, "width": frame.width, "height": frame.height, "grayPath": fileURL.path,
                "inputByteCount": bytes.count,
                "inputSha256": digest,
                "road": ["boundaries": boundaries, "corridors": corridors, "budgetExceeded": road.budgetExceeded,
                         "operationCount": road.operationCount, "detectorMs": (roadEnd - roadStart) * 1000,
                         "inputAdmissible": frame.width <= 384 && frame.height <= 216],
                "legacy": ["left": legacyBoundary(legacy.left), "right": legacyBoundary(legacy.right),
                           "state": legacy.state.rawValue, "detectorMs": (legacyEnd - roadEnd) * 1000],
                "executionHost": "macOS native Swift, not Moto performance acceptance",
                "timingScope": "detector only; excludes input decode, resampling, variant preprocessing, JSON and display",
                "trackerApplied": false,
            ]
            var encoded = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            encoded.append(10)
            try handle.write(contentsOf: encoded)
        }
        print("wrote \(manifest.frames.count) unchanged-production detector comparisons to \(destination.path)")
    }
}
