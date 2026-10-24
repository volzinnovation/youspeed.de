import Foundation
import CoreLocation
import SQLite3
import SwiftUI
import Charts
import MapKit
import AVKit
import CryptoKit
import UniformTypeIdentifiers
import Darwin

/// Private journal. This store never enables camera, contributions, uploads or location permissions.
final class TripJournal: ObservableObject, @unchecked Sendable {
    static let shared = TripJournal()
    private let preferences: UserDefaults
    private let queue = DispatchQueue(label: "de.youspeed.trip-journal")
    private var db: OpaquePointer?
    private var directory: URL?
    private var active: String?
    private var finalizing: (id: String, start: Double, end: Double, deadline: Double)?
    private var requested = false
    private var endedLatch = false
    private var foreground = true
    private var previous: CLLocation?
    private var lastFixTime: Date?
    private var usageAnchor = TripJournal.monotonic()
    private var tripAnchor = TripJournal.monotonic()
    private var backgroundAt: Date?
    private var liveVideos = [String: [String: Any]]()
    private var liveVideoOwners = [String: Set<String>]()
    private var timer: DispatchSourceTimer?
    private var transactionFailed = false
    private let backlogLock = NSLock()
    private var backlog = 0
    private var dropped = 0
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    @Published private(set) var error: String?
    var enabled: Bool { preferences.bool(forKey: "youspeed.journal.enabled") }
    var configured: Bool { preferences.object(forKey: "youspeed.journal.enabled") != nil }

    private static func monotonic() -> Double {
        var info = mach_timebase_info_data_t(); mach_timebase_info(&info)
        return Double(mach_continuous_time()) * Double(info.numer) / Double(info.denom) / 1_000_000_000
    }
    static func recordingMonotonicTime() -> Double { monotonic() }
    private func submit(_ body: @escaping () -> Void) {
        backlogLock.lock()
        if backlog >= 4096 { dropped += 1; backlogLock.unlock(); return }
        backlog += 1; backlogLock.unlock()
        queue.async {
            self.backlogLock.lock(); let lost = self.dropped; self.dropped = 0; self.backlogLock.unlock()
            if lost > 0 {
                // A dropped fix may span unobserved movement; never bridge that interval.
                self.previous = nil
                self.record("gap", ["reason": "journal_queue_overflow", "events_lost": lost])
                self.fail("Trip log coverage gap: queue overflow")
            }
            body()
            self.backlogLock.lock(); self.backlog -= 1; self.backlogLock.unlock()
        }
    }
    init(directory: URL? = nil, preferences: UserDefaults = .standard, heartbeat: Bool = true) {
        self.preferences = preferences
        queue.async {
            do {
                self.directory = try directory ?? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true).appendingPathComponent("TripJournal", isDirectory: true)
                _ = try self.ensureDatabase()
            } catch { self.fail(error.localizedDescription) }
        }
        guard heartbeat else { return }
        let t = DispatchSource.makeTimerSource(queue: queue)
        t.schedule(deadline: .now() + 5, repeating: 5)
        t.setEventHandler { [weak self] in self?.checkpoint() }
        t.resume(); timer = t
    }
    deinit { timer?.cancel(); sqlite3_close_v2(db) }
    func close() { queue.sync { timer?.cancel(); timer = nil; sqlite3_close_v2(db); db = nil } }
    private func fail(_ message: String) { DispatchQueue.main.async { self.error = message } }
    @discardableResult private func ensureDatabase() throws -> Bool {
        if db != nil { return true }
        guard let directory else { throw CocoaError(.fileWriteUnknown) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var connection: OpaquePointer?
        guard sqlite3_open(directory.appendingPathComponent("trips.sqlite").path, &connection) == SQLITE_OK else {
            sqlite3_close_v2(connection); throw CocoaError(.fileWriteUnknown)
        }
        db = connection
        sqlite3_busy_timeout(connection, 3000)
        let setup = sql("PRAGMA journal_mode=WAL") && sql("PRAGMA secure_delete=ON")
        let committed = transaction {
            self.sql("CREATE TABLE IF NOT EXISTS trips(id TEXT PRIMARY KEY,start REAL,end REAL,state TEXT,distance REAL DEFAULT 0,duration REAL DEFAULT 0,odo_start REAL,odo_end REAL)")
            let columns = Set(self.rows("PRAGMA table_info(trips)").compactMap { $0["name"] as? String })
            for (name, type) in [("last_observed", "REAL"), ("end_reason", "TEXT"), ("timezone_seconds", "INTEGER"), ("vehicle", "TEXT"), ("observed", "REAL DEFAULT 0")] where !columns.contains(name) {
                self.sql("ALTER TABLE trips ADD COLUMN \(name) \(type)")
            }
            self.sql("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,trip TEXT,kind TEXT,time REAL,payload TEXT)")
            self.sql("CREATE INDEX IF NOT EXISTS events_trip ON events(trip,seq)")
            self.sql("CREATE TABLE IF NOT EXISTS bindings(session TEXT PRIMARY KEY,trip TEXT)")
            self.sql("CREATE TABLE IF NOT EXISTS counters(id INTEGER PRIMARY KEY CHECK(id=1),origin REAL,distance REAL,usage REAL)")
            self.sql("INSERT OR IGNORE INTO counters VALUES(1,?,0,0)", [Date().timeIntervalSince1970])
            self.sql("UPDATE trips SET last_observed=COALESCE(last_observed,end,start),end_reason='process_recovered',state='interrupted' WHERE state IN ('active','finalizing')")
            self.sql("PRAGMA user_version=2")
        }
        guard setup && committed else { sqlite3_close_v2(db); db = nil; throw CocoaError(.fileWriteUnknown) }
        try? FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: directory.path)
        DispatchQueue.main.async { self.error = nil }
        return true
    }
    @discardableResult private func sql(_ query: String, _ args: [Any] = []) -> Bool {
        guard let db else { transactionFailed = true; fail("Trip database unavailable"); return false }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK else {
            transactionFailed = true; fail(String(cString: sqlite3_errmsg(db))); return false
        }
        defer { sqlite3_finalize(statement) }
        for (i, value) in args.enumerated() {
            let index = Int32(i + 1)
            if value is NSNull { sqlite3_bind_null(statement, index) }
            else if let number = value as? Double { sqlite3_bind_double(statement, index, number) }
            else if let number = value as? Int { sqlite3_bind_int64(statement, index, Int64(number)) }
            else { sqlite3_bind_text(statement, index, String(describing: value), -1, transient) }
        }
        var result = sqlite3_step(statement)
        while result == SQLITE_ROW { result = sqlite3_step(statement) }
        guard result == SQLITE_DONE else { transactionFailed = true; fail(String(cString: sqlite3_errmsg(db))); return false }
        return true
    }
    @discardableResult private func transaction(_ body: () -> Void) -> Bool {
        transactionFailed = false
        guard sql("BEGIN IMMEDIATE") else { return false }
        body()
        if transactionFailed { _ = sql("ROLLBACK"); return false }
        guard sql("COMMIT") else { _ = sql("ROLLBACK"); return false }
        return true
    }
    private func rows(_ query: String, _ args: [String] = []) -> [[String: Any]] {
        guard let db else { return [] }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, query, -1, &statement, nil) == SQLITE_OK else { fail(String(cString: sqlite3_errmsg(db))); return [] }
        defer { sqlite3_finalize(statement) }
        for (i, value) in args.enumerated() { sqlite3_bind_text(statement, Int32(i + 1), value, -1, transient) }
        var result = [[String: Any]](), step = sqlite3_step(statement)
        while step == SQLITE_ROW {
            var row = [String: Any]()
            for i in 0..<sqlite3_column_count(statement) {
                let key = String(cString: sqlite3_column_name(statement, i))
                switch sqlite3_column_type(statement, i) {
                case SQLITE_NULL: break
                case SQLITE_INTEGER, SQLITE_FLOAT: row[key] = sqlite3_column_double(statement, i)
                default: if let text = sqlite3_column_text(statement, i) { row[key] = String(cString: text) }
                }
            }
            result.append(row); step = sqlite3_step(statement)
        }
        if step != SQLITE_DONE { fail(String(cString: sqlite3_errmsg(db))) }
        return result
    }
    func snapshot() -> (trips: [[String: Any]], counters: [String: Any]) {
        queue.sync { checkpoint(); return (rows("SELECT * FROM trips ORDER BY start DESC"), rows("SELECT * FROM counters").first ?? [:]) }
    }
    func events(_ id: String) -> [[String: Any]] { queue.sync { rows("SELECT * FROM events WHERE trip=? ORDER BY time,seq", [id]) } }
    func setEnabled(_ value: Bool) {
        preferences.set(value, forKey: "youspeed.journal.enabled")
        queue.async {
            if value && self.requested { self.endedLatch = false; self.begin() }
            else if !value { self.finish("disabled", reason: "recording_disabled") }
        }
    }
    func start() {
        let intent = Date()
        queue.async {
            guard (try? self.ensureDatabase()) == true else { return }
            self.requested = true
            if self.enabled { self.begin(at: intent) }
        }
    }
    /// Explicit parked action; dashboard recomposition does not release the stop latch.
    func newTrip() { queue.async { self.endedLatch = false; self.requested = true; if self.enabled { self.begin() } } }
    private func begin(at date: Date = Date()) {
        guard active == nil, !endedLatch, foreground, db != nil else { return }
        checkpoint()
        let id = UUID().uuidString, now = date.timeIntervalSince1970
        guard sql("INSERT INTO trips(id,start,end,state,last_observed,timezone_seconds) VALUES(?,?,?,'active',?,?)", [id, now, now, now, TimeZone.current.secondsFromGMT()]) else { return }
        active = id; previous = nil; lastFixTime = nil; tripAnchor = Self.monotonic()
        record("coverage", ["gps": "awaiting_location", "tsr": "existing_camera_setting", "measurement_policy": 1])
        for (captureID, payload) in liveVideos {
            liveVideoOwners[captureID, default: []].insert(id)
            sql("INSERT OR IGNORE INTO bindings VALUES(?,?)", [captureID, id])
            record("media", payload, trip: id)
        }
    }
    func stop(at intent: Date = Date()) {
        queue.async {
            self.requested = false; self.endedLatch = true
            if let id = self.active, let start = self.rows("SELECT start FROM trips WHERE id=?", [id]).first?["start"] as? Double {
                self.finish("finalizing", reason: "user_ended", at: intent)
                self.finalizing = (id, start, intent.timeIntervalSince1970, Self.monotonic() + 5)
                self.queue.asyncAfter(deadline: .now() + 5) { self.completeFinalizer(id) }
            }
        }
    }
    private func completeFinalizer(_ id: String) {
        guard finalizing?.id == id else { return }
        self.record("coverage", ["state": "sign_finalizer_closed", "window_s": 5], trip: id)
        self.sql("UPDATE trips SET state='ended' WHERE id=? AND state='finalizing'", [id]); finalizing = nil
    }
#if DEBUG
    func completeFinalizerForTesting() { queue.sync { if let id = finalizing?.id { completeFinalizer(id) } } }
#endif
    private func eventOwner(at date: Date) -> String? {
        let timestamp = date.timeIntervalSince1970
        if let id = active, let start = rows("SELECT start FROM trips WHERE id=?", [id]).first?["start"] as? Double, timestamp >= start { return id }
        if let pending = finalizing, Self.monotonic() <= pending.deadline, timestamp >= pending.start, timestamp <= pending.end { return pending.id }
        return nil
    }
    private func finish(_ state: String, reason: String, at intent: Date? = nil) {
        checkpoint()
        if let id = active {
            let endpoint = intent?.timeIntervalSince1970 ?? (rows("SELECT end FROM trips WHERE id=?", [id]).first?["end"] as? Double ?? Date().timeIntervalSince1970)
            let lag = intent.map { max(0, Date().timeIntervalSince($0)) } ?? 0
            sql("UPDATE trips SET state=?,end_reason=?,end=MIN(end,?),duration=MAX(0,duration-?) WHERE id=?", [state, reason, endpoint, lag, id])
        }
        active = nil; previous = nil; lastFixTime = nil
    }
    private func checkpoint() {
        let now = Self.monotonic(), delta = max(0, now - usageAnchor); usageAnchor = now
        guard db != nil else { return }
        transaction {
            if foreground { self.sql("UPDATE counters SET usage=usage+? WHERE id=1", [delta]) }
            if let id = active, foreground {
                self.sql("UPDATE trips SET end=?,last_observed=?,duration=?,observed=observed+? WHERE id=?", [Date().timeIntervalSince1970, Date().timeIntervalSince1970, max(0, now - tripAnchor), delta, id])
            }
        }
    }
    func lifecycle(_ value: Bool, at date: Date = Date()) {
        queue.async {
            guard value != self.foreground else { return }
            self.checkpoint()
            if !value {
                self.backgroundAt = date; self.previous = nil; self.lastFixTime = nil
                self.record("gap", ["reason": "background", "began_at": date.timeIntervalSince1970], at: date)
            } else {
                if let at = self.backgroundAt {
                    if date.timeIntervalSince(at) > 300 { self.finish("interrupted", reason: "foreground_timeout") }
                    else { self.record("gap_end", ["reason": "foreground_resumed", "began_at": at.timeIntervalSince1970, "duration_s": max(0, date.timeIntervalSince(at))], at: date) }
                }
                self.endedLatch = false
            }
            self.foreground = value; self.usageAnchor = Self.monotonic()
            if value && self.requested && self.enabled { self.begin() }
        }
    }
    private func record(_ kind: String, _ payload: [String: Any], trip: String? = nil, at: Date = Date()) {
        guard let id = trip ?? active, !rows("SELECT id FROM trips WHERE id=? LIMIT 1", [id]).isEmpty else { return }
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]), let json = String(data: data, encoding: .utf8) else { fail("Invalid journal event"); return }
        sql("INSERT INTO events(trip,kind,time,payload) VALUES(?,?,?,?)", [id, kind, at.timeIntervalSince1970, json])
    }
    func tsr(_ line: String, at date: Date? = nil) {
        let embedded = line.split(separator: " ").first(where: { $0.hasPrefix("timestamp=") }).flatMap { ISO8601DateFormatter().date(from: String($0.dropFirst(10))) }
        let at = date ?? embedded ?? Date()
        submit {
            guard self.foreground, let id = self.eventOwner(at: at) else { return }
            self.record("tsr", ["message": line, "received_at": Date().timeIntervalSince1970], trip: id, at: at)
        }
    }
    func tsrEvent(_ payload: [String: Any], at date: Date) {
        submit { guard self.foreground, let id = self.eventOwner(at: date) else { return }; self.record("tsr", payload, trip: id, at: date) }
    }
    func signEvent(_ payload: [String: Any], at date: Date = Date()) {
        submit {
            guard self.foreground, let id = self.eventOwner(at: date) else { return }
            self.record("sign", payload, trip: id, at: date)
        }
    }
    /// Offline matcher context, tied to the actual fix rather than the callback receipt time.
    func matchedPlace(at date: Date, streetName: String?, cityName: String?, latitude: Double, longitude: Double, accuracy: Double) {
        let street = streetName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let city = cityName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard date.timeIntervalSince1970.isFinite, !street.isEmpty || !city.isEmpty, latitude.isFinite, longitude.isFinite,
              CLLocationCoordinate2DIsValid(.init(latitude: latitude, longitude: longitude)), accuracy.isFinite, accuracy >= 0 else { return }
        submit {
            guard self.enabled, self.foreground, let id = self.eventOwner(at: date) else { return }
            self.record("place", ["source": "offline_matcher", "street_name": String(street.prefix(200)), "city_name": String(city.prefix(200)), "latitude": latitude, "longitude": longitude, "accuracy": accuracy], trip: id, at: date)
        }
    }
    func location(_ fix: CLLocation) {
        submit {
            guard self.requested, self.foreground else { return }
            let sourceTime = fix.timestamp.timeIntervalSince1970
            let timestampValid = sourceTime.isFinite
            let eventDate = timestampValid ? fix.timestamp : Date()
            let timely = timestampValid && abs(fix.timestamp.timeIntervalSinceNow) <= 10
            let coordinateFinite = fix.coordinate.latitude.isFinite && fix.coordinate.longitude.isFinite
            let coordinateValid = coordinateFinite && CLLocationCoordinate2DIsValid(fix.coordinate)
            let accuracyValid = fix.horizontalAccuracy.isFinite && fix.horizontalAccuracy >= 0 && fix.horizontalAccuracy <= 50
            let valid = coordinateValid && accuracyValid && timely
            let ordered = timestampValid && (self.lastFixTime.map { fix.timestamp > $0 } ?? true)
            var quality = [String]()
            if !coordinateValid { quality.append(coordinateFinite ? "coordinates_out_of_range" : "coordinates_nonfinite") }
            if !accuracyValid { quality.append("accuracy_invalid") }
            if !timestampValid { quality.append("source_timestamp_nonfinite") }
            if timestampValid && !timely { quality.append("source_timestamp_stale") }
            for (field, value) in [("speed", fix.speed), ("course", fix.course), ("altitude", fix.altitude)] where !value.isFinite { quality.append(field + "_nonfinite") }
            var distance = 0.0, reason = valid ? "segment_start" : "invalid_or_stale"
            if !coordinateValid { reason = "invalid_coordinates" }
            else if !timestampValid { reason = "invalid_timestamp" }
            else if !accuracyValid { reason = "invalid_accuracy" }
            else if !ordered { reason = "duplicate_or_out_of_order" }
            else if valid, let prior = self.previous {
                let elapsed = fix.timestamp.timeIntervalSince(prior.timestamp), metres = fix.distance(from: prior)
                distance = TripMeasurement.acceptedDistance(seconds: elapsed, metres: metres, accuracy: fix.horizontalAccuracy, previousAccuracy: prior.horizontalAccuracy, speed: fix.speed)
                reason = distance > 0 ? "accepted" : (elapsed > 15 ? "sampling_gap" : "jitter_or_jump")
                if elapsed > 15 { self.record("gap", ["reason": "sampling_gap", "duration_s": elapsed], at: fix.timestamp) }
            }
            func number(_ value: Double) -> Any { value.isFinite ? value : NSNull() }
            let eligible = valid && ordered && (reason == "segment_start" || reason == "accepted" || reason == "sampling_gap")
            let payload: [String: Any] = ["latitude": coordinateValid ? number(fix.coordinate.latitude) : NSNull(), "longitude": coordinateValid ? number(fix.coordinate.longitude) : NSNull(), "coordinate_valid": coordinateValid, "quality_flags": quality, "accuracy": number(fix.horizontalAccuracy), "speed": fix.speed >= 0 ? number(fix.speed) : NSNull(), "altitude": fix.verticalAccuracy >= 0 ? number(fix.altitude) : NSNull(), "course": fix.course >= 0 ? number(fix.course) : NSNull(), "received_at": Date().timeIntervalSince1970, "source_timestamp": number(sourceTime), "source_timestamp_valid": timestampValid, "valid": valid, "track_eligible": eligible, "distance_m": distance, "reason": reason, "measurement_policy": 1]
            let success = self.transaction {
                self.record("gps", payload, at: eventDate)
                if let id = self.active { self.sql("UPDATE trips SET distance=distance+?,last_observed=MAX(last_observed,?) WHERE id=?", [distance, eventDate.timeIntervalSince1970, id]) }
                self.sql("UPDATE counters SET distance=distance+? WHERE id=1", [distance])
            }
            guard success else { return }
            if !valid { self.previous = nil }
            guard ordered else { return }
            self.lastFixTime = fix.timestamp
            if valid && (self.previous == nil || distance > 0 || fix.timestamp.timeIntervalSince(self.previous!.timestamp) > 15) { self.previous = fix }
        }
    }
    func bind(_ session: String) { queue.async { if let id = self.active { self.sql("INSERT OR IGNORE INTO bindings VALUES(?,?)", [session, id]) } } }
    func aliasBinding(_ source: String, to target: String) { queue.async { self.sql("INSERT OR IGNORE INTO bindings(session,trip) SELECT ?,trip FROM bindings WHERE session=?", [target, source]) } }
    func media(session: String, id: String, path: String, kind: String, binding: String? = nil, at: Date = Date(), location: PanoramaxLocationSample? = nil) {
        submit {
            guard let trip = self.rows("SELECT trip FROM bindings WHERE session=?", [binding ?? id]).first?["trip"] as? String ?? self.rows("SELECT trip FROM bindings WHERE session=?", [binding ?? session]).first?["trip"] as? String else { return }
            var payload: [String: Any] = ["id": id, "session": session, "path": path, "type": kind]
            if let location, location.accuracyMeters >= 0, location.accuracyMeters <= 50,
               abs(location.capturedAt.timeIntervalSince(at)) <= 3 {
                payload["latitude"] = location.latitude; payload["longitude"] = location.longitude
                payload["accuracy"] = location.accuracyMeters; payload["location_at"] = location.capturedAt.timeIntervalSince1970
            }
            self.record("media", payload, trip: trip, at: at)
        }
    }
    /// AVFoundation's recorded-duration callback is an explicit estimated clock anchor, never file mtime.
    func videoTiming(id: String, path: String, session: String, startedAt: Date?, duration: Double?, finished: Bool, successful: Bool = true, monotonicStart: Double? = nil) {
        submit {
            var payload: [String: Any] = ["id": id, "session": session, "path": path, "type": "video", "timing_quality": "recorded_duration_anchor_estimated", "presentation_start_s": 0, "finished": finished, "available": successful]
            if let startedAt { payload["started_at"] = startedAt.timeIntervalSince1970 }
            if let monotonicStart {
                payload["first_frame_monotonic_s"] = monotonicStart
                if finished, let startedAt, let duration {
                    let elapsed = Self.monotonic() - monotonicStart
                    let drift = max(abs(elapsed - duration), abs(Date().timeIntervalSince(startedAt) - elapsed))
                    payload["clock_alignment_error_s"] = drift
                    if drift > 2 { payload["timing_quality"] = "clock_alignment_uncertain" }
                }
            }
            payload["estimated_tolerance_s"] = 2
            if let duration, duration.isFinite, duration >= 0 { payload["duration_s"] = duration; if let startedAt { payload["ended_at"] = startedAt.timeIntervalSince1970 + duration } }
            if let trip = self.rows("SELECT trip FROM bindings WHERE session=?", [id]).first?["trip"] as? String { self.liveVideoOwners[id, default: []].insert(trip) }
            if !finished { self.liveVideos[id] = payload }
            for trip in self.liveVideoOwners[id] ?? [] { self.record("media", payload, trip: trip) }
            if finished { self.liveVideos.removeValue(forKey: id); self.liveVideoOwners.removeValue(forKey: id) }
            if successful, let data = try? JSONSerialization.data(withJSONObject: payload, options: .sortedKeys) { try? data.write(to: URL(fileURLWithPath: path).appendingPathExtension("youspeed.json"), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]) }
        }
    }
    func odometer(_ id: String, start: Double?, end: Double?, unit: String = "km") {
        queue.async {
            guard id == self.active, ["km", "mi"].contains(unit) else { return }
            let multiplier = unit == "mi" ? 1.609344 : 1.0
            self.transaction {
                if let original = start, original.isFinite, original >= 0 {
                    let value = original * multiplier
                    guard value.isFinite else { return }
                    if self.sql("UPDATE trips SET odo_start=? WHERE id=? AND odo_start IS NULL AND (odo_end IS NULL OR odo_end>=?)", [value, id, value]), sqlite3_changes(self.db) > 0 {
                        self.record("odometer_entry", ["field": "start", "entered_value": original, "entered_unit": unit, "normalized_km": value])
                    }
                }
                if let original = end, original.isFinite, original >= 0 {
                    let value = original * multiplier
                    guard value.isFinite else { return }
                    if self.sql("UPDATE trips SET odo_end=? WHERE id=? AND odo_end IS NULL AND (odo_start IS NULL OR odo_start<=?)", [value, id, value]), sqlite3_changes(self.db) > 0 {
                        self.record("odometer_entry", ["field": "end", "entered_value": original, "entered_unit": unit, "normalized_km": value])
                    }
                }
            }
        }
    }
    /// Explicit user entry may fill a missing end reading on a saved trip; existing facts never change.
    func enterEndOdometer(_ id: String, kilometres: Double) throws {
        guard kilometres.isFinite, kilometres >= 0 else { throw JournalFailure(journalText("invalid_odo")) }
        try queue.sync {
            guard let trip = rows("SELECT * FROM trips WHERE id=?", [id]).first else { throw JournalFailure(journalText("trip_missing")) }
            guard trip["odo_end"] == nil else { throw JournalFailure(journalText("end_odo_readonly")) }
            guard kilometres >= (trip["odo_start"] as? Double ?? 0) else { throw JournalFailure(journalText("invalid_odo")) }
            guard transaction({
                if sql("UPDATE trips SET odo_end=? WHERE id=? AND odo_end IS NULL AND (odo_start IS NULL OR odo_start<=?)", [kilometres, id, kilometres]), sqlite3_changes(db) > 0 {
                    record("odometer_entry", ["field": "end", "entered_value": kilometres, "entered_unit": "km", "normalized_km": kilometres], trip: id)
                }
            }) else { throw JournalFailure(journalText("write_failed")) }
        }
    }
    func setVehicle(_ id: String, name: String) { queue.async { guard id == self.active else { return }; self.sql("UPDATE trips SET vehicle=? WHERE id=? AND vehicle IS NULL", [String(name.trimmingCharacters(in: .whitespacesAndNewlines).prefix(100)), id]) } }
    func delete(_ id: String) {
        queue.async {
            if self.finalizing?.id == id { self.finalizing = nil }
            for key in Array(self.liveVideoOwners.keys) { self.liveVideoOwners[key]?.remove(id) }
            if self.active == id { self.requested = false; self.endedLatch = true; self.finish("ended", reason: "deleted") }
            guard self.transaction({ self.sql("DELETE FROM events WHERE trip=?", [id]); self.sql("DELETE FROM bindings WHERE trip=?", [id]); self.sql("DELETE FROM trips WHERE id=?", [id]) }) else { return }
            try? FileManager.default.removeItem(at: Self.exportDirectory(id))
            self.removeTemporaryBackups()
            self.sql("PRAGMA wal_checkpoint(TRUNCATE)")
        }
    }
    private func removeTemporaryBackups(except preserved: URL? = nil) {
        guard let files = try? FileManager.default.contentsOfDirectory(at: FileManager.default.temporaryDirectory, includingPropertiesForKeys: nil) else { return }
        for file in files where file.lastPathComponent.hasPrefix("youspeed-journal-") && file.standardizedFileURL != preserved?.standardizedFileURL { try? FileManager.default.removeItem(at: file) }
    }
    func clearAll() {
        queue.sync {
            guard self.transaction({
                self.sql("DELETE FROM events"); self.sql("DELETE FROM bindings"); self.sql("DELETE FROM trips")
                self.sql("UPDATE counters SET origin=?,distance=0,usage=0 WHERE id=1", [Date().timeIntervalSince1970])
            }) else { return }
            self.active = nil; self.finalizing = nil; self.liveVideoOwners.removeAll(); self.requested = false; self.endedLatch = true; self.previous = nil; self.lastFixTime = nil; self.usageAnchor = Self.monotonic()
            if let roots = try? FileManager.default.contentsOfDirectory(at: FileManager.default.temporaryDirectory, includingPropertiesForKeys: nil) {
                for root in roots where root.lastPathComponent.hasPrefix("trip-") || root.lastPathComponent.hasPrefix("youspeed-journal-") { try? FileManager.default.removeItem(at: root) }
            }
            self.sql("PRAGMA wal_checkpoint(TRUNCATE)")
        }
    }
    private static func exportDirectory(_ id: String) -> URL { FileManager.default.temporaryDirectory.appendingPathComponent("trip-\(id)", isDirectory: true) }
    private func exportSnapshot(_ id: String) throws -> (trip: [String: Any], events: [[String: Any]], counters: [String: Any]) {
        try queue.sync {
            checkpoint()
            guard let trip = rows("SELECT * FROM trips WHERE id=?", [id]).first else { throw JournalFailure("Trip no longer exists") }
            return (trip, rows("SELECT * FROM events WHERE trip=? ORDER BY time,seq", [id]), rows("SELECT * FROM counters").first ?? [:])
        }
    }
    func export(_ id: String, options: TripExportOptions = .init()) throws -> URL {
        let snapshot = try exportSnapshot(id)
        let root = Self.exportDirectory(id).appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try TripJournalExport.write(trip: snapshot.trip, events: snapshot.events, counters: snapshot.counters, options: options, to: root)
        return root
    }
    func archive(_ id: String, options: TripExportOptions = .init()) throws -> URL {
        let root = try export(id, options: options)
        let url = root.appendingPathComponent("youspeed-trip-\(id).zip")
        try JournalZIP.write(directory: root, to: url)
        return url
    }
    func backup(password: String) throws -> URL {
        guard password.count >= 8 else { throw JournalFailure(journalText("password_minimum")) }
        let payload: Data = try queue.sync {
            checkpoint()
            return try JSONSerialization.data(withJSONObject: ["schema_version": 1, "kind": "youspeed-journal-backup", "trips": rows("SELECT * FROM trips"), "events": rows("SELECT * FROM events"), "bindings": rows("SELECT * FROM bindings"), "counters": rows("SELECT * FROM counters")], options: .sortedKeys)
        }
        let salt = Data((0..<16).map { _ in UInt8.random(in: 0...255) })
        let key = try Self.backupKey(password: password, salt: salt, iterations: 100_000)
        let box = try AES.GCM.seal(payload, using: key)
        let sealed = box.combined!
        let envelope: [String: Any] = ["backup_version": 1, "cipher": "AES-256-GCM", "kdf": "PBKDF2-HMAC-SHA256", "iterations": 100_000, "salt": salt.base64EncodedString(), "sealed": sealed.base64EncodedString(), "sha256": TripJournalExport.hash(sealed)]
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("youspeed-journal-\(UUID().uuidString).ysjournal")
        try JSONSerialization.data(withJSONObject: envelope, options: .sortedKeys).write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        return url
    }
    func restore(from url: URL, password: String) throws {
        let accessing = url.startAccessingSecurityScopedResource(); defer { if accessing { url.stopAccessingSecurityScopedResource() } }
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size <= 512 * 1024 * 1024 else { throw JournalFailure("Backup exceeds the supported size") }
        let bytes = try Data(contentsOf: url)
        guard let envelope = try JSONSerialization.jsonObject(with: bytes) as? [String: Any], envelope["backup_version"] as? Int == 1,
              envelope["cipher"] as? String == "AES-256-GCM", envelope["kdf"] as? String == "PBKDF2-HMAC-SHA256", envelope["iterations"] as? Int == 100_000,
              let saltText = envelope["salt"] as? String, let salt = Data(base64Encoded: saltText), salt.count == 16,
              let text = envelope["sealed"] as? String, let sealed = Data(base64Encoded: text),
              envelope["sha256"] as? String == TripJournalExport.hash(sealed) else { throw JournalFailure("Unsupported or damaged backup") }
        let payload = try AES.GCM.open(AES.GCM.SealedBox(combined: sealed), using: Self.backupKey(password: password, salt: salt, iterations: 100_000))
        guard let data = try JSONSerialization.jsonObject(with: payload) as? [String: Any], data["schema_version"] as? Int == 1, data["kind"] as? String == "youspeed-journal-backup",
              let trips = data["trips"] as? [[String: Any]], let events = data["events"] as? [[String: Any]], let bindings = data["bindings"] as? [[String: Any]], let counters = data["counters"] as? [[String: Any]], counters.count == 1,
              let origin = counters[0]["origin"] as? Double, origin.isFinite,
              let distance = counters[0]["distance"] as? Double, distance.isFinite, distance >= 0,
              let usage = counters[0]["usage"] as? Double, usage.isFinite, usage >= 0 else { throw JournalFailure("Invalid backup data") }
        let ids = Set(trips.compactMap { $0["id"] as? String })
        let sequences = events.compactMap { $0["seq"] as? Double }
        guard sequences.count == events.count, Set(sequences).count == sequences.count,
              sequences.allSatisfy({ $0.isFinite && $0 >= 1 && $0 < Double(Int64.max) && $0.rounded() == $0 }),
              Set(bindings.compactMap { $0["session"] as? String }).count == bindings.count else { throw JournalFailure("Invalid backup sequences") }
        guard ids.count == trips.count, ids.allSatisfy({ UUID(uuidString: $0) != nil }), trips.allSatisfy({ ($0["start"] as? Double)?.isFinite == true && ($0["distance"] as? Double).map { $0.isFinite && $0 >= 0 } == true }), events.allSatisfy({ ids.contains($0["trip"] as? String ?? "") && ($0["time"] as? Double)?.isFinite == true && ($0["payload"] as? String).flatMap { $0.data(using: .utf8) }.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } != nil }), bindings.allSatisfy({ ids.contains($0["trip"] as? String ?? "") && $0["session"] is String }) else { throw JournalFailure("Invalid backup references") }
        try queue.sync {
            let ok = transaction {
                self.sql("DELETE FROM events"); self.sql("DELETE FROM bindings"); self.sql("DELETE FROM trips")
                self.sql("UPDATE counters SET origin=?,distance=?,usage=? WHERE id=1", [origin, distance, usage])
                for trip in trips {
                    let fields = ["id", "start", "end", "state", "distance", "duration", "odo_start", "odo_end", "last_observed", "end_reason", "timezone_seconds", "vehicle", "observed"]
                    let restored = ["active", "finalizing"].contains(trip["state"] as? String ?? "")
                    self.sql("INSERT INTO trips(\(fields.joined(separator: ","))) VALUES(\(fields.map { _ in "?" }.joined(separator: ",")))", fields.map { key -> Any in if restored && key == "state" { return "interrupted" }; if restored && key == "end_reason" { return "backup_restored" }; return trip[key] ?? NSNull() })
                }
                for event in events { self.sql("INSERT INTO events(seq,trip,kind,time,payload) VALUES(?,?,?,?,?)", [event["seq"]!, event["trip"]!, event["kind"] ?? "unknown", event["time"]!, event["payload"]!]) }
                for binding in bindings { self.sql("INSERT INTO bindings(session,trip) VALUES(?,?)", [binding["session"]!, binding["trip"]!]) }
            }
            guard ok else { throw JournalFailure("Restore failed; existing journal was preserved") }
            active = nil; finalizing = nil; liveVideoOwners.removeAll(); requested = false; endedLatch = true; previous = nil; lastFixTime = nil; usageAnchor = Self.monotonic()
            if let exports = try? FileManager.default.contentsOfDirectory(at: FileManager.default.temporaryDirectory, includingPropertiesForKeys: nil) {
                for file in exports where file.lastPathComponent.hasPrefix("trip-") { try? FileManager.default.removeItem(at: file) }
            }
            removeTemporaryBackups(except: url)
        }
    }
    private static func backupKey(password: String, salt: Data, iterations: Int) throws -> SymmetricKey {
        let passwordKey = SymmetricKey(data: Data(password.utf8))
        var first = salt; first.append(contentsOf: [0, 0, 0, 1])
        var block = Data(HMAC<SHA256>.authenticationCode(for: first, using: passwordKey)), result = block
        for _ in 1..<iterations {
            block = Data(HMAC<SHA256>.authenticationCode(for: block, using: passwordKey))
            for i in result.indices { result[i] ^= block[i] }
        }
        return SymmetricKey(data: result)
    }
}

private struct JournalFailure: LocalizedError { let message: String; init(_ message: String) { self.message = message }; var errorDescription: String? { message } }

struct TripExportOptions {
    var masked = false
    var maskRadiusMetres = 300.0
    var homeCoordinate: CLLocationCoordinate2D?
    var includeRawLogs = true
    var includeOdometer = false
    var selectedMedia = Set<String>()
}

struct JournalEvent: Identifiable {
    let id: Int
    let kind: String
    let time: Date
    let payload: [String: Any]
    init(_ row: [String: Any]) {
        id = Int(row["seq"] as? Double ?? 0); kind = row["kind"] as? String ?? "unknown"
        time = Date(timeIntervalSince1970: row["time"] as? Double ?? 0)
        payload = (row["payload"] as? String).flatMap { $0.data(using: .utf8) }.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
    }
    var coordinate: CLLocationCoordinate2D? {
        let nested = payload["position"] as? [String: Any] ?? payload["location"] as? [String: Any] ?? [:]
        guard let lat = (payload["latitude"] ?? payload["lat"] ?? nested["latitude"] ?? nested["lat"]) as? Double,
              let lon = (payload["longitude"] ?? payload["lon"] ?? nested["longitude"] ?? nested["lon"]) as? Double,
              lat.isFinite, lon.isFinite, abs(lat) <= 90, abs(lon) <= 180 else { return nil }
        return CLLocationCoordinate2D(latitude: lat, longitude: lon)
    }
    var trackEligible: Bool { kind == "gps" && (payload["track_eligible"] as? Bool ?? payload["valid"] as? Bool ?? false) }
    var className: String { (payload["normalized_class"] ?? payload["class_code"] ?? payload["normalized_code"] ?? payload["sign_code"] ?? payload["class"] ?? payload["code"]) as? String ?? "" }
    var title: String {
        if kind == "sign" { return className.isEmpty ? journalText("sign") : className }
        if kind == "gps" { return (payload["speed"] as? Double).map { String(format: "%.0f km/h", max(0, $0) * 3.6) } ?? journalText("gps") }
        if kind == "media" { return payload["type"] as? String == "video" ? journalText("videos") : journalText("photos") }
        return journalText(kind)
    }
    var summary: String { (payload["reason"] ?? payload["outcome"] ?? payload["source"] ?? payload["evidence_source"] ?? payload["message"]) as? String ?? "" }
}

/// A discovery is a projection; every underlying update stays in the original sign/TSR logs.
enum JournalDiscoveries {
    static func project(_ events: [JournalEvent]) -> [JournalEvent] {
        var result = [JournalEvent](), indices = [String: Int](), latest = [String: Date]()
        for event in events where event.kind == "sign" {
            let explicit = (event.payload["encounter_id"] ?? event.payload["track_id"] ?? event.payload["physical_track_id"]) as? String
            let source = event.payload["evidence_source"] as? String ?? event.payload["source"] as? String ?? "unknown"
            let key = explicit ?? source + ":" + event.className
            if let index = indices[key], explicit != nil || event.time.timeIntervalSince(latest[key] ?? .distantPast) <= 15 {
                let old = result[index]
                var payload = old.payload
                for (key, value) in event.payload { payload[key] = value }
                payload["source_event_ids"] = (old.payload["source_event_ids"] as? [Int] ?? [old.id]) + [event.id]
                payload["updates"] = (old.payload["updates"] as? Int ?? 1) + 1
                payload["last_observed_at"] = event.time.timeIntervalSince1970
                // Keep the original encounter time and coordinate associated with that time.
                for coordinate in ["latitude", "longitude", "lat", "lon", "position", "location"] { payload[coordinate] = old.payload[coordinate] }
                if let bytes = try? JSONSerialization.data(withJSONObject: payload), let text = String(data: bytes, encoding: .utf8) {
                    result[index] = JournalEvent(["seq": Double(old.id), "time": old.time.timeIntervalSince1970, "kind": "sign", "payload": text])
                }
            } else { indices[key] = result.count; result.append(event) }
            latest[key] = event.time
        }
        return result
    }
}

struct JournalMedia: Identifiable {
    let id: String
    var payload: [String: Any]
    var capturedAt: Date
    var type: String { payload["type"] as? String ?? "photo" }
    var session: String { payload["session"] as? String ?? id }
    var path: String { payload["path"] as? String ?? "" }
    var localURL: URL? { let local = payload["local_path"] as? String ?? path; return !local.hasPrefix("https://") && FileManager.default.fileExists(atPath: local) ? URL(fileURLWithPath: local) : nil }
    var remoteURL: URL? { let remote = payload["remote_url"] as? String ?? path; guard remote.hasPrefix("https://") else { return nil }; return URL(string: remote) }
    var startedAt: Date? { (payload["started_at"] as? Double).map(Date.init(timeIntervalSince1970:)) }
    var duration: Double? { payload["duration_s"] as? Double }
    func offset(at date: Date) -> Double? {
        guard type == "video", payload["timing_quality"] as? String != "clock_alignment_uncertain", let start = startedAt, let duration, localURL != nil else { return nil }
        let offset = date.timeIntervalSince(start)
        return offset >= 0 && offset <= duration ? offset + (payload["presentation_start_s"] as? Double ?? 0) : nil
    }
    static func project(_ events: [JournalEvent]) -> [JournalMedia] {
        var result = [String: JournalMedia]()
        for event in events where event.kind == "media" {
            guard let id = event.payload["id"] as? String else { continue }
            if var existing = result[id] {
                for (key, value) in event.payload {
                    if key == "path", let remote = value as? String, remote.hasPrefix("https://") { existing.payload["remote_url"] = remote }
                    else { existing.payload[key] = value }
                }
                result[id] = existing
            } else {
                var payload = event.payload
                if let path = payload["path"] as? String, !path.hasPrefix("https://") { payload["local_path"] = path }
                result[id] = JournalMedia(id: id, payload: payload, capturedAt: event.time)
            }
        }
        return result.values.sorted { $0.capturedAt < $1.capturedAt }
    }
}

private enum TripJournalExport {
    static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private static func json(_ value: Any, to url: URL) throws { try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]).write(to: url, options: .atomic) }
    private static func csv(_ value: Any?) -> String {
        var string = value.map { String(describing: $0) } ?? ""
        if ["=", "+", "-", "@", "\t", "\r"].contains(where: { string.hasPrefix($0) }) { string = "'" + string }
        return "\"" + string.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }
    static func write(trip original: [String: Any], events raw: [[String: Any]], counters: [String: Any], options: TripExportOptions, to root: URL) throws {
        let all = raw.map(JournalEvent.init).filter { options.includeOdometer || $0.kind != "odometer_entry" }, points = all.filter(\.trackEligible)
        let ends = [points.first?.coordinate, points.last?.coordinate, options.homeCoordinate].compactMap { $0 }
        func hidden(_ coordinate: CLLocationCoordinate2D?) -> Bool {
            guard options.masked, let coordinate else { return false }
            let point = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
            return ends.contains { point.distance(from: CLLocation(latitude: $0.latitude, longitude: $0.longitude)) <= options.maskRadiusMetres }
        }
        let visible = all.filter { !hidden($0.coordinate) }
                var trip = original
        if !options.includeOdometer { trip.removeValue(forKey: "odo_start"); trip.removeValue(forKey: "odo_end") }
        if options.masked { for key in ["vehicle", "start_place", "end_place"] { trip.removeValue(forKey: key) } }
        let envelope: [String: Any] = ["schema_version": 1, "generated_at": ISO8601DateFormatter().string(from: Date()), "measurement_policy_version": 1, "coordinate_order": "longitude,latitude", "distance_unit": "metre", "duration_unit": "second", "timestamp_unit": "unix_seconds_utc", "in_progress_snapshot": ["active", "finalizing"].contains(trip["state"] as? String ?? ""), "masked": options.masked, "trip": trip]
        try json(envelope, to: root.appendingPathComponent("trip.json"))
        try json(["schema_version": 1, "counter_origin": counters["origin"] ?? NSNull(), "lifetime_distance_m": counters["distance"] ?? 0, "lifetime_usage_s": counters["usage"] ?? 0, "trip_distance_m": trip["distance"] ?? 0], to: root.appendingPathComponent("counters.json"))
        try Data(("counter_origin,lifetime_distance_m,lifetime_usage_s,trip_distance_m\n" + [counters["origin"], counters["distance"], counters["usage"], trip["distance"]].map(csv).joined(separator: ",") + "\n").utf8).write(to: root.appendingPathComponent("counters.csv"))
        var segments = [[[Double]]](), current = [[Double]](), gpx = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><gpx version=\"1.1\" creator=\"YouSpeed\" xmlns=\"http://www.topografix.com/GPX/1/1\"><trk><trkseg>"
        var visibleDistance = 0.0, prior: JournalEvent?, breakNext = true
        for event in all {
            if event.kind == "gap" { breakNext = true; continue }
            guard event.trackEligible, let c = event.coordinate else { continue }
            if hidden(c) { breakNext = true; continue }
            let reason = event.payload["reason"] as? String ?? ""
            if (breakNext || reason != "accepted") && !current.isEmpty {
                segments.append(current); current = []; gpx += "</trkseg><trkseg>"; prior = nil
            }
            breakNext = false
            current.append([c.longitude, c.latitude])
            gpx += "<trkpt lat=\"\(c.latitude)\" lon=\"\(c.longitude)\">"
            if let elevation = event.payload["altitude"] as? Double { gpx += "<ele>\(elevation)</ele>" }
            gpx += "<time>\(ISO8601DateFormatter().string(from: event.time))</time></trkpt>"
            if let a = prior?.coordinate { visibleDistance += CLLocation(latitude: a.latitude, longitude: a.longitude).distance(from: CLLocation(latitude: c.latitude, longitude: c.longitude)) }
            prior = event
        }
        if !current.isEmpty { segments.append(current) }
        gpx += "</trkseg></trk></gpx>"
        try Data(gpx.utf8).write(to: root.appendingPathComponent("track.gpx"), options: .atomic)
        try json(["type": "Feature", "geometry": ["type": "MultiLineString", "coordinates": segments.filter { $0.count >= 2 }], "properties": ["masked": options.masked, "measured_distance_m": original["distance"] ?? 0, "shared_geometry_distance_m": visibleDistance]], to: root.appendingPathComponent("track.geojson"))
        // Free-text TSR diagnostics can contain unstructured coordinates/road IDs. Never place them in a private sharing copy.
        let allowedRaw = !options.masked && options.includeRawLogs
        var safeEvents = [[String: Any]]()
        for kind in ["gps", "tsr", "gap", "sign"] {
            let events = (kind == "sign" ? JournalDiscoveries.project(visible) : all).filter { $0.kind == kind && (allowedRaw || kind == "sign" || kind == "gap") }
            var rows = [[String: Any]]()
            for event in events {
                var payload = event.payload
                if options.masked {
                    let safe = Set(["class_code", "latitude", "longitude", "lat", "lon", "source", "evidence_source", "sign_code", "normalized_code", "normalized_class", "class", "code", "confidence", "score", "numeric_value", "unit", "outcome", "reason"])
                    payload = payload.filter { safe.contains($0.key) }
                }
                rows.append(["schema_version": 1, "seq": event.id, "time": event.time.timeIntervalSince1970, "kind": event.kind, "payload": payload])
            }
            safeEvents.append(contentsOf: rows)
            let lines = try rows.map { String(data: try JSONSerialization.data(withJSONObject: $0, options: .sortedKeys), encoding: .utf8)! }.joined(separator: "\n")
            try Data(lines.utf8).write(to: root.appendingPathComponent("\(kind).ndjson"), options: .atomic)
            try json(["schema_version": 1, "events": rows], to: root.appendingPathComponent("\(kind).json"))
            let text = "sequence,time_utc,payload_json\n" + (try rows.map { row in
                [csv(row["seq"]), csv(ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: row["time"] as! Double))), csv(String(data: try JSONSerialization.data(withJSONObject: row["payload"]!, options: .sortedKeys), encoding: .utf8)!)].joined(separator: ",")
            }).joined(separator: "\n")
            try Data(text.utf8).write(to: root.appendingPathComponent("\(kind).csv"), options: .atomic)
        }
        var mediaRows = [[String: Any]](), omitted = [[String: String]]()
        for media in JournalMedia.project(all) {
            let nearest = points.min { abs($0.time.timeIntervalSince(media.capturedAt)) < abs($1.time.timeIntervalSince(media.capturedAt)) }
            let direct = JournalEvent(["payload": String(data: try JSONSerialization.data(withJSONObject: media.payload), encoding: .utf8)!]).coordinate
            let located = direct ?? nearest.flatMap { abs($0.time.timeIntervalSince(media.capturedAt)) <= 3 ? $0.coordinate : nil }
            if options.masked && (media.type == "video" || located == nil || hidden(located)) {
                omitted.append(["id": media.id, "reason": located == nil ? "unproven_photo_location" : "privacy_mask"]); continue
            }
            var row = media.payload
            row.removeValue(forKey: "path"); row.removeValue(forKey: "local_path")
            if options.masked { row = ["id": media.id, "type": media.type, "captured_at": media.capturedAt.timeIntervalSince1970] }
            if options.selectedMedia.contains(media.id), let source = media.localURL {
                let name = "media/\(UUID().uuidString).\(options.masked ? "jpg" : source.pathExtension)"
                let destination = root.appendingPathComponent(name)
                try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
                if options.masked {
                    guard let image = UIImage(contentsOfFile: source.path), let bytes = image.jpegData(compressionQuality: 0.95) else { omitted.append(["id": media.id, "reason": "photo_metadata_stripping_failed"]); continue }
                    try bytes.write(to: destination, options: .atomic)
                } else { try FileManager.default.copyItem(at: source, to: destination) }
                row["archive_path"] = name
            } else { omitted.append(["id": media.id, "reason": media.localURL == nil ? "local_media_unavailable" : "media_not_selected"]) }
            mediaRows.append(row)
        }
        try json(["schema_version": 1, "media": mediaRows, "omitted": omitted], to: root.appendingPathComponent("media.json"))
        let canonicalEvents: [[String: Any]] = allowedRaw ? all.map { ["seq": $0.id, "time": $0.time.timeIntervalSince1970, "kind": $0.kind, "payload": $0.payload] } : safeEvents
        let rawSignEvents = allowedRaw ? all.filter { $0.kind == "sign" }.map { ["seq": $0.id, "time": $0.time.timeIntervalSince1970, "kind": $0.kind, "payload": $0.payload] as [String: Any] } : []
        try Data(try rawSignEvents.map { String(data: try JSONSerialization.data(withJSONObject: $0, options: .sortedKeys), encoding: .utf8)! }.joined(separator: "\n").utf8).write(to: root.appendingPathComponent("sign_events.ndjson"))
        let mediaEvents = canonicalEvents.filter { $0["kind"] as? String == "media" }
        try Data(try mediaEvents.map { String(data: try JSONSerialization.data(withJSONObject: $0, options: .sortedKeys), encoding: .utf8)! }.joined(separator: "\n").utf8).write(to: root.appendingPathComponent("media.ndjson"))
        let state = trip["state"] as? String ?? "interrupted"
        var canonicalTrip: [String: Any] = ["id": trip["id"] ?? "", "started_at": trip["start"] ?? 0, "ended_at": trip["end"] ?? NSNull(), "distance_m": trip["distance"] ?? 0, "duration_s": trip["duration"] ?? 0, "state": state == "disabled" ? "ended" : state == "finalizing" ? "active" : state]
        if let vehicle = trip["vehicle"] { canonicalTrip["vehicle"] = vehicle }
        if let reading = trip["odo_start"] { canonicalTrip["odometer_start_km"] = reading }
        if let reading = trip["odo_end"] { canonicalTrip["odometer_end_km"] = reading }
        if options.includeOdometer { canonicalTrip["odometer_entries"] = all.filter { $0.kind == "odometer_entry" }.map(\.payload) }
        try json(["schema_version": 1, "generated_at": ISO8601DateFormatter().string(from: Date()), "measurement_policy_version": 1,
                  "units": ["distance": "metre", "duration": "second", "speed": "metres_per_second", "coordinates": "longitude,latitude", "event_time": "unix_seconds_utc"],
                  "trip": canonicalTrip, "events": canonicalEvents, "media": mediaRows, "privacy": ["masked": options.masked, "raw_logs_included": allowedRaw]], to: root.appendingPathComponent("journal.json"))
        let summary = "YouSpeed Fahrtenbuch\n\n" + journalText("scope") + "\n\n" + trip.keys.sorted().map { "\($0): \(trip[$0]!)" }.joined(separator: "\n") + "\n\n\(journalText("distance")): \(original["distance"] ?? 0) m\nShared geometry: \(visibleDistance) m\nMasked: \(options.masked)\n\(journalText("share_residual"))"
        let pdf = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 595, height: 842)).pdfData { context in
            let lines = summary.components(separatedBy: "\n")
            for start in stride(from: 0, to: lines.count, by: 40) {
                context.beginPage(); (lines[start..<min(start + 40, lines.count)].joined(separator: "\n") as NSString).draw(in: CGRect(x: 40, y: 40, width: 515, height: 750), withAttributes: [.font: UIFont.systemFont(ofSize: 12)])
            }
        }
        try pdf.write(to: root.appendingPathComponent("overview.pdf"), options: .atomic)
        try Data(("started_at,ended_at,distance_m,duration_s,state,vehicle,odo_start_km,odo_end_km\n" + [trip["start"], trip["end"], trip["distance"], trip["duration"], trip["state"], trip["vehicle"], trip["odo_start"], trip["odo_end"]].map(csv).joined(separator: ",") + "\n").utf8).write(to: root.appendingPathComponent("overview.csv"))
        var files = [[String: Any]]()
        if let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey]) {
            for case let file as URL in enumerator where (try file.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true {
                let bytes = try Data(contentsOf: file); files.append(["file": String(file.path.dropFirst(root.path.count + 1)), "bytes": bytes.count, "sha256": hash(bytes)])
            }
        }
        try json(["schema_version": 1, "generated_at": ISO8601DateFormatter().string(from: Date()), "files": files, "masked": options.masked, "raw_logs_included": allowedRaw, "omitted_media": omitted, "coverage_gaps": all.filter { $0.kind == "gap" }.count, "snapshot_state": trip["state"] ?? "unknown"], to: root.appendingPathComponent("manifest.json"))
    }
}

/// Portable store-only ZIP. Media already uses compressed codecs; no shell or external archiver is required.
private enum JournalZIP {
    static func write(directory: URL, to output: URL) throws {
        let files = (FileManager.default.enumerator(at: directory, includingPropertiesForKeys: [.isRegularFileKey])?.allObjects as? [URL] ?? []).filter { $0 != output && ((try? $0.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile) == true) }.sorted { $0.path < $1.path }
        guard files.count <= 65535 else { throw JournalFailure("Archive has too many files") }
        FileManager.default.createFile(atPath: output.path, contents: nil)
        let handle = try FileHandle(forWritingTo: output); defer { try? handle.close() }
        var central = Data(), offset: UInt64 = 0
        func u16(_ n: UInt16) -> Data { var v = n.littleEndian; return withUnsafeBytes(of: &v) { Data($0) } }
        func u32(_ n: UInt32) -> Data { var v = n.littleEndian; return withUnsafeBytes(of: &v) { Data($0) } }
        for file in files {
            let bytes = try Data(contentsOf: file, options: .mappedIfSafe), name = Data(String(file.path.dropFirst(directory.path.count + 1)).utf8)
            guard bytes.count <= UInt32.max, offset <= UInt32.max, name.count <= UInt16.max else { throw JournalFailure("Archive exceeds 4 GB; export fewer videos") }
            var crc: UInt32 = 0xffffffff
            for byte in bytes { crc ^= UInt32(byte); for _ in 0..<8 { crc = (crc >> 1) ^ (crc & 1 == 1 ? 0xedb88320 : 0) } }
            crc ^= 0xffffffff
            var local = u32(0x04034b50); local += u16(20); local += u16(0x800); local += u16(0); local += u16(0); local += u16(0x21); local += u32(crc); local += u32(UInt32(bytes.count)); local += u32(UInt32(bytes.count)); local += u16(UInt16(name.count)); local += u16(0); local += name
            try handle.write(contentsOf: local); try handle.write(contentsOf: bytes)
            central += u32(0x02014b50); central += u16(20); central += u16(20); central += u16(0x800); central += u16(0); central += u16(0); central += u16(0x21); central += u32(crc); central += u32(UInt32(bytes.count)); central += u32(UInt32(bytes.count)); central += u16(UInt16(name.count)); central += u16(0); central += u16(0); central += u16(0); central += u16(0); central += u32(0); central += u32(UInt32(offset)); central += name
            offset += UInt64(local.count + bytes.count)
        }
        guard offset <= UInt32.max, central.count <= UInt32.max else { throw JournalFailure("Archive exceeds 4 GB; export fewer videos") }
        try handle.write(contentsOf: central)
        var end = u32(0x06054b50); end += u16(0); end += u16(0); end += u16(UInt16(files.count)); end += u16(UInt16(files.count)); end += u32(UInt32(central.count)); end += u32(UInt32(offset)); end += u16(0)
        try handle.write(contentsOf: end)
    }
}

struct TripJournalMediaDeletionResult {
    var removed = 0
    var protected = 0
    var failed = 0
    var unavailable = 0
}

/// History filters use local calendar dates and include each selected end date in full.
/// Trips spanning midnight belong to their recorded start date; no trip facts or counters are split.
enum JournalHistoryRange {
    static func includes(start: Double, periodDays: Int, customFrom: Date? = nil, customTo: Date? = nil,
                         now: Date = Date(), calendar: Calendar = .current) -> Bool {
        guard start.isFinite else { return false }
        let timestamp = Date(timeIntervalSince1970: start)
        if let from = customFrom, let to = customTo {
            let lower = calendar.startOfDay(for: from), last = calendar.startOfDay(for: to)
            guard last >= lower, let upper = calendar.date(byAdding: .day, value: 1, to: last) else { return false }
            return timestamp >= lower && timestamp < upper
        }
        guard periodDays > 0 else { return true }
        let today = calendar.startOfDay(for: now)
        guard let lower = calendar.date(byAdding: .day, value: 1 - periodDays, to: today),
              let upper = calendar.date(byAdding: .day, value: 1, to: today) else { return false }
        return timestamp >= lower && timestamp < upper
    }
}

struct JournalPeriodDay: Identifiable {
    let date: Date
    var distanceMetres = 0.0
    var durationSeconds = 0.0
    var observedSeconds = 0.0
    var tripCount = 0
    var id: Date { date }
}

enum JournalHistoryProjection {
    static func days(_ trips: [[String: Any]], calendar: Calendar = .current) -> [JournalPeriodDay] {
        var buckets = [Date: JournalPeriodDay]()
        func nonnegative(_ value: Any?) -> Double { guard let number = value as? Double, number.isFinite else { return 0 }; return max(0, number) }
        for trip in trips {
            guard let start = trip["start"] as? Double, start.isFinite else { continue }
            let date = calendar.startOfDay(for: Date(timeIntervalSince1970: start))
            var bucket = buckets[date] ?? JournalPeriodDay(date: date)
            bucket.distanceMetres += nonnegative(trip["distance"])
            bucket.durationSeconds += nonnegative(trip["duration"])
            bucket.observedSeconds += nonnegative(trip["observed"])
            bucket.tripCount += 1
            buckets[date] = bucket
        }
        return buckets.values.sorted { $0.date < $1.date }
    }
}

private struct JournalPeriodChart: View {
    let trips: [[String: Any]]
    @State private var metric = "distance"
    private var days: [JournalPeriodDay] { JournalHistoryProjection.days(trips) }
    private var unit: String { metric == "distance" ? "km" : "h" }
    private var title: String {
        metric == "distance" ? journalText("daily_distance") : metric == "observed" ? journalText("daily_observed") : journalText("daily_duration")
    }
    private func value(_ day: JournalPeriodDay) -> Double {
        metric == "distance" ? day.distanceMetres / 1000 : (metric == "observed" ? day.observedSeconds : day.durationSeconds) / 3600
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Picker(journalText("chart_metric"), selection: $metric) {
                Text(journalText("chart_distance")).tag("distance")
                Text(journalText("chart_observed")).tag("observed")
                Text(journalText("duration")).tag("duration")
            }.pickerStyle(.menu)
            if days.isEmpty { Text(journalText("no_events")).font(.caption).foregroundStyle(.secondary) }
            else {
                Text(title).font(.caption.weight(.semibold))
                Chart(days) { day in
                    BarMark(x: .value(journalText("day"), day.date, unit: .day),
                            y: .value(unit, value(day)))
                        .foregroundStyle(Color.accentColor)
                        .accessibilityLabel(day.date.formatted(date: .complete, time: .omitted))
                        .accessibilityValue(String(format: "%.3f %@", locale: Locale.current, value(day), unit))
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 4)) { _ in
                        AxisGridLine(); AxisTick(); AxisValueLabel(format: .dateTime.day().month(.abbreviated))
                    }
                }
                .chartYAxis { AxisMarks(values: .automatic(desiredCount: 3)) }
                .chartYAxisLabel(unit)
                .frame(height: 135)
                .accessibilityLabel(title)
                .accessibilityIdentifier("journal.periodChart")
                Text(journalText("chart_scope")).font(.caption).foregroundStyle(.secondary)
                DisclosureGroup(journalText("daily_totals")) {
                    ForEach(days) { day in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(day.date, format: .dateTime.day().month().year()).font(.caption.weight(.semibold))
                            Text(String(format: "%d · %.3f km · %.2f h", locale: Locale.current, day.tripCount, day.distanceMetres / 1000, day.observedSeconds / 3600)).font(.caption.monospacedDigit())
                                .accessibilityLabel(Text(String(format: journalText("daily_accessibility"), locale: Locale.current, day.tripCount, day.distanceMetres / 1000, day.observedSeconds / 3600, day.durationSeconds / 3600)))
                        }.padding(.vertical, 3)
                    }
                }
            }
        }
    }
}

/// Display-only endpoint names; never add private place labels to exported trip fields.
enum JournalHistoryPresentation {
    static func emptyMessage(recordingEnabled:Bool) -> String {
        journalText(recordingEnabled ? "empty":"recording_off_history")
    }
    static func number(_ value: Double, locale: Locale = .current) -> String {
        let formatter = NumberFormatter(); formatter.locale = locale; formatter.numberStyle = .decimal
        formatter.minimumFractionDigits = 1; formatter.maximumFractionDigits = 1
        return formatter.string(from: NSNumber(value: value)) ?? "—"
    }
    static func endpointNames(trip: [String: Any], events: [JournalEvent]) -> (start: String, end: String) {
        let points = events.filter { $0.trackEligible && $0.coordinate != nil }
        func name(_ key: String, endpoint: JournalEvent?) -> String {
            if let stored = trip[key] as? String, !stored.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return stored }
            guard let endpoint, let coordinate = endpoint.coordinate else { return journalText("location_unknown") }
            let candidate = events.filter { event in
                guard event.kind == "place" || event.kind == "gps", abs(event.time.timeIntervalSince(endpoint.time)) <= 15,
                      let place = event.coordinate else { return false }
                let from = min(event.time, endpoint.time), to = max(event.time, endpoint.time)
                guard !events.contains(where: { $0.kind == "gap" && $0.time > from && $0.time <= to }) else { return false }
                let tolerance = max(50, max(endpoint.payload["accuracy"] as? Double ?? 0, event.payload["accuracy"] as? Double ?? 0))
                guard tolerance.isFinite, CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude).distance(from: CLLocation(latitude: place.latitude, longitude: place.longitude)) <= tolerance else { return false }
                return !placeName(event).isEmpty
            }.min { abs($0.time.timeIntervalSince(endpoint.time)) < abs($1.time.timeIntervalSince(endpoint.time)) }
            return candidate.map(placeName) ?? journalText("location_unknown")
        }
        return (name("start_place", endpoint: points.first), name("end_place", endpoint: points.last))
    }
    private static func placeName(_ event: JournalEvent) -> String {
        let context = event.payload["road_context"] as? [String: Any] ?? event.payload["roadContext"] as? [String: Any] ?? [:]
        func text(_ keys: [String]) -> String? {
            keys.compactMap { (event.payload[$0] ?? context[$0]) as? String }.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.first { !$0.isEmpty }
        }
        let street = text(["street_name", "streetName"]), city = text(["city_name", "cityName", "locality"])
        let values = [street, city].compactMap { $0 }
        return values.isEmpty ? text(["place_name", "placeName"]) ?? "" : Array(NSOrderedSet(array: values)).compactMap { $0 as? String }.joined(separator: ", ")
    }
}

struct TripJournalRecordingSettings: View {
    @ObservedObject private var journal = TripJournal.shared
    @State private var revision = 0
    var body: some View {
        Text(journalText("scope")).font(.footnote).foregroundStyle(.secondary)
        Text(journalText("consent")).font(.footnote).foregroundStyle(.secondary)
        Toggle(journalText("automatic"), isOn: Binding(get: { journal.enabled }, set: { journal.setEnabled($0); revision += 1 }))
            .accessibilityIdentifier("settings.journal.recording")
            .id(revision)
    }
}

/// Optional choice within the existing Driving setup step; appearance never writes a preference.
struct TripJournalSetupOption: View {
    @ObservedObject private var journal = TripJournal.shared
    @State private var revision = 0
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            Text(journalText("setup_title")).font(.headline)
            Toggle(journalText("automatic"),isOn:Binding(get:{journal.enabled},set:{journal.setEnabled($0);revision += 1}))
                .accessibilityIdentifier("onboarding.journal.recording")
            Text(journalText("setup_disclosure")).font(.footnote).foregroundStyle(.secondary)
                .accessibilityIdentifier("onboarding.journal.disclosure")
        }
        .id(revision)
    }
}

/// Less frequent data operations stay inline in normal Settings.
struct TripJournalDataSettings: View {
    @ObservedObject private var journal = TripJournal.shared
    @State private var password = ""
    @State private var busy = false
    @State private var importing = false
    @State private var restoreConfirmation = false
    @State private var clearConfirmation = false
    @State private var restoreURL: URL?
    @State private var files: [URL] = []
    @State private var sharing = false
    @State private var error: String?
    var body: some View {
        DisclosureGroup(journalText("backup")) {
            Text(journalText("backup_help")).font(.footnote).foregroundStyle(.secondary)
            SecureField(journalText("password"), text: $password).textContentType(.newPassword)
            Button(journalText("save_backup")) { run { [password] in [try journal.backup(password: password)] } }.disabled(password.count < 8 || busy)
                .accessibilityIdentifier("settings.journal.backup")
            Button(journalText("restore")) { importing = true }.disabled(password.count < 8 || busy)
                .accessibilityIdentifier("settings.journal.restore")
            Button(journalText("clear_all"), role: .destructive) { clearConfirmation = true }.disabled(busy)
                .accessibilityIdentifier("settings.journal.clearAll")
            if busy { ProgressView() }
            if let error { Text(error).font(.footnote).foregroundStyle(.red) }
        }
        .confirmationDialog(journalText("clear_preview"), isPresented: $clearConfirmation) {
            Button(journalText("clear_all"), role: .destructive) { journal.clearAll() }
        }
        .confirmationDialog(journalText("restore_preview"), isPresented: $restoreConfirmation) {
            Button(journalText("restore"), role: .destructive) { if let url = restoreURL { run { [password] in try journal.restore(from: url, password: password); return [] } } }
        }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.data, .json]) { result in
            do { restoreURL = try result.get(); restoreConfirmation = true } catch { self.error = error.localizedDescription }
        }
        .sheet(isPresented: $sharing) { TripShareSheet(urls: files) }
    }
    private func run(_ operation: @escaping () throws -> [URL]) {
        busy = true; error = nil
        Task {
            do {
                files = try await Task.detached(priority: .userInitiated) { try operation() }.value
                sharing = !files.isEmpty
            } catch { self.error = error.localizedDescription }
            busy = false
        }
    }
}

private struct JournalTripSelection: Identifiable { let id: String }

private struct TripEndOdometerSheet: View {
    let id: String
    @ObservedObject var journal: TripJournal
    var saved: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var reading = ""
    @State private var error: String?
    var body: some View {
        let trip = journal.snapshot().trips.first { $0["id"] as? String == id } ?? [:]
        Form {
            Section {
                if let value = trip["odo_end"] as? Double {
                    LabeledContent(journalText("odo_end"), value: JournalHistoryPresentation.number(value) + " km")
                        .accessibilityIdentifier("journal.odometer.savedValue")
                } else {
                    TextField(journalText("odo_end") + " (km)", text: $reading).keyboardType(.decimalPad)
                        .accessibilityIdentifier("journal.odometer.input")
                    if let error { Text(error).foregroundStyle(.red).accessibilityIdentifier("journal.odometer.error") }
                }
                Button(journalText("save")) { if trip["odo_end"] != nil { dismiss() } else { save() } }
                    .accessibilityIdentifier("journal.odometer.save")
            }
        }
        .navigationTitle(journalText("odo_end"))
        .navigationBarTitleDisplayMode(.inline)
        .journalWhiteSurface()
        .subscreenCloseButton()
        .accessibilityIdentifier("journal.odometer.dialog")
    }
    private func save() {
        let text = reading.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { dismiss(); return }
        let formatter = NumberFormatter(); formatter.locale = .current; formatter.numberStyle = .decimal
        // Decimal input permits the local separator, without ambiguous thousands grouping.
        let separator = formatter.decimalSeparator ?? "."
        let normalized = text.replacingOccurrences(of: separator, with: ".")
        guard !normalized.contains(","), let value = Double(normalized), value.isFinite, value >= 0 else { error = journalText("invalid_odo"); return }
        do { try journal.enterEndOdometer(id, kilometres: value); saved(); dismiss() }
        catch { self.error = error.localizedDescription }
    }
}

private extension View {
    func journalWhiteSurface() -> some View {
        self.scrollContentBackground(.hidden).background(Color.white).preferredColorScheme(.light)
            .toolbarBackground(Color.white, for: .navigationBar).toolbarBackground(.visible, for: .navigationBar)
    }
}

struct TripJournalView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var journal: TripJournal
    var gallery: ((Set<String>, Set<String>) -> AnyView)? = nil
    var deleteMedia: (@MainActor (Set<String>, Set<String>) async -> TripJournalMediaDeletionResult)? = nil
    var openSettings: (() -> Void)? = nil
    init(journal: TripJournal = .shared, gallery: ((Set<String>, Set<String>) -> AnyView)? = nil,
         deleteMedia: (@MainActor (Set<String>, Set<String>) async -> TripJournalMediaDeletionResult)? = nil,
         openSettings:(() -> Void)? = nil) {
        self.journal = journal; self.gallery = gallery; self.deleteMedia = deleteMedia; self.openSettings = openSettings
    }
    @State private var selectedTrip: JournalTripSelection?
    @State private var pendingDelete: String?
    @State private var files: [URL] = []
    @State private var share = false
    @State private var busy = false
    @State private var operationError: String?
    @State private var operationStatus: String?
    @State private var revision = 0
    var body: some View {
        TimelineView(.periodic(from: .now, by: 5)) { _ in
            let _ = revision
            let trips = journal.snapshot().trips
            ScrollView(.vertical) {
                ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: 0) {
                    tableHeader
                    Divider()
                    if !journal.enabled {
                        VStack(alignment:.leading,spacing:6) {
                            Text(journalText("recording_off_history")).font(.footnote).foregroundStyle(.secondary)
                                .accessibilityIdentifier("journal.recording.off")
                            RecordingSafeButton(journalText("recording_settings")) {
                                if let openSettings { openSettings() } else { dismiss() }
                            }
                            .font(.footnote).buttonStyle(.borderless)
                            .accessibilityIdentifier("journal.recording.settings")
                        }
                        .frame(maxWidth:280,alignment:.leading).fixedSize(horizontal:false,vertical:true).padding(8)
                    }
                    if let error = journal.error { Text(error).font(.footnote).foregroundStyle(.red).padding(8) }
                    else if trips.isEmpty && journal.enabled { Text(JournalHistoryPresentation.emptyMessage(recordingEnabled:true)).font(.footnote).foregroundStyle(.secondary).padding(8) }
                    ForEach(trips.compactMap { row -> HistoryItem? in
                        guard let id = row["id"] as? String else { return nil }; return HistoryItem(id: id, trip: row)
                    }, id: \.id) { item in
                        historyRow(item.trip)
                        Divider()
                    }
                }
                .frame(minWidth: 690, alignment: .leading)
                .padding(.horizontal, 12)
                }
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("journal.history.table")
            }
            .overlay { if busy { ProgressView().padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12)) } }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .navigationTitle(journalText("navigation"))
        .journalWhiteSurface()
        .subscreenCloseButton()
        .accessibilityIdentifier("journal.history")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(journalText("delete_preview"), isPresented: Binding(get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } })) {
            Button(journalText("delete"), role: .destructive) { if let id = pendingDelete { journal.delete(id) }; pendingDelete = nil; revision += 1 }
            if let deleteMedia {
                Button(journalText("delete_with_media"), role: .destructive) {
                    guard let id = pendingDelete else { return }
                    let media = JournalMedia.project(journal.events(id).map(JournalEvent.init))
                    pendingDelete = nil; busy = true
                    Task { @MainActor in
                        let result = await deleteMedia(Set(media.filter { $0.type == "photo" }.map(\.id)), Set(media.filter { $0.type == "video" }.map(\.id)))
                        journal.delete(id)
                        operationStatus = String(format: journalText("deletion_result"), result.removed, result.protected, result.failed, result.unavailable)
                        busy = false; revision += 1
                    }
                }
            }
        }
        .alert(journalText("title"), isPresented: Binding(get: { operationError != nil || operationStatus != nil }, set: { if !$0 { operationError = nil; operationStatus = nil } })) {
            Button("OK", role: .cancel) { operationError = nil; operationStatus = nil }
        } message: { Text(operationError ?? operationStatus ?? "") }
        .sheet(isPresented: $share) { TripShareSheet(urls: files) }
        .sheet(item: $selectedTrip) { selection in
            DismissibleNavigationSheet {
                TripEndOdometerSheet(id: selection.id, journal: journal) { revision += 1 }
            }
            .preferredColorScheme(.light)
            .presentationBackground(.white)
            .presentationDetents([.height(280)])
        }
    }
    private func run(_ operation: @escaping () throws -> [URL]) {
        busy = true; operationError = nil
        Task {
            do {
                let result = try await Task.detached(priority: .userInitiated) { try operation() }.value
                files = result; share = !result.isEmpty; revision += 1
            } catch { operationError = error.localizedDescription }
            busy = false
        }
    }
    private struct HistoryItem { let id: String; let trip: [String: Any] }
    private let columnWidths: [CGFloat] = [130, 155, 155, 90, 160]
    private var tableHeader: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(["table_datetime", "table_start", "table_end", "table_distance", "table_odo_end"].enumerated()), id: \.offset) { index, key in
                Text(journalText(key)).font(.caption.weight(.semibold))
                    .frame(width: columnWidths[index] - 16, alignment: .leading).padding(.horizontal, 8)
                    .accessibilityIdentifier("journal.history.column.\(index)")
            }
        }.padding(.vertical, 8)
    }
    private func historyCell<Content: View>(id: String, column: Int, @ViewBuilder content: () -> Content) -> some View {
        Button { selectedTrip = JournalTripSelection(id: id) } label: {
            content().frame(width: columnWidths[column] - 16, alignment: .topLeading).frame(minHeight: 44, alignment: .topLeading)
                .padding(.horizontal, 8).contentShape(Rectangle())
        }.buttonStyle(.plain).accessibilityIdentifier("journal.history.cell.\(column).\(id)")
    }
    private func historyRow(_ trip: [String: Any]) -> some View {
        let id = trip["id"] as? String ?? ""
        let names = JournalHistoryPresentation.endpointNames(trip: trip, events: journal.events(id).map(JournalEvent.init))
        let start = Date(timeIntervalSince1970: trip["start"] as? Double ?? 0)
        let end = Date(timeIntervalSince1970: trip["end"] as? Double ?? 0)
        return HStack(alignment: .top, spacing: 0) {
            historyCell(id: id, column: 0) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(start.formatted(date: .numeric, time: .omitted))
                    Text(start.formatted(date: .omitted, time: .shortened) + " – " + end.formatted(date: .omitted, time: .shortened)).font(.caption)
                }
            }
            historyCell(id: id, column: 1) { Text(names.start) }
            historyCell(id: id, column: 2) { Text(names.end) }
            historyCell(id: id, column: 3) { Text(JournalHistoryPresentation.number((trip["distance"] as? Double ?? 0) / 1000)).monospacedDigit() }
            VStack(alignment: .leading, spacing: 2) {
                Button { selectedTrip = JournalTripSelection(id: id) } label: {
                    Text((trip["odo_end"] as? Double).map { JournalHistoryPresentation.number($0) } ?? "—")
                        .monospacedDigit().frame(maxWidth: .infinity, minHeight: 22, alignment: .topLeading).contentShape(Rectangle())
                }.buttonStyle(.plain)
                HStack(spacing: 12) {
                    Button { run { [try journal.archive(id, options: TripExportOptions(includeRawLogs: true))] } } label: {
                        Image(systemName: "square.and.arrow.up").frame(minWidth: 44, minHeight: 44)
                    }.accessibilityLabel(journalText("share_drive")).accessibilityIdentifier("journal.history.share.\(id)").disabled(busy)
                    Button(role: .destructive) { pendingDelete = id } label: {
                        Image(systemName: "trash").frame(minWidth: 44, minHeight: 44)
                    }.accessibilityLabel(journalText("delete")).accessibilityIdentifier("journal.history.delete.\(id)")
                }.buttonStyle(.borderless)
            }.frame(width: columnWidths[4] - 16, alignment: .leading).padding(.horizontal, 8)
        }
        .font(.subheadline)
        .padding(.vertical, 6)
    }
}

private func journalState(_ trip: [String: Any], _ events: [JournalEvent]) -> String {
    var states = [journalText(trip["state"] as? String ?? "unknown")]
    if !events.contains(where: { $0.kind == "gps" && $0.coordinate != nil && $0.payload["valid"] as? Bool == true }) { states.append(journalText("no_gps")) }
    else if (trip["distance"] as? Double ?? 0) == 0 { states.append(journalText("no_movement")) }
    if events.contains(where: { $0.kind == "gap" }) { states.append(journalText("gaps")) }
    return states.joined(separator: " · ")
}

private struct TripJournalDetailView: View {
    let id: String
    var gallery: ((Set<String>, Set<String>) -> AnyView)?
    @ObservedObject var journal: TripJournal
    @State private var tab = "map"
    @State private var selected: Int?
    @State private var replayIndex = 0.0
    @State private var playing = false
    @State private var eventFilter = "all"
    @State private var reading = ""
    @State private var odometerUnit = "km"
    @State private var vehicle = ""
    @State private var masked = false
    @State private var maskHome = false
    @State private var radius = 300.0
    @State private var includeLogs = true
    @State private var includeOdometer = false
    @State private var selectedMedia = Set<String>()
    @State private var busy = false
    @State private var files: [URL] = []
    @State private var sharing = false
    @State private var error: String?
    var body: some View {
        TimelineView(.periodic(from: .now, by: 5)) { _ in
            let trip = journal.snapshot().trips.first { $0["id"] as? String == id } ?? [:]
            let events = journal.events(id).map(JournalEvent.init)
            let points = events.filter(\.trackEligible)
            let media = JournalMedia.project(events)
            let selection = events.first { $0.id == selected }
            List {
                Section {
                    Text(Date(timeIntervalSince1970: trip["start"] as? Double ?? 0), format: .dateTime.day().month().year().hour().minute()).font(.headline)
                    LabeledContent(journalText("distance"), value: String(format: "%.3f km", locale: Locale.current, (trip["distance"] as? Double ?? 0) / 1000))
                    LabeledContent(journalText("duration"), value: String(format: "%.1f min", locale: Locale.current, (trip["duration"] as? Double ?? 0) / 60))
                    LabeledContent(journalText("observed"), value: String(format: "%.1f min", locale: Locale.current, (trip["observed"] as? Double ?? 0) / 60))
                    Text(journalState(trip, events)).font(.caption).foregroundStyle(.secondary)
                    if trip["state"] as? String == "active" { activeFields(trip) }
                    if trip["vehicle"] != nil || trip["odo_start"] != nil || trip["odo_end"] != nil {
                        DisclosureGroup(journalText("vehicle")) {
                            if let vehicle = trip["vehicle"] as? String { LabeledContent(journalText("vehicle"), value: vehicle) }
                            if let value = trip["odo_start"] as? Double { LabeledContent(journalText("odo_start"), value: String(format: "%.1f km", locale: Locale.current, value)) }
                            if let value = trip["odo_end"] as? Double { LabeledContent(journalText("odo_end"), value: String(format: "%.1f km", locale: Locale.current, value)) }
                        }
                    }
                }
                Section {
                    Picker(journalText("view"), selection: $tab) {
                        Text(journalText("map")).tag("map"); Text(journalText("timeline")).tag("timeline"); Text(journalText("media")).tag("media"); Text(journalText("export")).tag("export")
                    }.pickerStyle(.segmented)
                }
                if let error { Section { Text(error).foregroundStyle(.red) } }
                if tab == "map" {
                    Section {
                        JournalMapView(events: events, selection: $selected).frame(height: 290).listRowInsets(EdgeInsets())
                        Text(journalText("map_help")).font(.caption).foregroundStyle(.secondary)
                        if !points.isEmpty {
                            Slider(value: $replayIndex, in: 0...Double(max(1, points.count - 1)), step: 1) { Text(journalText("replay")) }
                                .onChange(of: replayIndex) { _, value in selected = points[min(Int(value), points.count - 1)].id }
                            Button(playing ? journalText("pause") : journalText("replay"), systemImage: playing ? "pause.fill" : "play.fill") { playing.toggle() }
                        }
                        JournalSpeedChart(points: points).frame(height: 110).accessibilityLabel(journalText("speed_chart"))
                    }
                    selectionSection(selection, media: media)
                    Section(journalText("signs")) { eventRows(JournalDiscoveries.project(events)) }
                } else if tab == "timeline" {
                    Section {
                        Picker(journalText("logs"), selection: $eventFilter) {
                            ForEach(["all", "gps", "tsr", "sign", "media", "gap"], id: \.self) { Text(journalText($0)).tag($0) }
                        }
                        Text(journalText("logs_help")).font(.caption).foregroundStyle(.secondary)
                    }
                    selectionSection(selection, media: media)
                    Section { eventRows(events.filter { eventFilter == "all" || $0.kind == eventFilter }) }
                } else if tab == "media" {
                    if let gallery {
                        Section { NavigationLink(journalText("trip_gallery")) { gallery(Set(media.filter { $0.type == "photo" }.map(\.id)), Set(media.filter { $0.type == "video" }.map(\.id))) } }
                    }
                    if media.isEmpty { ContentUnavailableView(journalText("no_recording"), systemImage: "photo.on.rectangle") }
                    Section(journalText("photos")) { ForEach(media.filter { $0.type == "photo" }) { mediaRow($0) } }
                    ForEach(Array(Set(media.filter { $0.type == "video" }.map(\.session))).sorted(), id: \.self) { session in
                        Section(journalText("video_session") + " · " + String(session.prefix(8))) {
                            ForEach(media.filter { $0.type == "video" && $0.session == session }) { mediaRow($0) }
                        }
                    }
                } else {
                    exportSection(trip, events: events, media: media, selection: selection)
                }
            }
        }
        .navigationTitle(journalText("title"))
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $sharing) { TripShareSheet(urls: files) }
        .overlay { if busy { ProgressView().padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12)) } }
        .task(id: playing) {
            guard playing else { return }
            while playing && !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(400))
                guard !Task.isCancelled else { return }
                let count = journal.events(id).map(JournalEvent.init).filter(\.trackEligible).count
                if replayIndex >= Double(max(0, count - 1)) { playing = false }
                else { replayIndex += 1 }
            }
        }
    }
    @ViewBuilder private func activeFields(_ trip: [String: Any]) -> some View {
        if trip["vehicle"] == nil {
            TextField(journalText("optional_vehicle"), text: $vehicle)
            Button(journalText("save_vehicle")) { journal.setVehicle(id, name: vehicle) }.disabled(vehicle.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        if trip["odo_start"] == nil || trip["odo_end"] == nil {
            TextField(journalText("optional_odo"), text: $reading).keyboardType(.decimalPad)
            Picker(journalText("odometer_unit"), selection: $odometerUnit) { Text("km").tag("km"); Text("mi").tag("mi") }.pickerStyle(.segmented)
            HStack {
                if trip["odo_start"] == nil { Button(journalText("odo_start")) { saveReading(start: true, trip: trip) } }
                if trip["odo_end"] == nil { Button(journalText("odo_end")) { saveReading(start: false, trip: trip) } }
            }
            Text(journalText("odo_help")).font(.caption).foregroundStyle(.secondary)
        }
        Button(journalText("end_trip")) { journal.stop() }
    }
    private func saveReading(start: Bool, trip: [String: Any]) {
        guard let value = Double(reading.replacingOccurrences(of: ",", with: ".")), value.isFinite, value >= 0,
              start ? value * (odometerUnit == "mi" ? 1.609344 : 1) <= (trip["odo_end"] as? Double ?? .greatestFiniteMagnitude) : value * (odometerUnit == "mi" ? 1.609344 : 1) >= (trip["odo_start"] as? Double ?? 0) else { error = journalText("invalid_odo"); return }
        journal.odometer(id, start: start ? value : nil, end: start ? nil : value, unit: odometerUnit); reading = ""; error = nil
    }
    @ViewBuilder private func selectionSection(_ event: JournalEvent?, media: [JournalMedia]) -> some View {
        if let event {
            Section(journalText("selection")) {
                Label(event.title, systemImage: icon(event.kind))
                Text(event.time, format: .dateTime.hour().minute().second()).monospacedDigit()
                if let c = event.coordinate { Text(String(format: "%.6f, %.6f", locale: Locale.current, c.latitude, c.longitude)).font(.caption).textSelection(.enabled) }
                if let clip = media.first(where: { $0.offset(at: event.time) != nil }), let url = clip.localURL, let offset = clip.offset(at: event.time) {
                    NavigationLink(journalText("video_here")) { JournalVideoPlayer(url: url, offset: offset) }
                    Text(journalText("estimated_seek")).font(.caption).foregroundStyle(.secondary)
                } else { Text(journalText("no_recording")).font(.caption).foregroundStyle(.secondary) }
            }
        }
    }
    @ViewBuilder private func eventRows(_ events: [JournalEvent]) -> some View {
        if events.isEmpty { Text(journalText("no_events")).foregroundStyle(.secondary) }
        ForEach(events) { event in
            DisclosureGroup {
                Text((try? String(data: JSONSerialization.data(withJSONObject: event.payload, options: [.prettyPrinted, .sortedKeys]), encoding: .utf8)) ?? "").font(.caption.monospaced()).textSelection(.enabled)
                Button(journalText("select")) { selected = event.id; if event.coordinate != nil { tab = "map" } }
            } label: {
                HStack(alignment: .top) {
                    Image(systemName: icon(event.kind)).frame(width: 22)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(event.title).font(.subheadline.weight(.semibold))
                        Text(event.time, format: .dateTime.hour().minute().second()).font(.caption.monospacedDigit())
                        if !event.summary.isEmpty { Text(event.summary).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
                    }
                    if selected == event.id { Image(systemName: "checkmark.circle.fill").foregroundStyle(.tint) }
                }
            }
        }
    }
    private func icon(_ kind: String) -> String {
        switch kind { case "gps": return "location"; case "sign": return "signpost.right"; case "media": return "photo.on.rectangle"; case "gap", "gap_end": return "exclamationmark.triangle"; default: return "list.bullet.rectangle" }
    }
    @ViewBuilder private func mediaRow(_ media: JournalMedia) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(media.startedAt ?? media.capturedAt, format: .dateTime.hour().minute().second()).font(.subheadline.monospacedDigit())
            if let url = media.localURL {
                NavigationLink {
                    if media.type == "video" { JournalVideoPlayer(url: url, offset: 0) }
                    else if let image = UIImage(contentsOfFile: url.path) { ScrollView { Image(uiImage: image).resizable().scaledToFit() } }
                } label: {
                    if media.type == "photo", let image = UIImage(contentsOfFile: url.path) { Image(uiImage: image).resizable().scaledToFill().frame(width: 100, height: 65).clipped() }
                    Label(journalText("open_local"), systemImage: media.type == "video" ? "play.circle" : "photo")
                }
            } else { Label(journalText("media_missing"), systemImage: "externaldrive.badge.exclamationmark").font(.caption).foregroundStyle(.secondary) }
            if let url = media.remoteURL { Link(journalText("panoramax_open"), destination: url) }
            if media.type == "video" { Text(media.duration.map { String(format: "%.1f s · %@", locale: Locale.current, $0, journalText("estimated_seek")) } ?? journalText("timing_unavailable")).font(.caption).foregroundStyle(.secondary) }
        }.padding(.vertical, 4)
    }
    @ViewBuilder private func exportSection(_ trip: [String: Any], events: [JournalEvent], media: [JournalMedia], selection: JournalEvent?) -> some View {
        Section(journalText("export")) {
            Text(journalText("export_preview")).font(.footnote)
            Text("\(events.filter { $0.kind == "gps" }.count) GPS · \(events.filter { $0.kind == "tsr" }.count) TSR · \(media.count) " + journalText("media"))
            if trip["state"] as? String == "active" { Label(journalText("active_export"), systemImage: "clock").font(.caption) }
            Toggle(journalText("private_share"), isOn: $masked)
                .onChange(of: masked) { _, value in if value { includeLogs = false; selectedMedia = [] } }
            if masked {
                Slider(value: $radius, in: 100...2000, step: 100) { Text(journalText("mask_radius")) }
                LabeledContent(journalText("mask_radius"), value: "\(Int(radius)) m")
                Toggle(journalText("mask_home"), isOn: $maskHome).disabled(selection?.coordinate == nil)
                Text(journalText("mask_help")).font(.caption).foregroundStyle(.secondary)
            }
            Toggle(journalText("include_logs"), isOn: $includeLogs).disabled(masked)
            Toggle(journalText("include_odo"), isOn: $includeOdometer)
            Text(journalText("share_residual")).font(.caption).foregroundStyle(.secondary)
            ForEach(media.filter { $0.localURL != nil && (!masked || $0.type == "photo") }) { item in
                Toggle(journalText(item.type == "video" ? "videos" : "photos") + " · " + item.capturedAt.formatted(date: .omitted, time: .shortened), isOn: Binding(get: { selectedMedia.contains(item.id) }, set: { if $0 { selectedMedia.insert(item.id) } else { selectedMedia.remove(item.id) } }))
            }
            Button(journalText("share_archive"), systemImage: "square.and.arrow.up") {
                let options = TripExportOptions(masked: masked, maskRadiusMetres: radius, homeCoordinate: maskHome ? selection?.coordinate : nil, includeRawLogs: includeLogs, includeOdometer: includeOdometer, selectedMedia: selectedMedia)
                busy = true; error = nil
                Task {
                    do { let url = try await Task.detached(priority: .userInitiated) { try journal.archive(id, options: options) }.value; files = [url]; sharing = true }
                    catch { self.error = error.localizedDescription }
                    busy = false
                }
            }.disabled(busy)
        }
    }
}

private struct JournalVideoPlayer: View {
    let url: URL
    let offset: Double
    @State private var player: AVPlayer?
    var body: some View {
        VideoPlayer(player: player)
            .onAppear { let item = AVPlayer(url: url); item.seek(to: CMTime(seconds: max(0, offset), preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero); player = item }
            .onDisappear { player?.pause(); player = nil }
    }
}
private struct TripShareSheet: UIViewControllerRepresentable {
    let urls: [URL]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: urls, applicationActivities: nil) }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

private struct JournalMapView: View {
    let events: [JournalEvent]
    @Binding var selection: Int?
    @State private var position: MapCameraPosition = .automatic
    private var segments: [[CLLocationCoordinate2D]] {
        var result = [[CLLocationCoordinate2D]](), current = [CLLocationCoordinate2D]()
        for event in events {
            if event.kind == "gap" { if !current.isEmpty { result.append(current); current = [] }; continue }
            guard event.trackEligible, let coordinate = event.coordinate else { continue }
            if event.payload["reason"] as? String != "accepted", !current.isEmpty { result.append(current); current = [] }
            current.append(coordinate)
        }
        if !current.isEmpty { result.append(current) }; return result
    }
    var body: some View {
        Map(position: $position, selection: $selection) {
            ForEach(Array(segments.enumerated()), id: \.offset) { _, points in MapPolyline(coordinates: points).stroke(.blue, lineWidth: 4) }
            ForEach(JournalDiscoveries.project(events).filter { $0.coordinate != nil }) { event in
                Annotation(event.title, coordinate: event.coordinate!) {
                    Image(systemName: "signpost.right.fill").padding(7).background(.regularMaterial, in: Circle())
                }.tag(event.id)
            }
            if let event = events.first(where: { $0.id == selection }), let coordinate = event.coordinate {
                Marker(event.time.formatted(date: .omitted, time: .standard), coordinate: coordinate).tint(.orange).tag(event.id)
            }
            if let first = events.first(where: \.trackEligible)?.coordinate { Marker(journalText("start"), coordinate: first).tint(.green) }
            if let last = events.last(where: \.trackEligible)?.coordinate { Marker(journalText("end"), coordinate: last).tint(.red) }
        }
        .mapControls { MapScaleView(); MapCompass() }
        .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll, showsTraffic: false))
        .accessibilityLabel(journalText("map_help"))
        .onChange(of: selection) { _, selected in
            if let coordinate = events.first(where: { $0.id == selected })?.coordinate { withAnimation { position = .region(MKCoordinateRegion(center: coordinate, latitudinalMeters: 1500, longitudinalMeters: 1500)) } }
        }
    }
}
private struct JournalSpeedChart: View {
    let points: [JournalEvent]
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(journalText("speed_chart")).font(.caption).foregroundStyle(.secondary)
            Canvas { context, size in
                guard let start = points.first?.time, let end = points.last?.time, end > start else { return }
                let maximum = max(30, points.compactMap { $0.payload["speed"] as? Double }.max().map { $0 * 3.6 } ?? 30)
                var path = Path(), started = false
                for point in points {
                    guard let speed = point.payload["speed"] as? Double else { started = false; continue }
                    let coordinate = CGPoint(x: point.time.timeIntervalSince(start) / end.timeIntervalSince(start) * size.width, y: size.height - max(0, speed * 3.6) / maximum * size.height)
                    if !started || point.payload["reason"] as? String != "accepted" { path.move(to: coordinate) } else { path.addLine(to: coordinate) }
                    started = true
                }
                context.stroke(path, with: .color(.blue), lineWidth: 2)
            }
        }
    }
}

/// Four app languages, including exports and accessibility labels.
func journalText(_ key: String) -> String {
    let language = String((Bundle.main.preferredLocalizations.first ?? Locale.preferredLanguages.first ?? "en").prefix(2))
    let index = ["en": 0, "de": 1, "fr": 2, "nl": 3][language] ?? 0
    let strings: [String: [String]] = [
        "about": ["About this journal and counters", "Über Journal und Zähler", "À propos du carnet et des compteurs", "Over dit rittenboek en tellers"],
        "title": ["Trip journal", "Fahrtenbuch", "Carnet de trajets", "Rittenboek"],
        "navigation": ["Trips", "Fahrten", "Trajets", "Ritten"],
        "scope": ["Private local trip journal with GPS and traffic-sign logs. Trips can be deleted; vehicle odometer readings are optional. Tax recognition is not guaranteed.", "Privates lokales Fahrtenjournal mit GPS- und Verkehrszeichen-Protokollen. Fahrten sind löschbar; der Fahrzeug-Kilometerstand ist optional. Eine steuerliche Anerkennung wird nicht zugesichert.", "Carnet privé local avec journaux GPS et panneaux. Les trajets peuvent être supprimés ; le compteur du véhicule est facultatif. La reconnaissance fiscale n’est pas garantie.", "Privé lokaal rittenboek met GPS- en verkeersbordlogboeken. Ritten kunnen worden verwijderd; de kilometerstand is optioneel. Fiscale erkenning wordt niet gegarandeerd."],
        "setup_title": ["Trip journal (optional)","Fahrtenbuch (optional)","Carnet de trajets (facultatif)","Rittenboek (optioneel)"],
        "setup_disclosure": ["Save future trips, GPS routes and traffic-sign logs privately on this device. Camera and public contributions keep their separate choices. You can change this in Settings.","Künftige Fahrten, GPS-Strecken und Verkehrszeichen-Protokolle privat auf diesem Gerät speichern. Kamera und öffentliche Beiträge bleiben getrennte Entscheidungen. In den Einstellungen jederzeit änderbar.","Enregistrez les prochains trajets, traces GPS et journaux de panneaux en privé sur cet appareil. La caméra et les contributions publiques restent des choix séparés. Modifiable dans les réglages.","Sla toekomstige ritten, GPS-routes en verkeersbordlogboeken privé op dit apparaat op. Camera en openbare bijdragen blijven aparte keuzes. Dit is te wijzigen bij Instellingen."],
        "recording_off_history": ["Trip recording is off. Enable it in Settings to save future trips.","Fahrtenaufzeichnung ist aus. In den Einstellungen aktivieren, um künftige Fahrten zu speichern.","L’enregistrement des trajets est désactivé. Activez-le dans les réglages pour enregistrer les prochains trajets.","Ritten opnemen staat uit. Schakel dit in bij Instellingen om toekomstige ritten op te slaan."],
        "recording_settings": ["Recording settings","Aufzeichnungseinstellungen","Réglages de l’enregistrement","Opname-instellingen"],
        "automatic": ["Save future trips and tracks automatically", "Künftige Fahrten und Tracks automatisch speichern", "Enregistrer automatiquement les futurs trajets et traces", "Toekomstige ritten en routes automatisch opslaan"],
        "accept_recording": ["Enable private recording and continue", "Private Aufzeichnung aktivieren und fortfahren", "Activer l’enregistrement privé et continuer", "Privéregistratie inschakelen en doorgaan"],
        "decline_recording": ["Continue without saving trips", "Ohne Fahrtspeicherung fortfahren", "Continuer sans enregistrer les trajets", "Doorgaan zonder ritten op te slaan"],
        "consent": ["Enable to accept local GPS/TSR recording. Location, camera and public contributions keep their separate choices.", "Zum Einwilligen in lokale GPS-/TSR-Aufzeichnung einschalten. Standort, Kamera und öffentliche Beiträge bleiben getrennte Entscheidungen.", "Activez pour accepter l’enregistrement local GPS/panneaux. La localisation, la caméra et les contributions publiques restent des choix distincts.", "Schakel in om lokale GPS-/bordregistratie toe te staan. Locatie, camera en openbare bijdragen blijven aparte keuzes."],
        "distance": ["YouSpeed kilometres", "YouSpeed-Kilometer", "Kilomètres YouSpeed", "YouSpeed-kilometers"],
        "usage": ["App usage", "Nutzungsdauer", "Durée d’utilisation", "Gebruiksduur"],
        "since": ["Counter origin", "Zählerbeginn", "Début du compteur", "Teller gestart"],
        "counter_help": ["Lifetime counters include deleted trips and driving with track saving off. Saved-trip totals can differ.", "Gesamtzähler enthalten gelöschte Fahrten und Fahrten ohne Trackspeicherung. Summen gespeicherter Fahrten können abweichen.", "Les compteurs incluent les trajets supprimés et la conduite sans trace. Les totaux conservés peuvent différer.", "Totaaltellers bevatten verwijderde ritten en rijden zonder routeopslag. Opgeslagen totalen kunnen afwijken."],
        "new_trip": ["New trip", "Neue Fahrt", "Nouveau trajet", "Nieuwe rit"],
        "end_trip": ["End this trip", "Diese Fahrt beenden", "Terminer ce trajet", "Deze rit beëindigen"],
        "filters": ["Filters", "Filter", "Filtres", "Filters"],
        "custom_range": ["Custom dates", "Eigene Datumsgrenzen", "Dates personnalisées", "Aangepaste datums"],
        "date_from": ["From", "Von", "Du", "Vanaf"],
        "date_to": ["Through", "Bis einschließlich", "Jusqu’au inclus", "Tot en met"],
        "date_range_help": ["Includes both selected local dates. Whole trips are assigned to their start date.", "Beide gewählten lokalen Datumswerte sind eingeschlossen. Ganze Fahrten werden ihrem Startdatum zugeordnet.", "Inclut les deux dates locales choisies. Chaque trajet entier est affecté à sa date de départ.", "Beide gekozen lokale datums zijn inbegrepen. Hele ritten worden aan hun begindatum toegewezen."],
        "chart_metric": ["Chart value", "Diagrammwert", "Valeur du graphique", "Grafiekwaarde"],
        "chart_distance": ["Measured distance", "Gemessene Strecke", "Distance mesurée", "Gemeten afstand"],
        "chart_observed": ["Observed trip time", "Beobachtete Fahrtzeit", "Durée observée", "Waargenomen rittijd"],
        "daily_distance": ["Saved distance by day", "Gespeicherte Distanz je Tag", "Distance conservée par jour", "Bewaarde afstand per dag"],
        "daily_observed": ["Observed foreground recording time by day", "Beobachtete Aufzeichnungszeit im Vordergrund je Tag", "Durée d’enregistrement au premier plan par jour", "Waargenomen registratietijd op de voorgrond per dag"],
        "daily_duration": ["Trip duration by day · includes gaps", "Fahrtdauer je Tag · einschließlich Lücken", "Durée des trajets par jour · interruptions incluses", "Ritduur per dag · inclusief gaten"],
        "chart_scope": ["Saved trips in the selected period only. Observed trip time excludes background gaps and app use outside these trips; it is not the lifetime app-usage counter.", "Nur gespeicherte Fahrten im gewählten Zeitraum. Beobachtete Fahrtzeit enthält keine Hintergrundlücken und keine App-Nutzung außerhalb dieser Fahrten; sie ist nicht der App-Gesamtzähler.", "Uniquement les trajets conservés de la période. La durée observée exclut les interruptions et l’utilisation hors trajet ; ce n’est pas le compteur global.", "Alleen opgeslagen ritten in de gekozen periode. Waargenomen rittijd sluit achtergrondgaten en gebruik buiten deze ritten uit; dit is niet de totale gebruiksteller."],
        "daily_totals": ["Accessible daily totals", "Tageswerte als zugängliche Liste", "Totaux quotidiens accessibles", "Toegankelijke dagtotalen"],
        "daily_accessibility": ["%d saved trips, %.3f kilometres, %.2f hours observed recording, %.2f hours trip duration including gaps", "%d gespeicherte Fahrten, %.3f Kilometer, %.2f Stunden beobachtete Aufzeichnung, %.2f Stunden Fahrtdauer einschließlich Lücken", "%d trajets conservés, %.3f kilomètres, %.2f heures observées, %.2f heures de trajet avec interruptions", "%d opgeslagen ritten, %.3f kilometer, %.2f uur waargenomen registratie, %.2f uur ritduur inclusief gaten"],
        "day": ["Day", "Tag", "Jour", "Dag"],
        "period": ["Period", "Zeitraum", "Période", "Periode"],
        "all": ["All", "Alle", "Tous", "Alle"],
        "week": ["Last 7 days", "Letzte 7 Tage", "7 derniers jours", "Afgelopen 7 dagen"],
        "month": ["Last 30 days", "Letzte 30 Tage", "30 derniers jours", "Afgelopen 30 dagen"],
        "year": ["Last 365 days", "Letzte 365 Tage", "365 derniers jours", "Afgelopen 365 dagen"],
        "vehicle": ["Vehicle", "Fahrzeug", "Véhicule", "Voertuig"],
        "optional_vehicle": ["Optional vehicle name", "Optionaler Fahrzeugname", "Nom du véhicule facultatif", "Optionele voertuignaam"],
        "save_vehicle": ["Save vehicle once", "Fahrzeug einmalig speichern", "Enregistrer le véhicule une fois", "Voertuig eenmalig opslaan"],
        "media": ["Media", "Medien", "Médias", "Media"],
        "photos": ["Panoramax photos", "Panoramax-Fotos", "Photos Panoramax", "Panoramax-foto’s"],
        "videos": ["Dashcam videos", "Dashcam-Videos", "Vidéos dashcam", "Dashcamvideo’s"],
        "video_session": ["Dashcam session", "Dashcam-Sitzung", "Session dashcam", "Dashcamsessie"],
        "sign_filter": ["Sign class (e.g. DE:310)", "Zeichenklasse (z. B. DE:310)", "Classe du panneau (ex. DE:310)", "Bordklasse (bijv. DE:310)"],
        "interrupted_only": ["Interrupted trips or track gaps", "Unterbrochene Fahrten oder Tracklücken", "Trajets interrompus ou traces incomplètes", "Onderbroken ritten of routegaten"],
        "saved_total": ["Saved trips · selected period", "Gespeicherte Fahrten · gewählter Zeitraum", "Trajets conservés · période choisie", "Opgeslagen ritten · geselecteerde periode"],
        "empty": ["No matching trips", "Keine passenden Fahrten", "Aucun trajet correspondant", "Geen overeenkomende ritten"],
        "search": ["Search local places, vehicle or date", "Lokale Orte, Fahrzeug oder Datum suchen", "Rechercher lieux locaux, véhicule ou date", "Lokale plaatsen, voertuig of datum zoeken"],
        "delete": ["Delete trip", "Fahrt löschen", "Supprimer le trajet", "Rit verwijderen"],
        "delete_with_media": ["Delete trip and eligible local media", "Fahrt und freigegebene lokale Medien löschen", "Supprimer trajet et médias locaux autorisés", "Rit en beschikbare lokale media verwijderen"],
        "deletion_result": ["Local media: %d removed · %d protected · %d cleanup failures · %d already unavailable. Public uploads are unchanged.", "Lokale Medien: %d entfernt · %d geschützt · %d Bereinigungsfehler · %d bereits nicht verfügbar. Öffentliche Uploads bleiben unverändert.", "Médias locaux : %d supprimés · %d protégés · %d erreurs · %d déjà absents. Les envois publics restent inchangés.", "Lokale media: %d verwijderd · %d beschermd · %d opruimfouten · %d al afwezig. Openbare uploads blijven ongewijzigd."],
        "delete_preview": ["Delete this trip, GPS/TSR logs, odometer and private media links? Original media and lifetime counters remain. Saved-trip totals decrease. Shared copies cannot be recalled.", "Diese Fahrt, GPS-/TSR-Protokolle, Kilometerstände und private Medienverknüpfungen löschen? Originalmedien und Gesamtzähler bleiben erhalten. Die Summe gespeicherter Fahrten sinkt. Geteilte Kopien können nicht zurückgerufen werden.", "Supprimer ce trajet, ses journaux, compteurs et liens privés ? Les médias originaux et compteurs globaux restent. Les totaux conservés diminuent. Les copies partagées ne peuvent être rappelées.", "Deze rit, logboeken, kilometerstanden en privémedialinks verwijderen? Originele media en totaaltellers blijven behouden. Opgeslagen totalen dalen. Gedeelde kopieën kunnen niet worden teruggehaald."],
        "backup": ["Backup and local data", "Sicherung und lokale Daten", "Sauvegarde et données locales", "Back-up en lokale gegevens"],
        "backup_help": ["Password-encrypted backup contains all private logs and counters. Media files stay in their libraries. Keep the password; it cannot be recovered.", "Passwortverschlüsselte Sicherung aller privaten Protokolle und Zähler. Mediendateien bleiben in ihren Bibliotheken. Passwort aufbewahren; es kann nicht wiederhergestellt werden.", "Sauvegarde chiffrée des journaux privés et compteurs. Les médias restent dans leurs bibliothèques. Conservez le mot de passe ; il ne peut être récupéré.", "Met wachtwoord versleutelde back-up van alle privélogboeken en tellers. Media blijven in hun bibliotheken. Bewaar het wachtwoord; het kan niet worden hersteld."],
        "password": ["Backup password (at least 8 characters)", "Sicherungspasswort (mind. 8 Zeichen)", "Mot de passe (8 caractères minimum)", "Back-upwachtwoord (minimaal 8 tekens)"],
        "password_minimum": ["Use a password with at least 8 characters.", "Ein Passwort mit mindestens 8 Zeichen verwenden.", "Utilisez au moins 8 caractères.", "Gebruik minimaal 8 tekens."],
        "save_backup": ["Save encrypted backup", "Verschlüsselte Sicherung speichern", "Enregistrer la sauvegarde chiffrée", "Versleutelde back-up opslaan"],
        "restore": ["Restore backup", "Sicherung wiederherstellen", "Restaurer la sauvegarde", "Back-up herstellen"],
        "restore_preview": ["Replace the entire local journal and counter epoch with this backup? Existing media stays. Save a backup first if needed. Restoring again never adds the distance twice.", "Das gesamte lokale Journal und die Zählerepoche durch diese Sicherung ersetzen? Vorhandene Medien bleiben. Bei Bedarf vorher sichern. Erneutes Wiederherstellen zählt Entfernungen nicht doppelt.", "Remplacer tout le carnet et les compteurs par cette sauvegarde ? Les médias restent. Sauvegardez d’abord si nécessaire. Une nouvelle restauration ne double pas les distances.", "Het hele lokale rittenboek en de tellerperiode vervangen door deze back-up? Media blijven behouden. Maak zo nodig eerst een back-up. Opnieuw herstellen telt afstanden niet dubbel."],
        "clear_all": ["Clear all local trip data and counters", "Alle lokalen Fahrtdaten und Zähler löschen", "Effacer tous les trajets et compteurs locaux", "Alle lokale ritgegevens en tellers wissen"],
        "clear_preview": ["Permanently remove all private trips, GPS/TSR logs, associations and counters, and start a new empty counter epoch? Media libraries and public uploads stay separate.", "Alle privaten Fahrten, GPS-/TSR-Protokolle, Zuordnungen und Zähler endgültig entfernen und eine neue leere Zählerepoche beginnen? Medienbibliotheken und öffentliche Uploads bleiben getrennt.", "Supprimer définitivement les trajets, journaux, liens et compteurs privés et commencer une nouvelle période vide ? Les médias et envois publics restent séparés.", "Alle privéritten, logboeken, koppelingen en tellers definitief verwijderen en een nieuwe lege tellerperiode starten? Mediabibliotheken en openbare uploads blijven apart."],
        "active": ["In progress", "Läuft", "En cours", "Actief"],
        "finalizing": ["Finishing", "Wird abgeschlossen", "Finalisation", "Afronden"],
        "ended": ["Finished", "Beendet", "Terminé", "Beëindigd"],
        "disabled": ["Recording disabled", "Aufzeichnung deaktiviert", "Enregistrement désactivé", "Registratie uitgeschakeld"],
        "interrupted": ["Interrupted", "Unterbrochen", "Interrompu", "Onderbroken"],
        "no_gps": ["No GPS coverage", "Ohne GPS", "Sans GPS", "Zonder GPS"],
        "no_movement": ["No measured movement", "Ohne gemessene Bewegung", "Aucun déplacement mesuré", "Geen gemeten beweging"],
        "gaps": ["Track has gaps", "Track mit Lücken", "Trace avec interruptions", "Route met gaten"],
        "duration": ["Trip duration", "Fahrtdauer", "Durée du trajet", "Ritduur"],
        "observed": ["Observed recording time", "Beobachtete Aufzeichnungszeit", "Durée d’observation", "Waargenomen registratietijd"],
        "view": ["View", "Ansicht", "Vue", "Weergave"],
        "map": ["Map", "Karte", "Carte", "Kaart"],
        "timeline": ["Timeline", "Verlauf", "Chronologie", "Tijdlijn"],
        "export": ["Export", "Export", "Exporter", "Exporteren"],
        "map_help": ["Recorded route. Gaps are not connected. The timeline is available offline and for screen readers. Map tiles may need a connection.", "Aufgezeichnete Route. Lücken werden nicht verbunden. Der Zeitverlauf ist offline und für Screenreader verfügbar. Kartenkacheln benötigen eventuell eine Verbindung.", "Trace enregistrée ; les interruptions ne sont pas reliées. La chronologie reste accessible hors ligne et aux lecteurs d’écran. Les tuiles peuvent nécessiter une connexion.", "Opgenomen route. Gaten worden niet verbonden. De tijdlijn is offline en voor schermlezers beschikbaar. Kaarttegels vereisen mogelijk internet."],
        "replay": ["Replay route", "Route abspielen", "Rejouer la trace", "Route afspelen"],
        "pause": ["Pause", "Pause", "Pause", "Pauze"],
        "speed_chart": ["Recorded speed (km/h)", "Aufgezeichnete Geschwindigkeit (km/h)", "Vitesse enregistrée (km/h)", "Opgenomen snelheid (km/h)"],
        "signs": ["Sign discoveries", "Verkehrszeichen", "Panneaux rencontrés", "Verkeersborden"],
        "sign": ["Sign", "Verkehrszeichen", "Panneau", "Verkeersbord"],
        "gps": ["GPS log", "GPS-Protokoll", "Journal GPS", "GPS-logboek"],
        "tsr": ["TSR log", "TSR-Protokoll", "Journal des panneaux", "Bordlogboek"],
        "gap": ["Coverage gap", "Aufzeichnungslücke", "Interruption d’enregistrement", "Registratiegat"],
        "gap_end": ["Recording resumed", "Aufzeichnung fortgesetzt", "Enregistrement repris", "Registratie hervat"],
        "coverage": ["Coverage state", "Aufzeichnungsstatus", "État d’enregistrement", "Registratiestatus"],
        "logs": ["Logs", "Protokolle", "Journaux", "Logboeken"],
        "logs_help": ["Original GPS and TSR events are retained, including rejected fixes and uncertain detections. Expand an event for the complete recorded metadata.", "Originale GPS- und TSR-Ereignisse bleiben erhalten, einschließlich verworfener Positionen und unsicherer Erkennungen. Ein Ereignis aufklappen, um alle gespeicherten Metadaten zu sehen.", "Les événements originaux sont conservés, y compris les positions rejetées et détections incertaines. Développez un événement pour ses métadonnées complètes.", "Originele gebeurtenissen blijven bewaard, inclusief afgewezen posities en onzekere detecties. Klap een gebeurtenis open voor alle opgeslagen metadata."],
        "odometer_unit": ["Vehicle odometer unit", "Einheit des Fahrzeug-Kilometerstands", "Unité du compteur du véhicule", "Eenheid kilometerstand voertuig"],
        "odometer_entry": ["Odometer entry", "Kilometerstand-Eingabe", "Saisie du compteur", "Kilometerstandinvoer"],
        "optional_odo": ["Optional vehicle odometer", "Optionaler Fahrzeug-Kilometerstand", "Compteur du véhicule facultatif", "Optionele kilometerstand voertuig"],
        "odo_start": ["Starting odometer", "Start-Kilometerstand", "Compteur au départ", "Beginkilometerstand"],
        "odo_end": ["Ending odometer", "End-Kilometerstand", "Compteur à l’arrivée", "Eindkilometerstand"],
        "odo_help": ["Optional and saved once during the active trip. Leaving it blank never blocks saving. Saved facts are read-only.", "Optional und während der laufenden Fahrt einmalig speicherbar. Leer lassen verhindert das Speichern nie. Gespeicherte Angaben sind schreibgeschützt.", "Facultatif et enregistré une seule fois pendant le trajet. Le laisser vide ne bloque jamais l’enregistrement. Les données sauvegardées sont en lecture seule.", "Optioneel en eenmalig op te slaan tijdens de rit. Leeglaten blokkeert opslaan nooit. Opgeslagen gegevens zijn alleen-lezen."],
        "invalid_odo": ["Enter a non-negative reading; the end must not be below the start. You may leave the reading blank.", "Einen nichtnegativen Stand eingeben; der Endwert darf nicht unter dem Startwert liegen. Der Wert kann weggelassen werden.", "Saisissez une valeur positive ; l’arrivée ne doit pas être inférieure au départ. Vous pouvez laisser ce champ vide.", "Voer een niet-negatieve stand in; de eindstand mag niet lager zijn dan de beginstand. U kunt de stand weglaten."],
        "selection": ["Selected moment", "Ausgewählter Moment", "Moment sélectionné", "Geselecteerd moment"],
        "select": ["Select on route", "Auf Route auswählen", "Sélectionner sur la trace", "Op route selecteren"],
        "video_here": ["Video from here", "Video ab hier", "Vidéo à partir d’ici", "Video vanaf hier"],
        "estimated_seek": ["Estimated recording-clock alignment", "Geschätzte Zuordnung zur Aufnahmezeit", "Alignement temporel estimé", "Geschatte koppeling met opnameklok"],
        "no_recording": ["No recording available for this moment", "Keine Aufnahme für diesen Moment vorhanden", "Aucun enregistrement pour ce moment", "Geen opname voor dit moment beschikbaar"],
        "no_events": ["No recorded events", "Keine aufgezeichneten Ereignisse", "Aucun événement enregistré", "Geen opgenomen gebeurtenissen"],
        "trip_gallery": ["Open gallery · This trip", "Galerie öffnen · Diese Fahrt", "Ouvrir la galerie · Ce trajet", "Galerij openen · Deze rit"],
        "open_local": ["Open local original", "Lokales Original öffnen", "Ouvrir l’original local", "Lokaal origineel openen"],
        "media_missing": ["Local original missing, deleted or evicted", "Lokales Original fehlt, wurde gelöscht oder verdrängt", "Original local absent, supprimé ou évincé", "Lokaal origineel ontbreekt of is verwijderd"],
        "panoramax_open": ["Open in Panoramax", "In Panoramax öffnen", "Ouvrir dans Panoramax", "In Panoramax openen"],
        "timing_unavailable": ["No reliable recording-clock anchor; open from beginning", "Kein verlässlicher Aufnahmezeitanker; vom Anfang öffnen", "Sans repère temporel fiable ; ouvrir depuis le début", "Geen betrouwbare opnameklok; vanaf begin openen"],
        "export_preview": ["Archive includes trip, GPX/GeoJSON track, discovery log, overview PDF/CSV, counters and a checksum manifest. Select original media explicitly. Locations are private.", "Das Archiv enthält Fahrt, GPX-/GeoJSON-Track, Zeichenprotokoll, PDF-/CSV-Übersicht, Zähler und Prüfsummen. Originalmedien ausdrücklich auswählen. Standorte sind privat.", "L’archive contient trajet, trace GPX/GeoJSON, panneaux, synthèse PDF/CSV, compteurs et sommes de contrôle. Sélectionnez explicitement les médias. Les positions sont privées.", "Het archief bevat rit, GPX-/GeoJSON-route, bordenlogboek, PDF-/CSV-overzicht, tellers en controlesommen. Selecteer media expliciet. Locaties zijn privé."],
        "active_export": ["In-progress snapshot of an active trip", "Zwischenstand einer laufenden Fahrt", "Instantané d’un trajet en cours", "Momentopname van een actieve rit"],
        "private_share": ["Share privately · mask endpoint areas", "Privat teilen · Start-/Zielbereiche maskieren", "Partager en privé · masquer départ/arrivée", "Privé delen · begin/eindgebieden maskeren"],
        "mask_radius": ["Hidden-area radius", "Radius der verborgenen Bereiche", "Rayon masqué", "Straal verborgen gebied"],
        "mask_home": ["Also hide the selected map location", "Ausgewählten Kartenort ebenfalls verbergen", "Masquer aussi le point sélectionné", "Geselecteerde kaartlocatie ook verbergen"],
        "mask_help": ["Removes fixes and sign pins within the radius, raw logs, road/place identifiers, videos and remote links. Selected photos outside hidden areas are re-encoded without GPS metadata. Original facts and counters stay unchanged.", "Entfernt Positionen und Zeichen-Pins im Radius, Rohprotokolle, Straßen-/Ortskennungen, Videos und Fernlinks. Ausgewählte Fotos außerhalb verborgener Bereiche werden ohne GPS-Metadaten neu kodiert. Originale und Zähler bleiben unverändert.", "Retire positions et panneaux dans le rayon, journaux bruts, identifiants routiers/lieux, vidéos et liens distants. Les photos choisies hors zone sont réencodées sans GPS. Les originaux et compteurs restent inchangés.", "Verwijdert posities en bordpins binnen de straal, ruwe logboeken, weg-/plaatskenmerken, video’s en externe links. Geselecteerde foto’s buiten verborgen gebieden worden zonder GPS-metadata opgeslagen. Originelen en tellers blijven gelijk."],
        "include_logs": ["Include complete GPS/TSR logs", "Vollständige GPS-/TSR-Protokolle beifügen", "Inclure les journaux GPS/panneaux complets", "Volledige GPS-/bordlogboeken bijvoegen"],
        "include_odo": ["Include optional vehicle odometer", "Optionalen Fahrzeug-Kilometerstand beifügen", "Inclure le compteur facultatif", "Optionele kilometerstand bijvoegen"],
        "share_residual": ["Visible route, times, measured distance and photo content can still reveal locations. A shared copy cannot be recalled. Masked geometry length may differ from measured distance.", "Sichtbare Route, Zeiten, gemessene Strecke und Bildinhalte können weiterhin Orte verraten. Geteilte Kopien können nicht zurückgerufen werden. Die maskierte Geometrie kann von der gemessenen Strecke abweichen.", "Trace visible, horaires, distance et images peuvent encore révéler des lieux. Une copie partagée ne peut être rappelée. La longueur masquée peut différer de la distance mesurée.", "Zichtbare route, tijden, afstand en foto-inhoud kunnen nog locaties onthullen. Een gedeelde kopie kan niet worden teruggehaald. Gemaskeerde lengte kan afwijken van gemeten afstand."],
        "share_archive": ["Share trip archive", "Fahrtarchiv teilen", "Partager l’archive du trajet", "Ritarchief delen"],
        "table_datetime": ["Date / time", "Datum / Uhrzeit", "Date / heure", "Datum / tijd"],
        "table_start": ["Start location", "Startort", "Lieu de départ", "Vertrekplaats"],
        "table_end": ["End location", "Zielort", "Lieu d’arrivée", "Aankomstplaats"],
        "table_distance": ["Distance (km)", "Strecke (km)", "Distance (km)", "Afstand (km)"],
        "table_odo_end": ["Car end reading (km)", "Auto-Endstand (km)", "Compteur final (km)", "Eindstand auto (km)"],
        "location_unknown": ["Unknown location", "Ort unbekannt", "Lieu inconnu", "Onbekende locatie"],
        "details": ["Details, map and logs", "Details, Karte und Protokolle", "Détails, carte et journaux", "Details, kaart en logboeken"],
        "share_drive": ["Share drive with GPS and TSR logs", "Fahrt mit GPS- und TSR-Protokollen teilen", "Partager le trajet et les journaux GPS et TSR", "Rit met GPS- en TSR-logboeken delen"],
        "end_odo_prompt": ["Optionally enter the car’s odometer reading at the end of this drive, in kilometres. This does not change the measured distance or counters.", "Optional den Kilometerstand des Autos am Ende dieser Fahrt eingeben. Gemessene Strecke und Zähler bleiben unverändert.", "Indiquez éventuellement le compteur du véhicule à la fin de ce trajet, en kilomètres. La distance mesurée et les compteurs restent inchangés.", "Vul eventueel de kilometerstand van de auto aan het einde van deze rit in. Gemeten afstand en tellers blijven gelijk."],
        "end_odo_readonly": ["This saved end reading cannot be changed.", "Dieser gespeicherte Endstand kann nicht geändert werden.", "Ce compteur final enregistré ne peut pas être modifié.", "Deze opgeslagen eindstand kan niet worden gewijzigd."],
        "trip_missing": ["This trip no longer exists.", "Diese Fahrt ist nicht mehr vorhanden.", "Ce trajet n’existe plus.", "Deze rit bestaat niet meer."],
        "write_failed": ["The reading could not be saved. Please try again.", "Der Stand konnte nicht gespeichert werden. Bitte erneut versuchen.", "Le compteur n’a pas pu être enregistré. Réessayez.", "De stand kon niet worden opgeslagen. Probeer opnieuw."],
        "save": ["Save", "Speichern", "Enregistrer", "Opslaan"],
        "start": ["Start", "Start", "Départ", "Begin"],
        "end": ["End", "Ende", "Arrivée", "Einde"]
    ]
    return strings[key]?[index] ?? key
}

#if DEBUG
/// Isolated deterministic UI evidence. It never touches the normal journal or capture libraries.
struct TripJournalPreviewRoot: View {
    private let journal: TripJournal
    private let id: String
    init() {
        let preferences = UserDefaults(suiteName: "youspeed.trip-journal.preview")!
        preferences.removePersistentDomain(forName: "youspeed.trip-journal.preview")
        let journal = TripJournal(directory: FileManager.default.temporaryDirectory.appendingPathComponent("journal-preview-" + UUID().uuidString), preferences: preferences, heartbeat: false)
        self.journal = journal
        journal.setEnabled(true); journal.start(); _ = journal.snapshot()
        let at = Date()
        for (index, delta) in [-8.0, -4.0, 0.0].enumerated() {
            journal.location(CLLocation(coordinate: .init(latitude: 49.0069 + Double(index) * 0.00035, longitude: 8.4037 + Double(index) * 0.0001), altitude: 115, horizontalAccuracy: 3, verticalAccuracy: 5, course: 15, speed: 10, timestamp: at.addingTimeInterval(delta)))
        }
        journal.signEvent(["source": "camera", "evidence_source": "camera_observation", "class_code": "DE:274-30", "latitude": 49.0073, "longitude": 8.4038, "confidence": 0.97], at: Date())
        journal.signEvent(["source": "government", "evidence_source": "inventory_encounter", "class_code": "DE:101", "latitude": 49.0075, "longitude": 8.4039], at: Date())
        let id = journal.snapshot().trips.first?["id"] as! String
        self.id = id
        journal.setVehicle(id, name: "YouSpeed"); journal.odometer(id, start: 12030, end: ProcessInfo.processInfo.arguments.contains("--trip-journal-missing-odometer-preview") ? nil : 12030.08)
        journal.matchedPlace(at: Date(), streetName: "Kaiserstraße", cityName: "Karlsruhe", latitude: 49.0069, longitude: 8.4037, accuracy: 3)
        journal.matchedPlace(at: at, streetName: "Zirkel", cityName: "Karlsruhe", latitude: 49.0076, longitude: 8.4039, accuracy: 3)
        journal.tsr("camera_observation outcome=observed model=preview")
        journal.stop(); _ = journal.snapshot(); journal.completeFinalizerForTesting()
    }
    var body: some View {
        DismissibleNavigationSheet {
            if ProcessInfo.processInfo.arguments.contains("--trip-journal-detail-preview") {
                TripJournalDetailView(id: id, gallery: nil, journal: journal)
            } else { TripJournalView(journal: journal) }
        }
    }
}
#endif
