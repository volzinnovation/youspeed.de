import Foundation
import CoreLocation
import ImageIO

enum PanoramaxBatchState: String, Codable {
    case capturing
    case awaitingReview = "awaiting_review"
    case approved
    case creatingUploadSet = "creating_upload_set"
    case uploading
    case processing
    case complete
    case partial
    case blocked
}

enum PanoramaxItemState: String, Codable {
    case captured
    case included
    case excluded
    case queued
    case uploading
    case uploaded
    case accepted
    case duplicate
    case rejected
    case retryableError = "retryable_error"
    case permanentError = "permanent_error"
    /// The request was cancelled while its server outcome was unknown. It is
    /// intentionally not retried automatically because the server may already
    /// have accepted the bytes.
    case abandoned
}

struct PanoramaxLocationSample: Codable, Equatable {
    let latitude: Double
    let longitude: Double
    let capturedAt: Date
    let accuracyMeters: Double
    let altitudeMeters: Double?
    let headingDegrees: Double?
}

/// Panoramax semantics use key/value entries and qualify a detected object by
/// referring to its primary semantic, for example
/// `classification_confidence[osm|traffic_sign=DE:274-70]`.
struct PanoramaxSemanticTag: Codable, Equatable, Sendable {
    let key: String
    let value: String
}

/// Local representation of a Panoramax object annotation. `shape` follows the
/// Panoramax API's `[minX, minY, maxX, maxY]` pixel convention with a top-left
/// origin. The same payload is persisted in the queue sidecar and embedded in
/// the JPEG EXIF user-comment field.
struct PanoramaxTrafficSignAnnotation: Codable, Equatable, Sendable {
    let annotationID: String
    let sourceEventID: String
    let frameTimestampUTC: Date
    let shape: [Int]
    let semantics: [PanoramaxSemanticTag]
    let speedLimitKmh: Int
    let physicalSignTrackID: String?
    let detectionConfidence: Double
    let classificationConfidence: Double
    let wayID: String
    let latitude: Double
    let longitude: Double
    let headingDegrees: Double
    let travelDirection: TrafficSignTravelDirection

    var isValid: Bool {
        guard !annotationID.isEmpty,
              !sourceEventID.isEmpty,
              shape.count == 4,
              shape[0] >= 0,
              shape[1] >= 0,
              shape[2] > shape[0],
              shape[3] > shape[1],
              speedLimitKmh > 0,
              detectionConfidence.isFinite,
              (0...1).contains(detectionConfidence),
              classificationConfidence.isFinite,
              (0...1).contains(classificationConfidence),
              !wayID.isEmpty,
              latitude.isFinite,
              longitude.isFinite,
              headingDegrees.isFinite else { return false }
        return semantics.contains {
            $0.key == "osm|traffic_sign" && !$0.value.isEmpty
        }
    }
}

/// Recognition coordinates are normalized to the oriented camera frame. They
/// become Panoramax pixel coordinates only when associated with a JPEG.
struct PanoramaxTrafficSignAnnotationDraft: Equatable, Sendable {
    let annotationID: String
    let sourceEventID: String
    let frameTimestampUTC: Date
    let normalizedShape: TrafficSignNormalizedRect
    let semantics: [PanoramaxSemanticTag]
    let speedLimitKmh: Int
    let physicalSignTrackID: String?
    let detectionConfidence: Double
    let classificationConfidence: Double
    let context: TrafficSignDetectionContext

    init(
        annotationID: String,
        sourceEventID: String,
        frameTimestampUTC: Date,
        normalizedShape: TrafficSignNormalizedRect,
        semantics: [PanoramaxSemanticTag],
        speedLimitKmh: Int,
        physicalSignTrackID: String?,
        detectionConfidence: Double,
        classificationConfidence: Double,
        context: TrafficSignDetectionContext
    ) {
        self.annotationID = annotationID
        self.sourceEventID = sourceEventID
        self.frameTimestampUTC = frameTimestampUTC
        self.normalizedShape = normalizedShape
        self.semantics = semantics
        self.speedLimitKmh = speedLimitKmh
        self.physicalSignTrackID = physicalSignTrackID
        self.detectionConfidence = detectionConfidence
        self.classificationConfidence = classificationConfidence
        self.context = context
    }

    init?(emission: TrafficSignRuntimeEmission) {
        let event = emission.event
        guard event.source == .liveFrame,
              event.state == .confirmed,
              let candidate = event.candidate,
              candidate.semanticKind == TrafficSignSemanticKind.maximumSpeed.rawValue,
              let speedLimitKmh = candidate.value,
              speedLimitKmh > 0,
              candidate.boundingBox.isValid,
              let context = event.roadContext,
              context.isValid else { return nil }

        let shadow = emission.shadowEventV2
        let assembly = shadow?.assemblies.first(where: {
            $0.physicalSignTrackId == candidate.trackId
        }) ?? shadow?.assemblies.first(where: {
            $0.primary.classId == candidate.rawClassId
        })
        let detectionConfidence = Self.confidence(
            assembly?.primary.detectorScore,
            fallback: candidate.rawScore
        )
        let classificationConfidence = Self.confidence(
            assembly?.primary.classifierScore,
            fallback: candidate.calibratedConfidence ?? candidate.rawScore
        )
        let semanticValue = Self.trafficSignValue(
            speedLimitKmh: speedLimitKmh,
            packID: event.packId
        )
        let qualifiedSemantic = "osm|traffic_sign=\(semanticValue)"
        let detectorModel = shadow?.stageRuns.detector.componentId ?? event.packId
        let classifierModel = shadow?.stageRuns.classifier.componentId ?? event.packId
        let sourceEventID = shadow?.eventId ?? [
            event.packId,
            String(Int(event.frameTimestampUtc.timeIntervalSince1970 * 1_000)),
            candidate.trackId ?? candidate.rawClassId,
        ].joined(separator: "-")
        annotationID = "tsr-\(sourceEventID)"
        self.sourceEventID = sourceEventID
        frameTimestampUTC = event.frameTimestampUtc
        normalizedShape = candidate.boundingBox
        semantics = [
            PanoramaxSemanticTag(key: "osm|traffic_sign", value: semanticValue),
            PanoramaxSemanticTag(
                key: "detection_model[\(qualifiedSemantic)]",
                value: detectorModel
            ),
            PanoramaxSemanticTag(
                key: "detection_confidence[\(qualifiedSemantic)]",
                value: Self.formattedConfidence(detectionConfidence)
            ),
            PanoramaxSemanticTag(
                key: "classification_model[\(qualifiedSemantic)]",
                value: classifierModel
            ),
            PanoramaxSemanticTag(
                key: "classification_confidence[\(qualifiedSemantic)]",
                value: Self.formattedConfidence(classificationConfidence)
            ),
        ]
        self.speedLimitKmh = speedLimitKmh
        physicalSignTrackID = candidate.trackId
        self.detectionConfidence = detectionConfidence
        self.classificationConfidence = classificationConfidence
        self.context = context
    }

    func projected(
        imageWidth: Int,
        imageHeight: Int,
        imageTimestamp: Date,
        maximumTimeDelta: TimeInterval = 5
    ) -> PanoramaxTrafficSignAnnotation? {
        guard normalizedShape.isValid,
              imageWidth > 0,
              imageHeight > 0,
              abs(imageTimestamp.timeIntervalSince(frameTimestampUTC)) <= maximumTimeDelta else {
            return nil
        }
        let minX = max(0, min(imageWidth - 1, Int(floor(normalizedShape.x * Double(imageWidth)))))
        let minY = max(0, min(imageHeight - 1, Int(floor(normalizedShape.y * Double(imageHeight)))))
        let maxX = max(minX + 1, min(imageWidth, Self.upperPixel(
            normalizedShape.x + normalizedShape.width,
            dimension: imageWidth
        )))
        let maxY = max(minY + 1, min(imageHeight, Self.upperPixel(
            normalizedShape.y + normalizedShape.height,
            dimension: imageHeight
        )))
        let annotation = PanoramaxTrafficSignAnnotation(
            annotationID: annotationID,
            sourceEventID: sourceEventID,
            frameTimestampUTC: frameTimestampUTC,
            shape: [minX, minY, maxX, maxY],
            semantics: semantics,
            speedLimitKmh: speedLimitKmh,
            physicalSignTrackID: physicalSignTrackID,
            detectionConfidence: detectionConfidence,
            classificationConfidence: classificationConfidence,
            wayID: context.wayId,
            latitude: context.latitude,
            longitude: context.longitude,
            headingDegrees: context.headingDegrees,
            travelDirection: context.travelDirection
        )
        return annotation.isValid ? annotation : nil
    }

    private static func confidence(
        _ score: TrafficSignStageScoreV2?,
        fallback: Double
    ) -> Double {
        min(1, max(0, score?.calibratedConfidence ?? score?.rawScore ?? fallback))
    }

    private static func formattedConfidence(_ value: Double) -> String {
        String(format: "%.3f", locale: Locale(identifier: "en_US_POSIX"), value)
    }

    private static func upperPixel(_ normalized: Double, dimension: Int) -> Int {
        let scaled = normalized * Double(dimension)
        let nearestInteger = scaled.rounded()
        let stable = abs(scaled - nearestInteger) < 0.000_001 ? nearestInteger : scaled
        return Int(ceil(stable))
    }

    private static func trafficSignValue(speedLimitKmh: Int, packID: String) -> String {
        if packID.lowercased().hasPrefix("de-") {
            return "DE:274-\(speedLimitKmh)"
        }
        return "maxspeed:\(speedLimitKmh)"
    }
}

struct PanoramaxCaptureMetadata: Codable, Equatable {
    let captureID: String
    let captureSessionID: String
    let capturedAt: Date
    let location: PanoramaxLocationSample
    let sha256: String
    let byteSize: Int64
    let software: String
    let imageWidthPixels: Int?
    let imageHeightPixels: Int?
    let trafficSignAnnotations: [PanoramaxTrafficSignAnnotation]?

    init(
        captureID: String,
        captureSessionID: String,
        capturedAt: Date,
        location: PanoramaxLocationSample,
        sha256: String,
        byteSize: Int64,
        software: String,
        imageWidthPixels: Int? = nil,
        imageHeightPixels: Int? = nil,
        trafficSignAnnotations: [PanoramaxTrafficSignAnnotation]? = nil
    ) {
        self.captureID = captureID
        self.captureSessionID = captureSessionID
        self.capturedAt = capturedAt
        self.location = location
        self.sha256 = sha256
        self.byteSize = byteSize
        self.software = software
        self.imageWidthPixels = imageWidthPixels
        self.imageHeightPixels = imageHeightPixels
        self.trafficSignAnnotations = trafficSignAnnotations
    }

    func replacingImageMetadata(
        sha256: String,
        byteSize: Int64,
        imageWidthPixels: Int,
        imageHeightPixels: Int,
        trafficSignAnnotations: [PanoramaxTrafficSignAnnotation]
    ) -> Self {
        Self(
            captureID: captureID,
            captureSessionID: captureSessionID,
            capturedAt: capturedAt,
            location: location,
            sha256: sha256,
            byteSize: byteSize,
            software: software,
            imageWidthPixels: imageWidthPixels,
            imageHeightPixels: imageHeightPixels,
            trafficSignAnnotations: trafficSignAnnotations
        )
    }

    func validate(now: Date? = nil) -> [String] {
        let reference = now ?? capturedAt
        var errors: [String] = []
        if captureID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors.append("captureID is missing") }
        if captureSessionID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors.append("captureSessionID is missing") }
        if capturedAt > reference.addingTimeInterval(60) { errors.append("capture time is in the future") }
        if !location.latitude.isFinite || !(-90...90).contains(location.latitude) { errors.append("latitude is invalid") }
        if !location.longitude.isFinite || !(-180...180).contains(location.longitude) { errors.append("longitude is invalid") }
        if !location.accuracyMeters.isFinite || location.accuracyMeters < 0 { errors.append("location accuracy is invalid") }
        if location.capturedAt > reference.addingTimeInterval(60) { errors.append("location time is in the future") }
        if abs(location.capturedAt.timeIntervalSince(capturedAt)) > 120 { errors.append("location is not associated with shutter time") }
        if let heading = location.headingDegrees, (!heading.isFinite || !(0...360).contains(heading)) { errors.append("heading is invalid") }
        if byteSize <= 0 { errors.append("image is empty") }
        if sha256.range(of: "^[0-9a-fA-F]{64}$", options: .regularExpression) == nil { errors.append("sha256 is invalid") }
        if software.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { errors.append("software provenance is missing") }
        if let width = imageWidthPixels, width <= 0 { errors.append("image width is invalid") }
        if let height = imageHeightPixels, height <= 0 { errors.append("image height is invalid") }
        if imageWidthPixels == nil, imageHeightPixels != nil { errors.append("image width is missing") }
        if imageWidthPixels != nil, imageHeightPixels == nil { errors.append("image height is missing") }
        if trafficSignAnnotations?.allSatisfy(\.isValid) == false { errors.append("traffic-sign annotation is invalid") }
        return errors
    }
}

enum PanoramaxJPEGMetadata {
    private struct AnnotationEnvelope: Codable {
        let schemaVersion: Int
        let annotations: [PanoramaxTrafficSignAnnotation]
    }

    private static let userCommentPrefix = "YouSpeed.PanoramaxAnnotations/1 "

    static func pixelDimensions(from data: Data) -> (width: Int, height: Int)? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any],
              let rawWidth = properties[kCGImagePropertyPixelWidth as String] as? NSNumber,
              let rawHeight = properties[kCGImagePropertyPixelHeight as String] as? NSNumber else {
            return nil
        }
        let orientation = (properties[kCGImagePropertyOrientation as String] as? NSNumber)?.intValue ?? 1
        if (5...8).contains(orientation) {
            return (rawHeight.intValue, rawWidth.intValue)
        }
        return (rawWidth.intValue, rawHeight.intValue)
    }

    /// Reads the YouSpeed annotation envelope back from the JPEG. Upload code
    /// uses this to verify that the durable sidecar and the bytes about to be
    /// sent to Panoramax still agree.
    static func trafficSignAnnotations(from data: Data) -> [PanoramaxTrafficSignAnnotation]? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any],
              let exif = properties[kCGImagePropertyExifDictionary as String] as? [String: Any],
              let rawComment = exif[kCGImagePropertyExifUserComment as String] else {
            return nil
        }
        let comment: String?
        if let value = rawComment as? String {
            comment = value
        } else if let value = rawComment as? Data {
            comment = String(data: value, encoding: .utf8)
        } else {
            comment = nil
        }
        guard let comment,
              comment.hasPrefix(userCommentPrefix),
              let payload = comment.dropFirst(userCommentPrefix.count).data(using: .utf8),
              let envelope = try? JSONDecoder.panoramaxAnnotationDecoder.decode(
                  AnnotationEnvelope.self,
                  from: payload
              ),
              envelope.schemaVersion == 1 else {
            return nil
        }
        return envelope.annotations
    }

    static func adding(
        to data: Data,
        location: PanoramaxLocationSample? = nil,
        annotations: [PanoramaxTrafficSignAnnotation] = []
    ) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let type = CGImageSourceGetType(source),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [String: Any] else {
            return nil
        }
        let output = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(output, type, 1, nil) else {
            return nil
        }
        var merged = properties
        if let location {
            var gps = (merged[kCGImagePropertyGPSDictionary as String] as? [String: Any]) ?? [:]
            gps[kCGImagePropertyGPSLatitude as String] = abs(location.latitude)
            gps[kCGImagePropertyGPSLatitudeRef as String] = location.latitude >= 0 ? "N" : "S"
            gps[kCGImagePropertyGPSLongitude as String] = abs(location.longitude)
            gps[kCGImagePropertyGPSLongitudeRef as String] = location.longitude >= 0 ? "E" : "W"
            if let altitude = location.altitudeMeters, altitude.isFinite {
                gps[kCGImagePropertyGPSAltitude as String] = abs(altitude)
                gps[kCGImagePropertyGPSAltitudeRef as String] = altitude >= 0 ? 0 : 1
            }
            let timeFormatter = DateFormatter()
            timeFormatter.locale = Locale(identifier: "en_US_POSIX")
            timeFormatter.timeZone = TimeZone(secondsFromGMT: 0)
            timeFormatter.dateFormat = "HH:mm:ss"
            let dateFormatter = DateFormatter()
            dateFormatter.locale = Locale(identifier: "en_US_POSIX")
            dateFormatter.timeZone = TimeZone(secondsFromGMT: 0)
            dateFormatter.dateFormat = "yyyy:MM:dd"
            gps[kCGImagePropertyGPSTimeStamp as String] = timeFormatter.string(from: location.capturedAt)
            gps[kCGImagePropertyGPSDateStamp as String] = dateFormatter.string(from: location.capturedAt)
            if let heading = location.headingDegrees,
               heading.isFinite,
               (0...360).contains(heading) {
                gps[kCGImagePropertyGPSImgDirection as String] = heading
                gps[kCGImagePropertyGPSImgDirectionRef as String] = "T"
            }
            merged[kCGImagePropertyGPSDictionary as String] = gps
        }
        if !annotations.isEmpty,
           let payload = try? JSONEncoder.panoramaxAnnotationEncoder.encode(
               AnnotationEnvelope(schemaVersion: 1, annotations: annotations)
           ),
           let json = String(data: payload, encoding: .utf8) {
            var exif = (merged[kCGImagePropertyExifDictionary as String] as? [String: Any]) ?? [:]
            exif[kCGImagePropertyExifUserComment as String] = userCommentPrefix + json
            merged[kCGImagePropertyExifDictionary as String] = exif
        }
        CGImageDestinationAddImageFromSource(destination, source, 0, merged as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { return nil }
        return output as Data
    }
}

private extension JSONEncoder {
    static var panoramaxAnnotationEncoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}

private extension JSONDecoder {
    static var panoramaxAnnotationDecoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

struct PanoramaxCadenceConfiguration: Equatable {
    var distanceMeters: Double = 25
    var fallbackInterval: TimeInterval = 5
    var maxLocationAge: TimeInterval = 10
    var maxAccuracyMeters: Double = 50
    var triggerMode: PanoramaxCaptureTriggerMode = .distance
}

enum PanoramaxCaptureTriggerMode: String, CaseIterable, Codable {
    case distance
    case time

    var label: String {
        switch self {
        case .distance: return NSLocalizedString("panoramax.settings.trigger_distance", comment: "")
        case .time: return NSLocalizedString("panoramax.settings.trigger_time", comment: "")
        }
    }
}

enum PanoramaxCapturePolicy {
    static func shouldCapture(
        lastCapture: PanoramaxLocationSample?,
        current: PanoramaxLocationSample,
        now: Date? = nil,
        configuration: PanoramaxCadenceConfiguration = .init()
    ) -> Bool {
        let reference = now ?? current.capturedAt
        guard current.capturedAt <= reference.addingTimeInterval(60),
              reference.timeIntervalSince(current.capturedAt) <= configuration.maxLocationAge,
              current.accuracyMeters.isFinite,
              current.accuracyMeters >= 0,
              current.accuracyMeters <= configuration.maxAccuracyMeters else { return false }
        guard let previous = lastCapture else { return true }
        guard current.capturedAt > previous.capturedAt else { return false }
        let precisionMovement = 2 * max(current.accuracyMeters, previous.accuracyMeters)
        let distance = distanceMeters(from: previous, to: current)
        guard distance >= precisionMovement else { return false }
        switch configuration.triggerMode {
        case .distance:
            return distance >= max(configuration.distanceMeters, precisionMovement)
        case .time:
            return current.capturedAt.timeIntervalSince(previous.capturedAt) >= configuration.fallbackInterval
        }
    }

    static func distanceMeters(from first: PanoramaxLocationSample, to second: PanoramaxLocationSample) -> Double {
        CLLocation(latitude: first.latitude, longitude: first.longitude)
            .distance(from: CLLocation(latitude: second.latitude, longitude: second.longitude))
    }
}
