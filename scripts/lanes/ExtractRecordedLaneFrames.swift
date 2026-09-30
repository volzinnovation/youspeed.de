// Offline diagnostic extraction: never accesses an app or changes its recordings.
// swiftc -O -parse-as-library ExtractRecordedLaneFrames.swift -o extract-lane-frames
// extract-lane-frames source.mp4 output-directory source-name step-seconds
import Foundation
import AVFoundation
import CoreImage
import CryptoKit
import ImageIO
import UniformTypeIdentifiers

private struct ExtractionFailure: Error { let reason: String }

@main struct ExtractRecordedLaneFrames {
    static func main() async throws {
        let args = CommandLine.arguments
        guard args.count == 5, let step = Double(args[4]), step.isFinite, step >= 0.1,
              args[3].range(of: "^[a-zA-Z0-9_-]+$", options: .regularExpression) != nil else {
            throw ExtractionFailure(reason: "usage: extract-lane-frames source.mp4 new-output-directory source-name step-seconds")
        }
        let source = URL(fileURLWithPath: args[1]).standardizedFileURL
        let folder = URL(fileURLWithPath: args[2], isDirectory: true).standardizedFileURL
        guard !FileManager.default.fileExists(atPath: folder.path) else {
            throw ExtractionFailure(reason: "Output exists; preserve earlier evidence with a new directory")
        }
        let asset = AVURLAsset(url: source)
        guard let track = try await asset.loadTracks(withMediaType: .video).first else {
            throw ExtractionFailure(reason: "No video track")
        }
        // These Moto recordings are upright. Refuse silently mismapped replay geometry.
        guard try await track.load(.preferredTransform) == .identity else {
            throw ExtractionFailure(reason: "Nonidentity video orientation requires explicit mapping")
        }
        let duration = try await asset.load(.duration).seconds
        let reader = try AVAssetReader(asset: asset)
        let output = AVAssetReaderTrackOutput(track: track, outputSettings: [
            kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
        ])
        output.alwaysCopiesSampleData = false
        reader.add(output)
        guard reader.startReading() else { throw reader.error ?? ExtractionFailure(reason: "Reader failed") }
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let context = CIContext(options: [.cacheIntermediates: false])
        var frames: [[String: Any]] = []
        var index = 0
        while let sample = output.copyNextSampleBuffer() {
            let pts = CMSampleBufferGetPresentationTimeStamp(sample)
            guard pts.seconds >= Double(index) * step else { continue }
            try autoreleasepool {
                guard let pixel = CMSampleBufferGetImageBuffer(sample) else {
                    throw ExtractionFailure(reason: "Missing decoded pixel buffer")
                }
                CVPixelBufferLockBaseAddress(pixel, .readOnly)
                defer { CVPixelBufferUnlockBaseAddress(pixel, .readOnly) }
                let w = CVPixelBufferGetWidthOfPlane(pixel, 0), h = CVPixelBufferGetHeightOfPlane(pixel, 0)
                let row = CVPixelBufferGetBytesPerRowOfPlane(pixel, 0)
                let width = min(384, Int((Double(w) * min(384.0 / Double(w), 216.0 / Double(h))).rounded()))
                let height = min(216, Int((Double(h) * min(384.0 / Double(w), 216.0 / Double(h))).rounded()))
                guard width >= 64, height >= 64, let address = CVPixelBufferGetBaseAddressOfPlane(pixel, 0) else {
                    throw ExtractionFailure(reason: "Unsupported source dimensions")
                }
                let base = address.assumingMemoryBound(to: UInt8.self)
                var gray = [UInt8](repeating: 0, count: width * height)
                for y in 0..<height {
                    let sy = min(h - 1, Int((Double(y) + 0.5) / Double(height) * Double(h)))
                    for x in 0..<width {
                        let sx = min(w - 1, Int((Double(x) + 0.5) / Double(width) * Double(w)))
                        gray[y * width + x] = base[sy * row + sx]
                    }
                }
                let id = String(format: "%@-%06d", args[3], index)
                let grayName = id + ".gray", rgbName = id + ".jpg"
                let bytes = Data(gray)
                try bytes.write(to: folder.appendingPathComponent(grayName))
                let scale = min(640.0 / Double(w), 360.0 / Double(h), 1)
                let scene = CIImage(cvPixelBuffer: pixel).transformed(by: CGAffineTransform(scaleX: scale, y: scale))
                guard let rgb = context.createCGImage(scene, from: scene.extent),
                      let writer = CGImageDestinationCreateWithURL(folder.appendingPathComponent(rgbName) as CFURL,
                          UTType.jpeg.identifier as CFString, 1, nil) else {
                    throw ExtractionFailure(reason: "RGB export failed")
                }
                CGImageDestinationAddImage(writer, rgb, [kCGImageDestinationLossyCompressionQuality: 0.88] as CFDictionary)
                guard CGImageDestinationFinalize(writer) else { throw ExtractionFailure(reason: "JPEG write failed") }
                frames.append(["id": id, "sequenceId": args[3], "source": args[3], "time": pts.seconds,
                    "ptsValue": pts.value, "ptsTimescale": pts.timescale, "requestedTime": Double(index) * step,
                    "grayPath": grayName, "rgbPath": rgbName, "width": width, "height": height,
                    "decodedWidth": w, "decodedHeight": h,
                    "graySha256": SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()])
                index += 1
                if index % 500 == 0 { print("\(args[3]): \(index) frames, PTS \(pts.seconds)"); fflush(stdout) }
            }
        }
        guard reader.status == .completed else { throw reader.error ?? ExtractionFailure(reason: "Incomplete decode") }
        let file = try FileHandle(forReadingFrom: source)
        defer { try? file.close() }
        var hash = SHA256()
        while let chunk = try file.read(upToCount: 1_048_576), !chunk.isEmpty { hash.update(data: chunk) }
        let manifest: [String: Any] = ["schemaVersion": 1, "sourceVideo": source.path,
            "sourceVideoSha256": hash.finalize().map { String(format: "%02x", $0) }.joined(),
            "durationSeconds": duration, "requestedStepSeconds": step,
            "sampling": "AVAssetReader limited-range NV12 luma; nearest source pixel centre; upright identity transform; original encoded PTS",
            "qualification": "Offline encoded-video replay; no verified live crop, UTC/GPS or calibration mapping. Decode/sampling excluded from native pipeline timing.",
            "frames": frames]
        try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
            .write(to: folder.appendingPathComponent("dataset.json"), options: .atomic)
        print("Exported \(frames.count) frames, duration \(duration), to \(folder.path)")
    }
}
