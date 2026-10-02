// Offline reproduction: identical images, fixed versus slightly varying camera intrinsics.
// Compile with the nine RoadPathSession replay sources; no device or app changes.
import Foundation
@main struct Probe {
 static func main() throws {
  var gray=[UInt8](repeating:55,count:128*72)
  for y in 0..<72 { for x in [29,30,31,94,95,96] { gray[y*128+x]=230 } }
  let scope=TSRApplicabilityScope(sessionId:"fixture",bundleId:"camera",cameraGeometryId:"geometry",generation:1,contextGeneration:1,traversalEpoch:1)
  var report:[String:Any]=[:]
  for drifting in [false,true] {
   let session=RoadPathSession(previewMode:true,nowUptime:{1})
   var frames:[[String:Any]]=[]
   for i in 0..<10 {
    let c=RoadPathCalibration(revision:"mount",verified:true,fx:0.8,fy:0.8,cx:0.5+(drifting ? Double(i)*0.00001 : 0),cy:0.5,yawDegrees:0,pitchDegrees:0,rollDegrees:0,heightMeters:1.6,lateralOffsetMeters:-0.08)
    let f=RoadPathCameraFrame(grayscale:gray,width:128,height:72,capturedAtSeconds:10+Double(i)*0.1,geometryId:"geometry",calibration:c,clockKnown:true,preprocessingMs:0,startedAt:1,rawWidth:128,rawHeight:72,sourceTimestampSeconds:10+Double(i)*0.1)
    let p=session.prepare(frame:f,frameId:"frame-\(i)",scope:scope)
    frames.append(["frame":i,"raw":p.geometry.boundaries.count,"visible":p.presentation.visibleBoundaryIndices.count,"presentationReason":p.presentation.reason as Any? ?? NSNull(),"temporalReason":p.geometry.temporalResetReason as Any? ?? NSNull()])
   }
   report[drifting ? "tinyIntrinsicDrift" : "fixedIntrinsics"]=frames
  }
  print(String(data:try JSONSerialization.data(withJSONObject:report,options:[.sortedKeys,.prettyPrinted]),encoding:.utf8)!)
 }
}
