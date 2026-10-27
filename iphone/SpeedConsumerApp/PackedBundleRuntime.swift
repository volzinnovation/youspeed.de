import Foundation
import SQLite3

@_silgen_name("ysp_register_context_vfs")
private func packedRegisterVFS() -> Int32
@_silgen_name("ysp_sqlite_cache_kib")
private func packedSQLiteCacheKiB() -> Int32
@_silgen_name("ysp_geometry_open")
private func packedGeometryOpen(_ path: UnsafePointer<CChar>, _ cacheBytes: UInt64,
                                _ error: UnsafeMutablePointer<CChar>, _ errorSize: Int) -> UnsafeMutableRawPointer?
@_silgen_name("ysp_geometry_json")
private func packedGeometryJSON(_ handle: UnsafeMutableRawPointer, _ wayID: UnsafePointer<CChar>,
                                _ error: UnsafeMutablePointer<CChar>, _ errorSize: Int) -> UnsafeMutablePointer<CChar>?
@_silgen_name("ysp_geometry_close")
private func packedGeometryClose(_ handle: UnsafeMutableRawPointer)
@_silgen_name("ysp_packed_free")
private func packedFree(_ memory: UnsafeMutableRawPointer?)

/// Opens a complete read-only SQLite context through the bounded native VFS.
/// Every existing SQL join, condition and event lookup uses the same connection.
enum PackedBundleRuntime {
    static func isPackedContext(at url: URL) throws -> Bool {
        let file = try FileHandle(forReadingFrom: url)
        defer { try? file.close() }
        return try file.read(upToCount: 8) == Data([89, 83, 80, 67, 84, 88, 49, 0])
    }

    static func openReadOnly(path: String) throws -> OpaquePointer {
        let packed = try isPackedContext(at: URL(fileURLWithPath: path))
        if packed, packedRegisterVFS() != SQLITE_OK {
            throw ConsumerAppError.sqlite("Cannot register packed bundle reader")
        }
        let uri = URL(fileURLWithPath: path).absoluteString + "?mode=ro&immutable=1"
        var database: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        let code: Int32
        if packed {
            code = "ysp-packed-v1".withCString { sqlite3_open_v2(uri, &database, flags, $0) }
        } else {
            code = sqlite3_open_v2(uri, &database, flags, nil)
        }
        guard code == SQLITE_OK, let database else {
            if let database { sqlite3_close(database) }
            throw ConsumerAppError.sqlite("Cannot open immutable bundle: \(path)")
        }
        do {
            let cacheKiB = packedSQLiteCacheKiB()
            guard cacheKiB > 0,
                  sqlite3_exec(database, "PRAGMA mmap_size=0; PRAGMA cache_size=-\(cacheKiB); PRAGMA query_only=ON", nil, nil, nil) == SQLITE_OK else {
                throw ConsumerAppError.sqlite("Cannot configure bounded bundle query cache")
            }
            try registerGeometry(on: database, contextURL: URL(fileURLWithPath: path), required: packed)
            return database
        } catch {
            sqlite3_close(database)
            throw error
        }
    }

    static func metadata(_ key: String, database: OpaquePointer) -> String? {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, "SELECT value FROM metadata WHERE key=?1", -1, &statement, nil) == SQLITE_OK,
              let statement else { return nil }
        defer { sqlite3_finalize(statement) }
        _ = key.withCString { sqlite3_bind_text(statement, 1, $0, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self)) }
        guard sqlite3_step(statement) == SQLITE_ROW, let value = sqlite3_column_text(statement, 0) else { return nil }
        return String(cString: value)
    }

    /// Identity of the complete installed immutable generation. Human bundle
    /// versions are shared across regions and cannot authorize corrections.
    /// The installer has verified these installed hashes before activation.
    static func amendmentBaseIdentity(database: OpaquePointer) -> String? {
        guard let generation = metadata("packed_generation", database: database),
              let rawPath = sqlite3_db_filename(database, "main") else { return nil }
        let context = URL(fileURLWithPath: String(cString: rawPath))
        guard (try? isPackedContext(at: context)) == true else { return nil }
        let manifest = context.deletingLastPathComponent().appendingPathComponent("bundle-manifest.v3.json")
        guard let size = try? manifest.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              size > 0, size <= 1024 * 1024,
              let data = try? Data(contentsOf: manifest),
              let document = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              document["format"] as? String == "youspeed.v4.bundle.manifest",
              document["schema_version"] as? Int == 1, document["variant"] as? String == "v4",
              document["bundle_version"] as? String == generation,
              let db = document["db"] as? [String: Any], db["file"] as? String == context.lastPathComponent,
              let base = document["packed_base"] as? [String: Any], base["version"] as? Int == 1,
              let roads = base["roads"] as? [String: Any],
              roads["file"] as? String == metadata("packed_geometry_file", database: database) else { return nil }
        func installedHash(_ artifact: [String: Any]) -> String? {
            let compression = (artifact["compression"] as? String ?? "").lowercased()
            guard ["", "none", "identity", "gzip"].contains(compression),
                  let raw = artifact[compression == "gzip" ? "uncompressed_sha256" : "sha256"] as? String,
                  raw.range(of: "^[0-9a-fA-F]{64}$", options: .regularExpression) != nil else { return nil }
            return raw.lowercased()
        }
        guard let contextHash = installedHash(db), let roadsHash = installedHash(roads),
              roadsHash == metadata("packed_geometry_sha256", database: database)?.lowercased() else { return nil }
        let nodesHash: String
        if let nodes = base["nodes"] as? [String: Any] {
            guard let hash = installedHash(nodes) else { return nil }
            nodesHash = hash
        } else if base["nodes"] == nil { nodesHash = "absent" }
        else { return nil }
        return "ysp-base-v1:\(contextHash):\(roadsHash):\(nodesHash)"
    }

    private static func registerGeometry(on database: OpaquePointer, contextURL: URL, required: Bool) throws {
        let version = metadata("packed_geometry_version", database: database)
        guard required || version != nil else { return }
        guard version == "1",
              let filename = metadata("packed_geometry_file", database: database),
              !filename.isEmpty, filename == URL(fileURLWithPath: filename).lastPathComponent,
              filename != ".", filename != "..", !filename.contains("\\"),
              let digest = metadata("packed_geometry_sha256", database: database),
              digest.range(of: "^[0-9a-fA-F]{64}$", options: .regularExpression) != nil,
              let generation = metadata("packed_generation", database: database), !generation.isEmpty else {
            throw ConsumerAppError.invalidManifest("Incomplete or unsupported packed geometry capability")
        }
        let provider = try PackedGeometryProvider(url: contextURL.deletingLastPathComponent().appendingPathComponent(filename))
        let retained = Unmanaged.passRetained(provider).toOpaque()
        // SQLite owns retained userdata, including its release on registration
        // failure; the provider therefore outlives all prepared view statements.
        let result = sqlite3_create_function_v2(database, "ysp_way_points_json", 1,
            SQLITE_UTF8 | SQLITE_DETERMINISTIC | SQLITE_INNOCUOUS, retained, { context, count, values in
                guard let context, count == 1, let values, let value = values[0],
                      sqlite3_value_type(value) != SQLITE_NULL,
                      let wayID = sqlite3_value_text(value),
                      let rawProvider = sqlite3_user_data(context) else {
                    sqlite3_result_null(context)
                    return
                }
                let provider = Unmanaged<PackedGeometryProvider>.fromOpaque(rawProvider).takeUnretainedValue()
                let text = String(cString: wayID)
                guard let id = Int64(text), id > 0 else {
                    sqlite3_result_error(context, "Invalid packed geometry way ID", -1)
                    return
                }
                provider.withGeometryJSON(wayID: String(id), context: context)
            }, nil, nil, { raw in
                if let raw { Unmanaged<PackedGeometryProvider>.fromOpaque(raw).release() }
            })
        guard result == SQLITE_OK else { throw ConsumerAppError.sqlite("Cannot register packed geometry lookup") }
    }
}

private final class PackedGeometryProvider {
    private let handle: UnsafeMutableRawPointer

    init(url: URL) throws {
        let errorSize = 1024
        var error = [CChar](repeating: 0, count: errorSize)
        let opened = url.path.withCString { packedGeometryOpen($0, 0, &error, errorSize) }
        guard let opened else { throw ConsumerAppError.sqlite("Packed geometry open failed: \(String(cString: error))") }
        handle = opened
    }

    deinit { packedGeometryClose(handle) }

    func withGeometryJSON(wayID: String, context: OpaquePointer) {
        var error = [CChar](repeating: 0, count: 1024)
        let json = wayID.withCString { packedGeometryJSON(handle, $0, &error, 1024) }
        guard let json else {
            if error[0] == 0 { sqlite3_result_null(context) }
            else { error.withUnsafeBufferPointer { sqlite3_result_error(context, $0.baseAddress, -1) } }
            return
        }
        defer { packedFree(UnsafeMutableRawPointer(json)) }
        sqlite3_result_text(context, json, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
    }
}
