import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

struct SignCollectionCropGeometry {
    let supplied: [String: Double]
    let original: [Int]
    let requested: [Int]
    let actual: [Int]
    var wire: [String: Any] { ["supplied_box": supplied, "original_box": original, "requested_box": requested, "actual_box": actual,
                              "requested_extra_height": original[3] - original[1], "actual_extra_height": actual[3] - original[3], "bottom_clipped": actual != requested] }

    init(width: Int, height: Int, box: [String: Double]) throws {
        guard width > 0, height > 0, width <= 32768, height <= 32768, Set(box.keys) == Set(["x", "y", "width", "height"]),
              let x = box["x"], let y = box["y"], let w = box["width"], let h = box["height"],
              [x,y,w,h].allSatisfy(\.isFinite), x >= 0, y >= 0, w > 0, h > 0, x+w <= 1, y+h <= 1 else { throw SignCollectionError.invalidContract }
        supplied = box
        original = [Int(floor(x * Double(width))), Int(floor(y * Double(height))), min(width, Int(ceil((x+w) * Double(width)))), min(height, Int(ceil((y+h) * Double(height))))]
        guard original[2] > original[0], original[3] > original[1] else { throw SignCollectionError.invalidContract }
        requested = Array(original.prefix(3)) + [original[3] + original[3] - original[1]]
        actual = Array(original.prefix(3)) + [min(height, requested[3])]
        guard (actual[2] - actual[0]) * (actual[3] - actual[1]) <= 16_000_000 else { throw SignCollectionError.capacity }
    }
}

struct SignCollectionCrop {
    let geometry: SignCollectionCropGeometry
    let bytes: Data
    let sourceHash: String
    let sourceWidth: Int
    let sourceHeight: Int
    var encodedHash: String { SignCollectionJSON.sha256(bytes) }

    /// The caller supplies the exact representative frame, already orientation
    /// corrected into sRGB. No nearby Panoramax frame or EXIF metadata is reused.
    static func generate(upright: CGImage, box: [String: Double]) throws -> SignCollectionCrop {
        guard upright.colorSpace?.name == CGColorSpace.sRGB,
              [CGImageAlphaInfo.none, .noneSkipFirst, .noneSkipLast].contains(upright.alphaInfo) else { throw SignCollectionError.invalidContract }
        let geometry = try SignCollectionCropGeometry(width: upright.width, height: upright.height, box: box)
        let width = upright.width, height = upright.height
        guard width * height <= 32_000_000 else { throw SignCollectionError.capacity }
        var rgba = [UInt8](repeating: 0, count: width * height * 4)
        let color = CGColorSpace(name: CGColorSpace.sRGB)!
        guard let context = CGContext(data: &rgba, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4, space: color, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { throw SignCollectionError.storage }
        context.draw(upright, in: CGRect(x: 0, y: 0, width: width, height: height))
        var rgb = Data(capacity: width * height * 3)
        for offset in stride(from: 0, to: rgba.count, by: 4) { rgb.append(contentsOf: rgba[offset..<offset+3]) }
        guard let normalized = context.makeImage(), let cropped = normalized.cropping(to: CGRect(x: geometry.actual[0], y: geometry.actual[1], width: geometry.actual[2]-geometry.actual[0], height: geometry.actual[3]-geometry.actual[1])) else { throw SignCollectionError.storage }
        let bytes = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(bytes, UTType.png.identifier as CFString, 1, nil) else { throw SignCollectionError.storage }
        // Fresh encoding with empty metadata; no GPS, timestamp, EXIF or source tags.
        CGImageDestinationAddImage(destination, cropped, [:] as CFDictionary)
        guard CGImageDestinationFinalize(destination), bytes.length <= 5 * 1024 * 1024 else { throw SignCollectionError.capacity }
        return SignCollectionCrop(geometry: geometry, bytes: try privatePNG(bytes as Data), sourceHash: SignCollectionJSON.sha256(rgb), sourceWidth: width, sourceHeight: height)
    }

    /// ImageIO can insert sRGB/ICC ancillary chunks even with empty properties.
    /// Backend intake rejects embedded metadata; retain only critical PNG chunks.
    private static func privatePNG(_ bytes: Data) throws -> Data {
        let input = Array(bytes)
        guard input.count >= 8, Array(input.prefix(8)) == [137,80,78,71,13,10,26,10] else { throw SignCollectionError.invalidContract }
        var output = Data(input.prefix(8)); var offset = 8
        while offset < input.count {
            guard offset + 12 <= input.count else { throw SignCollectionError.invalidContract }
            let length = input[offset..<offset+4].reduce(0) { ($0 << 8) | Int($1) }
            guard length <= input.count - offset - 12 else { throw SignCollectionError.invalidContract }
            let type = String(decoding: input[offset+4..<offset+8], as: UTF8.self)
            if ["IHDR", "PLTE", "IDAT", "IEND"].contains(type) { output.append(contentsOf: input[offset..<offset+12+length]) }
            else if input[offset+4] & 32 == 0 { throw SignCollectionError.invalidContract }
            offset += length + 12
        }
        return output
    }

    func metadata(cropID: String, observationID: String, installationID: String, epoch: Int, sourceKind: String, frameAt: Date,
                  localFrameToken: String?, privacyPreflight: String, redactionVersion: String, collectionClaim: SignCollectionClaim,
                  processorClaim: SignCollectionClaim? = nil) -> [String: Any] {
        var result = geometry.wire
        result.merge(["schema_version": 1, "crop_id": cropID, "observation_id": observationID, "installation_id": installationID, "collection_epoch": epoch,
                      "source_kind": sourceKind, "source_frame_at": SignCollectionJSON.utc(frameAt), "source_width": sourceWidth, "source_height": sourceHeight,
                      "source_upright_sha256": sourceHash, "local_frame_token": localFrameToken as Any? ?? NSNull(), "encoded_sha256": encodedHash, "byte_length": bytes.count,
                      "decoded_width": geometry.actual[2]-geometry.actual[0], "decoded_height": geometry.actual[3]-geometry.actual[1], "encoding": "PNG",
                      "orientation_version": "upright-1", "crop_version": "downward-1", "redaction_version": redactionVersion, "redaction_masks": [],
                      "privacy_preflight": privacyPreflight, "collection_authorization": collectionClaim.wire, "processor_authorization": processorClaim?.wire as Any? ?? NSNull()]) { _, new in new }
        return result
    }
}

/// Retains the analyzed buffer only until the bounded storage task completes.
final class SignCollectionFrame: @unchecked Sendable, Equatable {
    let token: String
    let image: () throws -> CGImage
    init(token: String, image: @escaping () throws -> CGImage) { self.token = token; self.image = image }
    static func == (lhs: SignCollectionFrame, rhs: SignCollectionFrame) -> Bool { lhs.token == rhs.token }
}
