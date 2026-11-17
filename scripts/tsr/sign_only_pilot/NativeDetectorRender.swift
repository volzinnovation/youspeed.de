import Foundation
import CoreGraphics
import CoreImage
import CryptoKit
import ImageIO
import UniformTypeIdentifiers

// Standalone error shim only. Compile the actual app input/geometry source
// alongside this executable; do not duplicate or modify its rendering logic.
struct TrafficSignRuntimeUnavailability: Error {
    enum Code { case inferenceFailed }
    let code: Code
    let detail: String
}

private func digest(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
}

@main
struct NativeDetectorRender {
    static func main() throws {
        guard CommandLine.arguments.count == 4 else {
            throw NSError(domain: "usage: render input.json outputDirectory actualAppSource.swift", code: 1)
        }
        let source = URL(fileURLWithPath: CommandLine.arguments[1])
        let output = URL(fileURLWithPath: CommandLine.arguments[2])
        let helper = URL(fileURLWithPath: CommandLine.arguments[3])
        let inputs = try JSONSerialization.jsonObject(with: Data(contentsOf: source)) as! [[String: Any]]
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: false)
        let context = CIContext(options: [.cacheIntermediates: false])
        var rows: [[String: Any]] = []
        for row in inputs {
            let bytes = try Data(contentsOf: URL(fileURLWithPath: row["local_path"] as! String))
            precondition(digest(bytes) == row["image_sha256"] as! String)
            let imageSource = CGImageSourceCreateWithData(bytes as CFData, nil)!
            let properties = CGImageSourceCopyPropertiesAtIndex(imageSource, 0, nil) as? [CFString: Any]
            precondition((properties?[kCGImagePropertyOrientation] as? Int ?? 1) == 1)
            let cg = CGImageSourceCreateImageAtIndex(imageSource, 0, nil)!
            let image = CIImage(cgImage: cg)
            let id = row["image_id"] as! String
            let whole = CGRect(x: 0, y: 0, width: cg.width, height: cg.height)
            for mode in ["whole", "phone_windows"] {
                let windows = mode == "whole" ? [whole] : TrafficSignDetectorGeometry.twoEdgeWindows(width: cg.width, height: cg.height)
                for (index, window) in windows.enumerated() {
                    let rendered = try TrafficSignDetectorInput(source: image, orientation: .up, context: context, window: window)
                    let name = "\(id)-\(mode)-\(index).png"
                    let path = output.appendingPathComponent(name)
                    let destination = CGImageDestinationCreateWithURL(path as CFURL, UTType.png.identifier as CFString, 1, nil)!
                    CGImageDestinationAddImage(destination, rendered.image, nil)
                    precondition(CGImageDestinationFinalize(destination))
                    rows.append(["image_id": id, "source_sha256": row["image_sha256"]!, "mode": mode,
                                 "pass_index": index, "window_xyxy": [window.minX, window.minY, window.maxX, window.maxY],
                                 "path": name, "sha256": digest(try Data(contentsOf: path)),
                                 "width": rendered.image.width, "height": rendered.image.height])
                }
            }
        }
        let manifest: [String: Any] = [
            "schema": "streetshots-native-detector-inputs-v1", "source_images": inputs.count,
            "renderer": "Actual iPhone TrafficSignDetectorInput.swift compiled unchanged on macOS; Core Image default context",
            "app_source_sha256": digest(try Data(contentsOf: helper)),
            "wrapper_sha256": digest(try Data(contentsOf: URL(fileURLWithPath: #filePath))),
            "operating_system": ProcessInfo.processInfo.operatingSystemVersionString,
            "iphone_pixel_parity_verified": false,
            "limitation": "Uses the app rendering source and stored upright image bytes on macOS; camera decoding, iOS GPU and Core ML inference are not replicated.",
            "frames": rows]
        try JSONSerialization.data(withJSONObject: manifest, options: [.prettyPrinted, .sortedKeys])
            .write(to: output.appendingPathComponent("manifest.json"))
        print("Rendered \(rows.count) inputs for \(inputs.count) development images")
    }
}
