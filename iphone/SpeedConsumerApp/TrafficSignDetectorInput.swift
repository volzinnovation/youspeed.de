import CoreGraphics
import CoreImage
import ImageIO

/// Centered letterbox for the upright camera frame.
struct TrafficSignDetectorGeometry {
    static let size = 1024
    let sourceWidth: Int
    let sourceHeight: Int

    var scale: Double { Double(Self.size) / Double(max(sourceWidth, sourceHeight)) }
    var scaledWidth: Double { Double(sourceWidth) * scale }
    var scaledHeight: Double { Double(sourceHeight) * scale }
    var left: Double { (Double(Self.size) - scaledWidth) / 2 }
    var bottom: Double { (Double(Self.size) - scaledHeight) / 2 }

    /// Vision boxes use a bottom-left origin. Intersect with the image before
    /// normalizing to its extent so padding cannot produce a source proposal.
    func sourceRegion(for detectorRegion: CGRect) -> CGRect? {
        let content = CGRect(x: left, y: bottom, width: scaledWidth, height: scaledHeight)
        let pixels = detectorRegion.applying(CGAffineTransform(
            scaleX: CGFloat(Self.size), y: CGFloat(Self.size)))
        let clipped = pixels.intersection(content)
        guard !clipped.isEmpty else { return nil }
        return CGRect(x: (clipped.minX - content.minX) / content.width,
                      y: (clipped.minY - content.minY) / content.height,
                      width: clipped.width / content.width, height: clipped.height / content.height)
    }
}

struct TrafficSignDetectorInput {
    let image: CGImage
    let uprightSource: CIImage
    let geometry: TrafficSignDetectorGeometry

    init(source: CIImage, orientation: CGImagePropertyOrientation, context: CIContext) throws {
        uprightSource = Self.upright(source: source, orientation: orientation)
        let extent = uprightSource.extent
        guard extent.width > 0, extent.height > 0,
              extent.width.isFinite, extent.height.isFinite else {
            throw TrafficSignRuntimeUnavailability(code: .inferenceFailed, detail: "Invalid TSR image dimensions.")
        }
        geometry = TrafficSignDetectorGeometry(sourceWidth: Int(extent.width), sourceHeight: Int(extent.height))
        let square = CGRect(x: 0, y: 0, width: TrafficSignDetectorGeometry.size, height: TrafficSignDetectorGeometry.size)
        let scaled = uprightSource
            .transformed(by: CGAffineTransform(scaleX: geometry.scale, y: geometry.scale))
            .transformed(by: CGAffineTransform(translationX: geometry.left, y: geometry.bottom))
        let gray = CGFloat(114.0 / 255.0)
        let background = CIImage(color: CIColor(red: gray, green: gray, blue: gray)).cropped(to: square)
        guard let rendered = context.createCGImage(scaled.composited(over: background), from: square) else {
            throw TrafficSignRuntimeUnavailability(code: .inferenceFailed, detail: "The TSR detector image could not be rendered.")
        }
        image = rendered
    }

    static func upright(source: CIImage, orientation: CGImagePropertyOrientation) -> CIImage {
        let oriented = source.oriented(forExifOrientation: Int32(orientation.rawValue))
        return oriented.transformed(by: CGAffineTransform(
            translationX: -oriented.extent.minX, y: -oriented.extent.minY))
    }
}
