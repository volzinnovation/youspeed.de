import Foundation

/// Host-only timings for the actual core; external JSON parsing is measured separately.
@main struct SemanticHintBenchmark {
    typealias Doc = LaneSemanticHint.Document
    static func now() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
    static func milliseconds(_ start: UInt64) -> Double { Double(now() - start) / 1_000_000 }
    static func main() throws {
        guard (4...5).contains(CommandLine.arguments.count), let warmups = Int(CommandLine.arguments[2]),
              let repeats = Int(CommandLine.arguments[3]), (1...20).contains(warmups), (3...100).contains(repeats) else {
            fatalError("Expected vectors.json warmups[1..20] repeats[3..100]")
        }
        let typed = CommandLine.arguments.last == "--typed"
        var start = now()
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let readMs = milliseconds(start); start = now()
        let document = try JSONSerialization.jsonObject(with: data) as! Doc
        let parseMs = milliseconds(start)
        let policy = try LaneSemanticHint.Policy(document["policy"] as! Doc)
        let cases = (document["qualificationCases"] as! [Doc]).filter { $0["expectedReason"] as? String == "qualified" }
        guard !cases.isEmpty else { fatalError("No expected-qualified cases") }
        var outputs: [Doc] = []
        for item in cases {
            let context = item["context"] as! Doc, hint = item["hint"] as! Doc
            let materializeStart = now()
            let mask = hint["mask"] as! Doc
            let metadata = hint.filter { $0.key != "mask" }
            let scores = typed ? (mask["probabilities"] as! [NSNumber]).map { $0 is NSDecimalNumber ? Double($0.stringValue)! : $0.doubleValue } : []
            let validity = typed ? mask["validity"] as! [Bool] : []
            let width = (mask["width"] as! NSNumber).intValue, height = (mask["height"] as! NSNumber).intValue
            let materializationMs = milliseconds(materializeStart)
            var samples: [Doc] = []
            for iteration in 0..<(warmups + repeats) {
                let cycleStart = now()
                var sample = try autoreleasepool { () throws -> Doc in
                    var start = now()
                    let qualified = typed ? LaneSemanticHint.qualifyTyped(metadata, width: width, height: height, probabilities: scores, validity: validity, context: context, policy: policy) : LaneSemanticHint.qualify(hint, context: context, policy: policy)
                    let qualifyMs = milliseconds(start)
                    guard qualified.accepted else { fatalError(qualified.reason) }
                    start = now()
                    let cache = try LaneSemanticHint.Cache(policy: policy, context: context)
                    let cacheInitMs = milliseconds(start)
                    start = now()
                    let offered = typed ? cache.offerTyped(metadata, width: width, height: height, probabilities: scores, validity: validity) : cache.offer(hint)
                    let cacheOfferMs = milliseconds(start)
                    guard offered.accepted else { fatalError(offered.reason) }
                    start = now()
                    let current = cache.current()
                    let cacheCurrentMs = milliseconds(start)
                    guard current.accepted else { fatalError(current.reason) }
                    return ["qualificationMs": qualifyMs, "cacheConstructionMs": cacheInitMs,
                        "acceptedOfferMs": cacheOfferMs, "currentRevalidationMs": cacheCurrentMs]
                }
                sample["cycleMs"] = milliseconds(cycleStart)
                if iteration >= warmups { samples.append(sample) }
            }
            outputs.append(["id": item["id"]!, "width": width, "height": height, "typedMaterializationMs": materializationMs, "samples": samples])
        }
        let output: Doc = ["schemaVersion": 1, "platform": "swift", "clock": "DispatchTime.uptimeNanoseconds",
            "warmupsPerCase": warmups, "measuredRepetitionsPerCase": repeats,
            "inputRepresentation": typed ? "typed_buffers" : "json_bridge", "inputBytes": data.count, "inputReadMs": readMs, "inputParseMs": parseMs, "cases": outputs]
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]))
    }
}
