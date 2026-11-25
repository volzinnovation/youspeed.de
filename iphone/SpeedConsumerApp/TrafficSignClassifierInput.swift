import CoreGraphics
import CoreImage

enum TrafficSignClassifierInput {
    static let size = 224
    static let preprocessingVersion = "crop-fit-letterbox-rgb-224-min-aspect-0.8-v1"
    static let resizeMode = "scale_fit_letterbox"

    /// Vision boxes have a bottom-left origin. Check the tight box in source pixels.
    static func sourceCrop(for box: CGRect, in extent: CGRect) -> CGRect? {
        let width = box.width * extent.width
        let height = box.height * extent.height
        guard width > 0, height > 0, width >= height * 0.8 else { return nil }
        return CGRect(x: extent.minX + box.minX * extent.width, y: extent.minY + box.minY * extent.height,
                      width: width, height: height)
    }

    static func image(source: CIImage, crop: CGRect, context: CIContext) -> CGImage? {
        let square = CGRect(x: 0, y: 0, width: size, height: size)
        let scale = square.width / max(crop.width, crop.height)
        let left = (square.width - crop.width * scale) / 2
        let bottom = (square.height - crop.height * scale) / 2
        let scaled = source.cropped(to: crop).transformed(by: CGAffineTransform(
            a: scale, b: 0, c: 0, d: scale, tx: left - crop.minX * scale, ty: bottom - crop.minY * scale))
        let background = CIImage(color: .black).cropped(to: square)
        return context.createCGImage(scaled.composited(over: background), from: square)
    }
}
