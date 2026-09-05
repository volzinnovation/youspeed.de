import Foundation

struct TrafficSignRouteRelationMembership: Codable, Equatable, Hashable, Sendable {
    let groupID: Int
    let sourceRelationID: Int64?

    var isValid: Bool { groupID > 0 }
}

enum EffectiveSpeedLimitSource: String, Codable, Equatable, Sendable {
    case camera
    case localCorrection = "local_correction"
    case bundle
    case none
}

enum EffectiveSpeedLimitValue: Codable, Equatable, Sendable {
    case numeric(Int)
    case walk
    case unlimited
    case unknown

    var speedKmh: Int? {
        guard case .numeric(let value) = self else { return nil }
        return value
    }

    var displayText: String? {
        switch self {
        case .numeric:
            return nil
        case .walk:
            return "Schritt"
        case .unlimited, .unknown:
            return nil
        }
    }
}

struct EffectiveSpeedLimitState: Codable, Equatable, Sendable {
    let value: EffectiveSpeedLimitValue
    let source: EffectiveSpeedLimitSource
    let presentationReason: String
    let hasCameraEvidenceMarker: Bool

    static let none = EffectiveSpeedLimitState(
        value: .unknown,
        source: .none,
        presentationReason: "no_speed_limit",
        hasCameraEvidenceMarker: false
    )

    static func base(
        localValue: String?,
        bundledSpeedKmh: Int?,
        bundledUnlimited: Bool
    ) -> EffectiveSpeedLimitState {
        if let normalized = localValue?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(), !normalized.isEmpty {
            if normalized == "walk" {
                return EffectiveSpeedLimitState(
                    value: .walk,
                    source: .localCorrection,
                    presentationReason: "local_correction_walk",
                    hasCameraEvidenceMarker: false
                )
            }
            if normalized == "none" {
                return EffectiveSpeedLimitState(
                    value: .unlimited,
                    source: .localCorrection,
                    presentationReason: "local_correction_unlimited",
                    hasCameraEvidenceMarker: false
                )
            }
            if let speed = Int(normalized), speed > 0 {
                return EffectiveSpeedLimitState(
                    value: .numeric(speed),
                    source: .localCorrection,
                    presentationReason: "local_correction_numeric",
                    hasCameraEvidenceMarker: false
                )
            }
        }
        if bundledUnlimited {
            return EffectiveSpeedLimitState(
                value: .unlimited,
                source: .bundle,
                presentationReason: "bundle_unlimited",
                hasCameraEvidenceMarker: false
            )
        }
        if let bundledSpeedKmh, bundledSpeedKmh > 0 {
            return EffectiveSpeedLimitState(
                value: .numeric(bundledSpeedKmh),
                source: .bundle,
                presentationReason: "bundle_numeric",
                hasCameraEvidenceMarker: false
            )
        }
        return .none
    }
}

enum TrafficSignStructuralAction: Codable, Equatable, Hashable, Sendable {
    case postedMaximum(Int)
    case zoneStart(Int)
    case zoneEnd(Int?)
    case cityEntry(String)
    case cityExit
    case pedestrianZoneStart
    case pedestrianZoneEnd
    case maximumSpeedEnd(Int?)
    case allRestrictionsEnd
    case motorwayExit
    case motorroadExit
    case temporaryMaximum(Int)
    case nonSpeedRestrictionEnd
    case unresolved(String)

    var stableKey: String {
        switch self {
        case .postedMaximum(let value): return "posted_maximum:\(value)"
        case .zoneStart(let value): return "zone_start:\(value)"
        case .zoneEnd(let value): return "zone_end:\(value.map(String.init) ?? "")"
        case .cityEntry(let country): return "city_entry:\(country.uppercased())"
        case .cityExit: return "city_exit"
        case .pedestrianZoneStart: return "pedestrian_zone_start"
        case .pedestrianZoneEnd: return "pedestrian_zone_end"
        case .maximumSpeedEnd(let value): return "maximum_speed_end:\(value.map(String.init) ?? "")"
        case .allRestrictionsEnd: return "all_restrictions_end"
        case .motorwayExit: return "motorway_exit"
        case .motorroadExit: return "motorroad_exit"
        case .temporaryMaximum(let value): return "temporary_maximum:\(value)"
        case .nonSpeedRestrictionEnd: return "non_speed_restriction_end"
        case .unresolved(let raw): return "unresolved:\(raw)"
        }
    }

    var passageEventEligible: Bool {
        switch self {
        case .unresolved, .nonSpeedRestrictionEnd:
            return false
        default:
            return true
        }
    }

    /// The shared passage-event v1 contract permits concrete speed values only
    /// in this range. Keep the invariant on the typed action as a backstop for
    /// callers that do not originate in the model-pack adapter.
    var hasSupportedSpeedValue: Bool {
        switch self {
        case .postedMaximum(let value), .zoneStart(let value), .temporaryMaximum(let value):
            return (5...200).contains(value)
        case .zoneEnd(let value), .maximumSpeedEnd(let value):
            return value.map { (5...200).contains($0) } ?? true
        case .cityEntry, .cityExit, .pedestrianZoneStart, .pedestrianZoneEnd,
             .allRestrictionsEnd, .motorwayExit, .motorroadExit,
             .nonSpeedRestrictionEnd, .unresolved:
            return true
        }
    }

    static func normalized(
        from candidate: TrafficSignRecognitionCandidate,
        countryCode: String = "DE"
    ) -> TrafficSignStructuralAction {
        let rawClass = candidate.rawClassId.lowercased()
        switch candidate.semanticKind {
        case TrafficSignSemanticKind.maximumSpeed.rawValue:
            guard let value = candidate.value,
                  (5...200).contains(value),
                  candidate.unit == "km/h" else {
                return .unresolved(candidate.rawClassId)
            }
            return .postedMaximum(value)
        case TrafficSignSemanticKind.zoneStart.rawValue:
            guard let value = candidate.value,
                  (5...200).contains(value),
                  candidate.unit == "km/h" else {
                return .unresolved(candidate.rawClassId)
            }
            return .zoneStart(value)
        case TrafficSignSemanticKind.zoneEnd.rawValue:
            guard candidate.value.map({ (5...200).contains($0) }) ?? true else {
                return .unresolved(candidate.rawClassId)
            }
            return .zoneEnd(candidate.value)
        case TrafficSignSemanticKind.cityEntry.rawValue:
            return .cityEntry(countryCode)
        case TrafficSignSemanticKind.cityExit.rawValue:
            return .cityExit
        case TrafficSignSemanticKind.pedestrianZoneStart.rawValue:
            return .pedestrianZoneStart
        case TrafficSignSemanticKind.pedestrianZoneEnd.rawValue:
            return .pedestrianZoneEnd
        case TrafficSignSemanticKind.temporary.rawValue:
            guard let value = candidate.value, (5...200).contains(value) else {
                return .unresolved(candidate.rawClassId)
            }
            return .temporaryMaximum(value)
        case TrafficSignSemanticKind.restrictionEnd.rawValue:
            if rawClass.contains("all_restrictions") || rawClass == "de:282" {
                return .allRestrictionsEnd
            }
            if rawClass.contains("maxspeed") || rawClass.contains("maximum_speed") || rawClass == "de:278" {
                guard candidate.value.map({ (5...200).contains($0) }) ?? true else {
                    return .unresolved(candidate.rawClassId)
                }
                return .maximumSpeedEnd(candidate.value)
            }
            if rawClass.contains("motorway") { return .motorwayExit }
            if rawClass.contains("motorroad") { return .motorroadExit }
            return .nonSpeedRestrictionEnd
        default:
            return .unresolved(candidate.rawClassId)
        }
    }
}

struct TrafficSignPassageFrameEvidence: Codable, Equatable, Sendable {
    let frameID: String
    let timestampUTC: Date
    let outcome: String
    let analysisEligible: Bool
    let rawScore: Double
    let calibratedConfidence: Double?
    let proposalRawScore: Double?
    let proposalCalibratedConfidence: Double?
    let classifierRawScore: Double?
    let classifierCalibratedConfidence: Double?
    let assemblyConfidence: Double?
    let accumulatedSupport: Double
    let wayID: String?
}

struct TrafficSignPassageLossFrameEvidence: Codable, Equatable, Sendable {
    let frameID: String
    let timestampUTC: Date
    let outcome: String
    let analysisEligible: Bool
    let strongPassGeometry: Bool
    let speedMPS: Double
    let wayID: String?
}

enum TrafficSignPassageLossReason: String, Codable, Equatable, Sendable {
    case strongPassGeometry = "strong_pass_geometry"
    case negativeDebounce = "negative_debounce"
}

struct TrafficSignPassageEvent: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let finalizedEventID: String
    let driveSessionID: String
    let physicalTrackID: String
    let assemblyID: String?
    let assemblyIDs: [String]
    let packID: String
    let artifactSHA256: String
    let preprocessingVersion: String
    let modelComponents: [TrafficSignModelComponentLineage]
    let action: TrafficSignStructuralAction
    let conditionState: TrafficSignConditionState
    let restrictions: [TrafficSignRestriction]
    let firstSeenTimestampUTC: Date
    let lastSeenTimestampUTC: Date
    let passageBoundaryTimestampUTC: Date
    let lastSeenContext: TrafficSignDetectionContext?
    let passageBoundaryCoordinate: TrafficSignCoordinate?
    let passageBoundaryContext: TrafficSignDetectionContext?
    let initialRecognitionContext: TrafficSignDetectionContext?
    let activationContext: TrafficSignDetectionContext
    let activationTimestampUTC: Date
    let initialRecognitionRouteRelationMemberships: [TrafficSignRouteRelationMembership]
    let recognitionRouteRelationMemberships: [TrafficSignRouteRelationMembership]
    let frameEvidence: [TrafficSignPassageFrameEvidence]
    let lossEvidence: [TrafficSignPassageLossFrameEvidence]
    let accumulatedSupport: Double
    let finalCalibratedConfidence: Double?
    let peakConsecutiveFramesSeen: Int
    let lossNegativeFrames: Int
    let lossReason: TrafficSignPassageLossReason
    let negativeFramesRequired: Int
    let sessionGeneration: UInt64
    let contextGeneration: UInt64

    var isUnconditional: Bool {
        conditionState == .none && restrictions.isEmpty
    }
}

enum TrafficSignPassageWireEncodingError: Error, LocalizedError {
    case invalid(String)

    var errorDescription: String? {
        switch self {
        case .invalid(let detail): return detail
        }
    }
}

/// Canonical persistence adapter for the shared passage-event v1 contract.
/// Swift's synthesized Codable output is intentionally not used for durable
/// evidence because its camelCase keys and associated-enum encoding are not a
/// cross-platform wire format.
enum TrafficSignPassageWireEncoder {
    static func encode(
        event: TrafficSignPassageEvent,
        decision: TrafficSignPassagePersistenceDecision
    ) throws -> Data {
        guard event.schemaVersion == 1,
              nonempty(event.finalizedEventID) != nil,
              nonempty(event.driveSessionID) != nil,
              nonempty(event.packID) != nil,
              isSHA256(event.artifactSHA256),
              !event.modelComponents.isEmpty,
              event.modelComponents.allSatisfy(\.isValid),
              event.action.hasSupportedSpeedValue,
              nonempty(event.physicalTrackID) != nil,
              !event.assemblyIDs.isEmpty,
              event.assemblyIDs.allSatisfy({ nonempty($0) != nil }),
              let finalConfidence = confidence(event.finalCalibratedConfidence),
              event.negativeFramesRequired > 0,
              let bundleSHA = event.activationContext.sourceSignature.bundleSHA256?.lowercased(),
              isSHA256(bundleSHA),
              isPositiveWayID(event.activationContext.wayId),
              !event.frameEvidence.isEmpty,
              !event.lossEvidence.isEmpty else {
            throw TrafficSignPassageWireEncodingError.invalid(
                "Passage evidence is incomplete for the shared v1 contract"
            )
        }

        let seenFrames: [[String: Any]] = try event.frameEvidence.map { frame in
            guard nonempty(frame.frameID) != nil,
                  frame.outcome == "seen",
                  frame.analysisEligible,
                  let proposalRaw = confidence(frame.proposalRawScore),
                  let proposalCalibrated = confidence(frame.proposalCalibratedConfidence),
                  let classifierRaw = confidence(frame.classifierRawScore),
                  let classifierCalibrated = confidence(frame.classifierCalibratedConfidence),
                  let assembly = confidence(frame.assemblyConfidence),
                  let support = confidence(frame.accumulatedSupport) else {
                throw TrafficSignPassageWireEncodingError.invalid(
                    "Seen-frame evidence lacks calibrated detector/classifier stages"
                )
            }
            return [
                "frame_id": frame.frameID,
                "timestamp_utc": timestamp(frame.timestampUTC),
                "outcome": "seen",
                "analysis_eligible": true,
                "proposal_raw_score": proposalRaw,
                "proposal_calibrated_confidence": proposalCalibrated,
                "classifier_raw_score": classifierRaw,
                "classifier_calibrated_confidence": classifierCalibrated,
                "assembly_confidence": assembly,
                "accumulated_support": support,
            ]
        }
        let lossFrames: [[String: Any]] = try event.lossEvidence.map { frame in
            guard nonempty(frame.frameID) != nil,
                  frame.outcome == "analyzed_missing",
                  frame.analysisEligible else {
                throw TrafficSignPassageWireEncodingError.invalid(
                    "Loss evidence is not an eligible analyzed-missing frame"
                )
            }
            return [
                "frame_id": frame.frameID,
                "timestamp_utc": timestamp(frame.timestampUTC),
                "outcome": "analyzed_missing",
                "analysis_eligible": true,
                "pass_geometry": frame.strongPassGeometry ? "strong" : "not_established",
            ]
        }

        let boundaryContext = event.passageBoundaryContext
        let fallbackContext = event.lastSeenContext ?? event.activationContext
        guard let boundaryCoordinate = event.passageBoundaryCoordinate else {
            throw TrafficSignPassageWireEncodingError.invalid("Passage boundary has no coordinate")
        }
        let boundaryMatchState: String
        if let boundaryContext {
            boundaryMatchState = boundaryContext.matchedWayStable ? "matched" : "unstable"
        } else {
            boundaryMatchState = "no_match"
        }
        let boundaryFrame = event.lossEvidence[0]
        let boundaryWay: Any = boundaryContext.map { $0.wayId } ?? NSNull()
        let boundarySignature: Any = boundaryContext.map { sourceSignature($0) } ?? NSNull()
        let boundary: [String: Any] = [
            "frame_id": boundaryFrame.frameID,
            "timestamp_utc": timestamp(event.passageBoundaryTimestampUTC),
            "latitude": boundaryCoordinate.latitude,
            "longitude": boundaryCoordinate.longitude,
            "heading_degrees": normalizedHeading(
                boundaryContext?.headingDegrees ?? fallbackContext.headingDegrees
            ),
            "speed_mps": max(0, boundaryFrame.speedMPS),
            "travel_direction": boundaryContext?.travelDirection.rawValue ?? "unknown",
            "map_match_state": boundaryMatchState,
            "way_id": boundaryWay,
            "route_relation_group_ids": boundaryContext?.routeRelationMemberships.map(\.groupID) ?? [],
            "source_signature": boundarySignature,
        ]

        let activation = event.activationContext
        let activatedAt = event.activationTimestampUTC
        let activationWire: [String: Any] = [
            "reason": boundaryContext?.matchedWayStable == true
                ? "boundary_stable_match"
                : "first_stabilized_same_scope_rematch",
            "timestamp_utc": timestamp(activatedAt),
            "latitude": activation.latitude,
            "longitude": activation.longitude,
            "heading_degrees": normalizedHeading(activation.headingDegrees),
            "travel_direction": activation.travelDirection.rawValue,
            "way_id": activation.wayId,
            "route_relation_group_ids": activation.routeRelationMemberships.map(\.groupID),
            "source_signature": sourceSignature(activation),
            "pending_rematch_elapsed_ms": max(
                0,
                Int((activatedAt.timeIntervalSince(event.passageBoundaryTimestampUTC) * 1_000).rounded())
            ),
            "pending_rematch_distance_m": max(
                0,
                distanceMeters(
                    from: boundaryCoordinate,
                    to: TrafficSignCoordinate(
                        latitude: activation.latitude,
                        longitude: activation.longitude
                    )
                )
            ),
        ]

        let initialMemberships = event.initialRecognitionRouteRelationMemberships
        let eligibleMemberships = event.recognitionRouteRelationMemberships
        let action = try actionWire(
            event.action,
            condition: event.conditionState,
            restrictions: event.restrictions
        )
        let resolution = try resolutionWire(action: event.action, decision: decision)
        let persistenceIntent: String
        if decision.applicability == .temporary {
            persistenceIntent = "temporary_restriction"
        } else if decision.operation == .setMaxspeed {
            persistenceIntent = "set_maxspeed"
        } else {
            persistenceIntent = "map_inconsistency"
        }
        let root: [String: Any] = [
            "schema_version": 1,
            "event_kind": "traffic_sign_passage",
            "finalized_event_id": event.finalizedEventID,
            "drive_session_id": event.driveSessionID,
            "tsr_generation": Int(clamping: event.contextGeneration),
            "committed_at_utc": timestamp(
                event.lossEvidence.last?.timestampUTC ?? event.passageBoundaryTimestampUTC
            ),
            "pack": [
                "pack_id": event.packID,
                "taxonomy_version": "tsr-structural-action-v1",
                "execution_mode": "live",
                "override_eligible": true,
                "calibration_status": "passed",
                "components": event.modelComponents.map {
                    [
                        "role": $0.role,
                        "artifact_sha256": $0.artifactSHA256.lowercased(),
                        "preprocessing_version": $0.preprocessingVersion,
                        "calibration_id": $0.calibrationID,
                    ]
                },
            ],
            "track": [
                "physical_track_id": event.physicalTrackID,
                "assembly_ids": event.assemblyIDs,
                "first_seen_timestamp_utc": timestamp(event.firstSeenTimestampUTC),
                "last_seen_timestamp_utc": timestamp(event.lastSeenTimestampUTC),
                "frames_seen": event.frameEvidence.count,
                "peak_consecutive_frames_seen": max(1, event.peakConsecutiveFramesSeen),
                "single_sighting_exception": event.frameEvidence.count == 1,
                "final_calibrated_confidence": finalConfidence,
                "final_accumulated_support": min(max(event.accumulatedSupport, 0), 1),
                "accumulated_support_cap": 1.0,
                "loss_reason": event.lossReason.rawValue,
                "negative_frames_required": event.negativeFramesRequired,
                "frame_evidence": seenFrames,
                "loss_evidence": lossFrames,
            ],
            "action": action,
            "resolution": resolution,
            "boundary": boundary,
            "activation": activationWire,
            "applicability_scope": [
                "bundle_id": bundleID(from: activation.sourceSignature),
                "bundle_sha256": bundleSHA,
                "continuity_epoch_id": "\(activation.sourceSignature.bundleRevision)#\(activation.traversalEpoch)",
                "original_way_id": event.initialRecognitionContext?.wayId ?? activation.wayId,
                "original_travel_direction": event.initialRecognitionContext?.travelDirection.rawValue
                    ?? activation.travelDirection.rawValue,
                "continuity_capable_bundle": activation.routeContinuityAvailable,
                "initial_route_relation_group_ids": initialMemberships.map(\.groupID),
                "eligible_route_relation_group_ids": eligibleMemberships.map(\.groupID),
                "source_relation_ids": Array(
                    Set(eligibleMemberships.compactMap(\.sourceRelationID))
                ).sorted(),
            ],
            "persistence": [
                "observation_intent": persistenceIntent,
                "review_state": decision.initialState.rawValue,
                "runtime_applicable": decision.runtimeApplicable,
                "export_eligible_at_commit": false,
                "finalized_event_id_is_idempotency_key": true,
            ],
            "privacy": [
                "raw_frame_persisted": false,
                "crop_persisted": false,
                "image_path_persisted": false,
            ],
        ]
        guard JSONSerialization.isValidJSONObject(root) else {
            throw TrafficSignPassageWireEncodingError.invalid("Passage wire object is not valid JSON")
        }
        return try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
    }

    private static func actionWire(
        _ action: TrafficSignStructuralAction,
        condition: TrafficSignConditionState,
        restrictions: [TrafficSignRestriction]
    ) throws -> [String: Any] {
        var result: [String: Any] = [
            "permanence": action.isTemporary ? "temporary" : "permanent",
            "condition_state": conditionWire(condition),
            "restrictions": restrictions.map(restrictionWire),
        ]
        switch action {
        case .postedMaximum(let value):
            result["kind"] = "posted_maximum"; result["value_kmh"] = value
        case .zoneStart(let value):
            result["kind"] = "zone_start"; result["value_kmh"] = value
        case .zoneEnd(let value):
            result["kind"] = "zone_end"; if let value { result["ended_value_kmh"] = value }
        case .cityEntry(let country):
            result["kind"] = "city_entry"; result["country"] = country.uppercased()
        case .cityExit:
            result["kind"] = "city_exit"; result["country"] = "DE"
        case .pedestrianZoneStart: result["kind"] = "pedestrian_zone_start"
        case .pedestrianZoneEnd: result["kind"] = "pedestrian_zone_end"
        case .maximumSpeedEnd(let value):
            result["kind"] = "maximum_speed_end"; if let value { result["ended_value_kmh"] = value }
        case .allRestrictionsEnd: result["kind"] = "all_restrictions_end"
        case .motorwayExit: result["kind"] = "motorway_exit"
        case .motorroadExit: result["kind"] = "motorroad_exit"
        case .temporaryMaximum(let value):
            result["kind"] = "temporary_maximum"; result["value_kmh"] = value
        case .nonSpeedRestrictionEnd, .unresolved:
            throw TrafficSignPassageWireEncodingError.invalid("Action is not passage-event eligible")
        }
        return result
    }

    private static func restrictionWire(_ restriction: TrafficSignRestriction) -> [String: Any] {
        let value = restriction.normalizedValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            return ["kind": restriction.kind.rawValue, "evidence_state": "present_unreadable"]
        }
        return [
            "kind": restriction.kind.rawValue,
            "evidence_state": "present_readable",
            "normalized_value": value,
        ]
    }

    private static func resolutionWire(
        action: TrafficSignStructuralAction,
        decision: TrafficSignPassagePersistenceDecision
    ) throws -> [String: Any] {
        let mismatchReview = decision.reason.contains("mismatch")
        let unresolvedEnd = action.isSpeedEnd
            && !decision.runtimeApplicable
            && !mismatchReview
            && decision.value == nil
        let status = decision.runtimeApplicable
            ? "resolved"
            : (unresolvedEnd ? "unresolved_end" : "review_only")
        let presentation: [String: Any]
        if unresolvedEnd {
            presentation = ["kind": "unknown"]
        } else if let value = decision.value {
            if let numeric = Int(value), numeric > 0 {
                presentation = ["kind": "numeric", "value_kmh": numeric]
            } else if value == "walk" {
                presentation = ["kind": "walk"]
            } else if value == "none" {
                presentation = ["kind": "unlimited"]
            } else {
                presentation = ["kind": "unknown"]
            }
        } else {
            presentation = ["kind": "unknown"]
        }
        let normalized: Any
        if decision.runtimeApplicable,
           decision.operation == .setMaxspeed,
           let tagKey = decision.exportTagKey,
           let tagValue = decision.value {
            normalized = [
                "operation": "set_maxspeed",
                "tag_key": tagKey,
                "tag_value": tagValue,
                "direction_scope": directionWire(decision.directionScope),
            ]
        } else {
            normalized = NSNull()
        }
        var result: [String: Any] = [
            "runtime_status": status,
            "presentation": presentation,
            "resolution_basis": decision.runtimeApplicable
                ? resolutionBasis(action)
                : "unresolved",
            "normalized_operation": normalized,
            "masks_stale_camera_assertion": unresolvedEnd,
        ]
        if unresolvedEnd || status == "review_only" {
            result["unresolved_reason"] = decision.reason
        }
        return result
    }

    private static func resolutionBasis(_ action: TrafficSignStructuralAction) -> String {
        switch action {
        case .cityEntry: return "country_policy"
        case .zoneEnd, .maximumSpeedEnd, .allRestrictionsEnd,
             .pedestrianZoneEnd, .cityExit, .motorwayExit,
             .motorroadExit: return "captured_prior_rule"
        default: return "direct_sign"
        }
    }

    private static func conditionWire(_ condition: TrafficSignConditionState) -> String {
        switch condition {
        case .none: return "none"
        case .resolved: return "resolved"
        case .resolving, .unresolved: return "unresolved"
        }
    }

    private static func directionWire(_ direction: LocalObservationDirectionScope) -> String {
        switch direction {
        case .wayWide: return "way"
        case .forward: return "forward"
        case .backward: return "backward"
        case .unknown: return "way"
        }
    }

    private static func sourceSignature(_ context: TrafficSignDetectionContext) -> String {
        let local = context.sourceSignature.localCorrectionRevision ?? "none"
        return "osm=\(context.sourceSignature.osmRevision);local=\(local)"
    }

    private static func bundleID(from signature: TrafficSignRuntimeSourceSignature) -> String {
        let revision = signature.bundleRevision
        if revision.hasPrefix("bundle:"), let separator = revision.firstIndex(of: "|") {
            let start = revision.index(revision.startIndex, offsetBy: 7)
            let value = String(revision[start..<separator])
            if !value.isEmpty { return value }
        }
        return revision.isEmpty ? "unknown" : revision
    }

    private static func confidence(_ value: Double?) -> Double? {
        guard let value, value.isFinite, (0...1).contains(value) else { return nil }
        return value
    }

    private static func nonempty(_ value: String?) -> String? {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return normalized.isEmpty ? nil : normalized
    }

    private static func isSHA256(_ value: String) -> Bool {
        value.range(of: "^[a-fA-F0-9]{64}$", options: .regularExpression) != nil
    }

    private static func isPositiveWayID(_ value: String) -> Bool {
        value.range(of: "^[1-9][0-9]*$", options: .regularExpression) != nil
    }

    private static func normalizedHeading(_ value: Double) -> Double {
        guard value.isFinite else { return 0 }
        return (value.truncatingRemainder(dividingBy: 360) + 360)
            .truncatingRemainder(dividingBy: 360)
    }

    private static func timestamp(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        return formatter.string(from: date)
    }

    private static func distanceMeters(
        from: TrafficSignCoordinate,
        to: TrafficSignCoordinate
    ) -> Double {
        let earthRadius = 6_371_000.0
        let lat1 = from.latitude * .pi / 180
        let lat2 = to.latitude * .pi / 180
        let deltaLat = (to.latitude - from.latitude) * .pi / 180
        let deltaLon = (to.longitude - from.longitude) * .pi / 180
        let a = sin(deltaLat / 2) * sin(deltaLat / 2)
            + cos(lat1) * cos(lat2) * sin(deltaLon / 2) * sin(deltaLon / 2)
        return earthRadius * 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))
    }
}

enum TrafficSignPassageFinalizerUpdate: Equatable, Sendable {
    case idle
    case tracking(accumulatedSupport: Double, evidenceFrames: Int)
    case armed(accumulatedSupport: Double, evidenceFrames: Int)
    case lossPending(boundaryTimestampUTC: Date, negativeFrames: Int)
    case discarded(reason: String)
    case committed(TrafficSignPassageEvent)
}

/// Converts successful analyzed-frame results into one physical passage event.
/// Only explicit `.noRecognition` results are negative evidence; absent callbacks,
/// resets, stopped capture, throttling, and inference errors never call `ingest`.
struct TrafficSignPassageFinalizer: Sendable {
    struct Configuration: Equatable, Sendable {
        let repeatedSightingMinimumSupport: Double
        let singleSightingMinimumSupport: Double
        let repeatedSightingLossFrames: Int
        let singleSightingLossFrames: Int
        let supportCorrelationDiscount: Double
        let pendingRematchMinimumFrames: Int
        let pendingMaximumSeconds: TimeInterval
        let pendingMaximumMeters: Double
        let committedTrackSuppressionSeconds: TimeInterval
        let committedTrackSuppressionMeters: Double

        init(
            repeatedSightingMinimumSupport: Double = 0.72,
            singleSightingMinimumSupport: Double = 0.97,
            repeatedSightingLossFrames: Int = 2,
            singleSightingLossFrames: Int = 3,
            supportCorrelationDiscount: Double = 0.35,
            pendingRematchMinimumFrames: Int = 1,
            pendingMaximumSeconds: TimeInterval = 8,
            pendingMaximumMeters: Double = 160,
            committedTrackSuppressionSeconds: TimeInterval = 5,
            committedTrackSuppressionMeters: Double = 30
        ) {
            self.repeatedSightingMinimumSupport = repeatedSightingMinimumSupport
            self.singleSightingMinimumSupport = singleSightingMinimumSupport
            let boundedRepeatedLossFrames = max(2, repeatedSightingLossFrames)
            self.repeatedSightingLossFrames = boundedRepeatedLossFrames
            self.singleSightingLossFrames = max(
                boundedRepeatedLossFrames + 1,
                singleSightingLossFrames
            )
            self.supportCorrelationDiscount = min(max(supportCorrelationDiscount, 0), 1)
            self.pendingRematchMinimumFrames = max(1, pendingRematchMinimumFrames)
            self.pendingMaximumSeconds = max(0, pendingMaximumSeconds)
            self.pendingMaximumMeters = max(0, pendingMaximumMeters)
            self.committedTrackSuppressionSeconds = max(0, committedTrackSuppressionSeconds)
            self.committedTrackSuppressionMeters = max(0, committedTrackSuppressionMeters)
        }
    }

    private struct Track: Sendable {
        let id: String
        let action: TrafficSignStructuralAction
        let firstSeen: Date
        var lastSeen: Date
        var lastContext: TrafficSignDetectionContext?
        var lastSeenCoordinate: TrafficSignCoordinate?
        var initialRecognitionContext: TrafficSignDetectionContext?
        var initialRecognitionRouteRelationMemberships: [TrafficSignRouteRelationMembership]
        var recognitionRouteRelationMemberships: [TrafficSignRouteRelationMembership]
        var assemblyID: String?
        var assemblyIDs: [String]
        let packID: String
        let artifactSHA256: String
        let preprocessingVersion: String
        let modelComponents: [TrafficSignModelComponentLineage]
        var conditionState: TrafficSignConditionState
        var restrictions: [TrafficSignRestriction]
        var evidence: [TrafficSignPassageFrameEvidence]
        var lossEvidence: [TrafficSignPassageLossFrameEvidence]
        var currentConsecutiveFramesSeen: Int
        var peakConsecutiveFramesSeen: Int
        var support: Double
        var armed: Bool
        var boundaryEvent: TrafficSignRecognitionEvent?
        var boundaryCoordinate: TrafficSignCoordinate?
        var boundaryHasStrongPassGeometry: Bool
        var negativeFrames: Int
        var lossReason: TrafficSignPassageLossReason
        var negativeFramesRequired: Int
        var rematchWayID: String?
        var coherentRematchFrames: Int
        var firstStableRematchContext: TrafficSignDetectionContext?
        var firstStableRematchTimestamp: Date?
        let sessionGeneration: UInt64
        let contextGeneration: UInt64
        let driveSessionID: String
    }

    private struct CommittedSignSuppression: Sendable {
        let physicalTrackID: String
        let action: TrafficSignStructuralAction
        let committedAt: Date
        let coordinate: TrafficSignCoordinate?
    }

    private let configuration: Configuration
    private var track: Track?
    private var queuedTrack: Track?
    private var mostRecentCommittedSign: CommittedSignSuppression?

    init(configuration: Configuration = Configuration()) {
        self.configuration = configuration
    }

    mutating func reset() {
        track = nil
        queuedTrack = nil
        mostRecentCommittedSign = nil
    }

    mutating func ingest(
        _ event: TrafficSignRecognitionEvent,
        sessionGeneration: UInt64,
        contextGeneration: UInt64,
        frameCoordinate: TrafficSignCoordinate? = nil,
        frameSpeedKmh: Double? = nil,
        strongPassGeometry: Bool = false,
        calibratedActivationEligible: Bool = false,
        negativeForQueuedTrack: Bool = true
    ) -> TrafficSignPassageFinalizerUpdate {
        guard event.source == .liveFrame else { return .idle }
        // This legacy-named eligibility bit is frozen with the analyzed frame
        // and represents active-drive motion. Calibration remains evidence in
        // the event, but does not disable live testing with a raw-score pack.
        guard calibratedActivationEligible else { return currentStateUpdate }
        pruneCommittedSignSuppression(at: event.frameTimestampUtc)

        if let candidate = event.candidate,
           event.analysisEligible != false,
           event.state == .provisional || event.state == .confirmed {
            let action = TrafficSignStructuralAction.normalized(from: candidate)
            guard action.passageEventEligible else {
                // UNKNOWN and non-speed signs are neutral to an already armed
                // speed track. Only explicit analyzed-missing output or a
                // supported adjacent speed action advances passage loss.
                return currentStateUpdate
            }
            let activationConfidence = candidate.calibratedConfidence ?? candidate.rawScore
            guard activationConfidence.isFinite,
                  (0...1).contains(activationConfidence) else {
                return currentStateUpdate
            }
            guard !event.modelComponents.isEmpty,
                  event.modelComponents.allSatisfy(\.isValid) else {
                return currentStateUpdate
            }
            guard Self.validOptionalConfidence(candidate.detectorRawScore),
                  Self.validOptionalConfidence(candidate.detectorCalibratedConfidence),
                  Self.validOptionalConfidence(candidate.classifierRawScore),
                  Self.validOptionalConfidence(candidate.classifierCalibratedConfidence),
                  Self.validOptionalConfidence(candidate.assemblyConfidence),
                  Self.nonempty(candidate.assemblyId) != nil else {
                return currentStateUpdate
            }
            guard let driveSessionID = Self.nonempty(event.driveSessionId),
                  Self.nonempty(event.frameId) != nil else { return currentStateUpdate }
            let trackID = candidate.trackId ?? "semantic:\(action.stableKey)"
            let candidateCoordinate = Self.bestCoordinate(
                frameCoordinate: frameCoordinate,
                context: event.roadContext
            )
            if isSuppressedByRecentCommit(
                physicalTrackID: trackID,
                action: action,
                timestamp: event.frameTimestampUtc,
                coordinate: candidateCoordinate
            ), track?.action == action || track == nil {
                if track?.action == action {
                    track = nil
                }
                if queuedTrack?.action == action {
                    queuedTrack = nil
                }
                return .idle
            }
            let confidence = activationConfidence
            if var current = track,
               current.id == trackID,
               current.action == action,
               current.sessionGeneration == sessionGeneration,
               current.contextGeneration == contextGeneration,
               current.driveSessionID == driveSessionID,
               Self.isCompatibleVisibleContext(event.roadContext, with: current.lastContext) {
                guard event.frameTimestampUtc > current.lastSeen else {
                    return currentStateUpdate
                }
                current.lastSeen = event.frameTimestampUtc
                current.lastSeenCoordinate = candidateCoordinate ?? current.lastSeenCoordinate
                let resumedAfterLoss = current.boundaryEvent != nil
                if let context = event.roadContext, context.isValid {
                    if current.initialRecognitionContext == nil {
                        current.initialRecognitionContext = context
                        current.initialRecognitionRouteRelationMemberships = context.routeRelationMemberships
                        current.recognitionRouteRelationMemberships = context.routeRelationMemberships
                    } else if let previousContext = current.lastContext,
                              previousContext.wayId != context.wayId {
                        let currentIDs = Set(context.routeRelationMemberships.map(\.groupID))
                        current.recognitionRouteRelationMemberships.removeAll {
                            !currentIDs.contains($0.groupID)
                        }
                    }
                    current.lastContext = context
                }
                current.assemblyID = candidate.assemblyId ?? current.assemblyID
                if let assemblyID = Self.nonempty(candidate.assemblyId),
                   !current.assemblyIDs.contains(assemblyID) {
                    current.assemblyIDs.append(assemblyID)
                }
                current.currentConsecutiveFramesSeen = resumedAfterLoss
                    ? 1
                    : current.currentConsecutiveFramesSeen + 1
                current.peakConsecutiveFramesSeen = max(
                    current.peakConsecutiveFramesSeen,
                    current.currentConsecutiveFramesSeen
                )
                current.boundaryEvent = nil
                current.boundaryCoordinate = nil
                current.boundaryHasStrongPassGeometry = false
                current.negativeFrames = 0
                current.lossReason = .negativeDebounce
                current.negativeFramesRequired = 0
                current.lossEvidence.removeAll(keepingCapacity: true)
                current.rematchWayID = nil
                current.coherentRematchFrames = 0
                current.firstStableRematchContext = nil
                current.firstStableRematchTimestamp = nil
                current.conditionState = Self.mergedConditionState(
                    current.conditionState,
                    candidate.conditionState
                )
                current.restrictions = Self.mergedRestrictions(
                    current.restrictions,
                    candidate.restrictions
                )
                current.support = Self.accumulatedSupport(
                    previous: current.support,
                    next: confidence,
                    discount: configuration.supportCorrelationDiscount
                )
                current.evidence.append(TrafficSignPassageFrameEvidence(
                    frameID: Self.frameID(for: event),
                    timestampUTC: event.frameTimestampUtc,
                    outcome: "seen",
                    analysisEligible: true,
                    rawScore: candidate.rawScore,
                    calibratedConfidence: candidate.calibratedConfidence,
                    proposalRawScore: candidate.detectorRawScore,
                    proposalCalibratedConfidence: candidate.detectorCalibratedConfidence,
                    classifierRawScore: candidate.classifierRawScore,
                    classifierCalibratedConfidence: candidate.classifierCalibratedConfidence,
                    assemblyConfidence: candidate.assemblyConfidence,
                    accumulatedSupport: current.support,
                    wayID: event.roadContext?.wayId
                ))
                current.armed = Self.shouldArm(
                    evidenceCount: current.evidence.count,
                    support: current.support,
                    eventState: event.state,
                    configuration: configuration
                )
                track = current
            } else {
                if let current = track,
                   current.armed,
                   current.sessionGeneration == sessionGeneration,
                   current.contextGeneration == contextGeneration,
                   current.driveSessionID == event.driveSessionId,
                   Self.isCompatibleVisibleContext(event.roadContext, with: current.lastContext) {
                    // The classifier exposes one primary candidate per frame.
                    // A different compatible sign therefore proves the old
                    // sign is absent, while the new sign must simultaneously
                    // begin/continue its own visual track. Debounce the old
                    // passage and retain the adjacent sign for the next edge.
                    track = queuedTrack
                    _ = ingest(
                        event,
                        sessionGeneration: sessionGeneration,
                        contextGeneration: contextGeneration,
                        frameCoordinate: frameCoordinate,
                        frameSpeedKmh: frameSpeedKmh,
                        strongPassGeometry: strongPassGeometry,
                        calibratedActivationEligible: calibratedActivationEligible,
                        negativeForQueuedTrack: false
                    )
                    queuedTrack = track
                    track = current
                    let negativeEvent = TrafficSignRecognitionEvent(
                        schemaVersion: event.schemaVersion,
                        packId: event.packId,
                        artifactSha256: event.artifactSha256,
                        preprocessingVersion: event.preprocessingVersion,
                        frameId: event.frameId,
                        driveSessionId: event.driveSessionId,
                        analysisEligible: event.analysisEligible,
                        source: event.source,
                        frameTimestampUtc: event.frameTimestampUtc,
                        state: .noRecognition,
                        candidate: nil,
                        roadContext: event.roadContext,
                        latencyMs: event.latencyMs,
                        thermalState: event.thermalState
                    )
                    return ingest(
                        negativeEvent,
                        sessionGeneration: sessionGeneration,
                        contextGeneration: contextGeneration,
                        frameCoordinate: frameCoordinate,
                        frameSpeedKmh: frameSpeedKmh,
                        strongPassGeometry: strongPassGeometry,
                        calibratedActivationEligible: calibratedActivationEligible,
                        negativeForQueuedTrack: false
                    )
                }
                queuedTrack = nil
                // A different visible physical track is contradictory, not a
                // delayed passage edge for the old one. Replacing the pending
                // track prevents a later empty frame from committing the old
                // sign and never prevents the new sign from accumulating.
                track = Track(
                    id: trackID,
                    action: action,
                    firstSeen: event.frameTimestampUtc,
                    lastSeen: event.frameTimestampUtc,
                    lastContext: event.roadContext.flatMap { $0.isValid ? $0 : nil },
                    lastSeenCoordinate: candidateCoordinate,
                    initialRecognitionContext: event.roadContext.flatMap { $0.isValid ? $0 : nil },
                    initialRecognitionRouteRelationMemberships: event.roadContext?
                        .routeRelationMemberships ?? [],
                    recognitionRouteRelationMemberships: event.roadContext?
                        .routeRelationMemberships ?? [],
                    assemblyID: candidate.assemblyId,
                    assemblyIDs: Self.nonempty(candidate.assemblyId).map { [$0] } ?? [],
                    packID: event.packId,
                    artifactSHA256: event.artifactSha256,
                    preprocessingVersion: event.preprocessingVersion,
                    modelComponents: event.modelComponents,
                    conditionState: candidate.conditionState,
                    restrictions: candidate.restrictions,
                    evidence: [TrafficSignPassageFrameEvidence(
                        frameID: Self.frameID(for: event),
                        timestampUTC: event.frameTimestampUtc,
                        outcome: "seen",
                        analysisEligible: true,
                        rawScore: candidate.rawScore,
                        calibratedConfidence: candidate.calibratedConfidence,
                        proposalRawScore: candidate.detectorRawScore,
                        proposalCalibratedConfidence: candidate.detectorCalibratedConfidence,
                        classifierRawScore: candidate.classifierRawScore,
                        classifierCalibratedConfidence: candidate.classifierCalibratedConfidence,
                        assemblyConfidence: candidate.assemblyConfidence,
                        accumulatedSupport: confidence,
                        wayID: event.roadContext?.wayId
                    )],
                    lossEvidence: [],
                    currentConsecutiveFramesSeen: 1,
                    peakConsecutiveFramesSeen: 1,
                    support: confidence,
                    armed: Self.shouldArm(
                        evidenceCount: 1,
                        support: confidence,
                        eventState: event.state,
                        configuration: configuration
                    ),
                    boundaryEvent: nil,
                    boundaryCoordinate: nil,
                    boundaryHasStrongPassGeometry: false,
                    negativeFrames: 0,
                    lossReason: .negativeDebounce,
                    negativeFramesRequired: 0,
                    rematchWayID: nil,
                    coherentRematchFrames: 0,
                    firstStableRematchContext: nil,
                    firstStableRematchTimestamp: nil,
                    sessionGeneration: sessionGeneration,
                    contextGeneration: contextGeneration,
                    driveSessionID: driveSessionID
                )
            }
            return currentStateUpdate
        }

        guard event.state == .noRecognition,
              event.analysisEligible != false,
              Self.nonempty(event.frameId) != nil,
              Self.nonempty(event.driveSessionId) != nil,
              var current = track,
              current.driveSessionID == Self.nonempty(event.driveSessionId),
              current.armed else { return currentStateUpdate }

        current.lossEvidence.append(TrafficSignPassageLossFrameEvidence(
            frameID: Self.frameID(for: event),
            timestampUTC: event.frameTimestampUtc,
            outcome: "analyzed_missing",
            analysisEligible: true,
            strongPassGeometry: strongPassGeometry,
            speedMPS: max(0, (frameSpeedKmh ?? 0) / 3.6),
            wayID: event.roadContext?.wayId
        ))

        if current.boundaryEvent == nil {
            current.boundaryEvent = event
            current.boundaryCoordinate = frameCoordinate ?? event.roadContext.map {
                TrafficSignCoordinate(latitude: $0.latitude, longitude: $0.longitude)
            }
            current.boundaryHasStrongPassGeometry = strongPassGeometry
            current.negativeFrames = 1
            current.lossReason = current.evidence.count > 1 && strongPassGeometry
                ? .strongPassGeometry
                : .negativeDebounce
            current.negativeFramesRequired = current.evidence.count == 1
                ? configuration.singleSightingLossFrames
                : (strongPassGeometry ? 1 : configuration.repeatedSightingLossFrames)
        } else {
            current.negativeFrames += 1
        }
        let requiredLossFrames = current.negativeFramesRequired
        guard current.negativeFrames >= requiredLossFrames,
              let boundaryEvent = current.boundaryEvent else {
            track = current
            return .lossPending(
                boundaryTimestampUTC: current.boundaryEvent?.frameTimestampUtc ?? event.frameTimestampUtc,
                negativeFrames: current.negativeFrames
            )
        }

        if pendingBoundsExceeded(current, at: event.frameTimestampUtc, coordinate: frameCoordinate) {
            track = nil
            return .discarded(reason: "pending_passage_bound_exceeded")
        }

        // Map scope must be established while the physical sign is still
        // visible. A track observed entirely during a matcher gap cannot bind
        // to an arbitrary way/relation that appears only after disappearance.
        guard current.initialRecognitionContext != nil else {
            track = nil
            return .discarded(reason: "passage_missing_recognition_origin")
        }

        let activationContext: TrafficSignDetectionContext
        if let boundaryContext = boundaryEvent.roadContext,
           boundaryContext.isValid,
           boundaryContext.matchedWayStable {
            guard current.lastContext.map({ Self.isCompatibleRematch(boundaryContext, with: $0) }) != false else {
                track = nil
                return .discarded(reason: "passage_boundary_left_traversal_scope")
            }
            guard Self.isWithinNarrowedRecognitionScope(boundaryContext, track: current) else {
                track = nil
                return .discarded(reason: "passage_boundary_left_recognition_scope")
            }
            activationContext = boundaryContext
        } else if let rematch = event.roadContext,
                  rematch.isValid,
                  rematch.matchedWayStable {
            guard current.lastContext.map({ Self.isCompatibleRematch(rematch, with: $0) }) != false else {
                track = nil
                return .discarded(reason: "pending_passage_unrelated_rematch")
            }
            guard Self.isWithinNarrowedRecognitionScope(rematch, track: current) else {
                track = nil
                return .discarded(reason: "pending_passage_left_recognition_scope")
            }
            if let firstRematch = current.firstStableRematchContext {
                guard Self.isCompatibleRematch(rematch, with: firstRematch) else {
                    track = nil
                    return .discarded(reason: "pending_passage_incoherent_rematch")
                }
                current.coherentRematchFrames += 1
            } else {
                current.rematchWayID = rematch.wayId
                current.coherentRematchFrames = 1
                current.firstStableRematchContext = rematch
                current.firstStableRematchTimestamp = event.frameTimestampUtc
            }
            guard current.coherentRematchFrames >= configuration.pendingRematchMinimumFrames else {
                track = current
                return .lossPending(
                    boundaryTimestampUTC: boundaryEvent.frameTimestampUtc,
                    negativeFrames: current.negativeFrames
                )
            }
            activationContext = current.firstStableRematchContext ?? rematch
        } else {
            track = current
            return .lossPending(
                boundaryTimestampUTC: boundaryEvent.frameTimestampUtc,
                negativeFrames: current.negativeFrames
            )
        }

        // Activation may only narrow the relations established while the sign
        // was visible. It must never acquire a group introduced by a boundary
        // or rematch after the physical sign disappeared.
        if current.initialRecognitionContext != nil {
            let activationGroupIDs = Set(activationContext.routeRelationMemberships.map(\.groupID))
            current.recognitionRouteRelationMemberships.removeAll {
                !activationGroupIDs.contains($0.groupID)
            }
        }

        if isSuppressedByRecentCommit(
            physicalTrackID: current.id,
            action: current.action,
            timestamp: event.frameTimestampUtc,
            coordinate: current.lastSeenCoordinate
        ) {
            track = queuedTrack
            queuedTrack = nil
            return .discarded(reason: "recent_physical_sign_duplicate")
        }

        let passage = TrafficSignPassageEvent(
            schemaVersion: 1,
            finalizedEventID: UUID().uuidString.lowercased(),
            driveSessionID: current.driveSessionID,
            physicalTrackID: current.id,
            assemblyID: current.assemblyID,
            assemblyIDs: current.assemblyIDs,
            packID: current.packID,
            artifactSHA256: current.artifactSHA256,
            preprocessingVersion: current.preprocessingVersion,
            modelComponents: current.modelComponents,
            action: current.action,
            conditionState: current.conditionState,
            restrictions: current.restrictions,
            firstSeenTimestampUTC: current.firstSeen,
            lastSeenTimestampUTC: current.lastSeen,
            passageBoundaryTimestampUTC: boundaryEvent.frameTimestampUtc,
            lastSeenContext: current.lastContext,
            passageBoundaryCoordinate: current.boundaryCoordinate,
            passageBoundaryContext: boundaryEvent.roadContext,
            initialRecognitionContext: current.initialRecognitionContext,
            activationContext: activationContext,
            activationTimestampUTC: boundaryEvent.roadContext?.matchedWayStable == true
                ? boundaryEvent.frameTimestampUtc
                : (current.firstStableRematchTimestamp ?? event.frameTimestampUtc),
            initialRecognitionRouteRelationMemberships: current.initialRecognitionRouteRelationMemberships,
            recognitionRouteRelationMemberships: current.recognitionRouteRelationMemberships,
            frameEvidence: current.evidence,
            lossEvidence: current.lossEvidence,
            accumulatedSupport: current.support,
            finalCalibratedConfidence: current.evidence.compactMap(\.calibratedConfidence).max(),
            peakConsecutiveFramesSeen: current.peakConsecutiveFramesSeen,
            lossNegativeFrames: current.negativeFrames,
            lossReason: current.lossReason,
            negativeFramesRequired: current.negativeFramesRequired,
            sessionGeneration: current.sessionGeneration,
            contextGeneration: current.contextGeneration
        )
        mostRecentCommittedSign = CommittedSignSuppression(
            physicalTrackID: current.id,
            action: current.action,
            committedAt: event.frameTimestampUtc,
            coordinate: current.lastSeenCoordinate
        )
        track = queuedTrack
        queuedTrack = nil
        if negativeForQueuedTrack, track != nil {
            // The same analyzed empty frame is also the first qualified loss
            // frame for an adjacent queued sign.
            _ = ingest(
                event,
                sessionGeneration: sessionGeneration,
                contextGeneration: contextGeneration,
                frameCoordinate: frameCoordinate,
                frameSpeedKmh: frameSpeedKmh,
                strongPassGeometry: strongPassGeometry,
                calibratedActivationEligible: calibratedActivationEligible,
                negativeForQueuedTrack: false
            )
        }
        return .committed(passage)
    }

    private var currentStateUpdate: TrafficSignPassageFinalizerUpdate {
        track.map {
            if let boundary = $0.boundaryEvent {
                return .lossPending(
                    boundaryTimestampUTC: boundary.frameTimestampUtc,
                    negativeFrames: $0.negativeFrames
                )
            }
            return $0.armed
                ? .armed(accumulatedSupport: $0.support, evidenceFrames: $0.evidence.count)
                : .tracking(accumulatedSupport: $0.support, evidenceFrames: $0.evidence.count)
        } ?? .idle
    }

    private mutating func pruneCommittedSignSuppression(at timestamp: Date) {
        guard let recent = mostRecentCommittedSign else { return }
        let age = timestamp.timeIntervalSince(recent.committedAt)
        if age < 0 || age > configuration.committedTrackSuppressionSeconds {
            mostRecentCommittedSign = nil
        }
    }

    private func isSuppressedByRecentCommit(
        physicalTrackID: String,
        action: TrafficSignStructuralAction,
        timestamp: Date,
        coordinate: TrafficSignCoordinate?
    ) -> Bool {
        guard let recent = mostRecentCommittedSign,
              recent.action == action else { return false }
        let age = timestamp.timeIntervalSince(recent.committedAt)
        guard age >= 0,
              age <= configuration.committedTrackSuppressionSeconds else { return false }
        if let recentCoordinate = recent.coordinate, let coordinate {
            return Self.distanceMeters(from: recentCoordinate, to: coordinate)
                <= configuration.committedTrackSuppressionMeters
        }
        // Stable tracker identity remains a safe fallback when one side lacks
        // coordinates. When both positions are known, distance always wins so
        // an ID reused at a later sign cannot create lifetime suppression.
        return recent.physicalTrackID == physicalTrackID
    }

    private static func bestCoordinate(
        frameCoordinate: TrafficSignCoordinate?,
        context: TrafficSignDetectionContext?
    ) -> TrafficSignCoordinate? {
        if let frameCoordinate,
           frameCoordinate.latitude.isFinite,
           frameCoordinate.longitude.isFinite,
           (-90...90).contains(frameCoordinate.latitude),
           (-180...180).contains(frameCoordinate.longitude) {
            return frameCoordinate
        }
        guard let context,
              context.latitude.isFinite,
              context.longitude.isFinite,
              (-90...90).contains(context.latitude),
              (-180...180).contains(context.longitude) else { return nil }
        return TrafficSignCoordinate(latitude: context.latitude, longitude: context.longitude)
    }

    private static func frameID(for event: TrafficSignRecognitionEvent) -> String {
        // Authoritative callers are guarded before tracking. Keep this helper
        // total as a final fail-closed backstop instead of crashing on malformed
        // imported/legacy evidence.
        return nonempty(event.frameId) ?? ""
    }

    private static func nonempty(_ value: String?) -> String? {
        let normalized = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return normalized.isEmpty ? nil : normalized
    }

    private static func validOptionalConfidence(_ value: Double?) -> Bool {
        value.map { $0.isFinite && (0...1).contains($0) } ?? true
    }

    private func pendingBoundsExceeded(
        _ track: Track,
        at timestamp: Date,
        coordinate: TrafficSignCoordinate?
    ) -> Bool {
        guard let boundary = track.boundaryEvent else { return false }
        if timestamp.timeIntervalSince(boundary.frameTimestampUtc) > configuration.pendingMaximumSeconds {
            return true
        }
        guard let start = track.boundaryCoordinate, let coordinate else { return false }
        return Self.distanceMeters(from: start, to: coordinate) > configuration.pendingMaximumMeters
    }

    private static func isCompatibleRematch(
        _ context: TrafficSignDetectionContext,
        with original: TrafficSignDetectionContext
    ) -> Bool {
        guard context.sourceSignature.bundleRevision == original.sourceSignature.bundleRevision,
              context.traversalEpoch == original.traversalEpoch else { return false }
        if context.wayId == original.wayId {
            return original.travelDirection == .unknown
                || context.travelDirection == .unknown
                || context.travelDirection == original.travelDirection
        }
        guard context.routeContinuityAvailable, original.routeContinuityAvailable else { return false }
        let originalGroups = Set(original.routeRelationMemberships.map(\.groupID))
        let currentGroups = Set(context.routeRelationMemberships.map(\.groupID))
        return !originalGroups.isEmpty && !originalGroups.isDisjoint(with: currentGroups)
    }

    private static func isCompatibleVisibleContext(
        _ context: TrafficSignDetectionContext?,
        with original: TrafficSignDetectionContext?
    ) -> Bool {
        guard let context, context.isValid, let original else { return true }
        return isCompatibleRematch(context, with: original)
    }

    private static func isWithinNarrowedRecognitionScope(
        _ context: TrafficSignDetectionContext,
        track: Track
    ) -> Bool {
        guard let initial = track.initialRecognitionContext else { return false }
        guard context.sourceSignature.bundleRevision == initial.sourceSignature.bundleRevision,
              context.traversalEpoch == initial.traversalEpoch else { return false }
        if context.wayId == initial.wayId {
            return initial.travelDirection == .unknown
                || context.travelDirection == .unknown
                || context.travelDirection == initial.travelDirection
        }
        guard context.routeContinuityAvailable,
              initial.routeContinuityAvailable else { return false }
        let eligibleGroupIDs = Set(track.recognitionRouteRelationMemberships.map(\.groupID))
        let contextGroupIDs = Set(context.routeRelationMemberships.map(\.groupID))
        return !eligibleGroupIDs.isEmpty
            && !eligibleGroupIDs.isDisjoint(with: contextGroupIDs)
    }

    private static func mergedConditionState(
        _ lhs: TrafficSignConditionState,
        _ rhs: TrafficSignConditionState
    ) -> TrafficSignConditionState {
        if lhs == .unresolved || rhs == .unresolved || lhs == .resolving || rhs == .resolving {
            return .unresolved
        }
        if lhs == .resolved || rhs == .resolved { return .resolved }
        return .none
    }

    private static func mergedRestrictions(
        _ lhs: [TrafficSignRestriction],
        _ rhs: [TrafficSignRestriction]
    ) -> [TrafficSignRestriction] {
        var seen = Set<TrafficSignRestriction>()
        return (lhs + rhs).filter { seen.insert($0).inserted }
    }

    private static func shouldArm(
        evidenceCount: Int,
        support: Double,
        eventState: TrafficSignRecognitionResultState,
        configuration: Configuration
    ) -> Bool {
        if evidenceCount >= 2 {
            return eventState == .confirmed || support >= configuration.repeatedSightingMinimumSupport
        }
        return support >= configuration.singleSightingMinimumSupport
    }

    private static func accumulatedSupport(previous: Double, next: Double, discount: Double) -> Double {
        let boundedPrevious = min(max(previous, 0), 1)
        let boundedNext = min(max(next, 0), 1)
        return min(1, max(boundedPrevious, boundedPrevious + (1 - boundedPrevious) * boundedNext * discount))
    }

    private static func distanceMeters(
        from: TrafficSignCoordinate,
        to: TrafficSignCoordinate
    ) -> Double {
        let earthRadius = 6_371_000.0
        let lat1 = from.latitude * .pi / 180
        let lat2 = to.latitude * .pi / 180
        let deltaLat = (to.latitude - from.latitude) * .pi / 180
        let deltaLon = (to.longitude - from.longitude) * .pi / 180
        let a = sin(deltaLat / 2) * sin(deltaLat / 2)
            + cos(lat1) * cos(lat2) * sin(deltaLon / 2) * sin(deltaLon / 2)
        return earthRadius * 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))
    }
}

struct TrafficSignTraversalUpdate: Equatable, Sendable {
    let epoch: UInt64
    let continuouslyRelated: Bool
    let eligibleMemberships: [TrafficSignRouteRelationMembership]
}

/// Assigns a stable epoch to one continuously traversed route. Epoch continuity
/// is pairwise between adjacent matcher results; each camera assertion performs
/// its own recognition-time intersection to prevent transitive relation hops.
struct TrafficSignTraversalTracker: Sendable {
    private(set) var epoch: UInt64 = 1
    private var previousWayID: String?
    private var previousDirection: TrafficSignTravelDirection = .unknown
    private var previousMembershipsByGroupID: [Int: TrafficSignRouteRelationMembership] = [:]

    mutating func reset() {
        epoch &+= 1
        previousWayID = nil
        previousDirection = .unknown
        previousMembershipsByGroupID = [:]
    }

    mutating func update(
        wayID: String,
        direction: TrafficSignTravelDirection,
        continuityAvailable: Bool,
        memberships: [TrafficSignRouteRelationMembership]
    ) -> TrafficSignTraversalUpdate {
        let normalized = Dictionary(
            uniqueKeysWithValues: memberships.filter(\.isValid).map { ($0.groupID, $0) }
        )
        guard let previousWayID else {
            self.previousWayID = wayID
            previousDirection = direction
            previousMembershipsByGroupID = continuityAvailable ? normalized : [:]
            return TrafficSignTraversalUpdate(
                epoch: epoch,
                continuouslyRelated: true,
                eligibleMemberships: previousMembershipsByGroupID.values.sorted { $0.groupID < $1.groupID }
            )
        }

        if previousWayID == wayID,
           previousDirection != .unknown,
           direction != .unknown,
           previousDirection != direction {
            epoch &+= 1
            previousMembershipsByGroupID = continuityAvailable ? normalized : [:]
            self.previousWayID = wayID
            previousDirection = direction
            return TrafficSignTraversalUpdate(
                epoch: epoch,
                continuouslyRelated: false,
                eligibleMemberships: previousMembershipsByGroupID.values.sorted { $0.groupID < $1.groupID }
            )
        }

        if previousWayID == wayID {
            self.previousDirection = direction
            if continuityAvailable, !normalized.isEmpty {
                previousMembershipsByGroupID = normalized
            }
            return TrafficSignTraversalUpdate(
                epoch: epoch,
                continuouslyRelated: true,
                eligibleMemberships: previousMembershipsByGroupID.values.sorted { $0.groupID < $1.groupID }
            )
        }

        let sharedIDs = Set(previousMembershipsByGroupID.keys).intersection(normalized.keys)
        if continuityAvailable, !previousMembershipsByGroupID.isEmpty, !sharedIDs.isEmpty {
            previousMembershipsByGroupID = normalized
            self.previousWayID = wayID
            previousDirection = direction
            return TrafficSignTraversalUpdate(
                epoch: epoch,
                continuouslyRelated: true,
                eligibleMemberships: previousMembershipsByGroupID.values.sorted { $0.groupID < $1.groupID }
            )
        }

        epoch &+= 1
        self.previousWayID = wayID
        previousDirection = direction
        previousMembershipsByGroupID = continuityAvailable ? normalized : [:]
        return TrafficSignTraversalUpdate(
            epoch: epoch,
            continuouslyRelated: false,
            eligibleMemberships: previousMembershipsByGroupID.values.sorted { $0.groupID < $1.groupID }
        )
    }
}

struct TrafficSignPassagePersistenceDecision: Equatable, Sendable {
    let value: String?
    let oldSpeedKmh: Int?
    let runtimeApplicable: Bool
    let initialState: LocalObservationState
    let operation: LocalObservationOperation?
    let directionScope: LocalObservationDirectionScope
    let applicability: LocalObservationApplicability
    let exportTagKey: String?
    let reason: String
}

struct TrafficSignPassageCommitResult: Equatable, Sendable {
    let applied: Bool
    let effectiveState: EffectiveSpeedLimitState
    let persistence: TrafficSignPassagePersistenceDecision
}

extension TrafficSignPassageEvent {
    /// Revalidates delayed inference against the latest immutable matcher
    /// snapshot before either driver-facing state or persistence can change.
    func isCompatibleWithLatestRoadScope(
        _ currentContext: TrafficSignDetectionContext?,
        coordinate: TrafficSignCoordinate?,
        timestamp: Date,
        maximumGapSeconds: TimeInterval = 8,
        maximumGapMeters: Double = 160
    ) -> Bool {
        guard let currentContext else {
            guard timestamp.timeIntervalSince(activationTimestampUTC) <= maximumGapSeconds else {
                return false
            }
            guard let coordinate else { return true }
            let activationCoordinate = TrafficSignCoordinate(
                latitude: activationContext.latitude,
                longitude: activationContext.longitude
            )
            return Self.scopeDistanceMeters(from: activationCoordinate, to: coordinate)
                <= maximumGapMeters
        }
        guard currentContext.matchedWayStable,
              currentContext.sourceSignature.bundleRevision
                == activationContext.sourceSignature.bundleRevision,
              currentContext.traversalEpoch == activationContext.traversalEpoch else {
            return false
        }
        let originalContext = initialRecognitionContext ?? activationContext
        if currentContext.wayId == originalContext.wayId {
            return originalContext.travelDirection == .unknown
                || currentContext.travelDirection == .unknown
                || currentContext.travelDirection == originalContext.travelDirection
        }
        guard currentContext.routeContinuityAvailable,
              !recognitionRouteRelationMemberships.isEmpty else { return false }
        let currentGroups = Set(currentContext.routeRelationMemberships.map(\.groupID))
        return recognitionRouteRelationMemberships.contains { currentGroups.contains($0.groupID) }
    }

    private static func scopeDistanceMeters(
        from: TrafficSignCoordinate,
        to: TrafficSignCoordinate
    ) -> Double {
        let earthRadius = 6_371_000.0
        let lat1 = from.latitude * .pi / 180
        let lat2 = to.latitude * .pi / 180
        let deltaLat = (to.latitude - from.latitude) * .pi / 180
        let deltaLon = (to.longitude - from.longitude) * .pi / 180
        let a = sin(deltaLat / 2) * sin(deltaLat / 2)
            + cos(lat1) * cos(lat2) * sin(deltaLon / 2) * sin(deltaLon / 2)
        return earthRadius * 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))
    }
}

struct TrafficSignApplicabilityScope: Codable, Equatable, Sendable {
    let originalWayID: String
    let originalDirection: TrafficSignTravelDirection
    let traversalEpoch: UInt64
    let bundleRevision: String
    var eligibleMemberships: [TrafficSignRouteRelationMembership]
    var lastMatchedWayID: String
    var lastCoordinate: TrafficSignCoordinate
    var gapStartedAt: Date?
    var gapStartedCoordinate: TrafficSignCoordinate?
}

struct TrafficSignCoordinate: Codable, Equatable, Sendable {
    let latitude: Double
    let longitude: Double
}

enum TrafficSignBundleContextPolicy {
    /// A bundle-confirmed entry into a built-up area starts a new statutory
    /// speed context. Camera evidence captured outside that area ends there.
    static func enteredCity(previousInsideCity: Bool?, currentInsideCity: Bool?) -> Bool {
        previousInsideCity == false && currentInsideCity == true
    }
}

private struct TrafficSignRuleState: Equatable, Sendable {
    var enclosingBase: EffectiveSpeedLimitState?
    var city: EffectiveSpeedLimitValue?
    var zone: (value: Int, expectedEnd: Int?)?
    var pedestrian = false
    var posted: Int?

    static func == (lhs: TrafficSignRuleState, rhs: TrafficSignRuleState) -> Bool {
        lhs.enclosingBase == rhs.enclosingBase
            && lhs.city == rhs.city
            && lhs.zone?.value == rhs.zone?.value
            && lhs.zone?.expectedEnd == rhs.zone?.expectedEnd
            && lhs.pedestrian == rhs.pedestrian
            && lhs.posted == rhs.posted
    }
}

private struct TrafficSignCameraAssertion: Equatable, Sendable {
    let passage: TrafficSignPassageEvent
    var scope: TrafficSignApplicabilityScope
    let effectiveState: EffectiveSpeedLimitState
}

/// Session-scoped source reducer. Base revisions never invalidate an applicable
/// camera assertion; only generation/lifecycle reset or road-scope reconciliation
/// can do so.
struct TrafficSignEffectiveLimitResolver: Sendable {
    private(set) var activePassage: TrafficSignPassageEvent?
    private(set) var lastEffectiveState: EffectiveSpeedLimitState = .none
    private var assertion: TrafficSignCameraAssertion?
    private var rules = TrafficSignRuleState()
    private let maximumGapSeconds: TimeInterval
    private let maximumGapMeters: Double

    init(maximumGapSeconds: TimeInterval = 8, maximumGapMeters: Double = 160) {
        self.maximumGapSeconds = max(0, maximumGapSeconds)
        self.maximumGapMeters = max(0, maximumGapMeters)
    }

    var hasActiveCameraAssertion: Bool { assertion != nil }

    mutating func clear(base: EffectiveSpeedLimitState = .none) -> EffectiveSpeedLimitState {
        assertion = nil
        activePassage = nil
        rules = TrafficSignRuleState()
        lastEffectiveState = base
        return base
    }

    mutating func commit(
        _ passage: TrafficSignPassageEvent,
        base: EffectiveSpeedLimitState,
        verifiedEnclosingBase: EffectiveSpeedLimitState? = nil
    ) -> TrafficSignPassageCommitResult {
        let context = passage.activationContext
        let action = passage.action
        let conditional = !passage.isUnconditional
        // A normal local/bundle value is not proof of the rule that survives
        // beyond an observed end sign (the supplied end-of-70 case is exactly
        // such a stale base). Only a caller's separately corroborated
        // structural/statutory result may become an enclosing restore target.
        if rules.enclosingBase == nil { rules.enclosingBase = verifiedEnclosingBase }

        let resolution: (applied: Bool, value: EffectiveSpeedLimitValue, reason: String)
        let recognitionLostBeforeActivation: Bool = {
            guard let firstMatchedWay = passage.initialRecognitionContext?.wayId,
                  firstMatchedWay != context.wayId else { return false }
            return passage.recognitionRouteRelationMemberships.isEmpty
        }()
        if !action.hasSupportedSpeedValue {
            resolution = (false, .unknown, "camera_speed_value_out_of_range_review_only")
        } else if recognitionLostBeforeActivation {
            resolution = action.isSpeedEnd
                ? maskOrPreserveUnsafeEnd(action, reason: "camera_end_recognition_scope_lost")
                : (false, .unknown, "camera_recognition_scope_lost_review_only")
        } else if !context.matchedWayStable {
            resolution = action.isSpeedEnd
                ? maskOrPreserveUnsafeEnd(action, reason: "camera_end_unstable_way")
                : (false, .unknown, "camera_unstable_way_review_only")
        } else if !context.sourceSignature.hasVerifiedBundleLineage {
            resolution = action.isSpeedEnd
                ? maskOrPreserveUnsafeEnd(action, reason: "camera_end_unverified_bundle")
                : (false, .unknown, "camera_unverified_bundle_review_only")
        } else {
            resolution = reduce(action: action, base: base, conditional: conditional)
        }
        let directionScope: LocalObservationDirectionScope
        switch context.travelDirection {
        case .forward: directionScope = .forward
        case .reverse: directionScope = .backward
        case .unknown: directionScope = .wayWide
        }
        let exportTagKey: String?
        switch directionScope {
        case .forward: exportTagKey = "maxspeed:forward"
        case .backward: exportTagKey = "maxspeed:backward"
        case .wayWide: exportTagKey = "maxspeed"
        case .unknown: exportTagKey = nil
        }
        let runtimeApplicable = resolution.applied
            && resolution.value != .unknown
            && !conditional
            && !action.isTemporary
        let normalizedValue: String?
        switch resolution.value {
        case .numeric(let value): normalizedValue = String(value)
        case .walk: normalizedValue = "walk"
        case .unlimited: normalizedValue = "none"
        case .unknown: normalizedValue = nil
        }
        let persistence = TrafficSignPassagePersistenceDecision(
            value: normalizedValue,
            oldSpeedKmh: base.value.speedKmh,
            runtimeApplicable: runtimeApplicable,
            initialState: runtimeApplicable ? .localOnly : .needsReview,
            operation: runtimeApplicable && normalizedValue != nil ? .setMaxspeed : nil,
            directionScope: directionScope,
            applicability: action.isTemporary
                ? .temporary
                : (conditional ? .conditional : .permanent),
            exportTagKey: runtimeApplicable ? exportTagKey : nil,
            reason: resolution.reason
        )

        guard resolution.applied else {
            lastEffectiveState = assertion?.effectiveState ?? base
            return TrafficSignPassageCommitResult(
                applied: false,
                effectiveState: lastEffectiveState,
                persistence: persistence
            )
        }

        let state = EffectiveSpeedLimitState(
            value: resolution.value,
            source: resolution.value == .unknown ? .none : .camera,
            presentationReason: resolution.reason,
            hasCameraEvidenceMarker: true
        )
        let coordinate = TrafficSignCoordinate(
            latitude: context.latitude,
            longitude: context.longitude
        )
        let bundleRevision = context.sourceSignature.bundleRevision
        let scope = TrafficSignApplicabilityScope(
            originalWayID: context.wayId,
            originalDirection: context.travelDirection,
            traversalEpoch: context.traversalEpoch,
            bundleRevision: bundleRevision,
            eligibleMemberships: passage.recognitionRouteRelationMemberships,
            lastMatchedWayID: context.wayId,
            lastCoordinate: coordinate,
            gapStartedAt: nil,
            gapStartedCoordinate: nil
        )
        assertion = TrafficSignCameraAssertion(
            passage: passage,
            scope: scope,
            effectiveState: state
        )
        activePassage = passage
        lastEffectiveState = state
        return TrafficSignPassageCommitResult(
            applied: true,
            effectiveState: state,
            persistence: persistence
        )
    }

    mutating func resolve(
        base: EffectiveSpeedLimitState,
        currentContext: TrafficSignDetectionContext?,
        currentCoordinate: TrafficSignCoordinate?,
        timestamp: Date
    ) -> EffectiveSpeedLimitState {
        guard var assertion else {
            lastEffectiveState = base
            return base
        }
        guard let currentContext else {
            if assertion.scope.gapStartedAt == nil {
                assertion.scope.gapStartedAt = timestamp
                assertion.scope.gapStartedCoordinate = currentCoordinate
            }
            let elapsed = timestamp.timeIntervalSince(assertion.scope.gapStartedAt ?? timestamp)
            let distance = Self.distanceMeters(
                from: assertion.scope.gapStartedCoordinate,
                to: currentCoordinate
            ) ?? 0
            guard elapsed <= maximumGapSeconds, distance <= maximumGapMeters else {
                return clear(base: base)
            }
            self.assertion = assertion
            lastEffectiveState = assertion.effectiveState
            return assertion.effectiveState
        }

        guard currentContext.sourceSignature.bundleRevision == assertion.scope.bundleRevision,
              currentContext.traversalEpoch == assertion.scope.traversalEpoch else {
            return clear(base: base)
        }
        if currentContext.wayId == assertion.scope.originalWayID,
           assertion.scope.originalDirection != .unknown,
           currentContext.travelDirection != .unknown,
           currentContext.travelDirection != assertion.scope.originalDirection {
            return clear(base: base)
        }
        if currentContext.wayId == assertion.scope.lastMatchedWayID {
        } else {
            let currentByID = Dictionary(
                uniqueKeysWithValues: currentContext.routeRelationMemberships.map { ($0.groupID, $0) }
            )
            let shared = assertion.scope.eligibleMemberships.filter { currentByID[$0.groupID] != nil }
            guard currentContext.routeContinuityAvailable,
                  !assertion.scope.eligibleMemberships.isEmpty,
                  !shared.isEmpty else {
                return clear(base: base)
            }
            assertion.scope.eligibleMemberships = shared
        }
        assertion.scope.lastMatchedWayID = currentContext.wayId
        assertion.scope.lastCoordinate = TrafficSignCoordinate(
            latitude: currentContext.latitude,
            longitude: currentContext.longitude
        )
        assertion.scope.gapStartedAt = nil
        assertion.scope.gapStartedCoordinate = nil
        self.assertion = assertion
        lastEffectiveState = assertion.effectiveState
        return assertion.effectiveState
    }

    private mutating func reduce(
        action: TrafficSignStructuralAction,
        base: EffectiveSpeedLimitState,
        conditional: Bool
    ) -> (applied: Bool, value: EffectiveSpeedLimitValue, reason: String) {
        guard !conditional else {
            return action.isSpeedEnd
                ? maskOrPreserveUnsafeEnd(action, reason: "camera_conditional_end_masked")
                : (false, .unknown, "camera_conditional_review_only")
        }
        switch action {
        case .postedMaximum(let value):
            rules.posted = value
            return (true, .numeric(value), "camera_posted_maximum")
        case .zoneStart(let value):
            rules.zone = (value, value)
            rules.posted = nil
            return (true, .numeric(value), "camera_zone_start")
        case .cityEntry(let country):
            guard ["DE", "DEU"].contains(country.uppercased()) else {
                return (false, .unknown, "camera_city_entry_unsupported_country")
            }
            rules.city = .numeric(50)
            rules.posted = nil
            return (true, .numeric(50), "camera_german_city_entry")
        case .pedestrianZoneStart:
            rules.pedestrian = true
            rules.posted = nil
            return (true, .walk, "camera_pedestrian_zone_start")
        case .temporaryMaximum:
            return (false, .unknown, "camera_temporary_review_only")
        case .maximumSpeedEnd(let expected):
            guard let posted = rules.posted else {
                // A maximum-speed end only removes the posted layer. Preserve
                // an independently recognized enclosure when one is known;
                // never resurrect the ordinary bundle/local fallback here.
                if rules.pedestrian {
                    return (true, .walk, "camera_maximum_end_preserved_pedestrian_zone")
                }
                if let zone = rules.zone {
                    return (true, .numeric(zone.value), "camera_maximum_end_preserved_zone")
                }
                if let city = rules.city {
                    return (true, city, "camera_maximum_end_preserved_city")
                }
                if let enclosing = rules.enclosingBase {
                    return (true, enclosing.value, "camera_maximum_end_restored_verified_enclosing")
                }
                return (true, .unknown, "camera_maximum_end_unresolved")
            }
            if let expected, expected != posted {
                // A crossed-out value that contradicts the active camera layer
                // is unresolved evidence, not authority to remove that layer.
                return (false, .numeric(posted), "camera_maximum_end_mismatch_review_only")
            }
            rules.posted = nil
            return resolvedEnclosing(afterEnding: posted, reason: "camera_maximum_end")
        case .allRestrictionsEnd:
            let ended = rules.posted
            rules.posted = nil
            return resolvedEnclosing(afterEnding: ended, reason: "camera_all_restrictions_end")
        case .zoneEnd(let expected):
            guard let zone = rules.zone else {
                rules.posted = nil
                return (true, .unknown, "camera_zone_end_unresolved")
            }
            guard expected == nil || expected == zone.value else {
                // Contradictory crossed-out values are review evidence only;
                // they cannot claim that the currently active zone ended.
                return (false, .numeric(zone.value), "camera_zone_end_mismatch_review_only")
            }
            rules.zone = nil
            rules.posted = nil
            return resolvedEnclosing(afterEnding: zone.value, reason: "camera_zone_end")
        case .cityExit:
            guard rules.city != nil else {
                return (true, .unknown, "camera_city_exit_unresolved")
            }
            rules.city = nil
            rules.posted = nil
            return resolvedEnclosing(afterEnding: 50, reason: "camera_city_exit")
        case .pedestrianZoneEnd:
            guard rules.pedestrian else {
                return (true, .unknown, "camera_pedestrian_zone_end_unresolved")
            }
            rules.pedestrian = false
            rules.posted = nil
            return resolvedEnclosing(afterEnding: nil, reason: "camera_pedestrian_zone_end")
        case .motorwayExit:
            let ended = rules.posted
            rules.posted = nil
            return resolvedEnclosing(afterEnding: ended, reason: "camera_motorway_exit")
        case .motorroadExit:
            let ended = rules.posted
            rules.posted = nil
            return resolvedEnclosing(afterEnding: ended, reason: "camera_motorroad_exit")
        case .nonSpeedRestrictionEnd:
            return (false, currentRuleValue(base: base), "camera_non_speed_end_ignored")
        case .unresolved:
            return (false, currentRuleValue(base: base), "camera_unresolved_review_only")
        }
    }

    private func currentRuleValue(base: EffectiveSpeedLimitState) -> EffectiveSpeedLimitValue {
        if let posted = rules.posted { return .numeric(posted) }
        if rules.pedestrian { return .walk }
        if let zone = rules.zone { return .numeric(zone.value) }
        if let city = rules.city { return city }
        return rules.enclosingBase?.value ?? base.value
    }

    private mutating func maskUnresolvedEnd(
        _ action: TrafficSignStructuralAction,
        reason: String
    ) -> (applied: Bool, value: EffectiveSpeedLimitValue, reason: String) {
        switch action {
        case .maximumSpeedEnd, .allRestrictionsEnd:
            rules.posted = nil
        case .zoneEnd:
            rules.zone = nil
            rules.posted = nil
        case .cityExit:
            rules.city = nil
            rules.posted = nil
        case .pedestrianZoneEnd:
            rules.pedestrian = false
            rules.posted = nil
        case .motorwayExit, .motorroadExit:
            // The road-class exit invalidates the posted/road-class-dependent
            // camera layer even when the exit itself is review-only. Keeping
            // it here would allow a later action to resurrect stale numeric
            // state after the driver-facing value was already masked.
            rules.posted = nil
        default:
            return (false, currentRuleValue(base: .none), reason)
        }
        return (true, .unknown, reason)
    }

    private mutating func maskOrPreserveUnsafeEnd(
        _ action: TrafficSignStructuralAction,
        reason: String
    ) -> (applied: Bool, value: EffectiveSpeedLimitValue, reason: String) {
        if case .maximumSpeedEnd(let expected) = action,
           let expected,
           let posted = rules.posted,
           expected != posted {
            return (false, .numeric(posted), "\(reason)_mismatch_review_only")
        }
        if case .zoneEnd(let expected) = action,
           let expected,
           let zone = rules.zone,
           expected != zone.value {
            // An unsafe/conditional crossed-out value cannot prove that a
            // differently valued active zone ended. Preserve the complete
            // active camera rule stack and retain the mismatch for review.
            return (false, currentRuleValue(base: .none), "\(reason)_mismatch_review_only")
        }
        return maskUnresolvedEnd(action, reason: reason)
    }

    private func resolvedEnclosing(
        afterEnding endedValue: Int?,
        reason: String
    ) -> (applied: Bool, value: EffectiveSpeedLimitValue, reason: String) {
        if let posted = rules.posted { return (true, .numeric(posted), reason) }
        if rules.pedestrian { return (true, .walk, reason) }
        if let zone = rules.zone { return (true, .numeric(zone.value), reason) }
        if let city = rules.city { return (true, city, reason) }
        guard let enclosing = rules.enclosingBase else {
            return (true, .unknown, "\(reason)_unresolved")
        }
        if let endedValue, enclosing.value.speedKmh == endedValue {
            return (true, .unknown, "\(reason)_stale_base_masked")
        }
        return (true, enclosing.value, "\(reason)_restored_enclosing")
    }

    private static func distanceMeters(
        from: TrafficSignCoordinate?,
        to: TrafficSignCoordinate?
    ) -> Double? {
        guard let from, let to else { return nil }
        let earthRadius = 6_371_000.0
        let lat1 = from.latitude * .pi / 180
        let lat2 = to.latitude * .pi / 180
        let deltaLat = (to.latitude - from.latitude) * .pi / 180
        let deltaLon = (to.longitude - from.longitude) * .pi / 180
        let a = sin(deltaLat / 2) * sin(deltaLat / 2)
            + cos(lat1) * cos(lat2) * sin(deltaLon / 2) * sin(deltaLon / 2)
        return earthRadius * 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))
    }
}

private extension TrafficSignStructuralAction {
    var isTemporary: Bool {
        if case .temporaryMaximum = self { return true }
        return false
    }


    var isSpeedEnd: Bool {
        switch self {
        case .zoneEnd, .maximumSpeedEnd, .allRestrictionsEnd, .cityExit,
             .pedestrianZoneEnd, .motorwayExit, .motorroadExit:
            return true
        case .postedMaximum, .zoneStart, .cityEntry, .pedestrianZoneStart,
             .temporaryMaximum, .nonSpeedRestrictionEnd, .unresolved:
            return false
        }
    }
}

struct TrafficSignGenerationToken: Equatable, Sendable {
    let session: UInt64
    let context: UInt64
}

final class TrafficSignWriteGate: @unchecked Sendable {
    private let lock = NSLock()
    private var token = TrafficSignGenerationToken(session: 0, context: 0)
    private var enabled = false

    func update(token: TrafficSignGenerationToken, enabled: Bool) {
        lock.lock()
        self.token = token
        self.enabled = enabled
        lock.unlock()
    }

    func permit(for expected: TrafficSignGenerationToken) -> TrafficSignWritePermit? {
        lock.lock()
        defer { lock.unlock() }
        guard enabled, token == expected else { return nil }
        return TrafficSignWritePermit(token: expected, gate: self)
    }

    fileprivate func consume<T>(
        token expected: TrafficSignGenerationToken,
        _ body: () throws -> T
    ) rethrows -> T? {
        lock.lock()
        defer { lock.unlock() }
        guard enabled, token == expected else { return nil }
        return try body()
    }
}

struct TrafficSignWritePermit: @unchecked Sendable {
    fileprivate let token: TrafficSignGenerationToken
    fileprivate let gate: TrafficSignWriteGate

    func consume<T>(_ body: () throws -> T) rethrows -> T? {
        try gate.consume(token: token, body)
    }
}

extension TrafficSignRuntimeSourceSignature {
    var bundleRevision: String {
        if let range = osmRevision.range(of: "|way:") {
            return String(osmRevision[..<range.lowerBound])
        }
        return osmRevision
    }
}
