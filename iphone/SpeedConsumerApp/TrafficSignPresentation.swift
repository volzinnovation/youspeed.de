import Foundation

/// Reviewed presentation metadata. Reference aliases do not expand the model's
/// real class vocabulary or authorize a speed-limit change.
struct TrafficSignPresentationCatalog: Decodable, Sendable {
    struct Sign: Decodable, Equatable, Sendable {
        let classID: String
        let signCode: String?
        let imagePath: String?
        let label: [String: String]
        let displayEligible: Bool

        enum CodingKeys: String, CodingKey {
            case classID = "class_id", signCode = "sign_code", imagePath = "image_path"
            case label, displayEligible = "display_eligible"
        }

        func localizedLabel(language: String = Bundle.main.preferredLocalizations.first ?? "en") -> String {
            label[String(language.prefix(2))] ?? label["en"] ?? classID
        }

        func imageURL(bundle: Bundle = .main) -> URL? {
            guard let imagePath, imagePath.hasPrefix("tsr/sign-pictograms/"),
                  !imagePath.split(separator: "/").contains("..") else { return nil }
            let relativePath = String(imagePath.dropFirst("tsr/sign-pictograms/".count))
            let file = URL(fileURLWithPath: relativePath)
            let subdirectory = "sign-pictograms/" + file.deletingLastPathComponent().path
            return bundle.url(forResource: file.deletingPathExtension().lastPathComponent,
                              withExtension: file.pathExtension, subdirectory: subdirectory)
        }
    }

    let schemaVersion: Int
    let country: String
    let classifierCheckpointSHA256: String
    let classLabels: [String]
    let signs: [Sign]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version", country
        case classifierCheckpointSHA256 = "classifier_checkpoint_sha256"
        case classLabels = "class_labels", signs
    }

    static func bundled(bundle: Bundle = .main) -> Self? {
        guard let url = bundle.url(forResource: "prolix-de-class-catalog-v1", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let result = try? JSONDecoder().decode(Self.self, from: data),
              result.schemaVersion == 1, result.country == "DE",
              !result.classLabels.isEmpty, Set(result.classLabels).count == result.classLabels.count,
              result.classifierCheckpointSHA256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              Set(result.signs.map(\.classID)).count == result.signs.count else { return nil }
        return result
    }

    func canRecognize(_ classID: String) -> Bool { classLabels.contains(classID) }
    func sign(for classID: String) -> Sign? { signs.first { $0.classID == classID } }
}

/// A separate display stream uses classifier acceptance, before speed-oriented
/// fusion selects its candidate. It never activates or persists a road rule.
struct TrafficSignDisplayObservation: Equatable, Sendable {
    let classID: String
    let classifierScore: Double
    let timestamp: Date
    let affectsSpeed: Bool
    let isSpeedLimitEnd: Bool
    let classifierCheckpointSHA256: String

    init(
        classID: String,
        classifierScore: Double,
        timestamp: Date,
        affectsSpeed: Bool,
        isSpeedLimitEnd: Bool = false,
        classifierCheckpointSHA256: String
    ) {
        self.classID = classID
        self.classifierScore = classifierScore
        self.timestamp = timestamp
        self.affectsSpeed = affectsSpeed
        self.isSpeedLimitEnd = isSpeedLimitEnd
        self.classifierCheckpointSHA256 = classifierCheckpointSHA256
    }

    static func accepted(from primaryDetections: [TrafficSignDetection], timestamp: Date, classifierCheckpointSHA256: String?) -> Self? {
        guard let classifierCheckpointSHA256 else { return nil }
        let accepted = primaryDetections.filter {
            let score = $0.classifierRawScore ?? $0.rawScore
            let detectorScore = $0.detectorRawScore ?? $0.rawScore
            return $0.rawClassId != "bad" && !$0.rawClassId.hasPrefix("bad:")
                && $0.boundingBox.isValid && score.isFinite && detectorScore.isFinite
                && (0.25...1).contains(detectorScore) && (0.9...1).contains(score)
                && $0.classThreshold.isFinite && score >= $0.classThreshold
        }.sorted {
            let left = $0.classifierRawScore ?? $0.rawScore
            let right = $1.classifierRawScore ?? $1.rawScore
            if left != right { return left > right }
            if $0.boundingBox.area != $1.boundingBox.area { return $0.boundingBox.area > $1.boundingBox.area }
            return $0.rawClassId < $1.rawClassId
        }
        guard let detection = accepted.first else { return nil }
        let candidate = TrafficSignRecognitionCandidate(
            rawClassId: detection.rawClassId, rawLabel: detection.rawLabel,
            semanticKind: detection.semantic.kind.rawValue, value: detection.semantic.value,
            unit: detection.semantic.unit, rawScore: detection.rawScore,
            calibratedConfidence: detection.calibratedConfidence,
            boundingBox: detection.boundingBox, trackId: nil, evidenceFrames: 1
        )
        let action = TrafficSignStructuralAction.normalized(from: candidate)
        return Self(classID: detection.rawClassId,
                    classifierScore: detection.classifierRawScore ?? detection.rawScore,
                    timestamp: timestamp,
                    affectsSpeed: action.passageEventEligible,
                    isSpeedLimitEnd: action.isSpeedLimitEnd,
                    classifierCheckpointSHA256: classifierCheckpointSHA256)
    }
}

struct TrafficSignDisplayState {
    private(set) var sign: TrafficSignPresentationCatalog.Sign?
    private var lastAcceptedAt = Date.distantPast

    mutating func consume(_ observation: TrafficSignDisplayObservation?, catalog: TrafficSignPresentationCatalog?) {
        guard let observation, observation.timestamp.timeIntervalSince1970.isFinite,
              observation.timestamp > lastAcceptedAt else { return }
        lastAcceptedAt = observation.timestamp
        guard !observation.affectsSpeed,
              let catalog, observation.classifierCheckpointSHA256 == catalog.classifierCheckpointSHA256,
              catalog.canRecognize(observation.classID),
              let next = catalog.sign(for: observation.classID), next.displayEligible else {
            sign = nil
            return
        }
        sign = next
    }

    mutating func reset() { self = Self() }
}
