import Foundation
import AVFoundation
import Vision
import CoreML
import CoreGraphics
import CryptoKit
import Darwin

enum ReplayError: Error { case arguments, incompatibleModel, invalidFrame }

/// Local recorded-video harness. Uses the production observer and PNG encoder,
/// with the same Vision preprocessing as the two-stage iPhone backend.
@main
struct DashcamCropReplay {
    static func main() async {
        do { try await run() }
        catch {
            FileHandle.standardError.write(Data("Replay failed: \(error)\n".utf8))
            exit(1)
        }
    }

    private static func run() async throws {
        let arguments = CommandLine.arguments
        guard arguments.count >= 4 else {
            print("Usage: replay-dashcam VIDEO MODEL_PACK OUTPUT [INTERVAL [START [END]]]")
            throw ReplayError.arguments
        }
        let video = URL(fileURLWithPath: arguments[1]), pack = URL(fileURLWithPath: arguments[2]), output = URL(fileURLWithPath: arguments[3])
        let interval = arguments.count > 4 ? Double(arguments[4]) ?? 0 : 0.1
        let start = arguments.count > 5 ? Double(arguments[5]) ?? -1 : 0
        guard interval.isFinite, interval >= 0.1, start.isFinite, start >= 0,
              !FileManager.default.fileExists(atPath: output.appendingPathComponent("frames.ndjson").path) else { throw ReplayError.arguments }
        let manifestBytes = try Data(contentsOf: pack.appendingPathComponent("manifest.json"))
        let manifest = try JSONSerialization.jsonObject(with: manifestBytes) as! [String: Any]
        guard manifest["pipeline"] as? String == "proposal_classification" else { throw ReplayError.incompatibleModel }
        let manifestHash = SHA256.hash(data: manifestBytes).map { String(format: "%02x", $0) }.joined()
        let configuration = MLModelConfiguration(); configuration.computeUnits = .all
        func load(_ role: String) throws -> VNCoreMLModel {
            let component = manifest[role] as! [String: Any]
            let artifact = (component["artifacts"] as! [[String: Any]]).first { $0["platform"] as? String == "ios" }!
            return try VNCoreMLModel(for: MLModel(contentsOf: pack.appendingPathComponent(artifact["path"] as! String), configuration: configuration))
        }
        let detector = try load("detector"), classifier = try load("classifier")
        let mapping = Dictionary(uniqueKeysWithValues: (manifest["class_mapping"] as! [[String: Any]]).map { ($0["class_id"] as! String, $0) })
        let unknownThreshold = (manifest["thresholds"] as! [String: Any])["unknown"] as! Double
        let asset = AVURLAsset(url: video), duration = try await asset.load(.duration).seconds
        let end = min(duration, arguments.count > 6 ? Double(arguments[6]) ?? duration : duration)
        guard end.isFinite, end > start else { throw ReplayError.arguments }
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        let traceURL = output.appendingPathComponent("frames.ndjson")
        FileManager.default.createFile(atPath: traceURL.path, contents: nil)
        let trace = try FileHandle(forWritingTo: traceURL); defer { try? trace.close() }
        let generator = AVAssetImageGenerator(asset: asset)
        generator.appliesPreferredTrackTransform = true
        generator.requestedTimeToleranceBefore = .zero; generator.requestedTimeToleranceAfter = .zero
        let observer = SignCollectionObserver(), color = CGColorSpace(name: CGColorSpace.sRGB)!
        var crops = [[String: Any]](), sightings = [[String: Any]](), labels = [String: String](), frameCount = 0
        let replayStarted = ProcessInfo.processInfo.systemUptime
        for tick in 0..<Int(ceil((end - start) / interval)) {
            let generated = try await generator.image(at: CMTime(seconds: start + Double(tick) * interval, preferredTimescale: 60000))
            let pts = generated.actualTime.seconds
            try autoreleasepool {
                let image = generated.image
                let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
                let began = ProcessInfo.processInfo.systemUptime
                let request = VNCoreMLRequest(model: detector); request.imageCropAndScaleOption = .scaleFit
                try handler.perform([request])
                guard let objects = request.results as? [VNRecognizedObjectObservation] else { throw ReplayError.incompatibleModel }
                let proposals = objects.filter { object in
                    let label = object.labels.first?.identifier ?? ""
                    return ["sign", "class0", "0"].contains(label) && Double(object.confidence) >= unknownThreshold && valid(object.boundingBox)
                }.sorted { $0.confidence > $1.confidence }.prefix(12)
                var detections = [SignCollectionObserver.Detection](), traceDetections = [[String: Any]]()
                for proposal in proposals {
                    let classifierRequest = VNCoreMLRequest(model: classifier)
                    classifierRequest.imageCropAndScaleOption = .scaleFill
                    // Identical xpad10/lower35/upper5 ROI to the iPhone backend.
                    let b = proposal.boundingBox
                    let left = max(0, b.minX - b.width * 0.10), right = min(1, b.maxX + b.width * 0.10)
                    let bottom = max(0, b.minY - b.height * 0.35), top = min(1, b.maxY + b.height * 0.05)
                    classifierRequest.regionOfInterest = CGRect(x: left, y: bottom, width: right - left, height: top - bottom)
                    try handler.perform([classifierRequest])
                    guard let classification = (classifierRequest.results as? [VNClassificationObservation])?.first else { throw ReplayError.incompatibleModel }
                    let entry = mapping[classification.identifier]
                    let score = min(Double(proposal.confidence), Double(classification.confidence))
                    guard score >= (entry?["threshold"] as? Double ?? unknownThreshold),
                          entry?["sign_role"] as? String != "supplementary_plate" else { continue }
                    let box = [Double(b.minX), Double(1 - b.maxY), Double(b.width), Double(b.height)]
                    let label = entry?["label"] as? String ?? classification.identifier
                    let payload: [String: Any] = ["label": label, "raw_class_id": classification.identifier,
                        "scores": ["detector_raw": Double(proposal.confidence), "classifier_raw": Double(classification.confidence)],
                        "evidence": ["replay_box": box]]
                    let key = manifestHash + ":" + label
                    detections.append(.init(key: key, box: box, payload: payload, presentationTrack: nil))
                    traceDetections.append(["key": key, "label": label, "raw_class_id": classification.identifier, "box": box,
                        "detector_raw": Double(proposal.confidence), "classifier_raw": Double(classification.confidence)])
                }
                let inferenceMs = (ProcessInfo.processInfo.systemUptime - began) * 1000
                var upright: CGImage?, baselineCount = 0, sequenceCount = 0, failure: Error?
                func save(box: [Double], observationID: String, variant: String) throws {
                    let began = ProcessInfo.processInfo.systemUptime
                    if upright == nil {
                        guard let context = CGContext(data: nil, width: image.width, height: image.height, bitsPerComponent: 8,
                            bytesPerRow: image.width * 4, space: color, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { throw ReplayError.invalidFrame }
                        context.draw(image, in: CGRect(x: 0, y: 0, width: image.width, height: image.height))
                        upright = context.makeImage()
                    }
                    guard let upright else { throw ReplayError.invalidFrame }
                    let crop = try SignCollectionCrop.generate(upright: upright, box: Dictionary(uniqueKeysWithValues: zip(["x", "y", "width", "height"], box)), hashSource: false)
                    let name = "\(variant)-\(crops.count).png"
                    try crop.bytes.write(to: output.appendingPathComponent(name))
                    crops.append(["variant": variant, "observation_id": observationID, "label": labels[observationID] ?? "unknown",
                        "frame_seconds": pts, "source_width": image.width, "source_height": image.height,
                        "box": box, "original_box": crop.geometry.original, "requested_box": crop.geometry.requested, "actual_box": crop.geometry.actual,
                        "byte_length": crop.bytes.count, "capture_ms": (ProcessInfo.processInfo.systemUptime - began) * 1000, "file": name])
                }
                try observer.observe(at: Date(timeIntervalSince1970: pts), detections: detections, captureCrop: { candidate in
                    guard sequenceCount < 4 else { return .skipped }
                    sequenceCount += 1
                    do { try save(box: candidate.box, observationID: candidate.observationID, variant: "sequence"); return .stored }
                    catch { failure = error; return .failed }
                }) { observation in
                    let observationID = observation["event_id"] as! String
                    labels[observationID] = observation["label"] as? String
                    var event = observation; event["observation_id"] = observationID; event["frame_seconds"] = pts
                    sightings.append(event)
                    if baselineCount < 4 {
                        baselineCount += 1
                        try save(box: (observation["evidence"] as! [String: Any])["replay_box"] as! [Double], observationID: observationID, variant: "baseline")
                    }
                }
                if let failure { throw failure }
                let row: [String: Any] = ["frame_seconds": pts, "width": image.width, "height": image.height,
                    "inference_ms": inferenceMs, "sequence_count": sequenceCount, "detections": traceDetections]
                try trace.write(contentsOf: JSONSerialization.data(withJSONObject: row, options: [.sortedKeys]) + Data([10]))
                frameCount += 1
            }
            if tick % 100 == 0 {
                print("Replay: \(frameCount) frames, \(String(format: "%.1f", pts)) s, \(crops.count) crops")
                fflush(stdout)
            }
        }
        let report: [String: Any] = ["video": video.lastPathComponent, "duration_seconds": duration, "start_seconds": start, "end_seconds": end,
            "interval_seconds": interval, "frames": frameCount, "country": (manifest["countries"] as! [String])[0],
            "pack_id": manifest["pack_id"]!, "manifest_sha256": manifestHash, "wall_seconds": ProcessInfo.processInfo.systemUptime - replayStarted,
            "sightings": sightings, "crops": crops, "limitations": [
                "Recorded video, not original live analysis/Panoramax pixels; no GPS or saved visual calibration reconstruction.",
                "Fresh Core ML inference on Mac with iPhone Vision preprocessing; not an Android inference benchmark.",
                "Unpaced sampled replay; capture timing includes disk writes, excludes live camera contention, thermal and battery behavior."]]
        try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: output.appendingPathComponent("report.json"))
        print("Replay complete: \(frameCount) frames, \(sightings.count) sightings, \(crops.count) crops")
    }

    private static func valid(_ box: CGRect) -> Bool {
        box.minX.isFinite && box.minY.isFinite && box.width.isFinite && box.height.isFinite && box.width > 0 && box.height > 0 &&
            box.minX >= 0 && box.minY >= 0 && box.maxX <= 1 && box.maxY <= 1
    }
}
