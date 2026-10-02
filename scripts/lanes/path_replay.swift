import Foundation

private struct PathFixture: Decodable {
    let id: String; let scope: String; let nowSeconds: Double
    let calibration: RoadPathCalibration?; let poses: [RoadPathPose]
    let observations: [RoadPathObservation]; let corridors: [RoadPathCorridor]
}
private struct PixelFixture: Decodable {
    let id: String; let width: Int; let height: Int; let pixelsPath: String; let maximumOperations: Int?
}
private struct Fixture: Decodable { let boundaryCases: [PixelFixture]; let pathCases: [PathFixture] }

@main
struct PathReplay {
    static func main() throws {
        guard CommandLine.arguments.count==2 else { throw NSError(domain: "PathReplay",code: 64) }
        let fixture=try JSONDecoder().decode(Fixture.self,from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        var boundaryResults=[[String: Any]](), pathResults=[[String: Any]]()
        for c in fixture.boundaryCases {
            let pixels=[UInt8](try Data(contentsOf: URL(fileURLWithPath: c.pixelsPath)))
            let r=RoadBoundaryDetector().detect(grayscale: pixels,width: c.width,height: c.height,timestampSeconds: 0.8,
                maximumOperations: c.maximumOperations ?? 250_000)
            boundaryResults.append(["id": c.id,"timestampSeconds": r.timestampSeconds,"budgetExceeded": r.budgetExceeded,"operationCount": r.operationCount,
                "boundaries": r.boundaries.map { b in ["confidence": b.confidence,"cue": b.cue.rawValue,"supportRows": b.supportRows,"points": b.points.map { [$0.x,$0.y] }] as [String: Any] },
                "corridors": r.corridors.map { c in ["leftBoundaryIndex": c.leftBoundaryIndex,"rightBoundaryIndex": c.rightBoundaryIndex,"confidence": c.confidence] as [String: Any] }])
        }
        for c in fixture.pathCases {
            let r=RoadPathEvidence.evaluate(scope: c.scope,nowSeconds: c.nowSeconds,observations: c.observations,poses: c.poses,calibration: c.calibration,corridors: c.corridors)
            var row: [String: Any] = ["id": c.id,"result": try JSONSerialization.jsonObject(with: JSONEncoder().encode(r)),
                "roles": RoadPathEvidence.inferCorridorRoles(scope: c.scope,nowSeconds: c.nowSeconds,poses: c.poses,corridors: c.corridors).map(\.role)]
            if let p=RoadPathEvidence.causalPoseAt(scope: c.scope,timeSeconds: c.nowSeconds,poses: c.poses) {
                row["alignedPose"]=["timeSeconds": p.timeSeconds,"eastMeters": p.eastMeters,"northMeters": p.northMeters,"horizontalAccuracyMeters": p.horizontalAccuracyMeters]
                if let camera=c.calibration, let projected=RoadPathEvidence.projectGround(imageX: 0.5,imageY: 0.7,pose: p,calibration: camera) {
                    row["projectedGround"]=["x": projected.x,"y": projected.y]
                }
            }
            pathResults.append(row)
        }
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: ["boundaryCases": boundaryResults,"pathCases": pathResults],options: [.sortedKeys]))
    }
}
