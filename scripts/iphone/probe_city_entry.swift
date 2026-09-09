import Foundation
import CoreML
import Vision
import ImageIO
import CryptoKit
// Usage after compiling with swiftc: probe PACK_DIR IMAGE OUTPUT_JSON X1 Y1 X2 Y2
// Runs real bundled Core ML inference on macOS CPU; this is not an iPhone device test.
let args = CommandLine.arguments
guard args.count == 8, let x1 = Double(args[4]), let y1 = Double(args[5]),
      let x2 = Double(args[6]), let y2 = Double(args[7]), x2 > x1, y2 > y1 else {
    fputs("Usage: probe PACK_DIR IMAGE OUTPUT_JSON X1 Y1 X2 Y2\n", stderr); exit(64)
}
let root = URL(fileURLWithPath: args[1])
let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: args[2]) as CFURL, nil)!
let image = CGImageSourceCreateImageAtIndex(source, 0, nil)!
let configuration = MLModelConfiguration(); configuration.computeUnits = .cpuOnly
let detector = try VNCoreMLModel(for: MLModel(contentsOf: root.appendingPathComponent("yolo11n_panoramax.mlmodelc"), configuration: configuration))
let manifest = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("manifest.json"))) as! [String: Any]
let imageSHA256 = SHA256.hash(data: try Data(contentsOf: URL(fileURLWithPath: args[2]))).map { String(format: "%02x", $0) }.joined()
let metadata = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("classify_de_road_signs.mlmodelc/metadata.json"))) as! [[String: Any]]
let labels = metadata[0]["classLabels"] as! [String]
let supportsCity = ["city:start", "city_limit:start", "city_entry", "DE:310"].contains { labels.contains($0) }
let classifier = try VNCoreMLModel(for: MLModel(contentsOf: root.appendingPathComponent("classify_de_road_signs.mlmodelc"), configuration: configuration))
let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
func box(_ r: CGRect) -> [String: Double] { ["x":r.minX,"y_bottom":r.minY,"width":r.width,"height":r.height] }
func classify(_ roi: CGRect) throws -> [[String: Any]] {
 let request = VNCoreMLRequest(model: classifier); request.imageCropAndScaleOption = .scaleFill; request.regionOfInterest = roi
 try handler.perform([request])
 return (request.results as? [VNClassificationObservation] ?? []).prefix(10).map { ["class_id":$0.identifier,"raw_score":Double($0.confidence)] }
}
func padded(_ r: CGRect, left:Double, top:Double, bottom:Double) -> CGRect {
 let x=max(0,r.minX-r.width*left),y=max(0,r.minY-r.height*bottom)
 return CGRect(x:x,y:y,width:min(1,r.maxX+r.width*left)-x,height:min(1,r.maxY+r.height*top)-y)
}
let request = VNCoreMLRequest(model: detector);request.imageCropAndScaleOption = .scaleFit
try handler.perform([request])
var detections:[[String:Any]]=[]
for object in (request.results as? [VNRecognizedObjectObservation] ?? []).sorted(by:{$0.confidence>$1.confidence}).prefix(15) {
 let roi=padded(object.boundingBox,left:0.10,top:0.05,bottom:0.35)
 var row:[String:Any]=["bbox":box(object.boundingBox),"raw_score":Double(object.confidence),"labels":object.labels.prefix(3).map{["class_id":$0.identifier,"raw_score":Double($0.confidence)]}]
 if object.labels.first?.identifier.lowercased().contains("sign") == true { row["classifier_top10_mobile_crop"] = try classify(roi) }
 detections.append(row)
}
let roi=CGRect(x:x1/Double(image.width),y:1-y2/Double(image.height),width:(x2-x1)/Double(image.width),height:(y2-y1)/Double(image.height))
let mobile=padded(roi,left:0.10,top:0.05,bottom:0.35),prolix=padded(roi,left:0.15,top:0.15,bottom:0.15)
let result:[String:Any]=["kind":"actual_coreml_inference","execution":"macOS CoreML CPU-only; same bundled detector/classifier as iPhone; no physical-device run","image":args[2],"image_sha256":imageSHA256,"pack_id":manifest["pack_id"]!,"classifier_identity":manifest["classifier"]!,"detector_identity":manifest["detector"]!,"width":image.width,"height":image.height,"full_scene_detector":detections,"annotated_city_roi":box(roi),"annotated_crop_classifier_top10":try classify(roi),"mobile_padding_classifier_top10":try classify(mobile),"prolix_padding_classifier_top10":try classify(prolix),"classifier_supports_city_entry":supportsCity,"classifier_class_count":labels.count]
let data=try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]);try data.write(to:URL(fileURLWithPath:args[3]));print(String(data:data,encoding:.utf8)!)
