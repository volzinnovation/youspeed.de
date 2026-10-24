import CoreGraphics
import CoreText
import Foundation
@preconcurrency import Vision

/// Presentation evidence only. This value is never a speed-limit rule or model-stage output.
struct TrafficSignSupplementaryTimeWindow: Equatable, Hashable, Sendable {
    let startMinutes: Int
    let endMinutes: Int

    init?(startMinutes: Int, endMinutes: Int) {
        guard (0..<1440).contains(startMinutes), (0..<1440).contains(endMinutes),
              startMinutes != endMinutes else { return nil }
        self.startMinutes = startMinutes
        self.endMinutes = endMinutes
    }

    var crossesMidnight: Bool { startMinutes > endMinutes }
    var displayText: String {
        func time(_ minutes: Int) -> String {
            minutes % 60 == 0 ? "\(minutes / 60)" : String(format: "%d:%02d", minutes / 60, minutes % 60)
        }
        return "\(time(startMinutes))–\(time(endMinutes)) h"
    }

    /// Accept a whole time expression, never extract numbers from arbitrary prose.
    static func parse(_ raw: String) -> Self? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.count <= 40,
              let expression = try? NSRegularExpression(
                pattern: #"^(\d{1,2})(?::([0-5]\d))?\s*[-–—−]\s*(\d{1,2})(?::([0-5]\d))?\s*(?:h|Uhr)?$"#,
                options: [.caseInsensitive]),
              let match = expression.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              match.range == NSRange(text.startIndex..., in: text) else { return nil }
        func number(_ index: Int, default defaultValue: Int? = nil) -> Int? {
            guard let range = Range(match.range(at: index), in: text) else { return defaultValue }
            return Int(text[range])
        }
        guard let startHour = number(1), startHour < 24,
              let startMinute = number(2, default: 0),
              let endHour = number(3), endHour < 24,
              let endMinute = number(4, default: 0) else { return nil }
        return Self(startMinutes: startHour * 60 + startMinute, endMinutes: endHour * 60 + endMinute)
    }

    static func parseRecognizedLines(_ lines: [String]) -> Self? {
        guard !lines.isEmpty else { return nil }
        // Weekdays, exceptions and other clauses must not disappear while
        // extracting a valid-looking time from another line of the same plate.
        return parse(lines.joined(separator: " "))
    }
}

struct TrafficSignSupplementaryTextObservation: Equatable, Sendable {
    let primaryClassID: String
    let primarySpeedKmh: Int?
    let physicalSignID: String
    let window: TrafficSignSupplementaryTimeWindow
    let observedAt: Date
    let firstSeenAt: Date
    var text: String { window.displayText }

    init(primaryClassID: String, primarySpeedKmh: Int?, physicalSignID: String,
         window: TrafficSignSupplementaryTimeWindow, observedAt: Date, firstSeenAt: Date? = nil) {
        self.primaryClassID = primaryClassID
        self.primarySpeedKmh = primarySpeedKmh
        self.physicalSignID = physicalSignID
        self.window = window
        self.observedAt = observedAt
        self.firstSeenAt = firstSeenAt ?? observedAt
    }
}

enum TrafficSignSupplementaryOCRPhase: String, Codable, Sendable {
    case notRequired = "not_required"
    case pending
    case completed
}

enum TrafficSignSupplementaryOCRReadStatus: String, Codable, Sendable {
    case read
    case noText = "no_text"
    case failed
}

struct TrafficSignSupplementaryOCRRead: Equatable, Sendable {
    let rawText: String?
    let modelVersion: String
    let readStatus: TrafficSignSupplementaryOCRReadStatus
    var plateRect: TrafficSignPlateRect? = nil
    var decision: String = "legacy"
    var passes: [TrafficSignOCRPass] = []
    var scan: TrafficSignPlateScan? = nil
    var window: TrafficSignSupplementaryTimeWindow? {
        guard readStatus == .read else { return nil }
        return rawText.flatMap { TrafficSignSupplementaryTimeWindow.parseRecognizedLines($0.components(separatedBy: .newlines)) }
    }
}

/// JSON keeps the complete raw read on one trip-log line, including embedded newlines and unknown clauses.
enum TrafficSignSupplementaryOCRDiagnostics {
    static func attempt(read: TrafficSignSupplementaryOCRRead, classID: String, frameID: String,
                        width: Int, height: Int, number: Int, durationMilliseconds: Double) -> String {
        let fields: [String: Any] = ["status": read.readStatus.rawValue, "class": classID, "frame_id": frameID,
            "native_roi_width": width, "native_roi_height": height, "attempt": number,
            "duration_ms": durationMilliseconds, "raw_characters": read.rawText?.count ?? 0,
            "raw_text": read.rawText as Any? ?? NSNull(), "model": read.modelVersion,
            "decision": read.decision, "passes": read.passes.map { ["text": $0.text, "confidence": $0.confidence, "scale": $0.scale, "uncovered_ink": $0.uncoveredInk] as [String: Any] }]
        guard let data = try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return "ocr_attempt_v1={\"status\":\"diagnostic_encoding_failed\"}" }
        return "ocr_attempt_v1=\(json)"
    }
}

/// The original OCR source is immutable even when a matching later frame keeps
/// its presentation fresh. Consumers must attach this to frameID's crop.
/// Immutable actual-pixel inspection, bound to one captured frame and exact parent.
struct TrafficSignConditionalAssemblyEvidence: Equatable, Sendable {
    let revision = "live-assembly-pixels-v1"
    let sourceWidth: Int
    let sourceHeight: Int
    let sourceFrameID: String
    let capturedAt: Date
    let physicalSignID: String
    let primaryBox: TrafficSignNormalizedRect
    let contextRect: TrafficSignPlateRect
    let otherPrimaryBoxes: [TrafficSignNormalizedRect]
    let scan: TrafficSignPlateScan
    let qualityDecision: String
    let passes: [TrafficSignOCRPass]
    var nativeContentRect: TrafficSignPlateRect? = nil
}

struct TrafficSignSupplementaryOCRAnnotation: Equatable, Sendable {
    let primaryClassID: String
    let primarySpeedKmh: Int?
    let physicalSignID: String
    let frameID: String
    let sourceObservedAt: Date
    let observedAt: Date
    let firstSeenAt: Date
    let rawText: String?
    let window: TrafficSignSupplementaryTimeWindow?
    let readStatus: TrafficSignSupplementaryOCRReadStatus
    let primaryBoundingBox: TrafficSignNormalizedRect
    let ocrBoundingBox: TrafficSignNormalizedRect?
    let engine: String
    let modelVersion: String
    var assemblyEvidence: TrafficSignConditionalAssemblyEvidence? = nil

    var displayText: String? {
        guard readStatus == .read else { return nil }
        if let window { return window.displayText }
        guard let rawText else { return nil }
        let clean = TrafficSignOCRTextFormatting.display(rawText).unicodeScalars.map { scalar -> String in
            CharacterSet.controlCharacters.contains(scalar) ? " " : String(scalar)
        }.joined().split(whereSeparator: \.isWhitespace).joined(separator: " ")
        guard !clean.isEmpty else { return nil }
        return clean.count <= 160 ? clean : String(clean.prefix(157)) + "…"
    }
    var text: String? { displayText }
    var supplementaryText: TrafficSignSupplementaryTextObservation? {
        guard readStatus == .read else { return nil }
        return window.map { TrafficSignSupplementaryTextObservation(primaryClassID: primaryClassID,
            primarySpeedKmh: primarySpeedKmh, physicalSignID: physicalSignID, window: $0,
            observedAt: observedAt, firstSeenAt: firstSeenAt) }
    }

    func refreshed(at timestamp: Date) -> Self {
        Self(primaryClassID: primaryClassID, primarySpeedKmh: primarySpeedKmh, physicalSignID: physicalSignID,
            frameID: frameID, sourceObservedAt: sourceObservedAt, observedAt: timestamp, firstSeenAt: firstSeenAt,
            rawText: rawText, window: window, readStatus: readStatus, primaryBoundingBox: primaryBoundingBox,
            ocrBoundingBox: ocrBoundingBox, engine: engine, modelVersion: modelVersion, assemblyEvidence: assemblyEvidence)
    }
}

enum TrafficSignSupplementaryOCRGeometry {
    /// Native pixel crop: primary on top, one primary-height rectangle below it.
    /// Coordinates use an upright image's top-left origin. Do not stretch or infer
    /// a plate box here; the detector selects a separate plate from the lower half.
    static func cropRect(primaryBox: TrafficSignNormalizedRect, imageWidth: Int, imageHeight: Int) -> CGRect? {
        guard primaryBox.isValid, imageWidth > 0, imageHeight > 0 else { return nil }
        let width = Double(imageWidth), height = Double(imageHeight)
        let rect = CGRect(x: floor(primaryBox.x * width), y: floor(primaryBox.y * height),
            width: ceil(primaryBox.width * width), height: ceil(primaryBox.height * height) * 2)
        // An incomplete lower half cannot be substituted with a different ROI.
        guard rect.width >= 48, rect.height >= 64, rect.maxX <= width, rect.maxY <= height else { return nil }
        return rect
    }
}

/// One serial, reusable Vision request for warm-up and all runtime instances.
/// No pixels are retained after a synchronous read, written, or transmitted.
final class TrafficSignSupplementaryOCR: @unchecked Sendable {
    static let shared = TrafficSignSupplementaryOCR()
    private let queue = DispatchQueue(label: "de.youspeed.supplementary-ocr", qos: .userInitiated,
                                      autoreleaseFrequency: .workItem)
    private let warmLock = NSLock()
    private var warmingStarted = false
    private lazy var request: VNRecognizeTextRequest = {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .fast
        request.automaticallyDetectsLanguage = true
        request.usesLanguageCorrection = false
        request.minimumTextHeight = 0
        request.regionOfInterest = CGRect(x: 0, y: 0, width: 1, height: 1)
        return request
    }()

    static func warmUp() { shared.prepareAtStartup() }

    /// Primary-panel proof only; never a supplementary restriction or speed rule.
    static func verifiesZone(in primary: CGImage, speed: Int) -> Bool {
        guard primary.width >= 48, primary.height >= 48,
              primary.width * primary.height <= 1_000_000 else { return false }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = false
        request.automaticallyDetectsLanguage = true
        request.minimumTextHeight = 0
        do {
            try VNImageRequestHandler(cgImage: primary, options: [:]).perform([request])
            let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
            return TSRLiveSignAdmission.verifiesZoneText(text, speed: speed)
        } catch { return false }
    }

    private func prepareAtStartup() {
        warmLock.lock()
        guard !warmingStarted else { warmLock.unlock(); return }
        warmingStarted = true
        warmLock.unlock()
        queue.async { [self] in
            guard let context = CGContext(data: nil, width: 136, height: 230, bitsPerComponent: 8,
                bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(CGRect(x: 0, y: 0, width: 136, height: 230))
            // Exercise recognition as well as detection without private pixels,
            // expected-word hints, or any publication into presentation state.
            let text = NSAttributedString(string: "12-13 h", attributes: [
                NSAttributedString.Key(kCTFontAttributeName as String): CTFontCreateWithName("Helvetica" as CFString, 24, nil),
                NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: 0, alpha: 1)
            ])
            context.textPosition = CGPoint(x: 12, y: 50)
            CTLineDraw(CTLineCreateWithAttributedString(text), context)
            guard let synthetic = context.makeImage() else { return }
            for level: VNRequestTextRecognitionLevel in [.fast, .accurate] {
                request.recognitionLevel = level
                try? VNImageRequestHandler(cgImage: synthetic, options: [:]).perform([request])
            }
            TrafficSignOCRLanguageContext.prepare(text: "Synthetic language warmup", candidates: ["en-GB"])
        }
    }

    func recognizeTimeWindow(in nativePrimaryAndLowerCrop: CGImage) throws -> TrafficSignSupplementaryTimeWindow? {
        try read(in: nativePrimaryAndLowerCrop).window
    }

    private var requestModelVersion: String {
        "revision\(request.revision)-\(request.recognitionLevel == .fast ? "fast" : "accurate")"
    }
    var modelVersion: String { queue.sync { requestModelVersion } }

    static func needsAccurate(languages: [String], fast: [String], accurate: [String]) -> Bool {
        languages.contains { tag in
            !fast.contains { $0.prefix(2) == tag.prefix(2) }
                && accurate.contains { $0.prefix(2) == tag.prefix(2) }
        }
    }

    func read(in nativePrimaryAndLowerCrop: CGImage) throws -> TrafficSignSupplementaryOCRRead {
        queue.sync {
            let image = nativePrimaryAndLowerCrop
            let version = "revision\(request.revision)-accurate-\(TrafficSignPlateDetector.revision)"
            let pixels = Self.pixels(image)
            let scan = pixels.map { TrafficSignPlateDetector.scan(width: image.width, height: image.height, rgba: $0) }
                ?? .init(status: .unresolved, union: nil, components: [], decision: "pixels_unavailable")
            func result(_ raw: String?, _ accepted: Bool, _ decision: String,
                        _ rect: TrafficSignPlateRect? = nil, _ passes: [TrafficSignOCRPass] = []) -> TrafficSignSupplementaryOCRRead {
                .init(rawText: raw, modelVersion: version, readStatus: accepted ? .read : .noText,
                      plateRect: rect, decision: decision, passes: passes, scan: scan)
            }
            guard let rect = scan.union,
                  let plate = image.cropping(to: CGRect(x: rect.x, y: rect.y, width: rect.width, height: rect.height)),
                  let platePixels = Self.pixels(plate) else { return result(nil, false, "no_separate_plate") }
            guard !TrafficSignPlateDetector.isPrimaryGraphic(width: plate.width, height: plate.height, rgba: platePixels)
                else { return result(nil, false, "primary_graphic", rect) }
            do {
            let languages = TrafficSignOCRLanguageContext.recognitionLanguages
            request.recognitionLevel = .accurate
            let supported = try request.supportedRecognitionLanguages()
            request.recognitionLanguages = languages.compactMap { tag in
                supported.first { $0 == tag } ?? supported.first { $0.prefix(2) == tag.prefix(2) }
            }.reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
            func recognize(_ input: CGImage, scale: Int) throws -> TrafficSignOCRPass {
                try VNImageRequestHandler(cgImage: input, options: [:]).perform([request])
                let observations = (request.results ?? []).sorted { a,b in
                    abs(a.boundingBox.midY-b.boundingBox.midY) > min(a.boundingBox.height,b.boundingBox.height)/2
                        ? a.boundingBox.midY > b.boundingBox.midY : a.boundingBox.minX < b.boundingBox.minX
                }
                let candidates = observations.compactMap { $0.topCandidates(1).first }
                var rows = Set<Int>()
                for observation in observations {
                    let top = max(0, Int(floor((1-observation.boundingBox.maxY)*Double(plate.height)))-2)
                    let bottom = min(plate.height-1, Int(ceil((1-observation.boundingBox.minY)*Double(plate.height)))+2)
                    if top <= bottom { rows.formUnion(top...bottom) }
                }
                return .init(text: candidates.map(\.string).joined(separator: "\n"),
                             confidence: Double(candidates.map(\.confidence).min() ?? 0), scale: scale,
                             uncoveredInk: scan.components.contains { component in
                                 let local = CGRect(x: component.x-rect.x, y: component.y-rect.y, width: component.width, height: component.height)
                                     .intersection(CGRect(x:0,y:0,width:plate.width,height:plate.height))
                                 guard !local.isNull, local.width >= 48, local.height >= 32,
                                       let panel = plate.cropping(to:local), let bytes = Self.pixels(panel) else { return true }
                                 let offset = Int(local.minY)
                                 return TrafficSignPlateDetector.hasUncoveredInk(width:panel.width,height:panel.height,rgba:bytes,
                                     coveredRows:Set(rows.filter { $0 >= offset && $0 < offset+panel.height }.map { $0-offset }))
                             })
            }
            var passes = [try recognize(plate, scale: 1)]
            // One bounded interpolation pass improves small glyph sampling; it
            // cannot create native detail. Numeric disagreement causes abstention.
            if let scaled = Self.scaled(plate) { passes.append(try recognize(scaled, scale: 2)) }
            let chosen = TrafficSignOCRQuality.selected(passes)!
            let decision = TrafficSignOCRQuality.decision(passes: passes, nativeWidth: rect.width)
            let raw = chosen.text.isEmpty ? passes.first?.text : chosen.text
            if decision == "accepted", let raw { TrafficSignOCRLanguageContext.prepare(text: raw, candidates: languages) }
            return result(raw?.isEmpty == false ? raw : nil, decision == "accepted", decision, rect, passes)
            } catch {
                return .init(rawText:nil,modelVersion:version,readStatus:.failed,plateRect:rect,
                    decision:"native_ocr_failure",passes:[],scan:scan)
            }
        }
    }

    private static func pixels(_ image: CGImage) -> [UInt8]? {
        guard image.width > 0, image.height > 0, image.width <= 2048, image.height <= 2048 else { return nil }
        var bytes = [UInt8](repeating: 0, count: image.width*image.height*4)
        let ok = bytes.withUnsafeMutableBytes { data -> Bool in
            guard let context = CGContext(data: data.baseAddress, width: image.width, height: image.height,
                bitsPerComponent: 8, bytesPerRow: image.width*4, space: CGColorSpaceCreateDeviceRGB(),
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return false }
            context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height)); return true
        }
        return ok ? bytes : nil
    }
    private static func scaled(_ image: CGImage) -> CGImage? {
        guard let context = CGContext(data: nil, width: image.width*2, height: image.height*2, bitsPerComponent: 8,
            bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width*2, height: image.height*2))
        return context.makeImage()
    }

}

/// Bounded reads of increasingly useful native pixels, independent of road rules.
/// Owned exclusively by the runtime's existing single inference queue.
struct TrafficSignSupplementaryTextTracker {
    /// Re-reading a closer frame updates candidate interpretation, never authority.
    var conditionalInterpretationCandidate: ConditionalOCRInterpretation.Parsed? {
        guard let completed, completed.readStatus == .read,
              let speed = completed.primarySpeedKmh, completed.primaryClassID == "maxspeed:\(speed)", let raw = completed.rawText else { return nil }
        return ConditionalOCRInterpretation.parse(raw)
    }
    struct Primary: Equatable {
        let classID: String
        let speedKmh: Int?
        let box: TrafficSignNormalizedRect
        let physicalSignID: String?
    }
    struct Attempt {
        let primary: Primary
        let physicalSignID: String
        let firstSeenAt: Date
        let frameID: String
        let observedAt: Date
        let number: Int
        let cachedAnnotation: TrafficSignSupplementaryOCRAnnotation?
        fileprivate let previousAttemptAt: Date?
        fileprivate let previousAttemptArea: Double
    }
    enum Admission {
        case notRequired
        case perform(Attempt)
        case cached(TrafficSignSupplementaryOCRAnnotation)
    }
    private struct Budget {
        var count = 0
        var lastAttemptAt: Date?
        var largestAttemptArea = 0.0
        var inspectionSignature: String?
        var agreementFollowupPending = false
    }
    private var primary: Primary?
    private var associationID: String?
    private var associationStartedAt: Date?
    private var lastSeenAt: Date?
    private var lastFrameID: String?
    private var distinctFrames = 0
    private var budgets: [String: Budget] = [:]
    private var completed: TrafficSignSupplementaryOCRAnnotation?

    mutating func reset() { self = Self() }

    mutating func begin(primary next: Primary?, frameID: String, at timestamp: Date,
                        confirmed: Bool, evidenceFrames: Int, nativeROISize: CGSize?,
                        canRead: Bool = true) -> Admission {
        guard let next else { return .notRequired }
        guard next.box.isValid else { reset(); return .notRequired }
        let sameSign = primary.map { previous in
            let gap = lastSeenAt.map { timestamp.timeIntervalSince($0) } ?? .infinity
            guard previous.classID == next.classID, previous.speedKmh == next.speedKmh,
                  gap >= 0, gap <= 2 else { return false }
            // A stable fusion identity is stronger evidence than changes of size
            // and position as the car approaches. Different explicit IDs replace.
            if let previousID = previous.physicalSignID, let nextID = next.physicalSignID {
                return previousID == nextID
            }
            let scale = next.box.area / previous.box.area
            return scale >= 0.2 && scale <= 5
                && previous.box.intersectionOverUnion(with: next.box) >= 0.1
        } ?? false
        if !sameSign {
            primary = nil
            associationID = next.physicalSignID ?? UUID().uuidString.lowercased()
            associationStartedAt = timestamp
            lastFrameID = nil
            distinctFrames = 0
            completed = nil
        }
        primary = next
        lastSeenAt = timestamp
        if frameID != lastFrameID { distinctFrames += 1; lastFrameID = frameID }
        let cached = completed?.refreshed(at: timestamp)
        completed = cached
        func unavailable() -> Admission { cached.map(Admission.cached) ?? .notRequired }
        // Pictograms have no speed-fusion confirmation. Two distinct accepted
        // display frames establish their separate, presentation-only association.
        let qualified = next.speedKmh == nil ? distinctFrames >= 2 : confirmed && evidenceFrames >= 2
        guard qualified, let associationID, let associationStartedAt,
              canRead, let size = nativeROISize, size.width >= 48, size.height >= 32 else { return unavailable() }
        var budget = budgets[associationID] ?? Budget()
        let area = Double(size.width * size.height)
        guard budget.count < 6,
              budget.lastAttemptAt.map({ timestamp.timeIntervalSince($0) >= 0.3 }) ?? true,
              budget.count < 2 || budget.agreementFollowupPending || area >= budget.largestAttemptArea * 1.8 else { return unavailable() }
        let previousAttemptAt = budget.lastAttemptAt
        let previousAttemptArea = budget.largestAttemptArea
        budget.count += 1
        budget.lastAttemptAt = timestamp
        budget.largestAttemptArea = max(area, budget.largestAttemptArea)
        if budgets.count >= 256, budgets[associationID] == nil { budgets.removeAll() }
        budgets[associationID] = budget
        return .perform(Attempt(primary: next, physicalSignID: associationID, firstSeenAt: associationStartedAt,
                                frameID: frameID, observedAt: timestamp, number: budget.count, cachedAnnotation: cached,
                                previousAttemptAt: previousAttemptAt, previousAttemptArea: previousAttemptArea))
    }

    /// A heat change or missing crop between admission and execution is a
    /// deferral, so that the same useful view remains eligible when it can run.
    mutating func deferAttempt(_ attempt: Attempt) {
        guard associationID == attempt.physicalSignID,
              var budget = budgets[attempt.physicalSignID], budget.count == attempt.number else { return }
        budget.count -= 1
        budget.lastAttemptAt = attempt.previousAttemptAt
        budget.largestAttemptArea = attempt.previousAttemptArea
        budgets[attempt.physicalSignID] = budget
    }

    mutating func finish(_ attempt: Attempt, read: TrafficSignSupplementaryOCRRead,
                         ocrBoundingBox: TrafficSignNormalizedRect?,
                         assemblyEvidence: TrafficSignConditionalAssemblyEvidence? = nil) -> TrafficSignSupplementaryOCRAnnotation? {
        guard associationID == attempt.physicalSignID else { return nil }
        let annotation = TrafficSignSupplementaryOCRAnnotation(primaryClassID: attempt.primary.classID,
            primarySpeedKmh: attempt.primary.speedKmh, physicalSignID: attempt.physicalSignID, frameID: attempt.frameID,
            sourceObservedAt: attempt.observedAt, observedAt: attempt.observedAt, firstSeenAt: attempt.firstSeenAt,
            rawText: read.rawText, window: read.window, readStatus: read.readStatus,
            primaryBoundingBox: attempt.primary.box, ocrBoundingBox: ocrBoundingBox,
            engine: "apple_vision_text_recognition", modelVersion: read.modelVersion, assemblyEvidence: assemblyEvidence)
        if var budget = budgets[attempt.physicalSignID] {
            let signature: String?
            switch ConditionalOCRInterpretation.assess(annotation) {
            case .plain: signature = "plain"
            case .conditional(let parsed): signature = parsed.normalizedText
            case .unresolved: signature = nil
            }
            budget.agreementFollowupPending = signature != nil && signature != budget.inspectionSignature
            budget.inspectionSignature = signature
            budgets[attempt.physicalSignID] = budget
        }
        // A closer empty/failed read is still collected, but must not erase a
        // successful restriction already shown for this physical sign.
        if annotation.readStatus == .read || completed?.readStatus != .read { completed = annotation }
        return annotation
    }

    func presentationAnnotation(at timestamp: Date) -> TrafficSignSupplementaryOCRAnnotation? {
        completed?.refreshed(at: timestamp)
    }
}
