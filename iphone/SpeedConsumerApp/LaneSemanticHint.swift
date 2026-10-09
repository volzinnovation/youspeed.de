import Foundation
import CoreFoundation

/// Fail-closed, exact-exposure semantic evidence. This core is deliberately not wired into
/// detection, tracking, ranking or display. See shared/lanes/semantic-hint-v1.
enum LaneSemanticHint {
    typealias Document = [String: Any]
    static let maxSafeInteger: Int64 = 9_007_199_254_740_991
    static let outputKind = "lane-paint-probability-v1"
    private static let scopeKeys = ["sessionId", "sessionGeneration", "cameraId", "cameraGeneration", "calibrationGeneration"]
    private static let modelKeys = ["modelId", "revision", "outputKind"]

    struct Invalid: Error { let reason: String }

    struct Policy {
        let modelIdentity: Document
        let maskWidth: Int
        let maskHeight: Int
        let maxCaptureAgeNs: Int64

        init(_ value: Document) throws {
            guard keys(value, ["schemaVersion", "modelIdentity", "maskWidth", "maskHeight", "maxCaptureAgeNs"]),
                  integer(value["schemaVersion"]) == 1,
                  let model = value["modelIdentity"] as? Document, validModel(model),
                  model["outputKind"] as? String == outputKind,
                  let width = integer(value["maskWidth"], 1, 512),
                  let height = integer(value["maskHeight"], 1, 512),
                  let age = integer(value["maxCaptureAgeNs"], 1) else { throw Invalid(reason: "invalid_policy") }
            modelIdentity = snapshot(model)
            maskWidth = Int(width); maskHeight = Int(height); maxCaptureAgeNs = age
        }
    }

    /// Owned value arrays; unknown cells are never exposed as negative paint observations.
    struct Evidence {
        let frameId: String
        let sourceTimeNs: Int64
        let sourceClockId: String
        let capturedAtNs: Int64
        let clockId: String
        let arrivedAtNs: Int64
        let scopeIdentity: String
        let geometryIdentity: String
        let modelIdentity: String
        let provenanceIdentity: String
        let width: Int
        let height: Int
        let probabilities: [Double]
        let validity: [Bool]
        fileprivate let metadata: Document

        func probability(at index: Int) -> Double? {
            guard validity.indices.contains(index), validity[index] else { return nil }
            return probabilities[index]
        }
    }

    struct Qualification {
        let reason: String
        let hint: Evidence?
        let captureAgeNs: Int64?
        var accepted: Bool { hint != nil }
        init(_ reason: String, hint: Evidence? = nil, age: Int64? = nil) {
            self.reason = reason; self.hint = hint; captureAgeNs = age
        }
    }

    struct GuidanceInput<Baseline> {
        let baseline: Baseline
        let qualification: Qualification
    }

    static func prepareGuidance<Baseline>(_ baseline: Baseline, hint: Document?, context: Document,
                                          policy: Policy) -> GuidanceInput<Baseline> {
        GuidanceInput(baseline: baseline, qualification: qualify(hint, context: context, policy: policy))
    }

    static func prepareGuidanceTyped<Baseline>(_ baseline: Baseline, metadata: Document?, width: Int, height: Int,
                                               probabilities: [Double], validity: [Bool], context: Document, policy: Policy) -> GuidanceInput<Baseline> {
        GuidanceInput(baseline: baseline, qualification: qualifyTyped(metadata, width: width, height: height,
            probabilities: probabilities, validity: validity, context: context, policy: policy))
    }

    private static func qualifyMetadata(_ hint: Document?, context: Document, policy: Policy, containsMask: Bool) -> Qualification {
        if let reason = contextReason(context) { return Qualification(reason) }
        guard let hint else { return Qualification("missing_hint") }
        guard keys(hint, ["schemaVersion", "modelIdentity", "provenance", "scope", "exposure", "arrival", "geometry", "alignment"] + (containsMask ? ["mask"] : [])) else { return Qualification("invalid_hint") }
        guard integer(hint["schemaVersion"]) == 1 else { return Qualification("schema_mismatch") }
        guard let model = hint["modelIdentity"] as? Document, validModel(model), equal(model, policy.modelIdentity) else { return Qualification("model_mismatch") }
        guard let provenance = hint["provenance"] as? Document, keys(provenance, ["kind", "sourceId"]),
              ["model_inference", "synthetic_fixture"].contains(provenance["kind"] as? String ?? ""), text(provenance["sourceId"]) else { return Qualification("invalid_provenance") }
        guard let scope = hint["scope"] as? Document, validScope(scope) else { return Qualification("invalid_scope") }
        guard equal(scope, context["scope"] as! Document) else { return Qualification("scope_mismatch") }
        guard let exposure = hint["exposure"] as? Document, validExposure(exposure) else { return Qualification("invalid_exposure") }
        guard boolean(exposure["clockKnown"]) == true else { return Qualification("unknown_clock") }
        let currentExposure = context["exposure"] as! Document
        guard ["clockId", "sourceClockId"].allSatisfy({ sameIdentity(exposure[$0] as? String, currentExposure[$0] as? String) }) else { return Qualification("clock_mismatch") }
        guard equal(exposure, currentExposure) else { return Qualification("exposure_mismatch") }
        guard let arrival = hint["arrival"] as? Document, validReading(arrival) else { return Qualification("invalid_arrival") }
        guard boolean(arrival["clockKnown"]) == true else { return Qualification("unknown_clock") }
        guard sameIdentity(arrival["clockId"] as? String, exposure["clockId"] as? String) else { return Qualification("clock_mismatch") }
        let captured = integer(exposure["capturedAtNs"])!, arrived = integer(arrival["atNs"])!
        let now = integer((context["now"] as! Document)["atNs"])!
        guard arrived >= captured else { return Qualification("arrival_before_capture") }
        guard arrived <= now else { return Qualification("future_arrival") }
        let age = now - captured
        guard age <= policy.maxCaptureAgeNs else { return Qualification("stale_hint", age: age) }
        guard let geometry = hint["geometry"] as? Document, validGeometry(geometry) else { return Qualification("invalid_geometry", age: age) }
        guard equal(geometry, context["geometry"] as! Document) else { return Qualification("geometry_mismatch", age: age) }
        guard let alignment = hint["alignment"] as? Document, keys(alignment, ["mode"]), alignment["mode"] as? String == "exact_exposure" else { return Qualification("alignment_unsupported", age: age) }
        return Qualification("metadata_qualified", age: age)
    }

    /// JSON reference bridge. Mask decoding remains outside the typed producer path.
    static func qualify(_ hint: Document?, context: Document, policy: Policy) -> Qualification {
        let checked = qualifyMetadata(hint, context: context, policy: policy, containsMask: true)
        guard checked.reason == "metadata_qualified", let hint else { return checked }
        let age = checked.captureAgeNs!
        guard let mask = hint["mask"] as? Document, keys(mask, ["width", "height", "probabilities", "validity"]) else { return Qualification("invalid_mask", age: age) }
        guard integer(mask["width"], 1, 512) == Int64(policy.maskWidth), integer(mask["height"], 1, 512) == Int64(policy.maskHeight),
              let scores = mask["probabilities"] as? [Any], let valid = mask["validity"] as? [Any],
              scores.count == policy.maskWidth * policy.maskHeight, valid.count == scores.count else { return Qualification("shape_mismatch", age: age) }
        var decoded: [Double] = []; decoded.reserveCapacity(scores.count)
        for value in scores {
            guard let score = probability(value) else { return Qualification("invalid_scores", age: age) }
            decoded.append(score)
        }
        guard valid.allSatisfy({ boolean($0) != nil }) else { return Qualification("invalid_validity", age: age) }
        return ownAndQualify(hint.filter { $0.key != "mask" }, width: policy.maskWidth, height: policy.maskHeight,
            probabilities: decoded, validity: valid.map { boolean($0)! }, policy: policy, age: age)
    }

    /// Metadata is the exact hint envelope WITHOUT mask. Producer-owned typed arrays are
    /// checked once and retained by Swift value/COW semantics; later caller mutation detaches.
    /// The owner must not concurrently mutate a buffer while submitting it.
    static func qualifyTyped(_ metadata: Document?, width: Int, height: Int, probabilities: [Double], validity: [Bool],
                             context: Document, policy: Policy) -> Qualification {
        let checked = qualifyMetadata(metadata, context: context, policy: policy, containsMask: false)
        guard checked.reason == "metadata_qualified", let metadata else { return checked }
        return ownAndQualify(metadata, width: width, height: height, probabilities: probabilities, validity: validity,
                             policy: policy, age: checked.captureAgeNs!)
    }

    private static func ownAndQualify(_ metadata: Document, width: Int, height: Int, probabilities: [Double], validity: [Bool],
                                      policy: Policy, age: Int64) -> Qualification {
        guard (1...512).contains(width), (1...512).contains(height), width == policy.maskWidth, height == policy.maskHeight,
              probabilities.count == width * height, validity.count == probabilities.count else { return Qualification("shape_mismatch", age: age) }
        guard probabilities.allSatisfy({ $0.isFinite && (0...1).contains($0) }) else { return Qualification("invalid_scores", age: age) }
        guard validity.contains(true) else { return Qualification("no_valid_pixels", age: age) }
        let owned = snapshot(metadata), exposure = owned["exposure"] as! Document
        let evidence = Evidence(frameId: exposure["frameId"] as! String, sourceTimeNs: integer(exposure["sourceTimeNs"])!,
            sourceClockId: exposure["sourceClockId"] as! String, capturedAtNs: integer(exposure["capturedAtNs"])!, clockId: exposure["clockId"] as! String,
            arrivedAtNs: integer((owned["arrival"] as! Document)["atNs"])!, scopeIdentity: canonical(owned["scope"] as! Document),
            geometryIdentity: canonical(owned["geometry"] as! Document), modelIdentity: canonical(owned["modelIdentity"] as! Document),
            provenanceIdentity: canonical(owned["provenance"] as! Document), width: width, height: height,
            probabilities: probabilities, validity: validity, metadata: owned)
        return Qualification("qualified", hint: evidence, age: age)
    }

    /// Evidence enters the cache only after owned-buffer validation. Rechecking trusted
    /// context/age never reserializes or rescans its immutable mask.
    private static func requalify(_ hint: Evidence?, context: Document, policy: Policy) -> Qualification {
        let checked = qualifyMetadata(hint?.metadata, context: context, policy: policy, containsMask: false)
        guard checked.reason == "metadata_qualified", let hint else { return checked }
        guard hint.width == policy.maskWidth, hint.height == policy.maskHeight else { return Qualification("shape_mismatch", age: checked.captureAgeNs) }
        return Qualification("qualified", hint: hint, age: checked.captureAgeNs)
    }

    /// Single-owner cache. Call only on its owner's queue; arriving results cannot advance/reset it.
    /// This pure core makes no assertion about live camera queue latency or thread safety.
    final class Cache {
        let policy: Policy
        private var context: Document = [:]
        private var key = ""
        private var hint: Evidence?
        private(set) var latestSourceTimeNs: Int64?
        init(policy: Policy, context: Document) throws { self.policy = policy; try resetScope(context) }
        func resetScope(_ next: Document) throws {
            if let reason = contextReason(next) { throw Invalid(reason: reason) }
            context = snapshot(next); key = contextKey(next); hint = nil; latestSourceTimeNs = nil
        }
        @discardableResult func advance(_ next: Document) -> String {
            if let reason = contextReason(next) { return reason }
            guard sameIdentity(contextKey(next), key) else { return "context_scope_mismatch" }
            let old = context["exposure"] as! Document, new = next["exposure"] as! Document
            guard integer((next["now"] as! Document)["atNs"])! >= integer((context["now"] as! Document)["atNs"])! else { return "context_clock_regression" }
            let oldSource = integer(old["sourceTimeNs"])!, newSource = integer(new["sourceTimeNs"])!
            let oldCapture = integer(old["capturedAtNs"])!, newCapture = integer(new["capturedAtNs"])!
            guard newSource >= oldSource, newCapture >= oldCapture else { return "context_exposure_regression" }
            if newSource == oldSource && !equal(new, old) { return "context_exposure_conflict" }
            if newSource > oldSource && (sameIdentity(new["frameId"] as? String, old["frameId"] as? String) || newCapture == oldCapture) { return "context_exposure_conflict" }
            context = snapshot(next)
            return "advanced"
        }
        func offer(_ value: Document?) -> Qualification {
            accept(qualify(value, context: context, policy: policy))
        }
        func offerTyped(_ metadata: Document?, width: Int, height: Int, probabilities: [Double], validity: [Bool]) -> Qualification {
            accept(qualifyTyped(metadata, width: width, height: height, probabilities: probabilities, validity: validity, context: context, policy: policy))
        }
        private func accept(_ result: Qualification) -> Qualification {
            guard let accepted = result.hint else { return result }
            if let latest = latestSourceTimeNs, accepted.sourceTimeNs <= latest {
                return Qualification(accepted.sourceTimeNs == latest ? "duplicate_exposure" : "out_of_order_exposure", age: result.captureAgeNs)
            }
            hint = accepted; latestSourceTimeNs = accepted.sourceTimeNs
            return result
        }
        // Uses the last accepted owner context, not a clock read. The caller must
        // advance with fresh time/exposure before consumption and withhold evidence
        // after a rejected advance/reset; those operations preserve the prior state.
        func current() -> Qualification { requalify(hint, context: context, policy: policy) }
    }

    /// Rebase one already-trusted native clock into an exact JSON-safe relative epoch.
    /// The caller must retain the original capture reading. An inference completion/arrival
    /// reading is not an exposure reading. This subtraction does not establish synchronization.
    struct ClockEpoch {
        enum Role: String { case sourcePresentation = "source_presentation", captureMonotonic = "capture_monotonic" }
        let clockId: String
        let originNs: Int64
        let role: Role
        init(clockId: String, originNs: Int64, role: Role) throws {
            guard text(clockId), originNs >= 0 else { throw Invalid(reason: "invalid_clock_epoch") }
            self.clockId = clockId; self.originNs = originNs; self.role = role
        }
        func relative(readingNs: Int64, clockId readingClock: String, known: Bool) throws -> Int64 {
            guard known else { throw Invalid(reason: "unknown_clock") }
            guard sameIdentity(readingClock, clockId) else { throw Invalid(reason: "clock_mismatch") }
            guard readingNs >= 0 else { throw Invalid(reason: "invalid_clock_reading") }
            let (relative, overflow) = readingNs.subtractingReportingOverflow(originNs)
            guard !overflow, relative >= 0, relative <= maxSafeInteger else { throw Invalid(reason: "clock_out_of_range") }
            return relative
        }
    }

    static func exposure(frameId: String, source: ClockEpoch, sourceNs: Int64, sourceClockId: String,
                         capture: ClockEpoch, captureNs: Int64, captureClockId: String, clocksKnown: Bool) throws -> Document {
        guard text(frameId), source.role == .sourcePresentation, capture.role == .captureMonotonic else { throw Invalid(reason: "invalid_clock_role") }
        return ["frameId": frameId,
                "sourceTimeNs": try source.relative(readingNs: sourceNs, clockId: sourceClockId, known: clocksKnown),
                "sourceClockId": source.clockId,
                "capturedAtNs": try capture.relative(readingNs: captureNs, clockId: captureClockId, known: clocksKnown),
                "clockId": capture.clockId, "clockKnown": true]
    }

    static func contextReason(_ value: Document) -> String? {
        guard keys(value, ["schemaVersion", "scope", "exposure", "geometry", "now"]), integer(value["schemaVersion"]) == 1,
              let scope = value["scope"] as? Document, validScope(scope),
              let exposure = value["exposure"] as? Document, validExposure(exposure),
              let geometry = value["geometry"] as? Document, validGeometry(geometry),
              let now = value["now"] as? Document, validReading(now) else { return "invalid_context" }
        guard boolean(now["clockKnown"]) == true, boolean(exposure["clockKnown"]) == true else { return "unknown_clock" }
        guard sameIdentity(now["clockId"] as? String, exposure["clockId"] as? String) else { return "clock_mismatch" }
        guard integer(now["atNs"])! >= integer(exposure["capturedAtNs"])! else { return "future_capture" }
        let crop = geometry["crop"] as! Document
        guard boolean(geometry["fullScene"]) == true, integer(crop["x"]) == 0, integer(crop["y"]) == 0,
              integer(crop["width"]) == integer(geometry["sourceWidth"]), integer(crop["height"]) == integer(geometry["sourceHeight"]) else { return "partial_scene_unsupported" }
        return nil
    }
    static func integer(_ value: Any?, _ minimum: Int64 = 0, _ maximum: Int64 = maxSafeInteger) -> Int64? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              !["d", "f"].contains(String(cString: number.objCType)),
              number.doubleValue >= Double(minimum), number.doubleValue <= Double(maximum) else { return nil }
        let result = number.int64Value
        return result >= minimum && result <= maximum ? result : nil
    }
    private static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber, CFGetTypeID(number) == CFBooleanGetTypeID() else { return nil }
        return number.boolValue
    }
    private static func text(_ value: Any?) -> Bool {
        guard let value = value as? String else { return false }
        return value.unicodeScalars.count <= 512 && value.unicodeScalars.contains { !contractWhitespace($0.value) }
    }
    // Match the shared Python contract's Unicode whitespace and code-point length rules.
    private static func contractWhitespace(_ scalar: UInt32) -> Bool {
        (9...13).contains(scalar) || (28...32).contains(scalar) || (8192...8202).contains(scalar) ||
        [133, 160, 5760, 8232, 8233, 8239, 8287, 12288].contains(scalar)
    }
    private static func probability(_ value: Any) -> Double? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        // Foundation parses long JSON decimals as NSDecimalNumber. Its doubleValue can
        // differ by several ulps from correctly rounded Swift/JVM/Python parsing. Reparse
        // that exact decimal spelling; native NSNumber doubles retain their original bits.
        let score = number is NSDecimalNumber ? Double(number.stringValue) : number.doubleValue
        guard let score, score.isFinite, (0...1).contains(score) else { return nil }
        return score
    }
    private static func keys(_ value: Document, _ expected: [String]) -> Bool {
        // Field names are also byte-exact: e.g. Kelvin-sign K must not alias ASCII K.
        Set(value.keys.map { Data($0.utf8) }) == Set(expected.map { Data($0.utf8) })
    }
    private static func validModel(_ value: Document) -> Bool { keys(value, modelKeys) && modelKeys.allSatisfy { text(value[$0]) } }
    private static func validScope(_ value: Document) -> Bool {
        keys(value, scopeKeys) && text(value["sessionId"]) && text(value["cameraId"]) && scopeKeys.filter { $0.hasSuffix("Generation") }.allSatisfy { integer(value[$0]) != nil }
    }
    private static func validExposure(_ value: Document) -> Bool {
        keys(value, ["frameId", "sourceTimeNs", "sourceClockId", "capturedAtNs", "clockId", "clockKnown"]) &&
        ["frameId", "sourceClockId", "clockId"].allSatisfy { text(value[$0]) } &&
        ["sourceTimeNs", "capturedAtNs"].allSatisfy { integer(value[$0]) != nil } && boolean(value["clockKnown"]) != nil
    }
    private static func validReading(_ value: Document) -> Bool {
        keys(value, ["atNs", "clockId", "clockKnown"]) && integer(value["atNs"]) != nil && text(value["clockId"]) && boolean(value["clockKnown"]) != nil
    }
    private static func validGeometry(_ value: Document) -> Bool {
        guard keys(value, ["sourceWidth", "sourceHeight", "crop", "rotationDegrees", "mirrored", "analysisWidth", "analysisHeight", "mappingId", "fullScene"]),
              ["sourceWidth", "sourceHeight", "analysisWidth", "analysisHeight"].allSatisfy({ integer(value[$0], 1, 32_768) != nil }),
              let rotation = integer(value["rotationDegrees"]), [0, 90, 180, 270].contains(rotation),
              boolean(value["mirrored"]) != nil, boolean(value["fullScene"]) != nil, text(value["mappingId"]),
              let crop = value["crop"] as? Document, keys(crop, ["x", "y", "width", "height"]),
              let x = integer(crop["x"]), let y = integer(crop["y"]), let width = integer(crop["width"], 1, 32_768),
              let height = integer(crop["height"], 1, 32_768) else { return false }
        return x + width <= integer(value["sourceWidth"])! && y + height <= integer(value["sourceHeight"])!
    }
    private static func canonical(_ value: Document) -> String { String(data: try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes]), encoding: .utf8)! }
    // Swift String == applies Unicode canonical equivalence; opaque protocol identities
    // require the same UTF-8 bytes as Python/Kotlin (no implicit normalization).
    private static func sameIdentity(_ left: String?, _ right: String?) -> Bool {
        guard let left, let right else { return false }
        return left.utf8.elementsEqual(right.utf8)
    }
    private static func equal(_ left: Document, _ right: Document) -> Bool { sameIdentity(canonical(left), canonical(right)) }
    private static func snapshot(_ value: Document) -> Document {
        // Copy the validated value tree without a JSON round-trip, which can turn
        // -0.0 into integer zero and lose the original mask bits on cache reads.
        func copy(_ value: Any) -> Any {
            if let object = value as? Document { return object.mapValues(copy) }
            if let array = value as? [Any] { return array.map(copy) }
            if let text = value as? String { return String(text) }
            if let number = value as? NSNumber { return number.copy() }
            return value
        }
        return value.mapValues(copy)
    }
    private static func contextKey(_ value: Document) -> String {
        let exposure = value["exposure"] as! Document
        return canonical(["scope": value["scope"]!, "geometry": value["geometry"]!, "sourceClockId": exposure["sourceClockId"]!, "clockId": exposure["clockId"]!])
    }
}
