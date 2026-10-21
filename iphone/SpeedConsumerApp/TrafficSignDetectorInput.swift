import CoreGraphics
import CoreImage
import ImageIO

/// Mobile detector window in the upright image, independent of mounting/lane calibration.
/// Scale to height 1024, then retain the rightmost 1024 columns. Narrow images
/// are right-aligned with gray padding on the left instead of being stretched.
struct TrafficSignDetectorGeometry {
    static let size = 1024
    let sourceWidth: Int
    let sourceHeight: Int

    var scale: Double { Double(Self.size) / Double(sourceHeight) }
    var scaledWidth: Double { Double(sourceWidth) * scale }
    var left: Double { scaledWidth - Double(Self.size) }
}

struct TrafficSignDetectorInput {
    let image: CGImage
    let geometry: TrafficSignDetectorGeometry

    init(source: CIImage, orientation: CGImagePropertyOrientation, context: CIContext) throws {
        let upright = source.oriented(forExifOrientation: Int32(orientation.rawValue))
        let extent = upright.extent
        guard extent.width > 0, extent.height > 0,
              extent.width.isFinite, extent.height.isFinite else {
            throw TrafficSignRuntimeUnavailability(code: .inferenceFailed, detail: "Invalid TSR image dimensions.")
        }
        geometry = TrafficSignDetectorGeometry(sourceWidth: Int(extent.width), sourceHeight: Int(extent.height))
        let square = CGRect(x: 0, y: 0, width: TrafficSignDetectorGeometry.size, height: TrafficSignDetectorGeometry.size)
        let scaled = upright
            .transformed(by: CGAffineTransform(translationX: -extent.minX, y: -extent.minY))
            .transformed(by: CGAffineTransform(scaleX: geometry.scale, y: geometry.scale))
            .transformed(by: CGAffineTransform(translationX: -geometry.left, y: 0))
        let gray = CGFloat(114.0 / 255.0)
        let background = CIImage(color: CIColor(red: gray, green: gray, blue: gray)).cropped(to: square)
        guard let rendered = context.createCGImage(scaled.composited(over: background), from: square) else {
            throw TrafficSignRuntimeUnavailability(code: .inferenceFailed, detail: "The TSR detector window could not be rendered.")
        }
        image = rendered
    }

    /// The same window at native resolution for upload crops. No resizing;
    /// normalized window boxes continue to address the exact sampled pixels.
    static func nativeWindow(source: CIImage, orientation: CGImagePropertyOrientation) -> CIImage {
        let upright = source.oriented(forExifOrientation: Int32(orientation.rawValue))
        let extent = upright.extent
        let square = CGRect(x: 0, y: 0, width: extent.height, height: extent.height)
        let pixels = upright.transformed(by: CGAffineTransform(
            translationX: -extent.maxX + extent.height, y: -extent.minY))
        let gray = CGFloat(114.0 / 255.0)
        return pixels.composited(over: CIImage(color: CIColor(red: gray, green: gray, blue: gray)))
            .cropped(to: square)
    }
}
