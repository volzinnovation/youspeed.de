// Offline macOS development-corpus extraction. No app/device state is accessed.
// Build: xcrun swiftc -O -parse-as-library extract_dashcam_geometry_frames.swift -o /tmp/extract-dashcam-geometry
// Run: /tmp/extract-dashcam-geometry /absolute/source.mov /absolute/output name:startSeconds:endSeconds [...]
// Requests frames every 0.2 seconds; preserves actual rational presentation timestamps.
import Foundation
import AVFoundation
import CryptoKit
import ImageIO
import UniformTypeIdentifiers

enum ExtractionError: Error { case invalidArguments(String), invalidFrame(String), writeFailed(String) }

func sha256(_ url: URL) throws -> String {
    let stream = try FileHandle(forReadingFrom: url)
    defer { try? stream.close() }
    var hasher = SHA256()
    while let chunk = try stream.read(upToCount: 1_048_576), !chunk.isEmpty { hasher.update(data: chunk) }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
}

@main struct ExtractDashcamGeometryFrames {
    static func main() async throws {
        let args = CommandLine.arguments
        guard args.count >= 4 else {
            throw ExtractionError.invalidArguments("Usage: extract-dashcam-geometry /absolute/source.mov /absolute/output name:startSeconds:endSeconds [...]")
        }
        let source = URL(fileURLWithPath: args[1]).standardizedFileURL
        let output = URL(fileURLWithPath: args[2], isDirectory: true).standardizedFileURL
        let asset = AVURLAsset(url: source)
        let duration = try await asset.load(.duration)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        guard let track = tracks.first else { throw ExtractionError.invalidArguments("No video track") }
        let transform = try await track.load(.preferredTransform)
        let originalSize = try await track.load(.naturalSize)
        let rate = try await track.load(.nominalFrameRate)
        let hash = try sha256(source)
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 960, height: 540)
        generator.requestedTimeToleranceBefore = .zero
        generator.requestedTimeToleranceAfter = .zero
        let framesDirectory = output.appendingPathComponent("frames", isDirectory: true)
        try FileManager.default.createDirectory(at: framesDirectory, withIntermediateDirectories: true)
        var frames: [[String: Any]] = []
        var selections: [[String: Any]] = []
        var usedNames = Set<String>()
        for argument in args.dropFirst(3) {
            let parts = argument.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
            guard parts.count == 3, let start = Double(parts[1]), let end = Double(parts[2]),
                  start.isFinite, end.isFinite, start >= 0, end >= start, end < duration.seconds,
                  parts[0].range(of: "^[a-z0-9-]+$", options: .regularExpression) != nil,
                  usedNames.insert(parts[0]).inserted else {
                throw ExtractionError.invalidArguments("Invalid range: \(argument)")
            }
            let name = parts[0]
            let startTick = Int64((start * 5).rounded())
            let endTick = Int64((end * 5).rounded())
            guard abs(Double(startTick) / 5 - start) < 1e-9, abs(Double(endTick) / 5 - end) < 1e-9 else {
                throw ExtractionError.invalidArguments("Range endpoints must lie on the 0.2-second grid: \(argument)")
            }
            selections.append(["clip_id": name, "requested_start_seconds": start, "requested_end_seconds": end])
            for tick in startTick...endTick {
                let requested = CMTime(value: tick, timescale: 5)
                let result = try await generator.image(at: requested)
                let actual = result.actualTime
                guard actual.isValid, actual.isNumeric, actual.timescale > 0 else {
                    throw ExtractionError.invalidFrame("Invalid actual PTS at \(tick)/5")
                }
                let frameID = String(format: "%@-%07.1f", name, requested.seconds)
                let target = framesDirectory.appendingPathComponent(frameID + ".jpg")
                guard let writer = CGImageDestinationCreateWithURL(target as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
                    throw ExtractionError.writeFailed(target.path)
                }
                CGImageDestinationAddImage(writer, result.image, [kCGImageDestinationLossyCompressionQuality: 0.95] as CFDictionary)
                guard CGImageDestinationFinalize(writer) else { throw ExtractionError.writeFailed(target.path) }
                frames.append([
                    "frame_id": frameID, "image_path": target.path, "image_sha256": try sha256(target),
                    "pts_seconds": actual.seconds, "pts_value": actual.value, "pts_timescale": actual.timescale,
                    "requested_seconds": requested.seconds, "requested_value": requested.value, "requested_timescale": requested.timescale,
                    "projection": "rectilinear", "orientation_applied": true, "clip_id": name,
                    "capture_utc": NSNull(), "physical_track_confirmed": false,
                    "width": result.image.width, "height": result.image.height
                ])
            }
        }
        let info: [String: Any] = [
            "schema_version": 1, "source_video_path": source.path, "source_video_sha256": hash,
            "source_video_bytes": try FileManager.default.attributesOfItem(atPath: source.path)[.size]!,
            "duration_seconds": duration.seconds, "duration_value": duration.value, "duration_timescale": duration.timescale,
            "source_width": originalSize.width, "source_height": originalSize.height, "source_nominal_fps": rate,
            "source_preferred_transform": ["a": transform.a, "b": transform.b, "c": transform.c, "d": transform.d, "tx": transform.tx, "ty": transform.ty],
            "source_orientation_handling": "AVAssetImageGenerator.appliesPreferredTrackTransform=true; applied once before JPEG export",
            "extraction": "AVAssetImageGenerator zero requested time tolerance; 5 Hz requests; actual rational PTS retained. 960x540 maximum size, JPEG quality 0.95.",
            "latency_scope": "Offline decode, preferred-transform application, AVFoundation downscale and JPEG encode are excluded from subsequent image-extractor timing; that timing is not full device decision latency.",
            "capture_utc": NSNull(), "capture_utc_status": "No UTC clock mapping is assumed or inferred from filename/container creation time.",
            "qualification": "Development replay inputs; ranges chosen separately by reviewer. No road labels or physical track identities are inferred by this extractor.",
            "selections": selections, "frames": frames
        ]
        let json = try JSONSerialization.data(withJSONObject: info, options: [.prettyPrinted, .sortedKeys])
        try json.write(to: output.appendingPathComponent("frame-manifest.json"), options: .atomic)
        print("frames=\(frames.count) duration=\(duration.seconds) output=\(output.path)")
    }
}
