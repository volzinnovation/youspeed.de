import Foundation

/// Executable interpretation is separate from immutable collection OCR.
/// A parser match alone never verifies a sign assembly or grants authority.
enum ConditionalOCRInterpretation {
    /// Only positive parent-matched plate evidence withholds a numeric parent.
    /// Missing, failed or deferred auxiliary work does not block recognition.
    struct AuthorityGate {
        private var scope = ""
        private var blocked = Set<String>()
        mutating func observe(parentID: String, primaryClassID: String, speedKmh: Int?, rawText: String?, scope: String, knownPlate: Bool = false) -> Bool {
            select(scope)
            guard let speedKmh, primaryClassID == "maxspeed:\(speedKmh)", !parentID.isEmpty,
                  knownPlate || rawText?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else { return false }
            return blocked.insert(parentID).inserted
        }
        mutating func blocks(_ parentID: String?, scope: String) -> Bool {
            select(scope)
            return parentID.map { blocked.contains($0) } ?? false
        }
        private mutating func select(_ next: String) {
            if scope != next { scope = next; blocked = [] }
        }
    }
    enum Condition: Equatable {
        case informational
        case wet
        case schedule(weekdays: [Int], startMinute: Int, endMinute: Int)
        var ast: [String: Any] {
            switch self {
            case .informational: return ["kind":"true"]
            case .wet: return ["kind":"context","field":"road_surface_wet"]
            case .schedule(let days, let start, let end):
                return ["kind":"schedule","weekdays":days,"windows":[[start,end]],"weekday_anchor":"window_start_date"]
            }
        }
    }
    struct Parsed: Equatable {
        let condition: Condition
        let informationalText: [String]
        let normalizedText: String
        let parserRevision = "de-complete-plate-v1"
        func ruleSet(speedKmh: Int) -> [String: Any] {
            ["version":1,"grammar":"youspeed-osm-speed-1","tags":[[
                "role":"speed","vehicle":"all","direction":0,"priority":1,"conditional":true,"status":"supported",
                "clauses":[["limit":["kind":"numeric","kmh":speedKmh],"condition":condition.ast]]]]]
        }
    }
    enum Verification: String { case candidate, verified, rejected }
    enum Verdict: String { case applicable, inapplicable, unresolved }
    struct Observation {
        let physicalSignID: String
        let parentID: String
        let primaryClassID: String
        let primarySpeedKmh: Int
        let plateIDs: [String]
        let frameID: String
        let rawText: String
        let capturedAt: Date
        let evidenceOriginAt: Date
        let evidenceOriginDistanceM: Double
        let countryCode: String
        let scopeID: String
        let scopeGeneration: UInt64
        let pipelineID: String
        let modelHash: String
        var completeAssembly = false
        var exactAssociation = false
        var qualityAccepted = false
        var sourceEvaluationEnabled: Bool?
        var reviewedExport = false
        var reviewedRuntimeEligible = false
        var verifierID: String?
    }
    struct Record {
        let observation: Observation
        let parsed: Parsed?
        let verification: Verification
        let reason: String
        let supportingFrameIDs: [String]
        let originalEvidenceAt: Date
        let originalEvidenceDistanceM: Double
        func verdict(at: Date, distanceM: Double, scopeID: String, generation: UInt64,
                     clockTrusted: Bool = true, uncertaintySeconds: Double = 0,
                     timeZoneID: String? = "Europe/Berlin", roadSurfaceWet: Bool? = nil) -> Verdict {
            guard verification == .verified, let parsed, scopeID == observation.scopeID,
                  generation == observation.scopeGeneration, at >= originalEvidenceAt,
                  at.timeIntervalSince(originalEvidenceAt) <= 300, distanceM.isFinite,
                  distanceM >= originalEvidenceDistanceM, distanceM - originalEvidenceDistanceM <= 5000 else { return .unresolved }
            switch parsed.condition {
            case .informational: return .applicable
            case .wet: return roadSurfaceWet.map { $0 ? .applicable : .inapplicable } ?? .unresolved
            case .schedule(let days, let start, let end):
                guard clockTrusted, uncertaintySeconds.isFinite, (0...3600).contains(uncertaintySeconds),
                      timeZoneID == "Europe/Berlin", let zone = TimeZone(identifier: "Europe/Berlin") else { return .unresolved }
                var calendar = Calendar(identifier: .gregorian); calendar.timeZone = zone
                func active(_ instant: Date) -> Bool {
                    let minute = calendar.component(.hour, from: instant) * 60 + calendar.component(.minute, from: instant)
                    let inside = start < end ? minute >= start && minute < end : minute >= start || minute < end
                    guard inside else { return false }
                    let anchor = start > end && minute < end ? calendar.date(byAdding: .day, value: -1, to: instant)! : instant
                    return days.isEmpty || days.contains((calendar.component(.weekday, from: anchor) + 5) % 7 + 1)
                }
                let lower = at.addingTimeInterval(-uncertaintySeconds), upper = at.addingTimeInterval(uncertaintySeconds)
                let result = active(lower)
                var instant = lower
                while instant < upper {
                    guard active(instant) == result else { return .unresolved }
                    instant = instant.addingTimeInterval(60)
                }
                guard active(upper) == result else { return .unresolved }
                return result ? .applicable : .inapplicable
            }
        }
    }
    static func parse(_ raw: String) -> Parsed? {
        guard !raw.isEmpty, raw.count <= 4096 else { return nil }
        let normalized = raw.lowercased().replacingOccurrences(of:"–",with:"-").replacingOccurrences(of:"—",with:"-")
            .replacingOccurrences(of:"/",with:" ").split(whereSeparator: { $0.isWhitespace }).joined(separator:" ")
        let info = ["lärmschutz", "schule"]
        if info.contains(normalized) { return .init(condition:.informational,informationalText:[normalized],normalizedText:normalized) }
        if normalized == "bei nässe" { return .init(condition:.wet,informationalText:[],normalizedText:normalized) }
        let pattern = #"^(?:(lärmschutz|schule) )?(?:(mo|di|mi|do|fr|sa|so)(?:-(mo|di|mi|do|fr|sa|so))? )?([0-9]{1,4}(?::[0-9]{2})?)\s*-\s*([0-9]{1,4}(?::[0-9]{2})?)(?:\s*(?:h|uhr))?(?: (lärmschutz|schule))?$"#
        guard let expression=try? NSRegularExpression(pattern:pattern),
              let match=expression.firstMatch(in:normalized,range:NSRange(normalized.startIndex...,in:normalized)) else { return nil }
        func group(_ index:Int) -> String? { Range(match.range(at:index),in:normalized).map { String(normalized[$0]) } }
        func clock(_ value:String?, end:Bool) -> Int? {
            guard let value else { return nil }
            let parts=value.split(separator:":")
            let hour:Int?, minute:Int?
            if parts.count==2 { hour=Int(parts[0]);minute=Int(parts[1]) }
            else if value.count<=2 { hour=Int(value);minute=0 }
            else { hour=Int(value.dropLast(2));minute=Int(value.suffix(2)) }
            guard let hour,let minute,(0...59).contains(minute), hour>=0,
                  hour<24 || (end && hour==24 && minute==0) else { return nil }
            return hour*60+minute
        }
        guard let start=clock(group(4),end:false),let end=clock(group(5),end:true),start != end else { return nil }
        let names=["mo","di","mi","do","fr","sa","so"]
        var weekdays=[Int]()
        if let first=group(2),let lower=names.firstIndex(of:first) {
            let upper=group(3).flatMap { names.firstIndex(of:$0) } ?? lower
            guard lower<=upper else { return nil };weekdays=Array((lower+1)...(upper+1))
        }
        return .init(condition:.schedule(weekdays:weekdays,startMinute:start,endMinute:end),
            informationalText:[group(1),group(6)].compactMap{$0},normalizedText:normalized)
    }
    struct Tracker {
        private var first: Observation?
        private var interpretation: Parsed?
        mutating func reset() { first=nil;interpretation=nil }
        mutating func consume(_ observation: Observation) -> Record {
            let parsed=ConditionalOCRInterpretation.parse(observation.rawText)
            func record(_ verification:Verification,_ reason:String,_ frames:[String]=[]) -> Record {
                let origin = first?.physicalSignID == observation.physicalSignID ? first! : observation
                return .init(observation:observation,parsed:parsed,verification:verification,reason:reason,supportingFrameIDs:frames,
                    originalEvidenceAt:origin.evidenceOriginAt,originalEvidenceDistanceM:origin.evidenceOriginDistanceM)
            }
            guard ["DE","DEU"].contains(observation.countryCode.uppercased()),
                  observation.primaryClassID == "maxspeed:\(observation.primarySpeedKmh)",
                  (1...300).contains(observation.primarySpeedKmh), !observation.frameID.isEmpty,
                  !observation.scopeID.isEmpty,!observation.modelHash.isEmpty,!observation.pipelineID.isEmpty,
                  !observation.plateIDs.isEmpty,observation.plateIDs.allSatisfy({!$0.isEmpty}),
                  observation.evidenceOriginAt <= observation.capturedAt,observation.evidenceOriginDistanceM.isFinite else {
                reset();return record(.rejected,"invalid_primary_or_provenance")
            }
            if observation.sourceEvaluationEnabled == false && !(observation.reviewedExport && observation.reviewedRuntimeEligible && observation.verifierID?.isEmpty == false) {
                reset();return record(.rejected,"source_evaluation_disabled")
            }
            guard let parsed else { reset();return record(.rejected,"unsupported_or_residual_text") }
            guard observation.completeAssembly,observation.exactAssociation,observation.qualityAccepted else {
                reset();return record(.candidate,"assembly_not_verified")
            }
            if let prior=first, prior.physicalSignID == observation.physicalSignID,prior.scopeID == observation.scopeID,
               prior.scopeGeneration == observation.scopeGeneration,prior.parentID == observation.parentID,
               prior.primarySpeedKmh == observation.primarySpeedKmh,prior.plateIDs.sorted() == observation.plateIDs.sorted(),
               prior.pipelineID == observation.pipelineID,prior.modelHash == observation.modelHash,interpretation == parsed {
                let span=observation.capturedAt.timeIntervalSince(prior.capturedAt)
                let spanMillis = (span * 1000).rounded()
                if prior.frameID != observation.frameID,spanMillis>=100,spanMillis<=2000 {
                    return record(.verified,"two_distinct_complete_frames",[prior.frameID,observation.frameID])
                }
                if span>=0,spanMillis<100 { return record(.candidate,"distinct_frame_agreement_pending",[prior.frameID]) }
            }
            first=observation;interpretation=parsed
            return record(.candidate,"distinct_frame_agreement_pending",[observation.frameID])
        }
    }
}

/// Live callers supply pixel evidence, never assembly-verification flags.
extension ConditionalOCRInterpretation {
    enum PixelAssessment: Equatable {
        case plain
        case conditional(Parsed)
        case unresolved(String)
    }
    static func assess(_ annotation: TrafficSignSupplementaryOCRAnnotation) -> PixelAssessment {
        guard let evidence = annotation.assemblyEvidence,
              evidence.sourceWidth > 0, evidence.sourceHeight > 0,
              evidence.sourceFrameID == annotation.frameID, evidence.capturedAt == annotation.sourceObservedAt,
              evidence.physicalSignID == annotation.physicalSignID, evidence.primaryBox == annotation.primaryBoundingBox,
              annotation.primaryBoundingBox.isValid, !annotation.frameID.isEmpty else { return .unresolved("missing_pixel_provenance") }
        let c = evidence.contextRect, w = Double(evidence.sourceWidth), h = Double(evidence.sourceHeight)
        let p = annotation.primaryBoundingBox
        let actual = evidence.nativeContentRect ?? .init(x:0,y:0,width:evidence.sourceWidth,height:evidence.sourceHeight)
        let px = Int(floor(p.x*w)), py = Int(floor(p.y*h))
        let pw = Int(ceil(p.width*w)), ph = Int(ceil(p.height*h))
        guard actual.x >= 0, actual.y >= 0, actual.x+actual.width <= evidence.sourceWidth,
              actual.y+actual.height <= evidence.sourceHeight,
              px >= actual.x+2, py >= actual.y+2, px+pw <= actual.x+actual.width-2,
              py+ph <= actual.y+actual.height-2,
              c.x >= actual.x, c.y >= actual.y, c.x+c.width <= actual.x+actual.width,
              c.y+c.height <= actual.y+actual.height-2 else { return .unresolved("padded_or_clipped_native_context") }
        guard px >= 2, py >= 2, px+pw <= evidence.sourceWidth-2, py+ph <= evidence.sourceHeight-2,
              c.y+c.height <= evidence.sourceHeight-2,
              c.width >= 48, c.height >= 64, c.x >= 0, c.y >= 0,
              c.x + c.width <= evidence.sourceWidth, c.y + c.height <= evidence.sourceHeight,
              Double(c.x) <= p.x*w + 1, Double(c.y) <= p.y*h + 1,
              Double(c.x+c.width) >= (p.x+p.width)*w - 1,
              Double(c.y+c.height) >= (p.y+2*p.height)*h - 1 else { return .unresolved("clipped_context") }
        // The whole lower context must belong uniquely to this primary. A
        // second primary inside it may carry its own plates and cannot be merged.
        let lower = TrafficSignNormalizedRect(x: Double(c.x)/w, y: p.y+p.height,
            width: Double(c.width)/w, height: max(0, Double(c.y+c.height)/h-p.y-p.height))
        guard !evidence.otherPrimaryBoxes.contains(where: { other in
            other.isValid && min(other.x+other.width,lower.x+lower.width) > max(other.x,lower.x)
                && min(other.y+other.height,lower.y+lower.height) > max(other.y,lower.y)
        }) else { return .unresolved("ambiguous_parent") }
        if evidence.scan.status == .plain {
            let quiet = evidence.scan.decision == "quiet_lower_context"
                && evidence.scan.lowerMinimum.map({ $0 >= 40 }) == true
                && evidence.scan.lowerMinimum.flatMap({ low in evidence.scan.lowerMaximum.map { $0 >= low && $0-low <= 24 } }) == true
            let background = evidence.scan.decision == "natural_background_without_panel" && evidence.scan.backgroundVerified
                && c.width >= 80 && c.height >= 128
            return evidence.scan.components.isEmpty && (quiet || background) ? .plain : .unresolved("unproven_plain")
        }
        guard evidence.scan.status == .complete, !evidence.scan.components.isEmpty,
              evidence.scan.components.count <= 3, let union = evidence.scan.union,
              annotation.readStatus == .read, evidence.qualityDecision == "accepted",
              let raw = annotation.rawText, let parsed = parse(raw),
              evidence.passes.count >= 2,
              Set(evidence.passes.map(\.scale)).isSuperset(of: [1,2]),
              evidence.passes.allSatisfy({ $0.confidence.isFinite && $0.confidence >= 0.25 && !$0.uncoveredInk && parse($0.text) == parsed }),
              TrafficSignOCRQuality.decision(passes: evidence.passes, nativeWidth: union.width) == "accepted" else {
            return .unresolved("unread_or_unsupported_complete_assembly")
        }
        for plate in evidence.scan.components {
            guard plate.width >= 48, plate.height >= 32, plate.x >= 2, plate.y >= c.height/2,
                  plate.x+plate.width <= c.width-2, plate.y+plate.height <= c.height-2 else { return .unresolved("clipped_or_tiny_plate") }
            let box = TrafficSignNormalizedRect(x: Double(c.x+plate.x)/w, y: Double(c.y+plate.y)/h,
                width: Double(plate.width)/w, height: Double(plate.height)/h)
            func association(_ primary: TrafficSignNormalizedRect) -> Double? {
                let gap = box.y - primary.y - primary.height
                let overlap = min(box.x+box.width,primary.x+primary.width)-max(box.x,primary.x)
                guard gap >= -0.03, gap <= 0.18, overlap/max(0.000001,min(box.width,primary.width)) >= 0.25 else { return nil }
                return max(0,gap)+abs(box.x+box.width/2-primary.x-primary.width/2)
            }
            guard let selected = association(p), !evidence.otherPrimaryBoxes.contains(where: { other in
                association(other).map { $0 <= selected + 0.01 } ?? false
            }) else { return .unresolved("ambiguous_plate_association") }
        }
        return .conditional(parsed)
    }

    struct LiveResult {
        let record: Record?
        let plain: Bool
        let verification: Verification
        let reason: String
    }
    struct LiveTracker {
        private var tracker = Tracker()
        private var firstPlain: (frame: String, time: Date)?
        private var restricted = false
        private var priorAssessment: PixelAssessment?
        private var binding: String?
        mutating func observeKnownPlate() { restricted = true; firstPlain = nil }
        mutating func consume(_ annotation: TrafficSignSupplementaryOCRAnnotation, originAt: Date,
                              originDistanceM: Double, country: String, scopeID: String,
                              generation: UInt64, pipelineID: String, modelHash: String) -> LiveResult {
            let currentBinding = [annotation.physicalSignID, annotation.primaryClassID, String(annotation.primarySpeedKmh ?? 0), scopeID, String(generation), pipelineID, modelHash].joined(separator: "|")
            if binding != currentBinding {
                tracker.reset(); firstPlain = nil; restricted = false; priorAssessment = nil; binding = currentBinding
            }
            let assessment = assess(annotation)
            if case .plain = assessment {
                guard !restricted else { return .init(record:nil,plain:false,verification:.candidate,reason:"restricted_parent_cannot_become_bare") }
                if let first = firstPlain {
                    let elapsed = annotation.sourceObservedAt.timeIntervalSince(first.time)
                    if first.frame != annotation.frameID && elapsed >= 0.1 && elapsed <= 2 {
                        return .init(record:nil,plain:true,verification:.verified,reason:"two_distinct_plain_inspections")
                    }
                    if elapsed >= 0 && elapsed < 0.1 { return .init(record:nil,plain:false,verification:.candidate,reason:"distinct_plain_frame_pending") }
                }
                firstPlain = (annotation.frameID,annotation.sourceObservedAt)
                return .init(record:nil,plain:false,verification:.candidate,reason:"distinct_plain_frame_pending")
            }
            // A genuinely observed panel cannot later disappear into a bare
            // parent. An unresolved far/busy context merely remains pending.
            if annotation.assemblyEvidence?.scan.components.isEmpty == false { restricted = true }
            if case .conditional = assessment { restricted = true }
            firstPlain = nil
            guard case .conditional = assessment else {
                tracker.reset(); priorAssessment = assessment
                return .init(record:nil,plain:false,verification:.candidate,reason:"pixel_assembly_unresolved")
            }
            if let priorAssessment, priorAssessment != assessment { tracker.reset() }
            priorAssessment = assessment
            let count = annotation.assemblyEvidence?.scan.components.count ?? 0
            // These facts are derived above from actual bounded pixels, source
            // frame, all panel geometry and full native/interpolated OCR reads.
            let observation = Observation(physicalSignID: annotation.physicalSignID, parentID: annotation.physicalSignID,
                primaryClassID: annotation.primaryClassID, primarySpeedKmh: annotation.primarySpeedKmh ?? 0,
                plateIDs: (0..<count).map { annotation.physicalSignID+":plate:\($0)" }, frameID: annotation.frameID,
                rawText: annotation.rawText ?? "", capturedAt: annotation.sourceObservedAt,
                evidenceOriginAt: originAt, evidenceOriginDistanceM: originDistanceM, countryCode: country,
                scopeID: scopeID, scopeGeneration: generation, pipelineID: pipelineID, modelHash: modelHash,
                completeAssembly: true, exactAssociation: true, qualityAccepted: true)
            let result = tracker.consume(observation)
            return .init(record:result,plain:false,verification:result.verification,reason:result.reason)
        }
    }
}

// Runtime interpretation stays outside the portable collection DTO.
extension SupplementaryOCRAnnotation {
    /// Candidate only: this immutable DTO has no assembly-verification authority.
    var conditionalInterpretationCandidate: ConditionalOCRInterpretation.Parsed? {
        guard status == .read, let primarySpeedKmh, primaryClassID == "maxspeed:\(primarySpeedKmh)", let rawText else { return nil }
        return ConditionalOCRInterpretation.parse(rawText)
    }
}
