import Foundation

@main struct SemanticSelectorParity {
    typealias Doc = [String: Any]
    static func main() throws {
        let document = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! Doc
        var rows: [Doc] = []
        for scenario in document["cases"] as! [Doc] {
            let baseline = RoadBoundaryEgoSelector(), guided = RoadBoundaryEgoSelector()
            var frames: [Doc] = []
            for frame in scenario["frames"] as! [Doc] {
                let boundaries = (frame["boundaries"] as! [Doc]).map { value -> RoadBoundaryEvidence in
                    RoadBoundaryEvidence(points: (value["points"] as! [[Double]]).map { LanePoint(x: $0[0], y: $0[1]) },
                        confidence: value["confidence"] as! Double, cue: RoadBoundaryCue(rawValue: value["cue"] as! String)!, supportRows: value["supportRows"] as! Int,
                        provenance: RoadBoundaryProvenance(rawValue: value["provenance"] as! String)!)
                }
                let items = boundaries.indices.map { RoadBoundaryPresentationItem(trackId: Int64($0 + 1), boundaryIndex: $0,
                    state: "confirmed", observationCount: 4, firstObservedSeconds: 0, lastObservedSeconds: frame["time"] as! Double, missedExposures: 0) }
                let snapshot = RoadBoundaryPresentationSnapshot(accepted: true, reason: nil, visibleBoundaryIndices: frame["visible"] as! [Int], items: items, rawCount: boundaries.count)
                let adjustments = (frame["adjustments"] as? [Any]).map { values in values.map { value -> Double in
                    if let value = value as? String { return value == "nan" ? .nan : .infinity }
                    return (value as! NSNumber).doubleValue
                } }
                let before = boundaries
                let left = baseline.select(snapshot, boundaries: boundaries, visual: nil, time: frame["time"] as! Double, key: "fixture", fragmentAware: frame["fragmentAware"] as? Bool ?? false)
                let right = guided.select(snapshot, boundaries: boundaries, visual: nil, time: frame["time"] as! Double, key: "fixture", fragmentAware: frame["fragmentAware"] as? Bool ?? false, semanticScoreAdjustments: adjustments)
                frames.append(["baseline": left.diagnosticFields, "guided": right.diagnosticFields,
                    "rawEvidenceUnchanged": boundaries == before,
                    "confirmationCountsUnchanged": right.items.map(\.observationCount) == snapshot.items.map(\.observationCount),
                    "rawConfidence": boundaries.map(\.confidence), "rawSupportRows": boundaries.map(\.supportRows)])
            }
            rows.append(["id": scenario["id"]!, "frames": frames])
        }
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys]))
    }
}
