import Foundation
import SQLite3
import Darwin

/// One immutable bundle generation. Callers hold a session across the entire lookup,
/// so a cached statement can never be reset or a replaced database closed mid-query.
final class V3LookupResources: @unchecked Sendable {
    struct Statistics {
        var opens = 0
        var closes = 0
        var prepares = 0
        var finalizes = 0
        var geometryDecodes = 0
        var capabilityLoads = 0
        var generation: UInt64 = 0
        var cachedStatements = 0
        var cachedGeometries = 0
        var geometryBytes = 0
    }

    private struct Identity: Equatable {
        let device: Int32
        let inode: UInt64
        let size: Int64
        let modifiedSeconds: Int
        let modifiedNanos: Int
        let changedSeconds: Int
        let changedNanos: Int

        init(path: String) throws {
            var info = stat()
            guard stat(path, &info) == 0 else {
                throw ConsumerAppError.sqlite("sqlite bundle is unavailable: \(path)")
            }
            device = info.st_dev
            inode = info.st_ino
            size = info.st_size
            modifiedSeconds = info.st_mtimespec.tv_sec
            modifiedNanos = info.st_mtimespec.tv_nsec
            changedSeconds = info.st_ctimespec.tv_sec
            changedNanos = info.st_ctimespec.tv_nsec
        }
    }

    private struct Statement {
        let pointer: OpaquePointer
        let used: UInt64
    }
    private struct Geometry {
        let points: [(Double, Double)]
        let bytes: Int
        let used: UInt64
    }
    enum GeometryFormat: Hashable { case coordinatePairs, settlement }
    private struct GeometryKey: Hashable {
        let raw: String
        let format: GeometryFormat
    }

    private let path: String
    private let lock = NSRecursiveLock()
    private let statementLimit: Int
    private let geometryLimit: Int
    private let geometryByteLimit: Int
    private let capabilityLimit: Int
    private var db: OpaquePointer?
    private var identity: Identity?
    private var depth = 0
    private var clock: UInt64 = 0
    private var counts = Statistics()
    private var statements: [String: Statement] = [:]
    private var leased: [OpaquePointer: String] = [:]
    private var geometries: [GeometryKey: Geometry] = [:]
    private var capabilities: [String: Bool] = [:]

    init(path: String, statementLimit: Int = 48, geometryLimit: Int = 512,
         geometryByteLimit: Int = 4 * 1024 * 1024, capabilityLimit: Int = 128) {
        self.path = path
        self.statementLimit = max(0, statementLimit)
        self.geometryLimit = max(0, geometryLimit)
        self.geometryByteLimit = max(0, geometryByteLimit)
        self.capabilityLimit = max(0, capabilityLimit)
    }

    deinit { closeLocked() }

    func acquire() throws -> (db: OpaquePointer, generation: UInt64) {
        lock.lock()
        do {
            if depth == 0 {
                let current = try Identity(path: path)
                if identity != current { closeLocked() }
                if db == nil {
                    // A bundle can be atomically replaced while opening. Do not tag
                    // the old descriptor with the replacement file's identity.
                    for _ in 0..<3 {
                        let before = try Identity(path: path)
                        var opened: OpaquePointer?
                        let encoded = path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path
                        let code = sqlite3_open_v2("file:\(encoded)?mode=ro&immutable=1", &opened,
                                                  SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil)
                        guard code == SQLITE_OK, let opened else {
                            if let opened { sqlite3_close(opened) }
                            throw ConsumerAppError.sqlite("sqlite open failed for \(path)")
                        }
                        counts.opens += 1
                        let after: Identity
                        do { after = try Identity(path: path) }
                        catch { sqlite3_close(opened); counts.closes += 1; throw error }
                        if before != after {
                            sqlite3_close(opened); counts.closes += 1
                            continue
                        }
                        db = opened
                        identity = after
                        counts.generation &+= 1
                        break
                    }
                }
            }
            guard let db else { throw ConsumerAppError.sqlite("sqlite bundle changed while opening: \(path)") }
            depth += 1
            return (db, counts.generation)
        } catch {
            if depth == 0 { closeLocked() }
            lock.unlock()
            throw error
        }
    }

    func releaseSession() {
        precondition(depth > 0)
        depth -= 1
        if depth == 0 { precondition(leased.isEmpty, "Lookup statement outlived its session") }
        lock.unlock()
    }

    func invalidate() {
        lock.lock()
        defer { lock.unlock() }
        precondition(depth == 0, "Cannot invalidate an active lookup")
        closeLocked()
    }

    var statistics: Statistics {
        lock.lock()
        defer { lock.unlock() }
        var result = counts
        result.cachedStatements = statements.count
        result.cachedGeometries = geometries.count
        return result
    }

    func prepare(_ db: OpaquePointer, _ sql: String, _ length: Int32,
                 _ output: UnsafeMutablePointer<OpaquePointer?>, _ tail: UnsafeMutablePointer<UnsafePointer<CChar>?>?) -> Int32 {
        precondition(depth > 0 && self.db == db)
        if let cached = statements.removeValue(forKey: sql) {
            leased[cached.pointer] = sql
            output.pointee = cached.pointer
            return SQLITE_OK
        }
        counts.prepares += 1
        let code = sqlite3_prepare_v2(db, sql, length, output, tail)
        if code == SQLITE_OK, let statement = output.pointee {
            leased[statement] = sql
        } else if let statement = output.pointee {
            sqlite3_finalize(statement); counts.finalizes += 1; output.pointee = nil
        }
        return code
    }

    func release(_ statement: OpaquePointer?) {
        guard let statement else { return }
        precondition(depth > 0)
        let sql = leased.removeValue(forKey: statement)
        let resetCode = sqlite3_reset(statement)
        sqlite3_clear_bindings(statement)
        guard resetCode == SQLITE_OK, let sql, statementLimit > 0, statements[sql] == nil else {
            sqlite3_finalize(statement); counts.finalizes += 1; return
        }
        if statements.count >= statementLimit, let oldest = statements.min(by: { $0.value.used < $1.value.used }) {
            sqlite3_finalize(oldest.value.pointer); counts.finalizes += 1
            statements.removeValue(forKey: oldest.key)
        }
        clock &+= 1
        statements[sql] = Statement(pointer: statement, used: clock)
    }

    func capability(_ key: String, load: () -> Bool?) -> Bool {
        precondition(depth > 0)
        if let value = capabilities[key] { return value }
        counts.capabilityLoads += 1
        guard let value = load() else { return false }
        if capabilities.count < capabilityLimit { capabilities[key] = value }
        return value
    }

    func geometry(_ raw: String?, format: GeometryFormat = .coordinatePairs,
                  decode: (String?) -> [(Double, Double)]) -> [(Double, Double)] {
        precondition(depth > 0)
        guard let raw else { return [] }
        let key = GeometryKey(raw: raw, format: format)
        clock &+= 1
        if let cached = geometries[key] {
            geometries[key] = Geometry(points: cached.points, bytes: cached.bytes, used: clock)
            return cached.points
        }
        counts.geometryDecodes += 1
        let points = decode(raw)
        let bytes = raw.utf8.count + points.count * MemoryLayout<(Double, Double)>.stride
        guard geometryLimit > 0, bytes <= geometryByteLimit else { return points }
        while geometries.count >= geometryLimit || counts.geometryBytes + bytes > geometryByteLimit {
            guard let oldest = geometries.min(by: { $0.value.used < $1.value.used }) else { break }
            counts.geometryBytes -= oldest.value.bytes
            geometries.removeValue(forKey: oldest.key)
        }
        geometries[key] = Geometry(points: points, bytes: bytes, used: clock)
        counts.geometryBytes += bytes
        return points
    }

    private func closeLocked() {
        precondition(leased.isEmpty, "Lookup statement outlived its session")
        for statement in statements.values { sqlite3_finalize(statement.pointer); counts.finalizes += 1 }
        statements.removeAll()
        geometries.removeAll()
        capabilities.removeAll()
        counts.geometryBytes = 0
        if let db { sqlite3_close(db); counts.closes += 1 }
        db = nil
        identity = nil
    }
}
