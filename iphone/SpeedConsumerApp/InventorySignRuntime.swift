import Foundation
import SQLite3

/// The BW government inventory must never become a nationwide fallback merely
/// because its optional tables were copied into another region's database.
enum InventorySignSourceScope {
    static func allowsMobiData(countryCode: String?, dbPath: String, sourceInputPBF: String? = nil) -> Bool {
        if let countryCode, !["DE", "DEU"].contains(countryCode.uppercased()) { return false }
        let identity = (sourceInputPBF ?? dbPath).lowercased().replacingOccurrences(of: "_", with: "-")
        return identity.contains("baden-wuerttemberg") || identity.contains("baden-württemberg")
    }
}

/// A passed town boundary establishes locality until another physical town
/// boundary, drive end or country change. Road tags are not a new passage.
struct CameraTownLocalityLatch {
    private(set) var insideCity: Bool?
    private(set) var observedAt: Date?
    private var country: String?
    static let source = "settlement:camera_town:high"
    mutating func reset() { self = Self() }
    mutating func observe(insideCity: Bool, at: Date, countryCode: String?) {
        guard at.timeIntervalSince1970.isFinite, observedAt.map({ at >= $0 }) ?? true else { return }
        self.insideCity = insideCity; observedAt = at
        country = countryCode.map { RoadSpeedDefaults.country($0) }
    }
    mutating func selectCountry(_ countryCode: String?) {
        guard let countryCode, let country, RoadSpeedDefaults.country(countryCode) != country else { return }
        reset()
    }
    /// A later actual station opens a new legal context; stale competing map
    /// passages must not undo a newer visual boundary.
    mutating func supersedeByPhysicalBoundary(at: Date) -> Bool {
        guard let observedAt else { return true }
        guard at > observedAt else { return false }
        reset(); return true
    }
    func applying(to original: SpeedLimitResult, countryCode: String?, region: String? = nil) -> SpeedLimitResult {
        guard let insideCity else { return original }
        var result = original
        result.insideCity = insideCity; result.citySource = Self.source
        let exact = ["EXPLICIT_TAG", "EXPLICIT_UNLIMITED_TAG", "DIRECTIONAL_UNRESOLVED", "INVENTORY_SIGN"].contains(result.speedSource ?? "")
            || result.inventorySigns?.activeRule?.speedKmh != nil || result.conditionalRuleContext != nil
        if result.wayID != nil, !exact {
            let unlimited = !insideCity && result.highway == "motorway" && RoadSpeedDefaults.country(countryCode) == "DE"
            result.speedLimitKmh = unlimited ? nil : RoadSpeedDefaults.speedKmh(country: countryCode,
                region: region, highway: result.highway, insideCity: insideCity)
            result.isUnlimitedSpeedLimit = unlimited ? true : nil
            result.speedSource = "HIGHWAY_CLASS"
            result.bundleSpeedProvenance = .init(kind: .roadDefault, wayID: result.wayID)
        }
        return result
    }
}

enum TSRCaptureActivity: String, Sendable {
    case off, running, unavailable
    case pausedNight = "paused_night", pausedLocation = "paused_location", pausedBackground = "paused_background"
    case waitingDrive = "waiting_drive", waitingRecording = "waiting_recording", loadingModel = "loading_model"
    var localizationKey: String { "capture.tsr.activity." + rawValue }
    static func resolve(selected: Bool, daylightAllowed: Bool, locationKnown: Bool, applicationActive: Bool,
                        driving: Bool, modelReady: Bool, recognitionActive: Bool,
                        independent: Bool, driveRecording: Bool) -> Self {
        guard selected else { return .off }
        guard locationKnown else { return .pausedLocation }
        guard daylightAllowed else { return .pausedNight }
        guard applicationActive else { return .pausedBackground }
        guard driving else { return .waitingDrive }
        guard modelReady else { return .loadingModel }
        if recognitionActive { return .running }
        if !independent && !driveRecording { return .waitingRecording }
        return .unavailable
    }
}

/// Optional v1 bundle capability. This evidence never changes the protected policy.
struct InventoryTrafficSign: Codable, Equatable, Sendable {
    let signID: String
    let sourceID: String
    let recordKey: String
    let snapshotSHA256: String
    let code: String
    let kind: String
    let numericValue: Double?
    let unit: String?
    let parameterStatus: String
    let latitude: Double
    let longitude: Double
    let radiusM: Double
    let pictogramCode: String?
    let pictogramPath: String?
    let modelClasses: [String]
    let distanceM: Double
    var associatedWayID: String? = nil
    var associatedDirection: Int? = nil
    var associationStatus: String? = nil
    var associatedHeadingDeg: Double? = nil
    var confirmationSemanticsVerified: Bool {
        ["not_applicable","parsed_source_value","missing_value"].contains(parameterStatus)
    }
    var requiresDirectedEvidence: Bool { ["speed_limit","speed_limit_end","settlement_boundary"].contains(kind) || code == "DE:282" }
    func secondaryFaceStatus(heading: Double?, headingAccuracy: Double?) -> String {
        guard !requiresDirectedEvidence else { return "directed_target" }
        guard associationStatus == "accepted", let source=associatedHeadingDeg,
              source.isFinite, (0..<360).contains(source), let direction=associatedDirection, (direction == 1 || direction == -1),
              let heading, heading.isFinite, (0..<360).contains(heading),
              let headingAccuracy, headingAccuracy.isFinite, (0...35).contains(headingAccuracy) else { return "face_unknown" }
        let facing=(source + (direction == -1 ? 180 : 0)).truncatingRemainder(dividingBy:360)
        return InventorySignBundle.angle(heading,facing) > 90 ? "known_opposite_face" : "face_compatible"
    }
    func targetMatches(way: String?, direction: Int?, heading: Double? = nil, headingAccuracy: Double? = nil) -> Bool {
        if requiresDirectedEvidence {
            return associationStatus == "accepted" && associatedWayID != nil
                && associatedWayID == way && associatedDirection != nil && associatedDirection == direction
        }
        return secondaryFaceStatus(heading:heading,headingAccuracy:headingAccuracy) != "known_opposite_face"
    }
}

struct InventoryTrafficRule: Codable, Equatable, Sendable {
    let ruleID: String
    let signID: String
    let code: String
    let direction: Int
    let stationM: Double
    let startM: Double
    let endM: Double
    let speedKmh: Int?
    let insideCity: Bool?
    var distanceM: Double? = nil
    var radiusM: Double = 30
    var expectedEndSpeedKmh: Int? = nil
    var sourceLatitude: Double? = nil
    var sourceLongitude: Double? = nil
    var sourceID: String? = nil
    var snapshotSHA256: String? = nil
    var isBoundary: Bool { code == "DE:310" || code == "DE:311" }
    var isCancellation: Bool { code == "DE:278" || code.hasPrefix("DE:278-") || code == "DE:282" }
    func provenance(wayID: String?) -> BundleSpeedProvenance {
        .init(kind: isBoundary ? .inventoryTownContext : isCancellation ? .inventoryResetContext : .inventorySign,
            sourceID: sourceID, signID: signID, ruleID: ruleID == signID ? nil : ruleID, signCode: code,
            snapshotSHA256: snapshotSHA256, wayID: wayID, direction: direction)
    }
}

/// A geofence admits a new card; leaving it does not revoke that display.
/// Encounter/camera/capture eligibility remains in the separate live runtime.
struct InventorySecondaryDisplaySelection {
    private(set) var sign: InventoryTrafficSign?
    private(set) var triggeredAt: Date?
    private var lastCandidateID: String?
    private var newestPresentationAt=Date.distantPast
    mutating func consume(_ eligible: [InventoryTrafficSign], at: Date = Date()) -> Bool {
        guard at.timeIntervalSince1970.isFinite, at >= newestPresentationAt else { return false }
        let candidate = eligible.first { $0.kind != "speed_limit" }
        defer { lastCandidateID = candidate?.signID }
        guard let candidate, candidate.signID != lastCandidateID else { return false }
        let changed = sign?.signID != candidate.signID
        sign = candidate
        triggeredAt = at
        newestPresentationAt=at
        return changed
    }
    @discardableResult
    mutating func replacedByCamera(at: Date = Date()) -> Bool {
        guard at >= newestPresentationAt else { return false }
        sign = nil; triggeredAt = nil; newestPresentationAt=at
        return true
    }
    mutating func invalidateOppositeFace(signID: String, at: Date) -> Bool {
        guard sign?.signID == signID, at >= newestPresentationAt else { return false }
        sign=nil;triggeredAt=nil;newestPresentationAt=at
        return true
    }
    mutating func reset() { sign = nil; triggeredAt = nil; lastCandidateID = nil; newestPresentationAt = .distantPast }
}

struct SignUIPresentationDescriptor: Equatable, Sendable {
    let surface: String
    let itemID: String
    let sourceID: String
    let identityKind: String
    var signID: String? = nil
    var signCode: String? = nil
    var classID: String? = nil
    var value: String? = nil
    var triggerAt: Date? = nil
    var provenance: BundleSpeedProvenance? = nil
    var bundleSHA256: String? = nil
    var bundleVersion: String? = nil
    var identity: String { surface + "|" + sourceID + "|" + itemID + "|" + (bundleSHA256 ?? bundleVersion ?? "") }
}

/// Counts visible SwiftUI presentation episodes, never compositor/camera proof.
struct SignUIPresentationTracker {
    struct Event: Sendable {
        let phase: String
        let episodeID: String
        let descriptor: SignUIPresentationDescriptor
        let at: Date
        let startedAt: Date
        let reason: String
        let screenMounted: Bool
        let applicationActive: Bool
        var durationMs: Double { max(0,at.timeIntervalSince(startedAt)*1000) }
        var fields: [String:Any] {
            var result:[String:Any] = ["schema_version":1,"event_id":UUID().uuidString,
                "episode_id":episodeID,"phase":phase,"surface":descriptor.surface,
                "item_id":descriptor.itemID,"source_id":descriptor.sourceID,"identity_kind":descriptor.identityKind,
                "sign_id":descriptor.signID as Any? ?? NSNull(),"sign_code":descriptor.signCode as Any? ?? NSNull(),
                "class_id":descriptor.classID as Any? ?? NSNull(),"value":descriptor.value as Any? ?? NSNull(),
                "at":at.timeIntervalSince1970,"started_at":startedAt.timeIntervalSince1970,
                "duration_ms":durationMs,"reason":reason,"screen_mounted":screenMounted,
                "application_active":applicationActive,"visible":phase == "presented",
                "trigger_fix_at":descriptor.triggerAt?.timeIntervalSince1970 as Any? ?? NSNull(),
                "bundle_sha256":descriptor.bundleSHA256 as Any? ?? NSNull(),
                "bundle_version":descriptor.bundleVersion as Any? ?? NSNull(),
                "paint_observed":false,"camera_confirmation":false]
            if let provenance=descriptor.provenance,
               let data=try? JSONEncoder().encode(provenance),
               let object=try? JSONSerialization.jsonObject(with:data) { result["bundle_speed_provenance"]=object }
            return result
        }
    }
    private var current: (descriptor:SignUIPresentationDescriptor,id:String,startedAt:Date)?
    mutating func update(_ descriptor: SignUIPresentationDescriptor?, visible: Bool,
                         screenMounted: Bool, applicationActive: Bool, at: Date, reason: String) -> [Event] {
        let next=visible && screenMounted && applicationActive ? descriptor : nil
        if current?.descriptor.identity == next?.identity { return [] }
        var events:[Event]=[]
        if let current {
            events.append(.init(phase:"ended",episodeID:current.id,descriptor:current.descriptor,at:at,
                startedAt:current.startedAt,reason:reason,screenMounted:screenMounted,applicationActive:applicationActive))
        }
        current=nil
        if let next {
            let id=UUID().uuidString
            current=(next,id,at)
            events.append(.init(phase:"presented",episodeID:id,descriptor:next,at:at,startedAt:at,
                reason:reason,screenMounted:screenMounted,applicationActive:applicationActive))
        }
        return events
    }
}

struct InventorySignLookup: Codable, Equatable, Sendable {
    let signs: [InventoryTrafficSign]
    let activeRule: InventoryTrafficRule?
    let wayID: String?
    let direction: Int?
    let chainageM: Double?
    var boundaries: [InventoryTrafficRule] = []
}

struct InventorySignRoadOffer: Equatable {
    let speedKmh: Int?
    let unlimited: Bool
    static func resolve(_ rule: InventoryTrafficRule, country: String?, highway: String?, settlementInsideCity: Bool?) -> Self {
        if let posted=rule.speedKmh { return .init(speedKmh:posted,unlimited:false) }
        let inside=rule.insideCity ?? settlementInsideCity
        // A new settlement epoch must not re-admit the old way's posted tag.
        let speed=RoadSpeedDefaults.speedKmh(country:country,region:nil,
            highway:inside == true ? nil : highway,insideCity:inside)
        let unlimited=inside == false && RoadSpeedDefaults.country(country) == "DE" && highway == "motorway"
        return .init(speedKmh:speed,unlimited:unlimited)
    }
}

enum InventorySignBundle {
    private static let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    private static func string(_ s: OpaquePointer, _ i: Int32) -> String? {
        sqlite3_column_text(s, i).map { String(cString: $0) }
    }
    private static func number(_ s: OpaquePointer, _ i: Int32) -> Double? {
        sqlite3_column_type(s, i) == SQLITE_NULL ? nil : sqlite3_column_double(s, i)
    }
    private static func hasRequiredColumns(_ db:OpaquePointer) -> Bool {
        let required:[String:Set<String>]=[
            "traffic_sign_runtime":["sign_id","source_id","record_key","snapshot_sha256","sign_code","normalized_code","kind","numeric_value","unit","parameter_status","lon","lat","orientation_deg","display_radius_m","pictogram_code","pictogram_path","model_classes_json"],
            "traffic_sign_way_rule":["rule_id","sign_id","way_id","direction","start_chainage_m","end_chainage_m","station_chainage_m","local_heading_deg","speed_kmh","inside_city","association_status","lane_scope"],
            "traffic_sign_association":["sign_id","status","way_id","direction","station_chainage_m","local_heading_deg","confidence","evidence_json"]]
        for (table,columns) in required {
            var statement:OpaquePointer?
            guard sqlite3_prepare_v2(db,"PRAGMA table_info("+table+")",-1,&statement,nil) == SQLITE_OK,let q=statement else {
                if let statement { sqlite3_finalize(statement) };return false
            }
            var found=Set<String>()
            while sqlite3_step(q) == SQLITE_ROW { if let name=string(q,1) { found.insert(name) } }
            sqlite3_finalize(q)
            guard columns.isSubset(of:found) else { return false }
        }
        return true
    }
    static func distance(_ a: Double, _ b: Double, _ c: Double, _ d: Double) -> Double {
        let p = Double.pi / 180, x = sin((c-a)*p/2), y = sin((d-b)*p/2)
        return 12_742_017.6 * asin(min(1, sqrt(x*x + cos(a*p)*cos(c*p)*y*y)))
    }
    static func angle(_ a: Double, _ b: Double) -> Double {
        abs((a-b+540).truncatingRemainder(dividingBy: 360)-180)
    }
    static func projection(lat: Double, lon: Double, points: [(Double, Double)]) -> (chainage: Double, heading: Double, distance: Double)? {
        guard lat.isFinite, lon.isFinite, abs(lat) < 85, abs(lon) <= 180, points.count >= 2 else { return nil }
        let sy = Double.pi / 180 * 6_371_008.8, sx = sy * cos(lat * .pi / 180)
        var best: (Double, Double, Double)?, chainage = 0.0
        for (a,b) in zip(points, points.dropFirst()) {
            guard a.0.isFinite, a.1.isFinite, b.0.isFinite, b.1.isFinite else { continue }
            let ax = (a.1-lon)*sx, ay = (a.0-lat)*sy, dx = (b.1-a.1)*sx, dy = (b.0-a.0)*sy
            let length = hypot(dx, dy)
            guard length > 0 else { continue }
            let t = max(0, min(1, -(ax*dx+ay*dy)/(length*length)))
            let d = hypot(ax+t*dx, ay+t*dy)
            let sourceLength=distance(a.0,a.1,b.0,b.1)*(6_371_000.0/6_371_008.8)
            if best == nil || d < best!.2 { best = (chainage+t*sourceLength, (atan2(dx,dy)*180 / .pi+360).truncatingRemainder(dividingBy: 360), d) }
            chainage += sourceLength
        }
        return best.map { ($0.0, $0.1, $0.2) }
    }

    /// Unknown/absent capabilities fail closed, keeping old and other-region bundles unchanged.
    static func lookup(db: OpaquePointer, lat: Double, lon: Double, wayID: String?, points: [(Double, Double)],
                       heading: Double?, headingAccuracy: Double?, accuracy: Double, matchStable: Bool = true,
                       allowMobiData: Bool = true) -> InventorySignLookup? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, "SELECT value FROM traffic_sign_capability WHERE key='version'", -1, &statement, nil) == SQLITE_OK,
              let cap = statement else { return nil }
        let supported = sqlite3_step(cap) == SQLITE_ROW && string(cap,0) == "1"
        sqlite3_finalize(cap)
        guard supported, hasRequiredColumns(db), lat.isFinite, lon.isFinite, (-85..<85).contains(lat), (-180...180).contains(lon) else { return nil }
        let usable = accuracy.isFinite && (0...25).contains(accuracy)
        let p = usable ? projection(lat: lat, lon: lon, points: points) : nil
        let direction: Int?
        if let p, p.distance <= 25, let heading, heading.isFinite, (0..<360).contains(heading),
           let headingAccuracy, headingAccuracy.isFinite, (0...35).contains(headingAccuracy) {
            direction = angle(heading,p.heading) <= 35 ? 1 : angle(heading,p.heading+180) <= 35 ? -1 : nil
        } else { direction = nil }
        var active: [InventoryTrafficRule] = []
        if matchStable, let wayID, let direction, let p {
            let sql = """
                SELECT r.rule_id,r.sign_id,s.sign_code,r.direction,r.station_chainage_m,
                       r.start_chainage_m,r.end_chainage_m,r.speed_kmh,r.inside_city,s.numeric_value,s.source_id,s.snapshot_sha256
                FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s ON s.sign_id=r.sign_id
                WHERE r.way_id=? AND r.direction=? AND r.association_status='accepted'
                  \(allowMobiData ? "" : "AND s.source_id <> 'mobidata-bw-vzk'")
                  AND r.lane_scope='all' AND ((r.direction=1 AND r.start_chainage_m<=? AND r.end_chainage_m>?)
                      OR (r.direction=-1 AND r.start_chainage_m<? AND r.end_chainage_m>=?))
                ORDER BY r.start_chainage_m,r.rule_id
                """
            statement = nil
            if sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let q = statement {
                sqlite3_bind_text(q,1,wayID,-1,transient); sqlite3_bind_int(q,2,Int32(direction))
                for i in 3...6 { sqlite3_bind_double(q,Int32(i),p.chainage) }
                while sqlite3_step(q) == SQLITE_ROW {
                    guard let id=string(q,0),let sign=string(q,1),let code=string(q,2) else { continue }
                    active.append(.init(ruleID:id,signID:sign,code:code,direction:Int(sqlite3_column_int(q,3)),stationM:sqlite3_column_double(q,4),startM:sqlite3_column_double(q,5),endM:sqlite3_column_double(q,6),speedKmh:number(q,7).flatMap { $0.isFinite && $0 > 0 && $0 <= 300 && $0.rounded() == $0 ? Int($0) : nil },insideCity:number(q,8).flatMap { $0 == 0 ? false : $0 == 1 ? true : nil },expectedEndSpeedKmh:number(q,9).flatMap { $0.isFinite && $0 > 0 && $0 <= 300 && $0.rounded() == $0 ? Int($0) : nil },sourceID:string(q,10),snapshotSHA256:string(q,11)))
                }
                sqlite3_finalize(q)
            } else if let statement { sqlite3_finalize(statement) }
        }
        // Multiple different overlapping offers cannot establish a unique rule.
        let selected = active.count == 1 ? active.first : nil
        var signs: [InventoryTrafficSign] = []
        if usable {
            let dy = 30 / 111_195.08, dx = dy / cos(lat * .pi / 180)
            let sql = """
                SELECT s.sign_id,s.source_id,s.record_key,s.snapshot_sha256,s.sign_code,s.kind,s.numeric_value,s.unit,
                       s.parameter_status,s.lat,s.lon,s.display_radius_m,s.pictogram_code,s.pictogram_path,s.model_classes_json,
                       a.way_id,a.direction,a.status,a.local_heading_deg
                FROM traffic_sign_runtime s LEFT JOIN traffic_sign_association a ON a.sign_id=s.sign_id
                WHERE s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?
                  \(allowMobiData ? "" : "AND s.source_id <> 'mobidata-bw-vzk'")
                ORDER BY s.sign_id LIMIT 256
                """
            statement = nil
            if sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK, let q = statement {
                for (i,value) in [lat-dy,lat+dy,lon-dx,lon+dx].enumerated() { sqlite3_bind_double(q,Int32(i+1),value) }
                while sqlite3_step(q) == SQLITE_ROW {
                    let a=sqlite3_column_double(q,9), b=sqlite3_column_double(q,10), radius=sqlite3_column_double(q,11)
                    let d=distance(lat,lon,a,b)
                    guard d <= radius, radius == 10 || radius == 30, let id=string(q,0), let code=string(q,4) else { continue }
                    let classes=(string(q,14).flatMap { $0.data(using:.utf8) }.flatMap { try? JSONDecoder().decode([String].self,from:$0) }) ?? []
                    signs.append(.init(signID:id,sourceID:string(q,1) ?? "",recordKey:string(q,2) ?? "",snapshotSHA256:string(q,3) ?? "",code:code,kind:string(q,5) ?? "secondary",numericValue:number(q,6),unit:string(q,7),parameterStatus:string(q,8) ?? "unknown",latitude:a,longitude:b,radiusM:radius,pictogramCode:string(q,12),pictogramPath:string(q,13),modelClasses:classes,distanceM:d,associatedWayID:string(q,15),associatedDirection:number(q,16).map(Int.init),associationStatus:string(q,17),associatedHeadingDeg:number(q,18)))
                }
                sqlite3_finalize(q)
            } else if let statement { sqlite3_finalize(statement) }
        }
        var boundaries: [InventoryTrafficRule] = []
        if matchStable, let wayID, let direction {
            let sql = """
                SELECT s.sign_id,s.sign_code,a.station_chainage_m,s.lat,s.lon,s.display_radius_m,s.numeric_value,s.source_id,s.snapshot_sha256
                FROM traffic_sign_association a JOIN traffic_sign_runtime s ON s.sign_id=a.sign_id
                WHERE a.status='accepted' AND a.way_id=? AND a.direction=? AND (s.kind IN ('settlement_boundary','speed_limit_end') OR s.sign_code='DE:282')
                  \(allowMobiData ? "" : "AND s.source_id <> 'mobidata-bw-vzk'")
                """
            statement = nil
            if sqlite3_prepare_v2(db,sql,-1,&statement,nil) == SQLITE_OK, let q=statement {
                sqlite3_bind_text(q,1,wayID,-1,transient); sqlite3_bind_int(q,2,Int32(direction))
                while sqlite3_step(q) == SQLITE_ROW {
                    guard let id=string(q,0), let code=string(q,1), (["DE:310","DE:311","DE:278","DE:282"].contains(code) || code.hasPrefix("DE:278-")) else { continue }
                    let station=sqlite3_column_double(q,2)
                    boundaries.append(.init(ruleID:id,signID:id,code:code,direction:direction,stationM:station,
                        startM:station,endM:station,speedKmh:nil,insideCity:code == "DE:310" ? true : code == "DE:311" ? false : nil,
                        distanceM:distance(lat,lon,sqlite3_column_double(q,3),sqlite3_column_double(q,4)),radiusM:sqlite3_column_double(q,5),expectedEndSpeedKmh:number(q,6).flatMap { $0.isFinite && $0 > 0 && $0 <= 300 && $0.rounded() == $0 ? Int($0) : nil },sourceLatitude:sqlite3_column_double(q,3),sourceLongitude:sqlite3_column_double(q,4),sourceID:string(q,7),snapshotSHA256:string(q,8)))
                }
                sqlite3_finalize(q)
            } else if let statement { sqlite3_finalize(statement) }
        }
        // Preserve genuine physical OSM town-sign transitions in optional sign
        // regions. Derived polygon/urban-tag changes cannot release a town latch.
        statement=nil
        let materializedOSMTowns: Bool
        if sqlite3_prepare_v2(db,"SELECT value FROM traffic_sign_capability WHERE key='osm_town_fallback'",-1,&statement,nil) == SQLITE_OK,let q=statement {
            materializedOSMTowns=sqlite3_step(q) == SQLITE_ROW && string(q,0) == "materialized"
            sqlite3_finalize(q)
        } else { materializedOSMTowns=false; if let statement { sqlite3_finalize(statement) } }
        if !materializedOSMTowns, matchStable, let wayID, let direction {
            let sql = """
                SELECT sign_id,sign_code,lat,lon FROM settlement_sign
                WHERE way_id=? AND direction=? AND association IN ('node_membership','collinear_way_split')
                  AND sign_code IN ('DE:310','DE:311') AND lat IS NOT NULL AND lon IS NOT NULL
                """
            statement=nil
            if sqlite3_prepare_v2(db,sql,-1,&statement,nil) == SQLITE_OK, let q=statement {
                sqlite3_bind_text(q,1,wayID,-1,transient);sqlite3_bind_int(q,2,Int32(direction))
                while sqlite3_step(q) == SQLITE_ROW {
                    guard let rawID=string(q,0),let code=string(q,1),let a=number(q,2),let b=number(q,3),
                          a.isFinite,b.isFinite,let source=projection(lat:a,lon:b,points:points) else { continue }
                    guard !boundaries.contains(where: { $0.code==code && abs($0.stationM-source.chainage)<=10 }) else { continue }
                    let id="osm:"+(rawID.components(separatedBy:":w:").first ?? rawID)
                    boundaries.append(.init(ruleID:id,signID:id,code:code,direction:direction,stationM:source.chainage,
                        startM:source.chainage,endM:source.chainage,speedKmh:nil,insideCity:code == "DE:310",
                        distanceM:distance(lat,lon,a,b),radiusM:30,sourceLatitude:a,sourceLongitude:b))
                }
                sqlite3_finalize(q)
            } else if let statement { sqlite3_finalize(statement) }
        }
        return .init(signs:signs.sorted { ($0.distanceM,$0.signID) < ($1.distanceM,$1.signID) },activeRule:selected,wayID:wayID,direction:matchStable ? direction : nil,chainageM:p?.chainage,boundaries:boundaries)
    }
}

/// Passage stations are independent of applicability intervals: a town boundary
/// can have a zero-length interval when a fresh posted sign shares its station.
struct InventoryBoundaryPassageTracker {
    private var previous: (bundle: String, way: String, direction: Int, chainage: Double, at: Date?)?
    private var consumed = Set<String>()
    private var bundleIdentity: String?
    private var consumedCenters: [String:(latitude:Double,longitude:Double,radius:Double)] = [:]
    mutating func reset() { previous=nil; consumed=[];bundleIdentity=nil;consumedCenters=[:] }
    mutating func consume(_ lookup: InventorySignLookup?, bundle: String, at: Date? = nil,
                          latitude: Double? = nil, longitude: Double? = nil) -> [InventoryTrafficRule] {
        if bundleIdentity != bundle { reset();bundleIdentity=bundle }
        if let latitude, let longitude, latitude.isFinite, longitude.isFinite {
            for (key,center) in consumedCenters where InventorySignBundle.distance(latitude,longitude,center.latitude,center.longitude)>center.radius {
                consumed.remove(key);consumedCenters.removeValue(forKey:key)
            }
        }
        guard let lookup, let way=lookup.wayID, let direction=lookup.direction, let chainage=lookup.chainageM else {
            // A transient poor fix invalidates crossing interpolation, not the
            // fact that a boundary was already passed during this encounter.
            previous=nil; return []
        }
        let outside=Set(lookup.boundaries.filter { ($0.distanceM ?? 0) > $0.radiusM }.map { $0.signID+":"+String(direction) })
        consumed.subtract(outside)
        for key in outside { consumedCenters.removeValue(forKey:key) }
        defer { previous=(bundle,way,direction,chainage,at) }
        let comparable = previous.map { old in
            let freshPair: Bool
            if let at, let oldAt=old.at { freshPair=at >= oldAt && at.timeIntervalSince(oldAt) <= 3 }
            else { freshPair=true }
            return old.bundle==bundle && old.way==way && old.direction==direction && freshPair
        } == true
        let crossed=lookup.boundaries.filter {
            let key=$0.signID+":"+String(direction)
            guard !consumed.contains(key) else { return false }
            if comparable, let previous {
                return direction==1 ? previous.chainage < $0.stationM && chainage >= $0.stationM
                    : previous.chainage > $0.stationM && chainage <= $0.stationM
            }
            // Entering a new matched way can begin after its sign station. The
            // First-fix initialization still requires the real display radius.
            guard let distance=$0.distanceM, distance <= $0.radiusM else { return false }
            return direction==1 ? chainage >= $0.stationM : chainage <= $0.stationM
        }.sorted { direction==1 ? $0.stationM < $1.stationM : $0.stationM > $1.stationM }
        for item in crossed {
            let key=item.signID+":"+String(direction)
            consumed.insert(key)
            if let latitude=item.sourceLatitude, let longitude=item.sourceLongitude {
                consumedCenters[key]=(latitude,longitude,item.radiusM)
            }
        }
        return crossed
    }
}

/// Local immutable journal; no collection/upload consent is implied by an encounter.
final class InventorySignJournal {
    let url: URL
    private let evidenceSink: (([String: Any], Date) -> Void)?
    init(url: URL? = nil, evidenceSink: (([String: Any], Date) -> Void)? = nil) {
        self.evidenceSink = evidenceSink
        self.url = url ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0]
            .appendingPathComponent("InventorySignEncounters/events.ndjson")
    }
    func append(_ value: [String: Any]) throws {
        let data = try JSONSerialization.data(withJSONObject:value,options:[.sortedKeys]) + Data([10])
        try FileManager.default.createDirectory(at:url.deletingLastPathComponent(),withIntermediateDirectories:true)
        if !FileManager.default.fileExists(atPath:url.path) { FileManager.default.createFile(atPath:url.path,contents:nil) }
        let file = try FileHandle(forWritingTo:url)
        defer { try? file.close() }
        try file.seekToEnd(); try file.write(contentsOf:data); try file.synchronize()
        // Mirror only durably recorded evidence. The trip journal keeps the
        // inventory source and a visual confirmation as separate event kinds.
        var payload = value
        let confirmed = value["outcome"] as? String == "camera_confirmed"
        payload["event_kind"] = confirmed ? "inventory_camera_confirmation" : "inventory_encounter"
        payload["class_code"] = value["observed_class"] ?? value["expected_code"]
        payload["evidence_id"] = value["event_id"]
        let provider = value["source_id"] as? String
        payload["source"] = confirmed ? "camera" : (provider == "mobidata-bw-vzk" ? "government" : provider == "osm-settlement" ? "osm" : "inventory")
        payload["confidence"] = value["classifier_score"]
        payload["value"] = value["observed_value"] ?? value["numeric_value"]
        payload["units"] = value["unit"]
        payload["accuracy"] = value["accuracy_m"]
        payload["media_id"] = value["capture_id"]
        evidenceSink?(payload, Date(timeIntervalSince1970: value["at"] as? Double ?? Date().timeIntervalSince1970))
    }
}

/// Per-traversal camera association. Registry proximity is never visual confirmation.
final class InventorySignEncounterRuntime {
    struct Observation {
        let label: String
        let value: Int?
        let score: Double
        let frameID: String
        let at: Date
        let box: [Double]
        let packID: String
        let checkpoint: String?
        var wayID: String? = nil
        var direction: Int? = nil
        var bundle: String? = nil
    }
    private struct Encounter {
        let id: String
        let sign: InventoryTrafficSign
        let bundle: String
        let bundleSHA256: String?
        let bundleVersion: String?
        let way: String?
        let direction: Int?
        let entered: Date
        var lastFixAt: Date
        var position: [String:Any]
        var outcome: String
        var frames = Set<String>()
        var analyzedFrames = Set<String>()
        var firstAnalyzedAt: Date?
        var lastAnalyzedAt: Date?
        var first: Observation?
        var captureSaved = false
        var capturePending = false
    }
    private(set) var visible: [InventoryTrafficSign] = []
    private var encounters: [String:Encounter] = [:]
    private var detachedPending: [String:Encounter] = [:]
    private var latestFix = Date.distantPast
    private var lastAnalyzedFrameAt = Date.distantPast
    private var activeBundle = ""
    private var cameraState = "camera_off"
    private var knownClasses = Set<String>()
    private var latestPosition: [String:Any] = [:]
    let journal: InventorySignJournal
    init(journal: InventorySignJournal = .init()) { self.journal=journal }
    var pendingCaptureIDs: [String] { encounters.values.filter {
        !$0.captureSaved && !$0.capturePending && $0.sign.targetMatches(way:$0.way,direction:$0.direction,
            heading:$0.position["heading_deg"] as? Double,headingAccuracy:$0.position["heading_accuracy_deg"] as? Double)
    }.map(\.id).sorted() }
    private func event(_ e: Encounter, phase: String, at: Date, extra: [String:Any] = [:]) -> [String:Any] {
        var result: [String:Any] = ["schema_version":1,"event_id":UUID().uuidString,"encounter_id":e.id,
            "phase":phase,"at":at.timeIntervalSince1970,"outcome":e.outcome,"source_id":e.sign.sourceID,
            "snapshot_sha256":e.sign.snapshotSHA256,"record_key":e.sign.recordKey,"bundle_revision":e.bundle,
            "bundle_sha256":e.bundleSHA256 as Any? ?? NSNull(),"bundle_version":e.bundleVersion as Any? ?? NSNull(),
            "sign_id":e.sign.signID,"expected_code":e.sign.code,"way_id":e.way as Any? ?? NSNull(),"direction":e.direction as Any? ?? NSNull(),
            "started_at":e.entered.timeIntervalSince1970,"last_fix_at":e.lastFixAt.timeIntervalSince1970,
            "analyzed_frames":e.analyzedFrames.count,"support_frame_count":e.frames.count,
            "numeric_value":e.sign.numericValue as Any? ?? NSNull(),"unit":e.sign.unit as Any? ?? NSNull(),
            "sign_latitude":e.sign.latitude,"sign_longitude":e.sign.longitude,
            "parameter_status":e.sign.parameterStatus,"target_way_id":e.sign.associatedWayID as Any? ?? NSNull(),
            "target_direction":e.sign.associatedDirection as Any? ?? NSNull(),"association_status":e.sign.associationStatus as Any? ?? NSNull(),
            "associated_heading_deg":e.sign.associatedHeadingDeg as Any? ?? NSNull(),
            "face_status":e.sign.secondaryFaceStatus(heading:e.position["heading_deg"] as? Double,
                headingAccuracy:e.position["heading_accuracy_deg"] as? Double)]
        result.merge(e.position) { _,new in new }; result.merge(extra) { _,new in new }; return result
    }
    func update(_ lookup: InventorySignLookup?, bundle: String, at: Date, now: Date,
                cameraEnabled: Bool, cameraAvailable: Bool, classes: [String],
                latitude: Double? = nil, longitude: Double? = nil, accuracy: Double? = nil,
                bundleSHA256: String? = nil, bundleVersion: String? = nil,
                heading: Double? = nil, headingAccuracy: Double? = nil) {
        let oldCameraState = cameraState
        latestFix=at
        latestPosition = ["latitude":latitude as Any? ?? NSNull(),"longitude":longitude as Any? ?? NSNull(),
                          "accuracy_m":accuracy as Any? ?? NSNull(),"chainage_m":lookup?.chainageM as Any? ?? NSNull(),
                          "heading_deg":heading as Any? ?? NSNull(),"heading_accuracy_deg":headingAccuracy as Any? ?? NSNull()]
        knownClasses=Set(classes); cameraState = !cameraEnabled ? "camera_off" : !cameraAvailable ? "camera_unavailable" : "not_observed"
        let usable = at <= now.addingTimeInterval(1) && now.timeIntervalSince(at) <= 3
        let candidates = usable ? lookup?.signs ?? [] : []
        let keys = Set(candidates.map { bundle+":"+$0.signID+":"+(lookup?.wayID ?? "")+":"+String(lookup?.direction ?? 0) })
        for key in Array(encounters.keys) where !keys.contains(key) {
            guard var e=encounters[key] else { continue }
            if e.outcome == "awaiting_camera" {
                let span=e.firstAnalyzedAt.flatMap { first in e.lastAnalyzedAt.map { $0.timeIntervalSince(first) } } ?? 0
                e.outcome = e.analyzedFrames.count >= 2 && (span*1000).rounded() >= 100 ? "not_observed" : "camera_unavailable"
            }
            do {
                try journal.append(event(e,phase:"finished",at:now))
                if e.capturePending { detachedPending[e.id]=e }
                encounters.removeValue(forKey:key)
            } catch { }
        }
        activeBundle=bundle; latestFix=at
        for key in encounters.keys where keys.contains(key) {
            encounters[key]?.lastFixAt=at;encounters[key]?.position=latestPosition
        }
        if cameraState != oldCameraState {
            for key in Array(encounters.keys) {
                guard var e=encounters[key], e.outcome != "camera_confirmed" else { continue }
                e.outcome = cameraState == "not_observed" ? (!e.sign.confirmationSemanticsVerified || !e.sign.targetMatches(way:lookup?.wayID,direction:lookup?.direction,heading:heading,headingAccuracy:headingAccuracy)
                    ? "ambiguous" : e.sign.modelClasses.contains { knownClasses.contains($0) } ? "awaiting_camera" : "unsupported_model_class") : cameraState
                e.first=nil; e.frames=[]; e.analyzedFrames=[]; e.firstAnalyzedAt=nil; e.lastAnalyzedAt=nil
                do { try journal.append(event(e,phase:"camera_state",at:now)); encounters[key]=e } catch { }
            }
        }
        for sign in candidates {
            let key=bundle+":"+sign.signID+":"+(lookup?.wayID ?? "")+":"+String(lookup?.direction ?? 0)
            guard encounters[key] == nil else { continue }
            let supported = sign.modelClasses.contains { knownClasses.contains($0) }
            let outcome = cameraState != "not_observed" ? cameraState : !sign.confirmationSemanticsVerified || !sign.targetMatches(way:lookup?.wayID,direction:lookup?.direction,heading:heading,headingAccuracy:headingAccuracy)
                ? "ambiguous" : !supported ? "unsupported_model_class" : "awaiting_camera"
            let e=Encounter(id:UUID().uuidString,sign:sign,bundle:bundle,bundleSHA256:bundleSHA256,bundleVersion:bundleVersion,way:lookup?.wayID,direction:lookup?.direction,entered:at,
                lastFixAt:at,position:latestPosition,outcome:outcome)
            do { try journal.append(event(e,phase:"started",at:now)); encounters[key]=e } catch { }
        }
        visible=candidates.filter { $0.targetMatches(way:lookup?.wayID,direction:lookup?.direction,heading:heading,headingAccuracy:headingAccuracy) }
    }
    func observe(_ observations: [Observation], now: Date, frameID: String? = nil, frameAt: Date? = nil,
                 frameWayID: String? = nil, frameDirection: Int? = nil, frameBundle: String? = nil) {
        guard cameraState == "not_observed", now.timeIntervalSince(latestFix) >= -1,
              now.timeIntervalSince(latestFix) <= 3 else { return }
        if let observedAt=frameAt ?? observations.first?.at {
            guard observedAt >= lastAnalyzedFrameAt else { return }
            lastAnalyzedFrameAt=observedAt
        }
        if let frameID, let frameAt, frameAt <= now.addingTimeInterval(1), now.timeIntervalSince(frameAt) <= 3 {
            for key in Array(encounters.keys) {
                guard let e=encounters[key],e.outcome != "camera_confirmed",e.way != nil,e.way==frameWayID,e.direction != nil,
                      e.direction==frameDirection,e.bundle==frameBundle,frameAt>=e.entered else { continue }
                if e.analyzedFrames.count < 64 { encounters[key]?.analyzedFrames.insert(frameID) }
                if encounters[key]?.firstAnalyzedAt == nil { encounters[key]?.firstAnalyzedAt=frameAt }
                encounters[key]?.lastAnalyzedAt=frameAt
            }
        }
        for observation in observations where observation.score >= 0.9 && observation.at <= now.addingTimeInterval(1) && now.timeIntervalSince(observation.at) <= 3 {
            let matches=encounters.keys.filter { key in
                guard let e=encounters[key] else { return false }
                return e.sign.confirmationSemanticsVerified && e.bundle == activeBundle && e.bundle == observation.bundle
                    && e.way != nil && e.way == observation.wayID
                    && e.direction != nil && e.direction == observation.direction && observation.at >= e.entered
                    && e.sign.targetMatches(way:observation.wayID,direction:observation.direction,
                        heading:e.position["heading_deg"] as? Double,headingAccuracy:e.position["heading_accuracy_deg"] as? Double)
                    && e.sign.modelClasses.contains(observation.label)
                    && (e.sign.numericValue == nil || e.sign.numericValue == observation.value.map(Double.init))
            }
            for key in matches {
                guard var e=encounters[key], e.outcome != "camera_confirmed", !e.frames.contains(observation.frameID) else { continue }
                if e.analyzedFrames.count < 64 { e.analyzedFrames.insert(observation.frameID) }
                if e.firstAnalyzedAt == nil { e.firstAnalyzedAt=observation.at }
                e.lastAnalyzedAt=observation.at
                let oldOutcome=e.outcome
                let hadFirst=e.first != nil
                var shouldWrite=false
                if matches.count != 1 {
                    e.outcome="ambiguous";e.first=nil;e.frames=[]
                    shouldWrite=oldOutcome != e.outcome
                } else {
                    e.outcome="awaiting_camera"
                    if let first=e.first, first.frameID != observation.frameID,
                       observation.at >= first.at, observation.at.timeIntervalSince(first.at) <= 2,
                       first.packID == observation.packID, first.checkpoint != nil, first.checkpoint == observation.checkpoint,
                       Self.iou(first.box,observation.box) >= 0.3 {
                        // Keep the original supporting frame through sub-100ms
                        // camera frames; sliding it on every frame never confirms.
                        e.frames=[first.frameID,observation.frameID]
                        if (observation.at.timeIntervalSince(first.at)*1000).rounded() >= 100 {
                            e.outcome="camera_confirmed"
                        }
                    } else {
                        e.first=observation;e.frames=[observation.frameID]
                    }
                    shouldWrite=oldOutcome != e.outcome || !hadFirst
                }
                if shouldWrite {
                    do {
                        try journal.append(event(e,phase:"camera_observation",at:now,extra:["observed_class":observation.label,
                            "observed_value":observation.value as Any? ?? NSNull(),"classifier_score":observation.score,
                            "frame_id":observation.frameID,"first_frame_id":e.first?.frameID as Any? ?? NSNull(),
                            "track_id":e.id,"pack_id":observation.packID,"model_sha256":observation.checkpoint as Any? ?? NSNull(),
                            "frame_ids":Array(e.frames).sorted()]))
                        encounters[key]=e
                    } catch { }
                } else { encounters[key]=e }
            }
            if matches.isEmpty {
                let numericMismatch=encounters.keys.filter { key in
                    guard let e=encounters[key] else { return false }
                    return e.sign.confirmationSemanticsVerified && e.sign.kind == "speed_limit" && observation.label.hasPrefix("maxspeed:")
                        && e.bundle == observation.bundle && e.way != nil && e.way == observation.wayID
                        && e.direction != nil && e.direction == observation.direction && observation.at >= e.entered
                        && e.sign.targetMatches(way:observation.wayID,direction:observation.direction,
                            heading:e.position["heading_deg"] as? Double,headingAccuracy:e.position["heading_accuracy_deg"] as? Double)
                }
                for key in numericMismatch where encounters[key]?.outcome != "camera_confirmed" && encounters[key]?.outcome != "camera_mismatch" {
                    guard var e=encounters[key] else { continue }; e.outcome="camera_mismatch";e.first=nil;e.frames=[]
                    do { try journal.append(event(e,phase:"camera_observation",at:now,extra:["observed_class":observation.label,"observed_value":observation.value as Any? ?? NSNull(),
                        "classifier_score":observation.score,"frame_id":observation.frameID,
                        "pack_id":observation.packID,"model_sha256":observation.checkpoint as Any? ?? NSNull()])); encounters[key]=e } catch { }
                }
            }
        }
    }
    func captureRequested(_ ids: [String]) {
        for key in encounters.keys where ids.contains(encounters[key]!.id) { encounters[key]?.capturePending=true }
    }
    func captureFinished(_ ids: [String], saved: Bool, captureID: String?, now: Date) {
        for id in ids {
            guard var e=detachedPending[id] else { continue }
            e.capturePending=false
            do {
                try journal.append(event(e,phase:saved ? "capture_saved" : "capture_failed",at:now,
                    extra:["capture_id":captureID as Any? ?? NSNull()]))
                detachedPending.removeValue(forKey:id)
            } catch { }
        }
        for key in Array(encounters.keys) where ids.contains(encounters[key]!.id) {
            guard var e=encounters[key] else { continue }; e.capturePending=false
            do {
                try journal.append(event(e,phase:saved ? "capture_saved" : "capture_failed",at:now,extra:["capture_id":captureID as Any? ?? NSNull()]))
                e.captureSaved=saved; encounters[key]=e
            } catch { e.captureSaved=false; encounters[key]=e }
        }
    }
    func finish(now: Date) { update(nil,bundle:"",at:now,now:now,cameraEnabled:false,cameraAvailable:false,classes:[]) }
    private static func iou(_ a:[Double],_ b:[Double]) -> Double {
        guard a.count==4,b.count==4 else { return 0 }
        let intersection=max(0,min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0]))*max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
        return intersection/max(1e-12,a[2]*a[3]+b[2]*b[3]-intersection)
    }
}
