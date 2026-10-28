import XCTest
import SQLite3
import CryptoKit
import zlib
@testable import SpeedConsumer

final class PackedBundleRuntimeTests: XCTestCase {
    private func fixture(_ name: String) throws -> URL {
        let bundle = Bundle(for: Self.self)
        return try XCTUnwrap(bundle.url(forResource: name, withExtension: nil, subdirectory: "packed-runtime-v1"))
    }

    private func text(_ database: OpaquePointer, _ sql: String) throws -> String {
        var statement: OpaquePointer?
        XCTAssertEqual(sqlite3_prepare_v2(database, sql, -1, &statement, nil), SQLITE_OK)
        let prepared = try XCTUnwrap(statement)
        defer { sqlite3_finalize(prepared) }
        XCTAssertEqual(sqlite3_step(prepared), SQLITE_ROW)
        return String(cString: try XCTUnwrap(sqlite3_column_text(prepared, 0)))
    }

    func testPackedAndLegacyQueriesPreserveExactSourceJSONAndGlobals() throws {
        let source = try PackedBundleRuntime.openReadOnly(path: fixture("source.sqlite").path)
        defer { sqlite3_close(source) }
        let packed = try PackedBundleRuntime.openReadOnly(path: fixture("fixture.context.yspc").path)
        defer { sqlite3_close(packed) }
        XCTAssertNil(PackedBundleRuntime.amendmentBaseIdentity(database: packed), "An unactivated pack has no verified correction base identity")
        for id in ["10", "20", "9007199254740993"] {
            let sql = "SELECT points_json FROM way_geom WHERE way_id=\(id)"
            XCTAssertEqual(try text(source, sql), try text(packed, sql))
        }
        XCTAssertEqual(try text(packed, "SELECT points_json FROM way_geom WHERE way_id=10"), "[[48.1000000, 9.2],[48.100001,9.200001]]")
        XCTAssertEqual(try text(source, "SELECT raw FROM restrictions WHERE way_id=20"),
                       try text(packed, "SELECT raw FROM restrictions WHERE way_id=20"))
    }

    func testMissingCompanionFailsBeforeQuery() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let context = directory.appendingPathComponent("fixture.context.yspc")
        try FileManager.default.copyItem(at: fixture("fixture.context.yspc"), to: context)
        XCTAssertThrowsError(try PackedBundleRuntime.openReadOnly(path: context.path))
    }

    func testZstdPackedQueriesPreserveOriginalBytesAndCodecOneRemainsReadable() throws {
        let old = try PackedBundleRuntime.openReadOnly(path: fixture("fixture.context.yspc").path)
        defer { sqlite3_close(old) }
        let zstd = try PackedBundleRuntime.openReadOnly(path: fixture("fixture-zstd.context.yspc").path)
        defer { sqlite3_close(zstd) }
        for id in ["10", "20", "9007199254740993"] {
            XCTAssertEqual(try text(old, "SELECT points_json FROM way_geom WHERE way_id=\(id)"),
                           try text(zstd, "SELECT points_json FROM way_geom WHERE way_id=\(id)"))
        }
    }

    func testCorruptGeometryFailsClosedAndURIEscapesPaths() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("packed ? &# \(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let context = directory.appendingPathComponent("fixture.context.yspc")
        try FileManager.default.copyItem(at: fixture("fixture.context.yspc"), to: context)
        let geometry = directory.appendingPathComponent("fixture.ways.yspg")
        try FileManager.default.copyItem(at: fixture("fixture.ways.yspg"), to: geometry)
        do {
            let database = try PackedBundleRuntime.openReadOnly(path: context.path)
            XCTAssertEqual(try text(database, "SELECT points_json FROM way_geom WHERE way_id=20"), "[[48.2,9.3]]")
            sqlite3_close(database)
        }
        var bytes = try Data(contentsOf: geometry); bytes[bytes.count-1] ^= 0x40
        try bytes.write(to: geometry)
        do {
            let database = try PackedBundleRuntime.openReadOnly(path: context.path)
            defer { sqlite3_close(database) }
            var statement: OpaquePointer?
            XCTAssertEqual(sqlite3_prepare_v2(database, "SELECT points_json FROM way_geom WHERE way_id=10", -1, &statement, nil), SQLITE_OK)
            defer { sqlite3_finalize(statement) }
            XCTAssertNotEqual(sqlite3_step(statement), SQLITE_ROW)
        } catch { /* Rejection while opening also establishes fail-closed behavior. */ }
    }

    func testGenericNodeKeepsRawRestrictionAndUnknownBinding() throws {
        let source = try PackedGenericSpeedSignSource(url: fixture("fixture.nodes.yspn"))
        let json = try XCTUnwrap(source.sourceJSON(nodeID: "2532969814"))
        let node = try JSONDecoder().decode(GenericSpeedSignNode.self, from: Data(json.utf8))
        XCTAssertEqual(node.tags["maxspeed:hgv:conditional"], "30 @ (weight>7.5)")
        XCTAssertEqual(node.bindingStatus, "unresolved_direction")
        XCTAssertEqual(node.memberships.first?.direction, "unknown")
        XCTAssertEqual(node.memberships.first?.chainageM, 261.9489296929296)
        XCTAssertEqual(try source.nearby(lat: node.latitude, lon: node.longitude, radiusM: 1).map(\.osmNodeID), [2532969814])
    }

    func testAmendmentsBindCompleteSourceAcrossOverlappingSameVersionRegions() throws {
        let root = try fixture("source.sqlite").deletingLastPathComponent()
        let paths = ["overlap-a", "overlap-b", "overlap-nodes"].map { root.appendingPathComponent($0 + "/context.yspc") }
        var databases: [OpaquePointer] = []
        defer { for db in databases { sqlite3_close(db) } }
        for path in paths { databases.append(try PackedBundleRuntime.openReadOnly(path: path.path)) }
        let a = databases[0], b = databases[1], nodes = databases[2]
        for db in databases {
            XCTAssertEqual(PackedBundleRuntime.metadata("packed_generation", database: db), "overlap-shared-v1")
            XCTAssertEqual(try text(db, "SELECT way_id FROM ways"), "10")
        }
        let identities = try databases.map { try XCTUnwrap(PackedBundleRuntime.amendmentBaseIdentity(database: $0)) }
        XCTAssertEqual(Set(identities).count, 3, "Context and node-only changes both invalidate source authority")
        XCTAssertTrue(identities.allSatisfy(MapDataAmendmentStore.isCanonicalBaseIdentity))
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = MapDataAmendmentStore(directory: directory)
        let sourceA = try text(a, "SELECT rules_json FROM road_speed_rule_set WHERE way_id=10")
        let sourceB = try text(b, "SELECT rules_json FROM road_speed_rule_set WHERE way_id=10")
        var rules = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(sourceA.utf8)) as? [String: Any])
        var tags = try XCTUnwrap(rules["tags"] as? [[String: Any]])
        var clauses = try XCTUnwrap(tags[0]["clauses"] as? [[String: Any]])
        clauses[0]["limit"] = ["kind": "numeric", "kmh": 30]; tags[0]["clauses"] = clauses; rules["tags"] = tags
        let amended = String(data: try JSONSerialization.data(withJSONObject: rules), encoding: .utf8)!
        var record = MapDataAmendment(id: "way:10", sourceNamespace: "osm", entity: "way", sourceID: "10",
            basisBundle: identities[0], originalBundle: "overlap-shared-v1",
            sourceRevision: MapDataAmendmentStore.waySourceRevision(rulesJSON: sourceA), rulesJSON: amended,
            rawSourceTags: ["maxspeed": "50"], author: "reviewer", evidenceID: "source-review")
        _ = try store.put(record, expectedRevision: 0)
        func speed(_ db: OpaquePointer) -> Int? {
            ConditionalSpeedRules.resolve(db: db, wayID: "10", direction: 1, baseKmh: 50,
                baseUnlimited: false, countryCode: "DEU", amendmentStore: store)?.kmh
        }
        XCTAssertEqual(speed(a), 30)
        XCTAssertEqual(speed(b), 60, "Same way/version in a different source must retain its own rules")
        XCTAssertEqual(speed(nodes), 50, "A node-only source change requires a reviewed rebase")
        record.basisBundle = identities[1]
        _ = try store.put(record, expectedRevision: 1)
        XCTAssertEqual(speed(b), 60, "Changing the base alone cannot authorize a stale typed source revision")
        record.sourceRevision = MapDataAmendmentStore.waySourceRevision(rulesJSON: sourceB)
        _ = try store.put(record, expectedRevision: 2)
        XCTAssertEqual(speed(b), 30)
        XCTAssertEqual(speed(a), 50)
        record.basisBundle = "overlap-shared-v1"
        _ = try store.put(record, expectedRevision: 3)
        XCTAssertEqual(speed(a), 50, "Historical version-only records remain stored but cannot apply")
        XCTAssertEqual(try store.history(record.id).count, 4)
    }

    func testPackedManifestCompatibilityAndCatalogValidation() throws {
        let hash = String(repeating: "a", count: 64)
        let artifact = BundleArtifact(file: "context.yspc", bytes: 100, sha256: hash, url: nil)
        let roads = BundleArtifact(file: "ways.yspg", bytes: 100, sha256: hash, url: nil)
        let manifest = V3BundleManifest(format: "youspeed.v4.bundle.manifest", schemaVersion: 1, variant: "v4",
            region: "fixture", bundleVersion: "v1", createdAtUTC: "2026-10-27T00:00:00Z", minAppVersion: "1.6",
            db: artifact, dbParts: nil, deltaIndex: nil, packedBase: BundlePackedBase(version: 1, roads: roads, nodes: nil))
        XCTAssertNoThrow(try BundleCompatibility.validate(manifest, appVersion: "1.6"))
        XCTAssertEqual(BundleDisplayMetadata(manifest: manifest).bytes, 200)
        XCTAssertNoThrow(try BundleCompatibility.validate(manifest, appVersion: "1.5"))
        XCTAssertThrowsError(try BundlePackedBase(version: 2, roads: roads, nodes: nil).validate(databaseFile: artifact.file))
        XCTAssertThrowsError(try BundlePackedBase(version: 1, roads: artifact, nodes: nil).validate(databaseFile: artifact.file))
        let entry: [String: Any] = ["region": "fixture", "country_code": "DEU", "release_tag": "packed-v1", "bundle_version": "v1",
            "manifest": ["file": "manifest.json", "url": "https://packed-runtime.test/manifest.json", "bytes": 100, "sha256": hash]]
        let catalog: [String: Any] = ["format": "youspeed.v4.bundle.catalog", "schema_version": 1, "variant": "v4", "bundles": [entry]]
        XCTAssertEqual(try PackedBundleCatalog.decode(JSONSerialization.data(withJSONObject: catalog)).bundles.first?.region, "fixture")
        var duplicate = catalog; duplicate["bundles"] = [entry, entry]
        XCTAssertThrowsError(try PackedBundleCatalog.decode(JSONSerialization.data(withJSONObject: duplicate)))
    }

    func testPackedReaderCapabilityDoesNotRelaxLegacyOrFutureMinimumVersions() throws {
        let hash = String(repeating: "a", count: 64)
        let context = BundleArtifact(file: "context.yspc", bytes: 100, sha256: hash, url: nil)
        let roads = BundleArtifact(file: "ways.yspg", bytes: 100, sha256: hash, url: nil)
        func manifest(minimum: String, packed: Bool = true) -> V3BundleManifest {
            V3BundleManifest(format: packed ? "youspeed.v4.bundle.manifest" : "youspeed.v3.bundle.manifest",
                schemaVersion: 1, variant: packed ? "v4" : "v3", region: "fixture", bundleVersion: "v1",
                createdAtUTC: "2026-10-27T00:00:00Z", minAppVersion: minimum, db: context,
                dbParts: nil, deltaIndex: nil,
                packedBase: packed ? BundlePackedBase(version: 1, roads: roads, nodes: nil) : nil)
        }
        let published = manifest(minimum: "1.6")
        XCTAssertEqual(BundleCompatibility.packedReaderCompatibilityVersion, "1.6")
        XCTAssertEqual(published.minAppVersion, "1.6")
        XCTAssertNoThrow(try BundleCompatibility.validate(published, appVersion: "1.5"))
        XCTAssertNoThrow(try BundleCompatibility.validate(published, appVersion: "1.5-debug"))
        XCTAssertNoThrow(try BundleCompatibility.validate(published, appVersion: "1.6"))
        for marketing in ["1.5", "1.6", "1.7", "99.0"] {
            XCTAssertThrowsError(try BundleCompatibility.validate(manifest(minimum: "1.7"), appVersion: marketing))
        }
        XCTAssertThrowsError(try BundleCompatibility.validate(manifest(minimum: "1.5"), appVersion: "1.5"))
        XCTAssertThrowsError(try BundleCompatibility.validate(published, appVersion: "invalid"))
        XCTAssertThrowsError(try BundleCompatibility.validate(published, appVersion: nil))
        XCTAssertNoThrow(try BundleCompatibility.validate(manifest(minimum: "1.5", packed: false), appVersion: "1.5"))
        XCTAssertThrowsError(try BundleCompatibility.validate(manifest(minimum: "1.6", packed: false), appVersion: "1.5"))
        XCTAssertThrowsError(try BundleCompatibility.validate(manifest(minimum: "1.7", packed: false), appVersion: "1.5"))
    }

    func testPackedCompanionGzipInstallIsAtomicAndMissingUpdateKeepsActiveGeneration() async throws {
        let manager = V3BundleManager(fileManager: .default, session: Self.session())
        let support = try V3BundleManager.applicationSupportDirectory()
        let backup = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let hadSupport = FileManager.default.fileExists(atPath: support.path)
        if hadSupport { try FileManager.default.moveItem(at: support, to: backup) }
        defer {
            PackedRuntimeURLProtocol.configure([:])
            try? FileManager.default.removeItem(at: support)
            if hadSupport { try? FileManager.default.moveItem(at: backup, to: support) }
        }
        let context = try Data(contentsOf: fixture("manager.context.yspc"))
        let geometry = try Data(contentsOf: fixture("manager.ways.yspg"))
        let nodes = try Data(contentsOf: fixture("fixture.nodes.yspn"))
        let gzGeometry = try gzip(geometry), gzNodes = try gzip(nodes)
        let manifestURL = URL(string: "https://packed-runtime.test/manifest.json")!
        let contextURL = URL(string: "https://packed-runtime.test/context")!
        let geometryURL = URL(string: "https://packed-runtime.test/geometry.gz")!
        let nodeURL = URL(string: "https://packed-runtime.test/nodes.gz")!
        func artifact(_ name: String, transport: Data, installed: Data? = nil, url: URL) -> BundleArtifact {
            BundleArtifact(file: name, bytes: Int64(transport.count), sha256: sha(transport), url: url.absoluteString,
                compression: installed == nil ? nil : "gzip", uncompressedBytes: installed.map { Int64($0.count) },
                uncompressedSHA256: installed.map(sha))
        }
        func manifest(_ version: String) -> V3BundleManifest {
            V3BundleManifest(format: "youspeed.v4.bundle.manifest", schemaVersion: 1, variant: "v4", region: "packed-fixture",
                countryCode: "DEU", bundleVersion: version, createdAtUTC: "2026-10-27T00:00:00Z", minAppVersion: "1.6",
                db: artifact("manager.context.yspc", transport: context, url: contextURL), dbParts: nil, deltaIndex: nil,
                packedBase: BundlePackedBase(version: 1,
                    roads: artifact("manager.ways.yspg", transport: gzGeometry, installed: geometry, url: geometryURL),
                    nodes: artifact("fixture.nodes.yspn", transport: gzNodes, installed: nodes, url: nodeURL)))
        }
        let initial = manifest("manager-fixture-v1")
        PackedRuntimeURLProtocol.configure([
            manifestURL.absoluteString: (200, try JSONEncoder().encode(initial)), contextURL.absoluteString: (200, context),
            geometryURL.absoluteString: (200, gzGeometry), nodeURL.absoluteString: (200, gzNodes)])
        let result = try await manager.syncFromManifestURL(manifestURL)
        XCTAssertEqual(result.mode, .fullDownload)
        let installedCandidate = try await manager.activeDatabaseURL()
        let installed = try XCTUnwrap(installedCandidate)
        XCTAssertEqual(try Data(contentsOf: installed), context)
        XCTAssertEqual(try Data(contentsOf: installed.deletingLastPathComponent().appendingPathComponent("manager.ways.yspg")), geometry)
        XCTAssertEqual(try Data(contentsOf: installed.deletingLastPathComponent().appendingPathComponent("fixture.nodes.yspn")), nodes)
        do {
            let db = try PackedBundleRuntime.openReadOnly(path: installed.path)
            defer { sqlite3_close(db) }
            XCTAssertEqual(PackedBundleRuntime.amendmentBaseIdentity(database: db),
                "ysp-base-v1:\(sha(context)):\(sha(geometry)):\(sha(nodes))", "Identity uses installed bytes rather than gzip transport hashes")
        }
        let installedBundles = try await manager.listDownloadedBundles()
        XCTAssertEqual(installedBundles.first?.installedBytes, Int64(context.count + geometry.count + nodes.count))
        let previousState = try Data(contentsOf: support.appendingPathComponent("active_bundle.json"))
        let next = manifest("manager-fixture-v2")
        PackedRuntimeURLProtocol.configure([
            manifestURL.absoluteString: (200, try JSONEncoder().encode(next)), contextURL.absoluteString: (200, context),
            geometryURL.absoluteString: (200, gzGeometry), nodeURL.absoluteString: (404, Data())])
        do { _ = try await manager.syncFromManifestURL(manifestURL); XCTFail("Missing companion must reject the update") } catch {}
        XCTAssertEqual(try Data(contentsOf: support.appendingPathComponent("active_bundle.json")), previousState)
        XCTAssertEqual(try Data(contentsOf: installed), context)
    }

    func testLegacyManifestPathsRejectTraversalInEveryLocalArtifact() throws {
        let artifact = BundleArtifact(file: "speeds.sqlite", bytes: 100, sha256: String(repeating: "a", count: 64), url: nil)
        let valid = V3BundleManifest(format: "youspeed.v3.bundle.manifest", schemaVersion: 1, variant: "v3",
            region: "germany/baden-wuerttemberg", bundleVersion: "2026-09-01", createdAtUTC: "fixture", minAppVersion: "1.0",
            db: artifact, dbParts: nil, deltaIndex: nil)
        XCTAssertNoThrow(try BundleCompatibility.validate(valid, appVersion: "1.5"))
        let encoded = try JSONEncoder().encode(valid)
        let original = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        let escaped: [String: Any] = ["file": "../journal.sqlite", "bytes": 100, "sha256": String(repeating: "a", count: 64)]
        for field in ["db", "delta_index", "penalty_rules", "db_parts", "coverage", "packed_base"] {
            var poisoned = original
            switch field {
            case "db_parts": poisoned[field] = [escaped]
            case "coverage": poisoned[field] = ["bbox": ["min_lon": 0, "min_lat": 0, "max_lon": 1, "max_lat": 1], "poly": escaped]
            case "packed_base": poisoned[field] = ["version": 1, "roads": escaped]
            default: poisoned[field] = escaped
            }
            let data = try JSONSerialization.data(withJSONObject: poisoned)
            XCTAssertThrowsError(try JSONDecoder().decode(V3BundleManifest.self, from: data), field)
        }
        for name in ["", ".", "..", "a/b", "a\\b", "a\0b", " a.sqlite"] {
            XCTAssertThrowsError(try BundlePathSafety.validateFileName(name), name)
        }
        for region in ["../germany", "germany/../journal", "/germany", "germany//baden", "germany/"] {
            XCTAssertThrowsError(try BundlePathSafety.validateRegion(region), region)
        }
    }

    func testLegacyDownloadAndDeltaCannotOverwriteSiblingJournalAndKeepHierarchicalActiveLayout() async throws {
        guard Bundle.main.bundleIdentifier == "de.youspeed.SpeedConsumer.TestHost" else {
            throw XCTSkip("This install regression requires the isolated TestHost")
        }
        let fm = FileManager.default
        let support = try V3BundleManager.applicationSupportDirectory()
        try? fm.removeItem(at: support)
        try fm.createDirectory(at: support, withIntermediateDirectories: true)
        defer { PackedRuntimeURLProtocol.configure([:]); try? fm.removeItem(at: support) }
        func database(_ path: URL, sql: String) throws {
            var handle: OpaquePointer?
            XCTAssertEqual(sqlite3_open(path.path, &handle), SQLITE_OK)
            let db = try XCTUnwrap(handle)
            defer { sqlite3_close(db) }
            XCTAssertEqual(sqlite3_exec(db, sql, nil, nil, nil), SQLITE_OK, String(cString: sqlite3_errmsg(db)))
        }
        let source = support.appendingPathComponent("source.sqlite")
        try database(source, sql: """
            CREATE TABLE ways(way_id INTEGER PRIMARY KEY,street_name TEXT);
            CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
            CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
            INSERT INTO ways VALUES(1,'Before');
            """)
        let journalDirectory = support.appendingPathComponent("trip-journal")
        try fm.createDirectory(at: journalDirectory, withIntermediateDirectories: true)
        let journal = journalDirectory.appendingPathComponent("journal.sqlite")
        try database(journal, sql: "CREATE TABLE events(value TEXT); INSERT INTO events VALUES('private sentinel');")
        let privateBytes = try Data(contentsOf: journal), data = try Data(contentsOf: source)
        let manifestURL = URL(string: "https://packed-runtime.test/manifest.json")!
        let sourceURL = URL(string: "https://packed-runtime.test/speeds.sqlite")!
        func manifest(version: String = "2026-09-01", file: String = "speeds.sqlite", region: String = "germany/baden-wuerttemberg",
                      delta: BundleArtifact? = nil) -> V3BundleManifest {
            V3BundleManifest(format: "youspeed.v3.bundle.manifest", schemaVersion: 1, variant: "v3", region: region,
                bundleVersion: version, createdAtUTC: "fixture", minAppVersion: "1.0",
                db: BundleArtifact(file: file, bytes: Int64(data.count), sha256: sha(data), url: sourceURL.absoluteString),
                dbParts: nil, deltaIndex: delta)
        }
        // Pruning must keep real nested generations without following a
        // directory link that merely points at a bundle outside map storage.
        let external = fm.temporaryDirectory.appendingPathComponent("prune-external-\(UUID().uuidString)")
        try fm.createDirectory(at: external, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: external) }
        try data.write(to: external.appendingPathComponent("speeds.sqlite"))
        try JSONEncoder().encode(manifest()).write(to: external.appendingPathComponent("bundle-manifest.v3.json"))
        let orphan = support.appendingPathComponent("bundles/prune-orphan")
        try fm.createDirectory(at: orphan, withIntermediateDirectories: true)
        try fm.createSymbolicLink(at: orphan.appendingPathComponent("linked-generation"), withDestinationURL: external)
        let manager = V3BundleManager(session: Self.session())
        PackedRuntimeURLProtocol.configure([manifestURL.absoluteString: (200, try JSONEncoder().encode(manifest())), sourceURL.absoluteString: (200, data)])
        let initial = try await manager.syncFromManifestURL(manifestURL)
        XCTAssertTrue(initial.dbPath.contains("/bundles/germany/baden-wuerttemberg-2026-09-01/"))
        XCTAssertFalse(fm.fileExists(atPath: orphan.path), "A symlink target must not count as a stored descendant")
        XCTAssertEqual(try Data(contentsOf: external.appendingPathComponent("speeds.sqlite")), data)
        let reloaded = V3BundleManager(session: Self.session())
        let reloadedURL = try await reloaded.activeDatabaseURL()
        XCTAssertEqual(reloadedURL?.path, initial.dbPath, "Existing hierarchical-region paths must retain their layout")
        let state = try Data(contentsOf: support.appendingPathComponent("active_bundle.json"))
        for invalid in [manifest(version: "2026-09-02", file: "../../../trip-journal/journal.sqlite"),
                        manifest(version: "../../trip-journal"), manifest(region: "germany/../trip-journal")] {
            PackedRuntimeURLProtocol.configure([manifestURL.absoluteString: (200, try JSONEncoder().encode(invalid)), sourceURL.absoluteString: (200, data)])
            do { _ = try await manager.syncFromManifestURL(manifestURL); XCTFail("Unsafe paths must reject before activation") } catch {}
            XCTAssertEqual(try Data(contentsOf: journal), privateBytes)
            XCTAssertEqual(try Data(contentsOf: support.appendingPathComponent("active_bundle.json")), state)
        }
        let poisoned = support.appendingPathComponent("bundles/poison")
        try fm.createDirectory(at: poisoned, withIntermediateDirectories: true)
        try JSONEncoder().encode(manifest(file: "../../trip-journal/journal.sqlite"))
            .write(to: poisoned.appendingPathComponent("bundle-manifest.v3.json"))
        let inventory = try await manager.listDownloadedBundles()
        XCTAssertFalse(inventory.contains { $0.dbPath.contains("/trip-journal/") })

        let attack = Data("ATTACH DATABASE '\(journal.path.replacingOccurrences(of: "'", with: "''"))' AS private; DELETE FROM private.events; DETACH DATABASE private;".utf8)
        let index = Data(#"{"format":"youspeed.v3.delta.index","schema_version":1,"count":1,"entries":[{"from_bundle_version":"2026-09-01","to_bundle_version":"2026-09-02","region":"germany/baden-wuerttemberg","delta_manifest_file":"deltas/attack.json"}]}"#.utf8)
        let deltaManifest: [String: Any] = ["format": "youspeed.v3.delta.manifest", "schema_version": 1,
            "region": "germany/baden-wuerttemberg", "from_bundle_version": "2026-09-01", "to_bundle_version": "2026-09-02",
            "patch": ["file": "attack.sql", "bytes": attack.count, "sha256": sha(attack)]]
        let target = manifest(version: "2026-09-02", delta: BundleArtifact(file: "index.json", bytes: Int64(index.count), sha256: sha(index), url: nil))
        PackedRuntimeURLProtocol.configure([manifestURL.absoluteString: (200, try JSONEncoder().encode(target)),
            "https://packed-runtime.test/index.json": (200, index),
            "https://packed-runtime.test/deltas/attack.json": (200, try JSONSerialization.data(withJSONObject: deltaManifest)),
            "https://packed-runtime.test/deltas/attack.sql": (200, attack)])
        do { _ = try await manager.syncFromManifestURL(manifestURL); XCTFail("Publisher SQL must not attach private databases") } catch {}
        XCTAssertEqual(try Data(contentsOf: journal), privateBytes)
        XCTAssertEqual(try Data(contentsOf: support.appendingPathComponent("active_bundle.json")), state)
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: initial.dbPath)), data)
        let staging = support.appendingPathComponent("staging")
        XCTAssertTrue((try? fm.contentsOfDirectory(atPath: staging.path).isEmpty) ?? true)
    }

    private static func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [PackedRuntimeURLProtocol.self]
        return URLSession(configuration: configuration)
    }
    private func sha(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    private func gzip(_ data: Data) throws -> Data {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".gz")
        defer { try? FileManager.default.removeItem(at: url) }
        let file = try XCTUnwrap(gzopen(url.path, "wb9"))
        let wrote = data.withUnsafeBytes { gzwrite(file, $0.baseAddress, UInt32($0.count)) }
        let closed = gzclose(file)
        XCTAssertEqual(wrote, Int32(data.count)); XCTAssertEqual(closed, Z_OK)
        return try Data(contentsOf: url)
    }
}

private final class PackedRuntimeURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var responses: [String: (Int, Data)] = [:]
    static func configure(_ value: [String: (Int, Data)]) { lock.lock(); responses = value; lock.unlock() }
    override class func canInit(with request: URLRequest) -> Bool { request.url?.host == "packed-runtime.test" }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); let value = request.url.flatMap { Self.responses[$0.absoluteString] }; Self.lock.unlock()
        guard let url = request.url, let value,
              let response = HTTPURLResponse(url: url, statusCode: value.0, httpVersion: "HTTP/1.1",
                headerFields: ["Content-Length": "\(value.1.count)"]) else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable)); return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: value.1)
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
