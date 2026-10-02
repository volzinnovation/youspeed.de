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

/// Preview-only trust in saved image guides. Verification uses fresh paint found on
/// broad audit frames, never geometry predicted or selected using the saved guides.
struct RoadVisualGuideTrustSnapshot {
    let state, reason: String
    let independentAudit: Bool
    let matchedSides: Int
    let agreementCount: Int
    let leftResidual, rightResidual: Double?
    var diagnosticFields: [String: Any] {
        var fields: [String: Any] = ["state":state,"reason":reason,"independentAudit":independentAudit,
            "matchedSides":matchedSides,"agreementCount":agreementCount]
        if let leftResidual { fields["leftResidual"] = leftResidual }
        if let rightResidual { fields["rightResidual"] = rightResidual }
        return fields
    }
}
struct RoadVisualGuidePlan {
    let independentAudit: Bool
    let trusted: Bool
    let reason: String
}
final class RoadVisualGuideValidator {
    private var key: String?
    private var count = 0, agreements = 0
    private var firstAgreement: Double?, lastAgreement: Double?
    private var trusted = false
    private var reason = "awaiting_independent_paint"
    private(set) var snapshot = RoadVisualGuideTrustSnapshot(state:"unavailable",reason:"no_saved_guides",
        independentAudit:true,matchedSides:0,agreementCount:0,leftResidual:nil,rightResidual:nil)

    func begin(saved: VisualRoadCalibration?, compatible: VisualRoadCalibration?, time: Double, key: String) -> RoadVisualGuidePlan {
        if self.key != key { self.key=key; count=0; agreements=0; firstAgreement=nil; lastAgreement=nil; trusted=false; reason="awaiting_independent_paint" }
        count += 1
        if compatible == nil {
            trusted=false; agreements=0; firstAgreement=nil; lastAgreement=nil
            reason=saved == nil ? "no_saved_guides" : "incompatible_geometry"
        } else if let lastAgreement, time-lastAgreement > 1.0 {
            trusted=false; agreements=0; firstAgreement=nil; reason="independent_evidence_expired"
        }
        // A weak prior never changes the horizon, projection or ego-centre. Every
        // other exposure ignores it entirely; trusted guides are re-audited at 2 Hz.
        let audit = saved != nil && (compatible == nil || (trusted ? count % 5 == 0 : count % 2 == 1))
        return RoadVisualGuidePlan(independentAudit:audit,trusted:trusted,reason:reason)
    }

    func observe(_ boundaries: [RoadBoundaryEvidence], visual: VisualRoadCalibration?, time: Double,
                 plan: RoadVisualGuidePlan) -> RoadVisualGuideTrustSnapshot {
        var residuals: [Double?] = [nil,nil]
        var matched = 0
        if plan.independentAudit, let visual {
            // Choose the nearest observed border on each side of the image centre,
            // independently of the saved lane centre. Require substantial fresh paint.
            let candidates = boundaries.filter { $0.provenance == .fresh && $0.cue == .paint && $0.confidence >= 0.6 &&
                $0.points.count >= 2 && ($0.points.last!.y-$0.points.first!.y) >= 0.12 }
            for side in 0..<2 {
                let signed = candidates.filter { side == 0 ? $0.points.last!.x < 0.5 : $0.points.last!.x > 0.5 }
                guard let observed = signed.min(by: { abs($0.points.last!.x-0.5) < abs($1.points.last!.x-0.5) }) else { continue }
                let guide = [LanePoint(x:side == 0 ? visual.leftTopX : visual.rightTopX,y:visual.horizonY), side == 0 ? visual.leftBottom : visual.rightBottom]
                let low=max(observed.points.first!.y,guide[0].y), high=min(observed.points.last!.y,guide[1].y)
                guard high-low >= 0.10 else { continue }
                let errors = (0...2).map { i -> Double in
                    let y=low+(high-low)*Double(i)/2
                    return abs(roadBoundaryXAt(observed.points,y)-roadBoundaryXAt(guide,y))
                }.sorted()
                residuals[side]=errors[1]
                if errors[1] <= 0.055 && errors[2] <= 0.085 { matched += 1 }
            }
            if residuals.compactMap({$0}).contains(where:{$0 > 0.10}) {
                trusted=false; agreements=0; firstAgreement=nil; lastAgreement=nil; reason="observed_border_conflict"
            } else if matched == 2 {
                if firstAgreement == nil { firstAgreement=time }
                agreements += 1; lastAgreement=time
                trusted=agreements >= 3 && time-(firstAgreement ?? time) >= 0.2
                reason=trusted ? "independent_paint_agreement" : "confirming_independent_paint"
            } else {
                agreements=0; firstAgreement=nil
                if !trusted { reason="insufficient_independent_paint" }
            }
        }
        snapshot=RoadVisualGuideTrustSnapshot(state:visual == nil ? "unavailable" : trusted ? "trusted" : "weak",
            reason:reason,independentAudit:plan.independentAudit,matchedSides:matched,agreementCount:agreements,
            leftResidual:residuals[0],rightResidual:residuals[1])
        return snapshot
    }
}
