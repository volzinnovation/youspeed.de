import Foundation
import CryptoKit

/// Host harness compiling the production Swift core. All test data travels outside app wiring.
@main struct SemanticHintParity {
    typealias Doc = LaneSemanticHint.Document
    final class Baseline {
        let confidence = 0.6, supportRows = 5, confirmations = 2, trackId = 17
        var signature: [String: Any] { ["confidence": confidence, "supportRows": supportRows, "confirmations": confirmations, "trackId": trackId] }
    }
    static func record(_ result: LaneSemanticHint.Qualification) -> Doc {
        var output: Doc = ["reason": result.reason, "accepted": result.accepted, "captureAgeNs": result.captureAgeNs as Any? ?? NSNull()]
        guard let hint = result.hint else { output["hint"] = NSNull(); return output }
        var bytes = Data()
        for score in hint.probabilities { var bits = score.bitPattern.bigEndian; withUnsafeBytes(of: &bits) { bytes.append(contentsOf: $0) } }
        bytes.append(contentsOf: hint.validity.map { $0 ? UInt8(1) : UInt8(0) })
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        func identity(_ value: String) -> Any { try! JSONSerialization.jsonObject(with: Data(value.utf8)) }
        output["hint"] = ["frameId": hint.frameId, "sourceTimeNs": hint.sourceTimeNs, "sourceClockId": hint.sourceClockId,
            "capturedAtNs": hint.capturedAtNs, "clockId": hint.clockId, "arrivedAtNs": hint.arrivedAtNs,
            "scope": identity(hint.scopeIdentity), "geometry": identity(hint.geometryIdentity), "modelIdentity": identity(hint.modelIdentity),
            "provenance": identity(hint.provenanceIdentity), "width": hint.width, "height": hint.height,
            "maskSha256": digest, "validCells": hint.validity.filter { $0 }.count,
            "unknownCellsStayUnknown": hint.validity.indices.filter { !hint.validity[$0] }.allSatisfy { hint.probability(at: $0) == nil },
            "outsideCellsStayUnknown": hint.probability(at: -1) == nil && hint.probability(at: hint.validity.count) == nil]
        return output
    }
    static func nonfinite(_ hint: Doc?, _ name: String?) -> Doc? {
        guard var hint, let name else { return hint }
        var mask = hint["mask"] as! Doc; var scores = mask["probabilities"] as! [Any]
        scores[0] = name == "nan" ? Double.nan : name == "positive_infinity" ? Double.infinity : -Double.infinity
        mask["probabilities"] = scores; hint["mask"] = mask
        return hint
    }
    static func epoch(_ value: Doc) throws -> LaneSemanticHint.ClockEpoch {
        guard let role = LaneSemanticHint.ClockEpoch.Role(rawValue: value["role"] as! String) else { throw LaneSemanticHint.Invalid(reason: "invalid_clock_role") }
        return try LaneSemanticHint.ClockEpoch(clockId: value["clockId"] as! String, originNs: (value["originNs"] as! NSNumber).int64Value, role: role)
    }
    struct TypedInput {
        var metadata: Doc?
        let width: Int, height: Int
        var probabilities: [Double], validity: [Bool]
        init(_ hint: Doc?) {
            guard let hint else { metadata = nil; width = 0; height = 0; probabilities = []; validity = []; return }
            metadata = hint.filter { $0.key != "mask" }
            let mask = hint["mask"] as! Doc
            width = (mask["width"] as! NSNumber).intValue; height = (mask["height"] as! NSNumber).intValue
            probabilities = (mask["probabilities"] as! [NSNumber]).map { $0 is NSDecimalNumber ? Double($0.stringValue)! : $0.doubleValue }
            validity = mask["validity"] as! [Bool]
        }
        mutating func mutateCaller() {
            if !probabilities.isEmpty { probabilities[0] = .nan }
            if !validity.isEmpty { validity[0] = false }
            if var scope = metadata?["scope"] as? Doc { scope["sessionId"] = "mutated-caller"; metadata?["scope"] = scope }
        }
    }
    static func main() throws {
        guard (2...3).contains(CommandLine.arguments.count) else { fatalError("Expected prepared vector JSON path") }
        let document = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! Doc
        let typed = CommandLine.arguments.last == "--typed"
        let policy = try LaneSemanticHint.Policy(document["policy"] as! Doc)
        var cases: [Doc] = [], sequences: [Doc] = [], clocks: [Doc] = [], policies: [Doc] = []
        for item in document["qualificationCases"] as? [Doc] ?? [] {
            let hint = nonfinite(item["hint"] as? Doc, item["nonfiniteScore"] as? String)
            let baseline = Baseline(); let before = baseline.signature as NSDictionary
            var buffers = typed ? TypedInput(hint) : nil
            let input = typed ? LaneSemanticHint.prepareGuidanceTyped(baseline, metadata: buffers!.metadata, width: buffers!.width, height: buffers!.height,
                probabilities: buffers!.probabilities, validity: buffers!.validity, context: item["context"] as! Doc, policy: policy) :
                LaneSemanticHint.prepareGuidance(baseline, hint: hint, context: item["context"] as! Doc, policy: policy)
            if item["mutateCallerBuffers"] as? Bool == true {
                buffers?.mutateCaller()
                if let evidence = input.qualification.hint {
                    var exposedScores = evidence.probabilities, exposedValidity = evidence.validity
                    if !exposedScores.isEmpty { exposedScores[0] = .nan; exposedValidity[0] = false }
                }
            }
            var row = record(input.qualification); row["id"] = item["id"]!
            row["baselinePreserved"] = input.baseline === baseline && before.isEqual(to: baseline.signature)
            row["baseline"] = baseline.signature; cases.append(row)
        }
        for item in document["cacheSequences"] as? [Doc] ?? [] {
            let cache = try LaneSemanticHint.Cache(policy: policy, context: item["context"] as! Doc)
            var steps: [Doc] = []
            for operation in item["operations"] as! [Doc] {
                var row: Doc
                switch operation["op"] as! String {
                case "offer":
                    let hint = nonfinite(operation["hint"] as? Doc, operation["nonfiniteScore"] as? String)
                    if typed {
                        var buffers = TypedInput(hint)
                        let offered = cache.offerTyped(buffers.metadata, width: buffers.width, height: buffers.height, probabilities: buffers.probabilities, validity: buffers.validity)
                        if operation["mutateCallerBuffers"] as? Bool == true { buffers.mutateCaller() }
                        row = record(offered)
                    } else { row = record(cache.offer(hint)) }
                case "advance": row = ["reason": cache.advance(operation["context"] as! Doc)]
                case "reset":
                    do { try cache.resetScope(operation["context"] as! Doc); row = ["reason": "reset"] }
                    catch let error as LaneSemanticHint.Invalid { row = ["reason": error.reason] }
                case "current": row = record(cache.current())
                default: fatalError("Unknown operation")
                }
                row["current"] = record(cache.current()); row["latestSourceTimeNs"] = cache.latestSourceTimeNs as Any? ?? NSNull()
                steps.append(row)
            }
            sequences.append(["id": item["id"]!, "steps": steps])
        }
        for item in document["clockCases"] as? [Doc] ?? [] {
            var row: Doc = ["id": item["id"]!]
            do {
                if item["kind"] as? String == "exposure" {
                    row["exposure"] = try LaneSemanticHint.exposure(frameId: item["frameId"] as! String,
                        source: epoch(item["source"] as! Doc), sourceNs: (item["sourceNs"] as! NSNumber).int64Value, sourceClockId: item["sourceClockId"] as! String,
                        capture: epoch(item["capture"] as! Doc), captureNs: (item["captureNs"] as! NSNumber).int64Value, captureClockId: item["captureClockId"] as! String,
                        clocksKnown: item["known"] as! Bool)
                } else {
                    row["relativeNs"] = try epoch(item["epoch"] as! Doc).relative(readingNs: (item["readingNs"] as! NSNumber).int64Value,
                        clockId: item["readingClockId"] as! String, known: item["known"] as! Bool)
                }
                row["reason"] = "mapped"
            } catch let error as LaneSemanticHint.Invalid { row["reason"] = error.reason }
            clocks.append(row)
        }
        for item in document["policyCases"] as? [Doc] ?? [] {
            var reason = "valid_policy"
            do { _ = try LaneSemanticHint.Policy(item["policy"] as! Doc) }
            catch let error as LaneSemanticHint.Invalid { reason = error.reason }
            policies.append(["id": item["id"]!, "reason": reason])
        }
        let output: Doc = ["qualificationCases": cases, "cacheSequences": sequences, "clockCases": clocks, "policyCases": policies]
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]))
    }
}
