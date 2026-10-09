import Foundation
import CryptoKit

/// TSV input: id, absolute luma path, width, height, source PTS. JSON lines on stdout.
@main struct DetectorParity {
    static func main() throws {
        for line in try String(contentsOfFile:CommandLine.arguments[1],encoding:.utf8).split(separator:"\n") {
            let fields=line.split(separator:"\t",omittingEmptySubsequences:false).map(String.init)
            let width=Int(fields[2])!, height=Int(fields[3])!, time=Double(fields[4])!
            let bytes=Array(try Data(contentsOf:URL(fileURLWithPath:fields[1])))
            guard let filtered=RoadBoundaryPreprocessor.topHat5ForDetector(grayscale:bytes,width:width,height:height) else { throw NSError(domain:"Input",code:1) }
            let digest=SHA256.hash(data:Data(filtered)).map { String(format:"%02x",$0) }.joined()
            for options in [RoadBoundaryDetectionOptions(),RoadBoundaryDetectionOptions(useSearchBands:true),RoadBoundaryDetectionOptions(groupFragments:true),RoadBoundaryDetectionOptions(useSearchBands:true,groupFragments:true)] {
                var events: [[String: Any]] = []
                let frame=RoadBoundaryDetector().detect(grayscale:filtered,width:width,height:height,timestampSeconds:time,options:options,trace:{ events.append($0) })
                let untraced=RoadBoundaryDetector().detect(grayscale:filtered,width:width,height:height,timestampSeconds:time,options:options)
                guard frame == untraced else { throw NSError(domain:"TraceChangedDetection",code:1) }
                let value:[String:Any]=["id":fields[0],"variant":options.identifier,"filteredSha256":digest,"trace":events,"traceEquivalent":true,
                    "operationCount":frame.operationCount,"budgetExceeded":frame.budgetExceeded,"rejectionCounts":frame.rejectionCounts,
                    "boundaries":frame.boundaries.map { b -> [String:Any] in ["points":b.points.map { [$0.x,$0.y] },"confidence":b.confidence,
                        "cue":b.cue.rawValue,"supportRows":b.supportRows,"observedSegments":b.observedSegments.map { $0.map { [$0.x,$0.y] } },
                        "geometryConfidence":b.geometryConfidence as Any? ?? NSNull(),"paintOccupancy":b.paintOccupancy as Any? ?? NSNull()] },
                    "corridors":frame.corridors.map { ["leftBoundaryIndex":$0.leftBoundaryIndex,"rightBoundaryIndex":$0.rightBoundaryIndex,"confidence":$0.confidence] }]
                print(String(data:try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]),encoding:.utf8)!)
            }
        }
    }
}
