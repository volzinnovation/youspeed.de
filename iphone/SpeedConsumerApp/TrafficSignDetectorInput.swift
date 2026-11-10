import CoreGraphics
import CoreImage
import ImageIO

/// Centered letterbox for the upright camera frame.
struct TrafficSignDetectorGeometry {
    static let size = 1024
    let sourceWidth: Int
    let sourceHeight: Int
    var sourceWindow: CGRect? = nil

    var window: CGRect { sourceWindow ?? CGRect(x: 0, y: 0, width: sourceWidth, height: sourceHeight) }
    var scale: Double { Double(Self.size) / max(Double(window.width), Double(window.height)) }
    var scaledWidth: Double { Double(window.width) * scale }
    var scaledHeight: Double { Double(window.height) * scale }
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
        return CGRect(x: (window.minX + (clipped.minX - content.minX) / content.width * window.width) / Double(sourceWidth),
                      y: (window.minY + (clipped.minY - content.minY) / content.height * window.height) / Double(sourceHeight),
                      width: clipped.width / content.width * window.width / Double(sourceWidth),
                      height: clipped.height / content.height * window.height / Double(sourceHeight))
    }

    static func twoEdgeWindows(width: Int, height: Int) -> [CGRect] {
        precondition(width > 0 && height > 0)
        let whole = CGRect(x: 0, y: 0, width: width, height: height)
        guard width > height else { return [whole] }
        let edges = [CGRect(x: 0, y: 0, width: height, height: height),
                     CGRect(x: width - height, y: 0, width: height, height: height)]
        return width > 2 * height ? edges + [whole] : edges
    }
}

struct TrafficSignDetectorInput {
    let image: CGImage
    let uprightSource: CIImage
    let geometry: TrafficSignDetectorGeometry

    init(source: CIImage, orientation: CGImagePropertyOrientation, context: CIContext,
         window: CGRect? = nil) throws {
        uprightSource = Self.upright(source: source, orientation: orientation)
        let extent = uprightSource.extent
        guard extent.width > 0, extent.height > 0,
              extent.width.isFinite, extent.height.isFinite else {
            throw TrafficSignRuntimeUnavailability(code: .inferenceFailed, detail: "Invalid TSR image dimensions.")
        }
        if let window, window.isEmpty || !extent.contains(window) {
            throw TrafficSignRuntimeUnavailability(code: .inferenceFailed, detail: "Invalid TSR detector window.")
        }
        geometry = TrafficSignDetectorGeometry(sourceWidth: Int(extent.width), sourceHeight: Int(extent.height),
                                               sourceWindow: window)
        let square = CGRect(x: 0, y: 0, width: TrafficSignDetectorGeometry.size, height: TrafficSignDetectorGeometry.size)
        let scaled = uprightSource.cropped(to: geometry.window)
            .transformed(by: CGAffineTransform(translationX: -geometry.window.minX, y: -geometry.window.minY))
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
