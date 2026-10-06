import AVFoundation
import Foundation

@main struct ProbeDashcam {
    static func main() async {
        do { try await run() }
        catch {
            FileHandle.standardError.write(Data("Probe failed: \(error)\n".utf8))
            exit(1)
        }
    }

    private static func run() async throws {
        guard CommandLine.arguments.count == 2 else { throw CocoaError(.fileReadInvalidFileName) }
        let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
        let duration = try await asset.load(.duration).seconds
        let tracks = try await asset.loadTracks(withMediaType: .video)
        guard let track = tracks.first, duration.isFinite, duration > 0 else { throw CocoaError(.fileReadCorruptFile) }
        let size = try await track.load(.naturalSize)
        let transform = try await track.load(.preferredTransform)
        let upright = CGRect(origin: .zero, size: size).applying(transform)
        let fps = try await track.load(.nominalFrameRate)
        let value: [String: Any] = ["duration_seconds": duration, "encoded_width": Int(size.width),
            "encoded_height": Int(size.height), "upright_width": Int(abs(upright.width)),
            "upright_height": Int(abs(upright.height)), "nominal_fps": fps, "probe": "AVFoundation"]
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }
}
