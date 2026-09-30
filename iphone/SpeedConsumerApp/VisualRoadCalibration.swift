import Foundation

/// User-adjusted visual guides in the full, upright analysis image. These do not
/// establish metric intrinsics, camera attitude or authority over a sign.
struct VisualRoadCalibration: Equatable, Sendable, Codable {
    var horizonY: Double
    var leftBottom: LanePoint
    var leftTopX: Double
    var rightBottom: LanePoint
    var rightTopX: Double
    var revision: String
    var imageWidth: Int
    var imageHeight: Int
    var orientationKey: String

    static func defaults(width: Int, height: Int, orientationKey: String) -> Self {
        Self(horizonY: 0.42, leftBottom: LanePoint(x: 0, y: 1), leftTopX: 0.46,
             rightBottom: LanePoint(x: 1, y: 1), rightTopX: 0.54,
             revision: "draft", imageWidth: width, imageHeight: height, orientationKey: orientationKey)
    }

    var isValid: Bool {
        let values = [horizonY, leftBottom.x, leftBottom.y, leftTopX, rightBottom.x, rightBottom.y, rightTopX]
        return values.allSatisfy { $0.isFinite && (0...1).contains($0) }
            && imageWidth > 0 && imageHeight > 0 && !orientationKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !revision.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && horizonY >= 0.05 && horizonY <= 0.80
            && leftBottom.y >= horizonY + 0.05 && rightBottom.y >= horizonY + 0.05
            && leftTopX <= rightTopX && leftTopX <= 0.95 && leftBottom.x + 0.02 < rightBottom.x
    }

    func compatible(width: Int, height: Int, orientationKey: String) -> Bool {
        guard isValid, width > 0, height > 0, self.orientationKey == orientationKey else { return false }
        return abs(Double(width) / Double(height) - Double(imageWidth) / Double(imageHeight)) < 0.015
    }

    /// The selected upper-left x is the only cropped edge. Quantize once and
    /// use this exact pixel boundary to map inference boxes back to the source.
    func cropLeftPixels(width: Int) -> Int { max(0, min(width - 1, Int((leftTopX * Double(width)).rounded(.down)))) }

    mutating func move(step: Int, dx: Double, dy: Double) {
        func clamp(_ value: Double, _ low: Double, _ high: Double) -> Double { min(high, max(low, value)) }
        switch step {
        case 0:
            horizonY = clamp(horizonY + dy, 0.05, min(0.80, min(leftBottom.y, rightBottom.y) - 0.05))
        case 1:
            leftBottom = LanePoint(x: clamp(leftBottom.x + dx, 0, 1),
                                   y: clamp(leftBottom.y + dy, horizonY + 0.05, 1))
        case 2: leftTopX = clamp(leftTopX + dx, 0, 0.95)
        case 3:
            rightBottom = LanePoint(x: clamp(rightBottom.x + dx, 0, 1),
                                    y: clamp(rightBottom.y + dy, horizonY + 0.05, 1))
        case 4: rightTopX = clamp(rightTopX + dx, 0, 1)
        default: break
        }
    }

    private enum CodingKeys: String, CodingKey { case schemaVersion, horizonY, leftBottom, leftTopX, rightBottom, rightTopX, revision, imageWidth, imageHeight, orientationKey }
    private struct Point: Codable { let x: Double; let y: Double }
    init(horizonY: Double, leftBottom: LanePoint, leftTopX: Double, rightBottom: LanePoint, rightTopX: Double,
         revision: String, imageWidth: Int, imageHeight: Int, orientationKey: String) {
        self.horizonY = horizonY; self.leftBottom = leftBottom; self.leftTopX = leftTopX
        self.rightBottom = rightBottom; self.rightTopX = rightTopX; self.revision = revision
        self.imageWidth = imageWidth; self.imageHeight = imageHeight; self.orientationKey = orientationKey
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        guard try c.decode(Int.self, forKey: .schemaVersion) == 1 else { throw DecodingError.dataCorruptedError(forKey: .schemaVersion, in: c, debugDescription: "Unsupported calibration version") }
        let left = try c.decode(Point.self, forKey: .leftBottom), right = try c.decode(Point.self, forKey: .rightBottom)
        self.init(horizonY: try c.decode(Double.self, forKey: .horizonY), leftBottom: LanePoint(x: left.x, y: left.y),
                  leftTopX: try c.decode(Double.self, forKey: .leftTopX), rightBottom: LanePoint(x: right.x, y: right.y),
                  rightTopX: try c.decode(Double.self, forKey: .rightTopX), revision: try c.decode(String.self, forKey: .revision),
                  imageWidth: try c.decode(Int.self, forKey: .imageWidth), imageHeight: try c.decode(Int.self, forKey: .imageHeight),
                  orientationKey: try c.decode(String.self, forKey: .orientationKey))
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(1, forKey: .schemaVersion)
        try c.encode(horizonY, forKey: .horizonY); try c.encode(Point(x: leftBottom.x, y: leftBottom.y), forKey: .leftBottom)
        try c.encode(leftTopX, forKey: .leftTopX); try c.encode(Point(x: rightBottom.x, y: rightBottom.y), forKey: .rightBottom)
        try c.encode(rightTopX, forKey: .rightTopX); try c.encode(revision, forKey: .revision)
        try c.encode(imageWidth, forKey: .imageWidth); try c.encode(imageHeight, forKey: .imageHeight)
        try c.encode(orientationKey, forKey: .orientationKey)
    }
}

/// One immutable snapshot is read at frame admission; edits are never visible
/// until Save. UserDefaults is touched only at load/save, not on every frame.
final class VisualRoadCalibrationStore: @unchecked Sendable {
    static let defaultsKey = "youspeed.visual_road_calibration.v1"
    private let lock = NSLock()
    private let defaults: UserDefaults
    private var value: VisualRoadCalibration?
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: Self.defaultsKey),
           let decoded = try? JSONDecoder().decode(VisualRoadCalibration.self, from: data), decoded.isValid { value = decoded }
    }
    func snapshot() -> VisualRoadCalibration? { lock.lock(); defer { lock.unlock() }; return value }
    @discardableResult func save(_ calibration: VisualRoadCalibration) -> Bool {
        guard calibration.isValid, let data = try? JSONEncoder().encode(calibration) else { return false }
        lock.lock(); defer { lock.unlock() }
        defaults.set(data, forKey: Self.defaultsKey); value = calibration; return true
    }
}
