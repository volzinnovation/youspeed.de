#!/usr/bin/env swift

import CoreML
import Foundation
import Vision

struct CalibrationBin: Codable {
    let lowerBound: Double
    let upperBound: Double
    var sampleCount: Int
    var correctCount: Int
    var confidenceSum: Double

    enum CodingKeys: String, CodingKey {
        case lowerBound = "lower_bound"
        case upperBound = "upper_bound"
        case sampleCount = "sample_count"
        case correctCount = "correct_count"
        case confidenceSum = "confidence_sum"
    }
}

struct ValidationReport: Codable {
    let schemaVersion: Int
    let modelPath: String
    let datasetPath: String
    let sampleCount: Int
    let classCount: Int
    let top1CorrectCount: Int
    let top1Accuracy: Double
    let negativeLogLikelihood: Double
    let expectedCalibrationError: Double
    let maximumCalibrationError: Double
    let bins: [CalibrationBin]
    let failures: [String]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case modelPath = "model_path"
        case datasetPath = "dataset_path"
        case sampleCount = "sample_count"
        case classCount = "class_count"
        case top1CorrectCount = "top1_correct_count"
        case top1Accuracy = "top1_accuracy"
        case negativeLogLikelihood = "negative_log_likelihood"
        case expectedCalibrationError = "expected_calibration_error"
        case maximumCalibrationError = "maximum_calibration_error"
        case bins
        case failures
    }
}

private func usage() -> Never {
    FileHandle.standardError.write(Data(
        "usage: validate_tsr_classifier.swift MODEL.mlmodelc DATASET_DIR [MAX_SAMPLES]\n".utf8
    ))
    exit(64)
}

let arguments = CommandLine.arguments
guard arguments.count == 3 || arguments.count == 4 else { usage() }

let modelURL = URL(fileURLWithPath: arguments[1]).standardizedFileURL
let datasetURL = URL(fileURLWithPath: arguments[2]).standardizedFileURL
let maximumSamples: Int?
if arguments.count == 4 {
    guard let parsed = Int(arguments[3]), parsed > 0 else { usage() }
    maximumSamples = parsed
} else {
    maximumSamples = nil
}

let fileManager = FileManager.default
let classDirectories = try fileManager.contentsOfDirectory(
    at: datasetURL,
    includingPropertiesForKeys: [.isDirectoryKey],
    options: [.skipsHiddenFiles]
).filter {
    (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
}.sorted { $0.lastPathComponent < $1.lastPathComponent }

var samples: [(url: URL, expectedClass: String)] = []
for directory in classDirectories {
    let expectedClass = directory.lastPathComponent
    let imageURLs = try fileManager.contentsOfDirectory(
        at: directory,
        includingPropertiesForKeys: [.isRegularFileKey],
        options: [.skipsHiddenFiles]
    ).filter {
        ["jpeg", "jpg", "png"].contains($0.pathExtension.lowercased())
    }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    samples.append(contentsOf: imageURLs.map { ($0, expectedClass) })
}
if let maximumSamples, samples.count > maximumSamples {
    samples = Array(samples.prefix(maximumSamples))
}

let configuration = MLModelConfiguration()
configuration.computeUnits = .all
let coreMLModel = try MLModel(contentsOf: modelURL, configuration: configuration)
let visionModel = try VNCoreMLModel(for: coreMLModel)

let binCount = 10
var bins = (0..<binCount).map { index in
    CalibrationBin(
        lowerBound: Double(index) / Double(binCount),
        upperBound: Double(index + 1) / Double(binCount),
        sampleCount: 0,
        correctCount: 0,
        confidenceSum: 0
    )
}
var processedCount = 0
var correctCount = 0
var negativeLogLikelihood = 0.0
var failures: [String] = []

for (index, sample) in samples.enumerated() {
    autoreleasepool {
        let request = VNCoreMLRequest(model: visionModel)
        request.imageCropAndScaleOption = .scaleFill
        do {
            try VNImageRequestHandler(url: sample.url, options: [:]).perform([request])
            guard let observations = request.results as? [VNClassificationObservation],
                  let top = observations.first else {
                failures.append("\(sample.url.path): no classification output")
                return
            }
            let confidence = min(max(Double(top.confidence), 0), 1)
            let correct = top.identifier == sample.expectedClass
            let expectedConfidence = observations.first(where: {
                $0.identifier == sample.expectedClass
            }).map { min(max(Double($0.confidence), 1e-12), 1) } ?? 1e-12
            let binIndex = min(Int(confidence * Double(binCount)), binCount - 1)
            bins[binIndex].sampleCount += 1
            bins[binIndex].correctCount += correct ? 1 : 0
            bins[binIndex].confidenceSum += confidence
            processedCount += 1
            correctCount += correct ? 1 : 0
            negativeLogLikelihood -= log(expectedConfidence)
        } catch {
            failures.append("\(sample.url.path): \(error.localizedDescription)")
        }
    }
    if (index + 1).isMultiple(of: 500) {
        FileHandle.standardError.write(Data("processed \(index + 1)/\(samples.count)\n".utf8))
    }
}

guard processedCount > 0 else {
    throw NSError(domain: "TSRCalibrationValidation", code: 1, userInfo: [
        NSLocalizedDescriptionKey: "No validation images were processed.",
    ])
}

var expectedCalibrationError = 0.0
var maximumCalibrationError = 0.0
for bin in bins where bin.sampleCount > 0 {
    let accuracy = Double(bin.correctCount) / Double(bin.sampleCount)
    let meanConfidence = bin.confidenceSum / Double(bin.sampleCount)
    let error = abs(accuracy - meanConfidence)
    expectedCalibrationError += Double(bin.sampleCount) / Double(processedCount) * error
    maximumCalibrationError = max(maximumCalibrationError, error)
}

let report = ValidationReport(
    schemaVersion: 1,
    modelPath: modelURL.path,
    datasetPath: datasetURL.path,
    sampleCount: processedCount,
    classCount: classDirectories.count,
    top1CorrectCount: correctCount,
    top1Accuracy: Double(correctCount) / Double(processedCount),
    negativeLogLikelihood: negativeLogLikelihood / Double(processedCount),
    expectedCalibrationError: expectedCalibrationError,
    maximumCalibrationError: maximumCalibrationError,
    bins: bins,
    failures: failures
)
let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
FileHandle.standardOutput.write(try encoder.encode(report))
FileHandle.standardOutput.write(Data("\n".utf8))
