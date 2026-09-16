import CoreML
import CoreVideo
import CryptoKit
import Foundation

struct ProbeReport: Encodable {
    let schemaVersion: Int
    let model: String
    let inputRGB: String
    let inputSHA256: String
    let outputCount: Int
    let topClass: String?
    let topScore: Double?
    let scores: [String: Double]
    let computeUnits: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case model
        case inputRGB = "input_rgb"
        case inputSHA256 = "input_sha256"
        case outputCount = "output_count"
        case topClass = "top_class"
        case topScore = "top_score"
        case scores
        case computeUnits = "compute_units"
    }
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(1)
}

guard CommandLine.arguments.count == 4 else {
    fail("usage: CoreMLParity.swift MODEL.mlmodelc INPUT.rgb OUTPUT.json")
}

let modelURL = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let inputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[3])
let inputData: Data
do {
    inputData = try Data(contentsOf: inputURL)
} catch {
    fail("cannot read input: \(error)")
}
guard inputData.count == 224 * 224 * 3 else {
    fail("input must contain exactly 224*224*3 RGB bytes")
}

var pixelBuffer: CVPixelBuffer?
let status = CVPixelBufferCreate(
    kCFAllocatorDefault,
    224,
    224,
    kCVPixelFormatType_32BGRA,
    [kCVPixelBufferCGImageCompatibilityKey: true, kCVPixelBufferCGBitmapContextCompatibilityKey: true] as CFDictionary,
    &pixelBuffer
)
guard status == kCVReturnSuccess, let pixelBuffer else {
    fail("could not allocate the Core Video input buffer")
}
CVPixelBufferLockBaseAddress(pixelBuffer, [])
defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
guard let base = CVPixelBufferGetBaseAddress(pixelBuffer) else {
    fail("Core Video input buffer has no base address")
}
let stride = CVPixelBufferGetBytesPerRow(pixelBuffer)
let pixelLayout = ProcessInfo.processInfo.environment["YOUSPEED_COREML_PIXEL_LAYOUT"] ?? "bgra"
guard ["bgra", "rgba"].contains(pixelLayout) else {
    fail("YOUSPEED_COREML_PIXEL_LAYOUT must be bgra or rgba")
}
inputData.withUnsafeBytes { raw in
    guard let bytes = raw.bindMemory(to: UInt8.self).baseAddress else { return }
    let destination = base.assumingMemoryBound(to: UInt8.self)
    for y in 0..<224 {
        for x in 0..<224 {
            let source = (y * 224 + x) * 3
            let target = y * stride + x * 4
            if pixelLayout == "bgra" {
                destination[target] = bytes[source + 2]
                destination[target + 1] = bytes[source + 1]
                destination[target + 2] = bytes[source]
            } else {
                destination[target] = bytes[source]
                destination[target + 1] = bytes[source + 1]
                destination[target + 2] = bytes[source + 2]
            }
            destination[target + 3] = 255
        }
    }
}

let configuration = MLModelConfiguration()
let computeUnits = ProcessInfo.processInfo.environment["YOUSPEED_COREML_COMPUTE_UNITS"] ?? "all"
switch computeUnits {
case "all": configuration.computeUnits = .all
case "cpu_only": configuration.computeUnits = .cpuOnly
case "cpu_and_gpu": configuration.computeUnits = .cpuAndGPU
case "cpu_and_ne": configuration.computeUnits = .cpuAndNeuralEngine
default: fail("YOUSPEED_COREML_COMPUTE_UNITS must be all, cpu_only, cpu_and_gpu, or cpu_and_ne")
}
let model: MLModel
do {
    model = try MLModel(contentsOf: modelURL, configuration: configuration)
} catch {
    fail("could not load Core ML model: \(error)")
}
let provider: MLFeatureProvider
do {
    provider = try MLDictionaryFeatureProvider(dictionary: [
        "image": MLFeatureValue(pixelBuffer: pixelBuffer),
    ])
} catch {
    fail("could not construct Core ML input: \(error)")
}
let prediction: MLFeatureProvider
do {
    prediction = try model.prediction(from: provider)
} catch {
    fail("Core ML prediction failed: \(error)")
}
guard let probabilityValue = prediction.featureValue(for: "classLabel_probs"),
      let dictionary = probabilityValue.dictionaryValue as? [AnyHashable: Any] else {
    fail("Core ML output classLabel_probs is missing")
}
var scores: [String: Double] = [:]
for (key, value) in dictionary {
    guard let label = key as? String, let number = value as? NSNumber else { continue }
    scores[label] = number.doubleValue
}
let best = scores.max { $0.value < $1.value }
let digest = SHA256.hash(data: inputData).map { String(format: "%02x", $0) }.joined()
let report = ProbeReport(
    schemaVersion: 1,
    model: modelURL.path,
    inputRGB: inputURL.path,
    inputSHA256: digest,
    outputCount: scores.count,
    topClass: best?.key,
    topScore: best?.value,
    scores: scores,
    computeUnits: computeUnits,
)
do {
    let data = try JSONEncoder().encode(report)
    try data.write(to: outputURL, options: .atomic)
} catch {
    fail("could not write Core ML report: \(error)")
}
