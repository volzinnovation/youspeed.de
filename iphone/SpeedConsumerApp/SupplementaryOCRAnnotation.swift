import Foundation

/// Immutable OCR provenance for collection only. Raw text never replaces the
/// detector/classifier label and this DTO has no camera or road-rule dependency.
struct SupplementaryOCRAnnotation: Equatable, Sendable {
    enum Status: String, Sendable { case read, noText = "no_text", failed }
    struct Box: Equatable, Sendable {
        let x: Double, y: Double, width: Double, height: Double
        var valid: Bool {
            [x, y, width, height].allSatisfy(\.isFinite) && x >= 0 && y >= 0
                && width > 0 && height > 0 && x + width <= 1 && y + height <= 1
        }
        var wire: [String: Double] { ["x": x, "y": y, "width": width, "height": height] }
    }
    struct ParsedTimeWindow: Equatable, Sendable {
        let startMinutes: Int, endMinutes: Int
        var wire: [String: Int] { ["start_minutes": startMinutes, "end_minutes": endMinutes] }
    }
    let primaryClassID: String
    let primarySpeedKmh: Int?
    let physicalSignID: String
    let frameID: String
    let observedAt: Date
    let firstSeenAt: Date
    let rawText: String?
    let status: Status
    let primaryBox: Box
    let ocrBox: Box?
    let engine: String
    let modelVersion: String
    let parsedTimeWindow: ParsedTimeWindow?

    init?(primaryClassID: String, primarySpeedKmh: Int?, physicalSignID: String, frameID: String,
          observedAt: Date, firstSeenAt: Date, rawText: String?, status: Status,
          primaryBox: Box, ocrBox: Box?, engine: String, modelVersion: String,
          parsedTimeWindow: ParsedTimeWindow?) {
        let textFields = [primaryClassID, physicalSignID, frameID, engine, modelVersion]
        guard textFields.allSatisfy({ !$0.isEmpty && $0.unicodeScalars.count <= 160 }),
              primarySpeedKmh.map({ (1...1000).contains($0) }) != false, primaryBox.valid, ocrBox?.valid != false,
              observedAt.timeIntervalSince1970.isFinite, firstSeenAt.timeIntervalSince1970.isFinite,
              firstSeenAt <= observedAt,
              rawText.map({ !$0.isEmpty && $0.unicodeScalars.count <= 4096 }) != false,
              status != .read || rawText != nil,
              parsedTimeWindow.map({ (0..<1440).contains($0.startMinutes) && (0..<1440).contains($0.endMinutes) }) != false else { return nil }
        self.primaryClassID = primaryClassID; self.primarySpeedKmh = primarySpeedKmh
        self.physicalSignID = physicalSignID; self.frameID = frameID
        self.observedAt = observedAt; self.firstSeenAt = firstSeenAt
        self.rawText = rawText; self.status = status; self.primaryBox = primaryBox; self.ocrBox = ocrBox
        self.engine = engine; self.modelVersion = modelVersion; self.parsedTimeWindow = parsedTimeWindow
    }

    var wire: [String: Any] {
        ["schema_version": 1, "primary_class_id": primaryClassID, "primary_speed_kmh": primarySpeedKmh as Any? ?? NSNull(),
         "physical_sign_id": physicalSignID, "frame_id": frameID,
         "observed_at": SignCollectionJSON.utc(observedAt), "first_seen_at": SignCollectionJSON.utc(firstSeenAt),
         "raw_text": rawText as Any? ?? NSNull(), "status": status.rawValue,
         "normalized_primary_box": primaryBox.wire, "normalized_ocr_box": ocrBox?.wire as Any? ?? NSNull(),
         "engine": engine, "model_version": modelVersion,
         "parsed_time_window": parsedTimeWindow?.wire as Any? ?? NSNull()]
    }

    func matches(modelLabel: String, speedKmh: Int?, box: [Double]) -> Bool {
        guard primaryClassID == modelLabel, primarySpeedKmh == nil || primarySpeedKmh == speedKmh, box.count == 4,
              box.allSatisfy(\.isFinite), box[2] > 0, box[3] > 0 else { return false }
        let intersection = max(0, min(primaryBox.x + primaryBox.width, box[0] + box[2]) - max(primaryBox.x, box[0]))
            * max(0, min(primaryBox.y + primaryBox.height, box[1] + box[3]) - max(primaryBox.y, box[1]))
        return intersection / max(1e-12, primaryBox.width * primaryBox.height + box[2] * box[3] - intersection) >= 0.2
    }
}
