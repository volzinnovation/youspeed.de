import SwiftUI
import CoreML
import Vision
import ImageIO
import CryptoKit
import Darwin

struct BenchmarkManifest: Decodable {
    struct Model: Decodable {
        let id: String
        let path: String
        let classCount: Int
        let classLabels: [String]
        let sha256: String
    }
    struct Image: Decodable {
        let id: String
        let path: String
        let canonicalPath: String
        let sha256: String
        let canonicalSha256: String
        let canonicalRGBSha256: String?
        let source: String
    }
    let schemaVersion: Int
    let models: [Model]
    let images: [Image]
    let warmupCount: Int
    let rounds: Int
    let repeatsPerImage: Int
    let computeUnits: String?
}

enum BenchmarkError: Error, CustomStringConvertible {
    case invalid(String)
    var description: String { switch self { case .invalid(let message): return message } }
}

private func require(_ condition: Bool, _ message: String) throws {
    if !condition { throw BenchmarkError.invalid(message) }
}

private func benchmarkClock() -> UInt64 { DispatchTime.now().uptimeNanoseconds }
private func milliseconds(since start: UInt64) -> Double { Double(benchmarkClock() - start) / 1_000_000 }
private func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }

private func fileDigest(_ url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var hash = SHA256()
    while let chunk = try handle.read(upToCount: 1_048_576), !chunk.isEmpty { hash.update(data: chunk) }
    return hash.finalize().map { String(format: "%02x", $0) }.joined()
}

private func containedURL(_ relative: String, root: URL) throws -> URL {
    try require(!relative.hasPrefix("/") && !relative.split(separator: "/").contains(".."), "Unsafe relative input path")
    let resolved = root.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
    try require(resolved.path.hasPrefix(root.resolvingSymlinksInPath().path + "/"), "Input escapes package directory")
    return resolved
}

// Directory digest: sorted UTF-8 relative path + NUL + lowercase file SHA + LF.
private func artifactDigest(_ url: URL) throws -> String {
    var isDirectory: ObjCBool = false
    try require(FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory), "Missing model artifact")
    if !isDirectory.boolValue { return try fileDigest(url) }
    let keys: [URLResourceKey] = [.isRegularFileKey, .isSymbolicLinkKey]
    // atPath emits relative names. URL enumeration may canonicalize /var to
    // /private/var on iOS; slicing its absolute path by the original prefix
    // length then hashes truncated or extra path characters.
    guard let iterator = FileManager.default.enumerator(atPath: url.path) else {
        throw BenchmarkError.invalid("Cannot enumerate model artifact")
    }
    var files: [(String, URL)] = []
    for case let name as String in iterator {
        let file = url.appendingPathComponent(name)
        let values = try file.resourceValues(forKeys: Set(keys))
        try require(values.isSymbolicLink != true, "Symbolic link in model artifact")
        if values.isRegularFile == true { files.append((name, file)) }
    }
    try require(!files.isEmpty, "Empty model artifact")
    var text = ""
    for (name, file) in files.sorted(by: { $0.0 < $1.0 }) { text += name + "\0" + (try fileDigest(file)) + "\n" }
    return digest(Data(text.utf8))
}

private func quantile(_ values: [Double], _ q: Double) -> Double {
    let sorted = values.sorted()
    guard !sorted.isEmpty else { return 0 }
    let point = q * Double(sorted.count - 1)
    let low = Int(point), high = min(low + 1, sorted.count - 1)
    return sorted[low] + (point - Double(low)) * (sorted[high] - sorted[low])
}

private func distribution(_ values: [Double]) -> [String: Any] {
    ["count": values.count, "p50_ms": quantile(values, 0.5), "p95_ms": quantile(values, 0.95),
     "min_ms": values.min() ?? 0, "max_ms": values.max() ?? 0,
     "mean_ms": values.isEmpty ? 0 : values.reduce(0, +) / Double(values.count)]
}

private func memorySnapshot() -> [String: Any] {
    var info = mach_task_basic_info()
    var count = mach_msg_type_number_t(MemoryLayout<mach_task_basic_info>.size / MemoryLayout<integer_t>.size)
    let status = withUnsafeMutablePointer(to: &info) { pointer in
        pointer.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
            task_info(mach_task_self_, task_flavor_t(MACH_TASK_BASIC_INFO), $0, &count)
        }
    }
    return ["resident_bytes": status == KERN_SUCCESS ? Int(info.resident_size) : -1,
            "thermal_state": ProcessInfo.processInfo.thermalState.rawValue,
            "low_power_mode": ProcessInfo.processInfo.isLowPowerModeEnabled,
            "uptime_seconds": ProcessInfo.processInfo.systemUptime]
}

private func decode(_ url: URL) throws -> CGImage {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary) else {
        throw BenchmarkError.invalid("Unable to decode \(url.lastPathComponent)")
    }
    return image
}

private func pixelBuffer(_ image: CGImage) throws -> (CVPixelBuffer, String) {
    try require(image.width == 224 && image.height == 224, "Canonical image must be 224x224")
    var buffer: CVPixelBuffer?
    let attrs = [kCVPixelBufferCGImageCompatibilityKey: true, kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary
    let status = CVPixelBufferCreate(kCFAllocatorDefault, 224, 224, kCVPixelFormatType_32BGRA, attrs, &buffer)
    guard status == kCVReturnSuccess, let result = buffer else { throw BenchmarkError.invalid("Cannot allocate pixel buffer") }
    CVPixelBufferLockBaseAddress(result, [])
    defer { CVPixelBufferUnlockBaseAddress(result, []) }
    guard let base = CVPixelBufferGetBaseAddress(result),
          let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
          let context = CGContext(data: base, width: 224, height: 224, bitsPerComponent: 8,
                                  bytesPerRow: CVPixelBufferGetBytesPerRow(result), space: colorSpace,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue) else {
        throw BenchmarkError.invalid("Cannot initialize RGB pixel buffer")
    }
    context.interpolationQuality = .none
    context.draw(image, in: CGRect(x: 0, y: 0, width: 224, height: 224))
    let bytes = base.assumingMemoryBound(to: UInt8.self)
    let stride = CVPixelBufferGetBytesPerRow(result)
    var rgb = Data(capacity: 224 * 224 * 3)
    for y in 0..<224 { for x in 0..<224 {
        let offset = y * stride + x * 4
        try require(bytes[offset + 3] == 255, "Canonical image must be opaque")
        rgb.append(bytes[offset + 2]); rgb.append(bytes[offset + 1]); rgb.append(bytes[offset])
    } }
    return (result, digest(rgb))
}

private func probabilities(_ output: MLFeatureProvider, model: MLModel, classes: [String]) throws -> [Double] {
    guard let name = model.modelDescription.predictedProbabilitiesName,
          let value = output.featureValue(for: name), value.type == .dictionary else {
        throw BenchmarkError.invalid("CoreML classifier probability dictionary unavailable")
    }
    let values = value.dictionaryValue
    try require(Set(values.keys.compactMap { $0 as? String }) == Set(classes), "Output labels differ from frozen class index")
    let result = try classes.map { label -> Double in
        guard let value = values[AnyHashable(label)]?.doubleValue, value.isFinite, value >= 0 else {
            throw BenchmarkError.invalid("Invalid probability for \(label)")
        }
        return value
    }
    try require(abs(result.reduce(0, +) - 1) < 0.002, "Probabilities do not sum to one")
    return result
}

private func bestIndex(_ values: [Double]) -> Int { values.indices.max(by: { values[$0] < values[$1] }) ?? 0 }

@available(iOS 17.4, *)
private func computePlanSummary(url: URL, units: MLComputeUnits) async throws -> [String: Any] {
    let configuration = MLModelConfiguration(); configuration.computeUnits = units
    let plan = try await MLComputePlan.load(contentsOf: url, configuration: configuration)
    var records: [[String: Any]] = []
    func deviceName(_ device: MLComputeDevice) -> String {
        switch device { case .cpu: return "CPU"; case .gpu: return "GPU"; case .neuralEngine: return "NeuralEngine"; @unknown default: return "unknown" }
    }
    func programBlock(_ block: MLModelStructure.Program.Block) {
        for operation in block.operations {
            let usage = plan.deviceUsage(for: operation)
            var row: [String: Any] = ["operator": operation.operatorName, "outputs": operation.outputs.map(\.name),
                                      "preferred": usage.map { deviceName($0.preferred) } ?? "unknown",
                                      "supported": usage.map { $0.supported.map(deviceName) } ?? []]
            if let cost = plan.estimatedCost(of: operation) { row["estimated_cost_weight"] = cost.weight }
            records.append(row)
            for nested in operation.blocks { programBlock(nested) }
        }
    }
    func structure(_ value: MLModelStructure) {
        switch value {
        case .program(let program):
            for name in program.functions.keys.sorted() { programBlock(program.functions[name]!.block) }
        case .neuralNetwork(let network):
            for layer in network.layers {
                let usage = plan.deviceUsage(for: layer)
                records.append(["operator": layer.type, "outputs": layer.outputNames,
                                "preferred": usage.map { deviceName($0.preferred) } ?? "unknown",
                                "supported": usage.map { $0.supported.map(deviceName) } ?? []])
            }
        case .pipeline(let pipeline): for model in pipeline.subModels { structure(model) }
        case .unsupported: break
        @unknown default: break
        }
    }
    structure(plan.modelStructure)
    let counts = records.reduce(into: [String: Int]()) { $0[$1["preferred"] as! String, default: 0] += 1 }
    return ["status": "available", "preferred_operation_counts": counts, "operations": records,
            "scope": "CoreML anticipated compute placement; not an observed per-operation GPU trace"]
}

struct PreparedImage {
    let spec: BenchmarkManifest.Image
    let nativeURL: URL
    let buffer: CVPixelBuffer
    let rgbHash: String
    let canonicalDecodeMs: Double
    let bufferPreparationMs: Double
}

enum ClassifierBenchmark {
    static func run(package: URL, runID: String, metadata: [String: Any]) async throws -> URL {
        let manifestURL = package.appendingPathComponent("manifest.json")
        let data = try Data(contentsOf: manifestURL)
        let manifest = try JSONDecoder().decode(BenchmarkManifest.self, from: data)
        try require(manifest.schemaVersion == 1 && !manifest.models.isEmpty && !manifest.images.isEmpty, "Invalid benchmark manifest")
        try require(manifest.warmupCount >= 0 && manifest.rounds > 0 && manifest.repeatsPerImage > 0, "Invalid repetition counts")
        try require(Set(manifest.images.map(\.id)).count == manifest.images.count, "Duplicate image IDs")
        try require(Set(manifest.models.map(\.id)).count == manifest.models.count, "Duplicate model IDs")
        var prepared: [PreparedImage] = []
        for spec in manifest.images {
            let nativeURL = try containedURL(spec.path, root: package)
            let canonicalURL = try containedURL(spec.canonicalPath, root: package)
            try require(try fileDigest(nativeURL) == spec.sha256, "Native input hash mismatch")
            try require(try fileDigest(canonicalURL) == spec.canonicalSha256, "Canonical input hash mismatch")
            let decodeStart = benchmarkClock(); let image = try decode(canonicalURL)
            let decodeMs = milliseconds(since: decodeStart)
            let bufferStart = benchmarkClock(); let (buffer, rgbHash) = try pixelBuffer(image)
            if let expected = spec.canonicalRGBSha256 { try require(rgbHash == expected, "Canonical RGB pixel hash mismatch") }
            prepared.append(PreparedImage(spec: spec, nativeURL: nativeURL, buffer: buffer, rgbHash: rgbHash,
                                          canonicalDecodeMs: decodeMs, bufferPreparationMs: milliseconds(since: bufferStart)))
        }
        var blocks: [[String: Any]] = []
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        func checkpoint(_ phase: String, modelID: String, round: Int) throws {
            let value: [String: Any] = ["status": "running", "run_id": runID, "phase": phase,
                                        "last_model": modelID, "last_round": round,
                                        "completed_blocks": blocks.count, "snapshot": memorySnapshot()]
            try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
                .write(to: documents.appendingPathComponent("benchmark-\(runID)-progress.json"), options: .atomic)
        }
        let requestedMode = manifest.computeUnits ?? "cpuAndGPU"
        try require(["cpuAndGPU", "all"].contains(requestedMode), "Unsupported compute mode")
        let modes: [(String, MLComputeUnits)] = [(requestedMode, requestedMode == "all" ? .all : .cpuAndGPU)]
        let reverse = ProcessInfo.processInfo.arguments.contains("--reverse-model-order")
        let specs = reverse ? Array(manifest.models.reversed()) : manifest.models
        for (modeName, computeUnits) in modes {
          for globalRound in 0..<manifest.rounds {
            let roundSpecs = globalRound % 2 == 0 ? specs : Array(specs.reversed())
            for spec in roundSpecs {
                try checkpoint("before_model_load", modelID: spec.id, round: globalRound)
                var block: [String: Any] = try autoreleasepool {
                    try require(spec.classCount == spec.classLabels.count && Set(spec.classLabels).count == spec.classCount, "Invalid class index")
                    let sourceURL = try containedURL(spec.path, root: package)
                    let sourceDigest = try artifactDigest(sourceURL)
                    try require(sourceDigest == spec.sha256, "Model hash mismatch: \(spec.id)")
                    let memoryBefore = memorySnapshot()
                    let compileStart = benchmarkClock()
                    let compiled = sourceURL.pathExtension == "mlmodelc" ? sourceURL : try MLModel.compileModel(at: sourceURL)
                    let compileMs = milliseconds(since: compileStart)
                    let config = MLModelConfiguration(); config.computeUnits = computeUnits
                    let loadStart = benchmarkClock(); let model = try MLModel(contentsOf: compiled, configuration: config)
                    let loadMs = milliseconds(since: loadStart)
                    let inputs = model.modelDescription.inputDescriptionsByName.filter { $0.value.type == .image }
                    try require(inputs.count == 1, "Expected exactly one CoreML image input")
                    let inputName = inputs.keys.first!
                    let constraint = inputs[inputName]!.imageConstraint!
                    try require(constraint.pixelsWide == 224 && constraint.pixelsHigh == 224, "CoreML input must be224RGB")
                    if let actual = model.modelDescription.classLabels as? [String] {
                        try require(actual == spec.classLabels, "CoreML class order differs from manifest")
                    }
                    let providers = try prepared.map { try MLDictionaryFeatureProvider(dictionary: [inputName: MLFeatureValue(pixelBuffer: $0.buffer)]) }
                    try checkpoint("before_first_prediction", modelID: spec.id, round: globalRound)
                    let firstStart = benchmarkClock(); let first = try model.prediction(from: providers[0])
                    let firstForwardMs = milliseconds(since: firstStart)
                    _ = try probabilities(first, model: model, classes: spec.classLabels)
                    for i in 0..<manifest.warmupCount { _ = try model.prediction(from: providers[i % providers.count]) }
                    var vectorRows: [[String: Any]] = []
                    var timingRows: [[String: Any]] = []
                    var nativeRows: [[String: Any]] = []
                    var memoryRows: [[String: Any]] = []
                    let vision = try VNCoreMLModel(for: model)
                    for round in [globalRound] {
                        memoryRows.append(["round": round, "phase": "before", "snapshot": memorySnapshot()])
                        for repetition in 0..<manifest.repeatsPerImage {
                            for i in prepared.indices {
                                try autoreleasepool {
                                    let forwardStart = benchmarkClock(); let output = try model.prediction(from: providers[i])
                                    let forwardMs = milliseconds(since: forwardStart)
                                    let p = try probabilities(output, model: model, classes: spec.classLabels)
                                    timingRows.append(["image_id": prepared[i].spec.id, "round": round, "repetition": repetition,
                                                       "forward_ms": forwardMs, "top1_index": bestIndex(p)])
                                    if round == 0 && repetition == 0 {
                                        vectorRows.append(["image_id": prepared[i].spec.id, "source": prepared[i].spec.source,
                                                           "canonical_rgb_sha256": prepared[i].rgbHash, "probabilities": p,
                                                           "top1_index": bestIndex(p), "top1_label": spec.classLabels[bestIndex(p)]])
                                    }
                                }
                            }
                        }
                        memoryRows.append(["round": round, "phase": "after", "snapshot": memorySnapshot()])
                    }
                    // Same supplied native crops, decoded on each iteration. Vision owns resize/color conversion.
                    // Its preprocessing and model scheduling cannot be separated by this API.
                    try checkpoint("before_native_vision", modelID: spec.id, round: globalRound)
                    for i in 0..<manifest.warmupCount {
                        let image = try decode(prepared[i % prepared.count].nativeURL)
                        let request = VNCoreMLRequest(model: vision); request.imageCropAndScaleOption = .scaleFill
                        try VNImageRequestHandler(cgImage: image, orientation: .up).perform([request])
                    }
                    for round in [globalRound] {
                        for repetition in 0..<manifest.repeatsPerImage {
                            for imageSpec in prepared {
                                try autoreleasepool {
                                    let totalStart = benchmarkClock(); let decodeStart = benchmarkClock()
                                    let image = try decode(imageSpec.nativeURL)
                                    let decodeMs = milliseconds(since: decodeStart)
                                    let setupStart = benchmarkClock()
                                    let request = VNCoreMLRequest(model: vision); request.imageCropAndScaleOption = .scaleFill
                                    let handler = VNImageRequestHandler(cgImage: image, orientation: .up)
                                    let setupMs = milliseconds(since: setupStart)
                                    let visionStart = benchmarkClock(); try handler.perform([request])
                                    let visionMs = milliseconds(since: visionStart)
                                    let totalMs = milliseconds(since: totalStart)
                                    guard let observations = request.results as? [VNClassificationObservation], let top = observations.first else {
                                        throw BenchmarkError.invalid("Vision classifier output unavailable")
                                    }
                                    var row: [String: Any] = ["image_id": imageSpec.spec.id, "round": round, "repetition": repetition,
                                                            "decode_ms": decodeMs, "request_setup_ms": setupMs,
                                                            "vision_scale_fill_and_inference_ms": visionMs, "total_ms": totalMs,
                                                            "top1_label": top.identifier, "top1_score": Double(top.confidence)]
                                    if round == 0 && repetition == 0 {
                                        let byLabel = Dictionary(uniqueKeysWithValues: observations.map { ($0.identifier, Double($0.confidence)) })
                                        try require(Set(byLabel.keys) == Set(spec.classLabels), "Vision class labels differ")
                                        row["probabilities"] = spec.classLabels.map { byLabel[$0]! }
                                    }
                                    nativeRows.append(row)
                                }
                            }
                        }
                    }
                    return ["model_id": spec.id, "source_sha256": sourceDigest, "class_labels": spec.classLabels,
                            "benchmark_round": globalRound, "model_order_this_round": roundSpecs.map(\.id),
                            "requested_compute_units": modeName, "neural_engine_allowed": modeName == "all",
                            "actual_compute_placement": "CoreML chooses among allowed units. See anticipated compute plan, not runtime trace; no accelerator-only assertion.",
                            "compiled_model_path": compiled.path,
                            "compile_ms": compileMs, "compile_scope": "MLModel.compileModel call; OS compilation cache may apply",
                            "model_load_ms": loadMs, "first_process_load": globalRound == 0,
                            "load_scope": "Reload per counterbalanced round; only round0 first in process, not reboot-cold",
                            "first_forward_ms": firstForwardMs, "warmup_count": manifest.warmupCount,
                            "memory_before_load": memoryBefore, "memory_after": memorySnapshot(), "memory_round_samples": memoryRows,
                            "canonical_forward_summary": distribution(timingRows.map { $0["forward_ms"] as! Double }),
                            "native_vision_summary": distribution(nativeRows.map { $0["vision_scale_fill_and_inference_ms"] as! Double }),
                            "native_decode_summary": distribution(nativeRows.map { $0["decode_ms"] as! Double }),
                            "native_total_summary": distribution(nativeRows.map { $0["total_ms"] as! Double }),
                            "canonical_probabilities": vectorRows, "canonical_timings": timingRows, "native_timings": nativeRows]
                }
                if #available(iOS 17.4, *) {
                    try checkpoint("before_compute_plan", modelID: spec.id, round: globalRound)
                    do {
                        block["compute_plan"] = try await computePlanSummary(url: URL(fileURLWithPath: block["compiled_model_path"] as! String), units: computeUnits)
                    } catch { block["compute_plan"] = ["status": "unavailable", "error": String(describing: error)] }
                }
                blocks.append(block)
                let progress: [String: Any] = ["status": "running", "run_id": runID, "completed_blocks": blocks.count,
                                                "planned_blocks": manifest.rounds * manifest.models.count * modes.count,
                                                "last_model": spec.id, "last_round": globalRound, "snapshot": memorySnapshot()]
                try JSONSerialization.data(withJSONObject: progress, options: [.prettyPrinted, .sortedKeys])
                    .write(to: documents.appendingPathComponent("benchmark-\(runID)-progress.json"), options: .atomic)
            }
          }
        }
        let output: [String: Any] = ["schema": "youspeed-iphone-classifier-benchmark-v1", "run_id": runID,
                                    "created_at": ISO8601DateFormatter().string(from: Date()), "manifest_sha256": digest(data),
                                    "device": metadata, "status": "complete", "images": manifest.images.count,
                                    "rounds": manifest.rounds, "repeats_per_image": manifest.repeatsPerImage,
                                    "model_order": specs.map(\.id), "order_policy": "Reverse model order on odd-numbered rounds", "blocks": blocks,
                                    "input_preparation": prepared.map { ["image_id": $0.spec.id, "canonical_rgb_sha256": $0.rgbHash,
                                                                       "canonical_decode_ms": $0.canonicalDecodeMs, "buffer_preparation_ms": $0.bufferPreparationMs] },
                                    "scope": "Classification only. Native fixture crops are supplied diagnostic crops; no missing live ROI context is synthesized.",
                                    "timing_notes": "Canonical forward excludes decode and BGRA buffer preparation. Vision perform includes internal scaleFill/color conversion/inference. Full vectors are copied after forward timers. Resident memory is sampled, not a true peak. Detector/OCR/tracking excluded.",
                                    "production_app_modified": false]
        let result = documents.appendingPathComponent("benchmark-\(runID).json")
        try JSONSerialization.data(withJSONObject: output, options: [.prettyPrinted, .sortedKeys]).write(to: result, options: .atomic)
        return result
    }
}

@MainActor final class BenchmarkState: ObservableObject {
    @Published var status = "Waiting for benchmark inputs"
    private var started = false
    func start() {
        guard !started else { return }; started = true
        UIDevice.current.isBatteryMonitoringEnabled = true
        UIApplication.shared.isIdleTimerDisabled = true
        let arguments = ProcessInfo.processInfo.arguments
        let packageName = arguments.first(where: { $0.hasPrefix("--package=") }).map { String($0.dropFirst(10)) } ?? "BenchmarkInputs"
        let runID = arguments.first(where: { $0.hasPrefix("--run-id=") }).map { String($0.dropFirst(9)) } ?? UUID().uuidString
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        var system = utsname(); uname(&system)
        let machineBytes = MemoryLayout.size(ofValue: system.machine)
        let machine = withUnsafePointer(to: &system.machine) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: machineBytes) { String(cString: $0) }
        }
        let metadata: [String: Any] = ["model_identifier": machine, "os_version": UIDevice.current.systemVersion,
                                      "battery_level": UIDevice.current.batteryLevel, "battery_state": UIDevice.current.batteryState.rawValue,
                                      "process": ProcessInfo.processInfo.processName, "initial_snapshot": memorySnapshot(),
                                      "simulator": ProcessInfo.processInfo.environment["SIMULATOR_UDID"] != nil]
        status = "Running classifier benchmark"
        Task.detached(priority: .userInitiated) {
            do {
                try require(!packageName.contains("/") && !runID.contains("/"), "Unsafe package or run identifier")
                let result = try await ClassifierBenchmark.run(package: documents.appendingPathComponent(packageName), runID: runID, metadata: metadata)
                await MainActor.run {
                    self.status = "Complete: \(result.lastPathComponent)"
                    UIApplication.shared.isIdleTimerDisabled = false
                }
                print("CLASSIFIER_BENCHMARK_COMPLETE \(result.lastPathComponent)")
            } catch {
                let failure: [String: Any] = ["status": "failed", "error": String(describing: error), "run_id": runID, "device": metadata]
                if let bytes = try? JSONSerialization.data(withJSONObject: failure, options: [.prettyPrinted, .sortedKeys]) {
                    try? bytes.write(to: documents.appendingPathComponent("benchmark-\(runID)-error.json"), options: .atomic)
                }
                await MainActor.run {
                    self.status = "Benchmark failed: \(error)"
                    UIApplication.shared.isIdleTimerDisabled = false
                }
                print("CLASSIFIER_BENCHMARK_FAILED \(error)")
            }
        }
    }
}

@main struct ClassifierBenchmarkApp: App {
    @StateObject private var state = BenchmarkState()
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 18) {
                Text("Classifier benchmark").font(.headline)
                Text(state.status).multilineTextAlignment(.center)
                Text("This isolated test does not change YouSpeed’s installed models.").font(.footnote)
            }.padding().task { state.start() }
        }
    }
}
