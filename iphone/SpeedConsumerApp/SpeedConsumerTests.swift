import XCTest
@testable import SpeedConsumer
import CryptoKit
import SQLite3
import CoreLocation

final class SpeedConsumerTests: XCTestCase {
    func testParseExplicitSpeed() {
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed("30"), 30)
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed("80 km/h"), 80)
        XCTAssertNil(V3SpeedLimitService.parseExplicitSpeed("signals"))
    }

    func testDeriveSpeedLimitFallbacks() {
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: "DE:urban", sourceMaxspeed: nil, highway: nil), 50)
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: nil, sourceMaxspeed: "DE:rural", highway: nil), 100)
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: nil, sourceMaxspeed: nil, highway: "motorway"), 130)
    }

    func testFormattedStreetDisplayUsesNameRefFallbackRules() {
        XCTAssertEqual(
            V3SpeedLimitService.formattedStreetDisplay(streetName: "Main Street", ref: nil),
            "Main Street"
        )
        XCTAssertEqual(
            V3SpeedLimitService.formattedStreetDisplay(streetName: nil, ref: "L 605"),
            "L 605"
        )
        XCTAssertEqual(
            V3SpeedLimitService.formattedStreetDisplay(streetName: "Main Street", ref: "L 605"),
            "Main Street (L 605)"
        )
        XCTAssertNil(
            V3SpeedLimitService.formattedStreetDisplay(streetName: nil, ref: nil)
        )
        XCTAssertNil(
            V3SpeedLimitService.formattedStreetDisplay(streetName: "   ", ref: " ")
        )
    }

    func testPenaltyRuleEngineResolvesBands() {
        let rules = SpeedPenaltyRuleSet.fallbackDEU()

        let moneyOnly = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 8, rules: rules)
        XCTAssertEqual(moneyOnly?.severity, .moneyOnly)
        XCTAssertEqual(moneyOnly?.deltaKmh, 8)
        XCTAssertEqual(moneyOnly?.moneyFineEUR, 30)

        let pointsAndFine = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 35, rules: rules)
        XCTAssertEqual(pointsAndFine?.severity, .pointsAndFine)
        XCTAssertEqual(pointsAndFine?.deltaKmh, 35)
        XCTAssertEqual(pointsAndFine?.penaltyPoints, 2)
    }

    func testLoadBundledDEURules() throws {
        let rules = try SpeedPenaltyRuleSet.loadBundled(
            named: "DEU-rules",
            bundle: Bundle(for: SpeedConsumerAppDelegate.self)
        )
        XCTAssertEqual(rules.countryCode, "DEU")
        XCTAssertEqual(rules.currencyCode, "EUR")
        XCTAssertGreaterThanOrEqual(rules.bands.count, 1)
        XCTAssertEqual(rules.bands.first?.moneyFineEUR, 30)
        XCTAssertEqual(rules.bands.last?.penaltyPoints, 2)
    }

    func testPenaltyRuleEngineUsesInnerortsAusserortsVariants() throws {
        let rules = try SpeedPenaltyRuleSet.loadBundled(
            named: "DEU-rules",
            bundle: Bundle(for: SpeedConsumerAppDelegate.self)
        )

        let inner = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 12, rules: rules, insideCity: true)
        let outer = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 12, rules: rules, insideCity: false)
        XCTAssertEqual(inner?.moneyFineEUR, 50)
        XCTAssertEqual(outer?.moneyFineEUR, 40)

        let innerHigh = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 31, rules: rules, insideCity: true)
        let outerHigh = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 31, rules: rules, insideCity: false)
        XCTAssertEqual(innerHigh?.penaltyPoints, 2)
        XCTAssertEqual(outerHigh?.penaltyPoints, 1)
        XCTAssertEqual(innerHigh?.drivingBanMonths, 1)
        XCTAssertEqual(outerHigh?.drivingBanMonths, 0)

        let outerVeryHigh = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 41, rules: rules, insideCity: false)
        XCTAssertEqual(outerVeryHigh?.drivingBanMonths, 1)
    }

    func testDecodeBundleManifest() throws {
        let raw = """
        {
          "format": "youspeed.v3.bundle.manifest",
          "schema_version": 1,
          "variant": "v3",
          "region": "germany",
          "bundle_version": "2026-02-24",
          "created_at_utc": "2026-02-24T00:00:00Z",
          "min_app_version": "1.0.0",
          "db": {
            "file": "DEU-latest.speeds_v3.sqlite",
            "bytes": 123,
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "url": "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.speeds_v3.sqlite"
          },
          "delta_index": null
        }
        """
        let data = Data(raw.utf8)
        let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: data)
        XCTAssertEqual(manifest.variant, "v3")
        XCTAssertEqual(manifest.bundleVersion, "2026-02-24")
        XCTAssertEqual(manifest.db.file, "DEU-latest.speeds_v3.sqlite")
    }

    @MainActor
    func testDefaultGitHubReleaseTokenFromInfoDictionary() {
        let token = DriveSessionViewModel.defaultGitHubReleaseToken(
            infoDictionary: [
                "YOUSPEED_RELEASE_READ_TOKEN": "  built-in-token  ",
            ]
        )
        XCTAssertEqual(token, "built-in-token")
    }

    @MainActor
    func testDefaultGitHubReleaseTokenIgnoresPlaceholderAndUsesFallbackKey() {
        let token = DriveSessionViewModel.defaultGitHubReleaseToken(
            infoDictionary: [
                "YOUSPEED_RELEASE_READ_TOKEN": "$(YOUSPEED_RELEASE_READ_TOKEN)",
                "YouSpeedGitHubReleaseToken": "fallback-token",
            ]
        )
        XCTAssertEqual(token, "fallback-token")
    }

    @MainActor
    func testDefaultManifestURLFromInfoDictionary() {
        let raw = "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.bundle-manifest.v3.json"
        let url = DriveSessionViewModel.defaultManifestURL(
            infoDictionary: [
                "YouSpeedV3ManifestURL": raw,
            ]
        )
        XCTAssertEqual(url?.absoluteString, raw)
    }

    @MainActor
    func testDefaultManifestURLIgnoresPlaceholderAndInvalidScheme() {
        let placeholder = DriveSessionViewModel.defaultManifestURL(
            infoDictionary: [
                "YouSpeedV3ManifestURL": "$(YOSPEED_MANIFEST_URL)",
            ]
        )
        XCTAssertNil(placeholder)

        let invalidScheme = DriveSessionViewModel.defaultManifestURL(
            infoDictionary: [
                "YouSpeedV3ManifestURL": "file:///tmp/manifest.json",
            ]
        )
        XCTAssertNil(invalidScheme)
    }

    func testMultipartBundleSyncAndFirstQuery() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-tests-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)
        let sourceSHA = sha256Hex(sourceData)
        XCTAssertGreaterThan(sourceData.count, 0)

        let splitAt = max(1, sourceData.count / 2)
        let part1Data = sourceData.subdata(in: 0..<splitAt)
        let part2Data = sourceData.subdata(in: splitAt..<sourceData.count)

        let manifestURL = URL(string: "https://speedconsumer.test/DEU-latest.bundle-manifest.v3.json")!
        let part1URL = URL(string: "https://speedconsumer.test/DEU-latest.speeds_v3.sqlite.part001")!
        let part2URL = URL(string: "https://speedconsumer.test/DEU-latest.speeds_v3.sqlite.part002")!

        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "DEU",
            bundleVersion: "2026-02-24",
            createdAtUTC: "2026-02-24T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-latest.speeds_v3.sqlite",
                bytes: Int64(sourceData.count),
                sha256: sourceSHA,
                url: nil
            ),
            dbParts: [
                BundleArtifact(
                    file: "DEU-latest.speeds_v3.sqlite.part001",
                    bytes: Int64(part1Data.count),
                    sha256: sha256Hex(part1Data),
                    url: part1URL.absoluteString
                ),
                BundleArtifact(
                    file: "DEU-latest.speeds_v3.sqlite.part002",
                    bytes: Int64(part2Data.count),
                    sha256: sha256Hex(part2Data),
                    url: part2URL.absoluteString
                ),
            ],
            deltaIndex: nil
        )
        let manifestData = try JSONEncoder().encode(manifest)

        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 200, body: manifestData),
            part1URL.absoluteString: (status: 200, body: part1Data),
            part2URL.absoluteString: (status: 200, body: part2Data),
        ]
        defer {
            MockURLProtocol.responses = [:]
        }

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let manager = V3BundleManager(fileManager: fm, session: session)

        let sync = try await manager.syncFromManifestURL(manifestURL)
        XCTAssertEqual(sync.mode, .fullDownload)
        XCTAssertEqual(sync.bundleVersion, "2026-02-24")

        guard let dbURL = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after multipart sync")
            return
        }
        XCTAssertTrue(fm.fileExists(atPath: dbURL.path))
        let assembledData = try Data(contentsOf: dbURL)
        XCTAssertEqual(sourceData.count, assembledData.count)
        XCTAssertEqual(sourceSHA, sha256Hex(assembledData))

        let service = V3SpeedLimitService(dbPath: dbURL.path)
        let result = try service.lookupSpeedLimit(
            lat: 52.5205,
            lon: 13.4055,
            radiusM: 250.0,
            maxCandidates: 64
        )
        XCTAssertEqual(result.wayID, "100")
        XCTAssertEqual(result.speedLimitKmh, 30)
        XCTAssertEqual(result.streetName, "Fixture Main Street")
        XCTAssertEqual(result.cityName, "Fixture City")
        XCTAssertEqual(result.insideCity, true)
    }

    func testMultipartSyncReusesCachedPartAfterLaterPartFailure() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-cache-tests-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)
        let sourceSHA = sha256Hex(sourceData)

        let splitAt = max(1, sourceData.count / 2)
        let part1Data = sourceData.subdata(in: 0..<splitAt)
        let part2Data = sourceData.subdata(in: splitAt..<sourceData.count)

        let manifestURL = URL(string: "https://speedconsumer.test/DEU-latest.bundle-manifest.v3.json")!
        let part1URL = URL(string: "https://speedconsumer.test/DEU-latest.speeds_v3.sqlite.part001")!
        let part2URL = URL(string: "https://speedconsumer.test/DEU-latest.speeds_v3.sqlite.part002")!

        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "DEU",
            bundleVersion: "2026-02-24",
            createdAtUTC: "2026-02-24T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-latest.speeds_v3.sqlite",
                bytes: Int64(sourceData.count),
                sha256: sourceSHA,
                url: nil
            ),
            dbParts: [
                BundleArtifact(
                    file: "DEU-latest.speeds_v3.sqlite.part001",
                    bytes: Int64(part1Data.count),
                    sha256: sha256Hex(part1Data),
                    url: part1URL.absoluteString
                ),
                BundleArtifact(
                    file: "DEU-latest.speeds_v3.sqlite.part002",
                    bytes: Int64(part2Data.count),
                    sha256: sha256Hex(part2Data),
                    url: part2URL.absoluteString
                ),
            ],
            deltaIndex: nil
        )
        let manifestData = try JSONEncoder().encode(manifest)

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let manager = V3BundleManager(fileManager: fm, session: session)

        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 200, body: manifestData),
            part1URL.absoluteString: (status: 200, body: part1Data),
            part2URL.absoluteString: (status: 500, body: Data("broken".utf8)),
        ]
        do {
            _ = try await manager.syncFromManifestURL(manifestURL)
            XCTFail("Expected initial sync to fail while downloading part 2")
        } catch {
            // Expected.
        }

        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 200, body: manifestData),
            part1URL.absoluteString: (status: 404, body: Data("should not be downloaded again".utf8)),
            part2URL.absoluteString: (status: 200, body: part2Data),
        ]
        defer {
            MockURLProtocol.responses = [:]
        }

        let sync = try await manager.syncFromManifestURL(manifestURL)
        XCTAssertEqual(sync.mode, .fullDownload)
        XCTAssertEqual(sync.bundleVersion, "2026-02-24")

        guard let dbURL = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after retry")
            return
        }
        let assembledData = try Data(contentsOf: dbURL)
        XCTAssertEqual(sourceSHA, sha256Hex(assembledData))
    }

    func testStartupRecoveryActivatesValidStagingDatabase() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let stageDir = supportDir.appendingPathComponent("staging", isDirectory: true)
        try fm.createDirectory(at: stageDir, withIntermediateDirectories: true)

        let recoveredCandidate = stageDir.appendingPathComponent("2026-02-24-\(UUID().uuidString).sqlite")
        try createFixtureV3DB(at: recoveredCandidate)
        let staleCandidate = stageDir.appendingPathComponent("stale.sqlite")
        try Data("not a sqlite database".utf8).write(to: staleCandidate, options: .atomic)

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let recovered = try await manager.recoverLocalDataAtStartup()
        XCTAssertNotNil(recovered)
        XCTAssertEqual(recovered?.bundleVersion, "2026-02-24")

        guard let activeDB = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after startup recovery")
            return
        }
        XCTAssertTrue(fm.fileExists(atPath: activeDB.path))
        XCTAssertFalse(fm.fileExists(atPath: recoveredCandidate.path), "Staging candidate should be moved into active bundles")

        let remainingStageEntries = (try? fm.contentsOfDirectory(atPath: stageDir.path)) ?? []
        XCTAssertTrue(remainingStageEntries.isEmpty, "Expected staging artifacts cleanup after recovery, got: \(remainingStageEntries)")

        let service = V3SpeedLimitService(dbPath: activeDB.path)
        let result = try service.lookupSpeedLimit(
            lat: 52.5205,
            lon: 13.4055,
            radiusM: 250.0,
            maxCandidates: 64
        )
        XCTAssertEqual(result.speedLimitKmh, 30)
        XCTAssertEqual(result.wayID, "100")
    }

    func testStartupRecoveryRemovesUnusableRemnantsWhenNothingIsRecoverable() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let stageDir = supportDir.appendingPathComponent("staging", isDirectory: true)
        let cacheDir = supportDir.appendingPathComponent("multipart-cache", isDirectory: true)
        try fm.createDirectory(at: stageDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: cacheDir, withIntermediateDirectories: true)

        let stageGarbage = stageDir.appendingPathComponent("broken.sqlite")
        try Data("broken-stage".utf8).write(to: stageGarbage, options: .atomic)

        let cacheGarbage = cacheDir.appendingPathComponent("deadbeef.assembled.sqlite")
        let checkpointGarbage = cacheDir.appendingPathComponent("deadbeef.checkpoint.json")
        try Data("broken-cache".utf8).write(to: cacheGarbage, options: .atomic)
        try Data("{\"nextPartIndex\":1,\"assembledBytes\":128}".utf8).write(to: checkpointGarbage, options: .atomic)

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let recovered = try await manager.recoverLocalDataAtStartup()
        XCTAssertNil(recovered)

        let remainingStageEntries = (try? fm.contentsOfDirectory(atPath: stageDir.path)) ?? []
        let remainingCacheEntries = (try? fm.contentsOfDirectory(atPath: cacheDir.path)) ?? []
        XCTAssertTrue(remainingStageEntries.isEmpty, "Expected staging remnants to be removed, got: \(remainingStageEntries)")
        XCTAssertTrue(remainingCacheEntries.isEmpty, "Expected multipart cache remnants to be removed, got: \(remainingCacheEntries)")
    }

    func testStartupRecoveryPrefersDownloadedCacheOverActiveSeed() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundlesDir = supportDir.appendingPathComponent("bundles", isDirectory: true)
        let seedDir = bundlesDir.appendingPathComponent("seed", isDirectory: true)
        let cacheDir = supportDir.appendingPathComponent("multipart-cache", isDirectory: true)
        try fm.createDirectory(at: seedDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: cacheDir, withIntermediateDirectories: true)

        let seedDB = seedDir.appendingPathComponent("speeds_v3.sqlite")
        try createFixtureV3DB(at: seedDB)

        let activeState = ActiveBundleState(
            region: "unknown",
            bundleVersion: "seed",
            dbFileName: "speeds_v3.sqlite",
            activatedAtUTC: "2026-02-25T00:00:00Z"
        )
        let activeStateData = try JSONEncoder().encode(activeState)
        try activeStateData.write(to: supportDir.appendingPathComponent("active_bundle.json"), options: .atomic)

        let downloadedCacheDB = cacheDir.appendingPathComponent("abcdef.assembled.sqlite")
        try createFixtureV3DB(at: downloadedCacheDB)

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let recovered = try await manager.recoverLocalDataAtStartup()
        XCTAssertNotNil(recovered)
        XCTAssertNotEqual(recovered?.bundleVersion, "seed")

        guard let activeDB = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after startup recovery")
            return
        }
        XCTAssertFalse(activeDB.path.contains("/bundles/seed/"), "Should not keep seed as active DB when downloaded cache exists")
        XCTAssertFalse(fm.fileExists(atPath: downloadedCacheDB.path), "Recovered cache DB should be moved out of multipart-cache")
    }

    func testBootstrapSeedUsesBundledDatabasePathWithoutCopy() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let appBundle = Bundle(for: SpeedConsumerAppDelegate.self)
        guard let bundledSeed = appBundle.url(forResource: "speeds_v3", withExtension: "sqlite") else {
            throw XCTSkip("Bundled seed DB not found")
        }

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let result = try await manager.bootstrapSeedIfNeeded(bundle: appBundle)

        XCTAssertEqual(result.bundleVersion, "seed")
        XCTAssertEqual(result.dbPath, bundledSeed.path)
        XCTAssertEqual(result.details, "seed bundle referenced")

        let state = try await manager.activeState()
        XCTAssertEqual(state?.bundleVersion, "seed")
        XCTAssertEqual(state?.dbPath, bundledSeed.path)

        let copiedSeedDB = supportDir
            .appendingPathComponent("bundles", isDirectory: true)
            .appendingPathComponent("seed", isDirectory: true)
            .appendingPathComponent("speeds_v3.sqlite")
        XCTAssertFalse(fm.fileExists(atPath: copiedSeedDB.path), "Seed should not be copied into app support on clean bootstrap")
    }

    func testBootstrapSeedMigratesOldCopiedSeedToBundledPath() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundlesDir = supportDir.appendingPathComponent("bundles", isDirectory: true)
        let seedDir = bundlesDir.appendingPathComponent("seed", isDirectory: true)
        try fm.createDirectory(at: seedDir, withIntermediateDirectories: true)
        let copiedSeedDB = seedDir.appendingPathComponent("speeds_v3.sqlite")
        try createFixtureV3DB(at: copiedSeedDB)

        let legacySeedState = ActiveBundleState(
            region: "unknown",
            bundleVersion: "seed",
            dbFileName: "speeds_v3.sqlite",
            activatedAtUTC: "2026-02-25T00:00:00Z"
        )
        try JSONEncoder().encode(legacySeedState).write(
            to: supportDir.appendingPathComponent("active_bundle.json"),
            options: .atomic
        )

        let appBundle = Bundle(for: SpeedConsumerAppDelegate.self)
        guard let bundledSeed = appBundle.url(forResource: "speeds_v3", withExtension: "sqlite") else {
            throw XCTSkip("Bundled seed DB not found")
        }

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let result = try await manager.bootstrapSeedIfNeeded(bundle: appBundle)

        XCTAssertEqual(result.bundleVersion, "seed")
        XCTAssertEqual(result.dbPath, bundledSeed.path)
        XCTAssertFalse(fm.fileExists(atPath: copiedSeedDB.path), "Legacy copied seed should be removed after migration")

        let state = try await manager.activeState()
        XCTAssertEqual(state?.dbPath, bundledSeed.path)
    }

    @MainActor
    func testSyncResolvesGitHubReleaseURLsViaAPIWithAuthorization() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-auth-tests-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)

        let manifestURL = URL(string: "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.bundle-manifest.v3.json")!
        let dbURL = URL(string: "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.speeds_v3.sqlite")!
        let releaseTagURL = URL(string: "https://api.github.com/repos/volzinnovation/youspeed.de/releases/tags/deu-v3-data-latest")!
        let manifestAssetURL = URL(string: "https://api.github.com/repos/volzinnovation/youspeed.de/releases/assets/1001")!
        let dbAssetURL = URL(string: "https://api.github.com/repos/volzinnovation/youspeed.de/releases/assets/1002")!
        let token = DriveSessionViewModel.defaultGitHubReleaseToken(
            infoDictionary: [
                "YOUSPEED_RELEASE_READ_TOKEN": "test-token",
            ]
        )
        XCTAssertEqual(token, "test-token")

        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "DEU",
            bundleVersion: "2026-02-24",
            createdAtUTC: "2026-02-24T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-latest.speeds_v3.sqlite",
                bytes: Int64(sourceData.count),
                sha256: sha256Hex(sourceData),
                url: dbURL.absoluteString
            ),
            dbParts: nil,
            deltaIndex: nil
        )
        let manifestData = try JSONEncoder().encode(manifest)

        let releasePayload = """
        {
          "assets": [
            { "id": 1001, "name": "DEU-latest.bundle-manifest.v3.json" },
            { "id": 1002, "name": "DEU-latest.speeds_v3.sqlite" }
          ]
        }
        """
        MockURLProtocol.responses = [
            releaseTagURL.absoluteString: (status: 200, body: Data(releasePayload.utf8)),
            manifestAssetURL.absoluteString: (status: 200, body: manifestData),
            dbAssetURL.absoluteString: (status: 200, body: sourceData),
        ]
        MockURLProtocol.requiredAuthorizationPrefixByURL = [
            releaseTagURL.absoluteString: "Bearer \(token)",
            manifestAssetURL.absoluteString: "Bearer \(token)",
            dbAssetURL.absoluteString: "Bearer \(token)",
        ]
        defer {
            MockURLProtocol.responses = [:]
            MockURLProtocol.requiredAuthorizationPrefixByURL = [:]
        }

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let manager = V3BundleManager(fileManager: fm, session: session)
        await manager.setGitHubToken(token)

        let sync = try await manager.syncFromManifestURL(manifestURL)
        XCTAssertEqual(sync.mode, .fullDownload)
        XCTAssertEqual(sync.bundleVersion, "2026-02-24")
    }

    func testHTTPErrorIncludesStatusAndBodyPreview() async throws {
        let manifestURL = URL(string: "https://speedconsumer.test/DEU-latest.bundle-manifest.v3.json")!
        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 404, body: Data("{\"message\":\"Not Found\"}".utf8)),
        ]
        defer {
            MockURLProtocol.responses = [:]
        }

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let manager = V3BundleManager(fileManager: .default, session: session)

        do {
            _ = try await manager.syncFromManifestURL(manifestURL)
            XCTFail("Expected syncFromManifestURL to fail on HTTP 404")
        } catch let ConsumerAppError.network(message) {
            XCTAssertTrue(message.contains("status=404"), "Expected status code in error message: \(message)")
            XCTAssertTrue(message.contains("Not Found"), "Expected body preview in error message: \(message)")
            XCTAssertTrue(message.contains(manifestURL.absoluteString), "Expected URL in error message: \(message)")
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testReplayTrackFromGPXFixture() throws {
        let track = try parseGPXTrack(url: fixtureURL(named: "replay_track.gpx"))
        let expected = try loadReplayExpectations(url: fixtureURL(named: "replay_expected.json"))
        try runReplayAssertion(track: track, expected: expected, radiusM: 120.0)
    }

    func testReplayTrackFromKMLFixture() throws {
        let track = try parseKMLTrack(url: fixtureURL(named: "replay_track.kml"))
        let expected = try loadReplayExpectations(url: fixtureURL(named: "replay_expected.json"))
        try runReplayAssertion(track: track, expected: expected, radiusM: 120.0)
    }

    func testRealReleaseSyncAssembleAndLookup_whenEnabled() async throws {
        let env = ProcessInfo.processInfo.environment
        if env["SPEEDCONSUMER_SKIP_REAL_RELEASE_SYNC"] == "1" {
            throw XCTSkip("SPEEDCONSUMER_SKIP_REAL_RELEASE_SYNC=1")
        }
        let autoTapSyncEnabled = isAutoTapSyncEnabled(env: env)
        let envTokenCandidates = ["SPEEDCONSUMER_GITHUB_TOKEN", "YOUSPEED_RELEASE_READ_TOKEN", "GITHUB_RELEASE_TOKEN"]
        let envToken = envTokenCandidates
            .compactMap { env[$0] }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && !$0.contains("$(") } ?? ""
        let token = !envToken.isEmpty ? envToken : embeddedGitHubReleaseToken()
        guard !token.isEmpty else {
            throw XCTSkip("Set SPEEDCONSUMER_GITHUB_TOKEN or YOUSPEED_RELEASE_READ_TOKEN (or GITHUB_RELEASE_TOKEN) to access private GitHub release assets")
        }

        let lat = Double(env["SPEEDCONSUMER_TEST_LAT"] ?? "48.801157") ?? 48.801157
        let lon = Double(env["SPEEDCONSUMER_TEST_LON"] ?? "8.442467") ?? 8.442467

        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        let manager: V3BundleManager
        if autoTapSyncEnabled {
            manager = V3BundleManager(fileManager: fm)
            print("REAL_RELEASE_AUTOTAP_WAIT started")
            let didActivate = try await waitForTapDrivenSyncActivation(manager: manager, timeoutSeconds: 1800)
            XCTAssertTrue(didActivate, "Timed out waiting for tap-driven sync activation")
            if !didActivate {
                return
            }
        } else {
            if fm.fileExists(atPath: supportDir.path) {
                try fm.removeItem(at: supportDir)
            }
            defer {
                try? fm.removeItem(at: supportDir)
            }

            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = 300
            config.timeoutIntervalForResource = 14_400
            let session = URLSession(configuration: config)
            manager = V3BundleManager(fileManager: fm, session: session)
            await manager.setGitHubToken(token)

            let manifestURL = embeddedManifestURL()
                ?? URL(string: "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.bundle-manifest.v3.json")!
            let sync = try await manager.syncFromManifestURL(manifestURL)
            XCTAssertTrue([BundleSyncResult.Mode.fullDownload, BundleSyncResult.Mode.upToDate].contains(sync.mode))
        }

        guard let dbURL = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after real release sync")
            return
        }
        let activeState = try await manager.activeState()
        guard let activeState else {
            XCTFail("Expected active bundle state after real release sync")
            return
        }
        let activatedManifestURL = supportDir
            .appendingPathComponent("bundles", isDirectory: true)
            .appendingPathComponent(activeState.bundleVersion, isDirectory: true)
            .appendingPathComponent("bundle-manifest.v3.json")
        let activatedManifestData = try Data(contentsOf: activatedManifestURL)
        let activatedManifest = try JSONDecoder().decode(V3BundleManifest.self, from: activatedManifestData)
        let assembledSize = try fileSize(dbURL)
        XCTAssertEqual(assembledSize, activatedManifest.db.bytes, "Assembled DB size mismatch after sync")
        print("REAL_RELEASE_ASSEMBLED db=\(dbURL.lastPathComponent) size=\(assembledSize) expected=\(activatedManifest.db.bytes)")

        try assertDBIntegrity(dbURL)
        let first = try readFirstWayRow(dbURL)
        print(String(format: "REAL_RELEASE_FIRST_ROW row_id=%lld way_id=%@ min_lat=%.6f min_lon=%.6f", first.rowID, first.wayID, first.minLat, first.minLon))

        let service = V3SpeedLimitService(dbPath: dbURL.path)
        let result = try service.lookupSpeedLimit(lat: lat, lon: lon, radiusM: 1500.0, maxCandidates: 2048)
        print(
            String(
                format: "REAL_RELEASE_LOCATION_QUERY lat=%.6f lon=%.6f way_id=%@ speed_kmh=%@ query_ms=%.3f rows=%d speed_rows=%d",
                lat,
                lon,
                result.wayID ?? "nil",
                result.speedLimitKmh.map(String.init) ?? "nil",
                result.queryTimeMs,
                result.candidateCount,
                result.speedCandidateCount
            )
        )
        XCTAssertGreaterThan(result.candidateCount, 0, "Expected at least one candidate near test location")
    }

    @MainActor
    func testFirstQueryAtDeviceActualLocation() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let locationManager = CLLocationManager()
        let delegate = OneShotLocationDelegate()
        locationManager.delegate = delegate
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters

        let authorization = locationManager.authorizationStatus
        if authorization == .notDetermined {
            let authExpectation = expectation(description: "Resolve location permission")
            var granted = false
            delegate.onAuthorizationChange = { status in
                switch status {
                case .authorizedWhenInUse, .authorizedAlways:
                    granted = true
                    authExpectation.fulfill()
                case .denied, .restricted:
                    granted = false
                    authExpectation.fulfill()
                case .notDetermined:
                    break
                @unknown default:
                    granted = false
                    authExpectation.fulfill()
                }
            }
            locationManager.requestWhenInUseAuthorization()
            let authWait = XCTWaiter.wait(for: [authExpectation], timeout: 20.0)
            delegate.onAuthorizationChange = nil
            guard authWait == .completed else {
                throw XCTSkip("Location permission prompt did not resolve in time")
            }
            guard granted else {
                throw XCTSkip("Location permission for SpeedConsumer was not granted")
            }
        } else if authorization != .authorizedWhenInUse && authorization != .authorizedAlways {
            throw XCTSkip("Location permission for SpeedConsumer is not granted on this device")
        }

        let locationExpectation = expectation(description: "Receive one GPS location")
        var locationResult: Result<CLLocation, Error>?
        delegate.onResult = { result in
            locationResult = result
            locationExpectation.fulfill()
        }
        locationManager.requestLocation()
        let locationWait = XCTWaiter.wait(for: [locationExpectation], timeout: 15.0)
        guard locationWait == .completed else {
            throw XCTSkip("Device location request did not resolve in time")
        }

        guard let locationResult else {
            XCTFail("Did not receive a device location in time")
            return
        }
        let location = try locationResult.get()

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let started = DispatchTime.now().uptimeNanoseconds
        let result = try service.lookupSpeedLimit(
            lat: location.coordinate.latitude,
            lon: location.coordinate.longitude,
            radiusM: 1500.0,
            maxCandidates: 512
        )
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000.0
        let wayIDText = result.wayID ?? "nil"
        let speedText = result.speedLimitKmh.map(String.init) ?? "nil"
        let serviceMsText = String(format: "%.3f", result.queryTimeMs)

        print(
            String(
                format: "DEVICE_GPS_QUERY lat=%.6f lon=%.6f way_id=%@ speed_kmh=%@ query_ms=%.3f service_query_ms=%@",
                location.coordinate.latitude,
                location.coordinate.longitude,
                wayIDText,
                speedText,
                elapsedMs,
                serviceMsText
            )
        )
        guard let speedLimit = result.speedLimitKmh else {
            throw XCTSkip("No speed limit returned for device location")
        }
        XCTAssertGreaterThan(speedLimit, 0)
    }

    func testBundledKarlsruheSeedLookupIncludesExpectedWayAndResolvesSpeed30Within100m() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let tags = try readWaySpeedTags(dbURL: bundledDB, wayID: "17721265")
        XCTAssertEqual(tags.maxspeed, "30")
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed(tags.maxspeed), 30)
        XCTAssertEqual(
            V3SpeedLimitService.deriveSpeedLimitKmh(
                maxspeed: tags.maxspeed,
                maxspeedType: tags.maxspeedType,
                sourceMaxspeed: tags.sourceMaxspeed,
                highway: tags.highway
            ),
            30
        )

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let result = try service.lookupSpeedLimit(
            lat: 48.801169,
            lon: 8.442691,
            radiusM: 100.0,
            maxCandidates: 512
        )
        let candidates = try readCandidateWayIDs(
            dbURL: bundledDB,
            lat: 48.801169,
            lon: 8.442691,
            radiusM: 100.0,
            maxCandidates: 512
        )
        XCTAssertGreaterThan(
            candidates.count,
            1,
            "Expected overlapping nearby candidates in bbox window (for example 17721265 and 69233057)"
        )
        XCTAssertTrue(candidates.contains("17721265"), "Expected way_id=17721265 in candidate set, got \(candidates)")
        if let returnedWayID = result.wayID {
            XCTAssertTrue(candidates.contains(returnedWayID), "Returned way_id \(returnedWayID) should be part of candidate set \(candidates)")
        }
        // Regression intent: this coordinate can match multiple nearby ways, but the resolved speed must stay stable.
        XCTAssertEqual(result.speedLimitKmh, 30)
    }

    func testLookupSwitchesWayWhenHeadingConflictsWithPreferredWay() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-heading-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("heading_fixture.sqlite")
        try createHeadingDisambiguationFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let turnedResult = try service.lookupSpeedLimit(
            lat: 52.0,
            lon: 13.005,
            radiusM: 80.0,
            maxCandidates: 32,
            preferredWayID: "A1",
            headingDeg: 0.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 40.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(turnedResult.wayID, "B1")
        XCTAssertEqual(turnedResult.speedLimitKmh, 50)

        let lowSpeedResult = try service.lookupSpeedLimit(
            lat: 52.0,
            lon: 13.005,
            radiusM: 80.0,
            maxCandidates: 32,
            preferredWayID: "A1",
            headingDeg: 0.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 2.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(lowSpeedResult.wayID, "A1")
        XCTAssertEqual(lowSpeedResult.speedLimitKmh, 30)
    }

    func testLookupRemainsCompatibleWithLegacySchemaWithoutWayGeomAndApproxHeading() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-legacy-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("legacy_fixture.sqlite")
        try createLegacyFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let onWay = try service.lookupSpeedLimit(
            lat: 52.5205,
            lon: 13.4055,
            radiusM: 80.0,
            maxCandidates: 64,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 40.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(onWay.wayID, "100")
        XCTAssertEqual(onWay.speedLimitKmh, 30)
        XCTAssertNil(onWay.insideCity)

        let insideOnly = try service.lookupSpeedLimit(
            lat: 52.5202,
            lon: 13.4078,
            radiusM: 20.0,
            maxCandidates: 64,
            preferredWayID: nil,
            headingDeg: nil,
            headingAccuracyDeg: nil,
            speedKmh: nil,
            horizontalAccuracyM: nil
        )
        XCTAssertNil(insideOnly.wayID)
        XCTAssertNil(insideOnly.insideCity)
        XCTAssertNil(insideOnly.speedLimitKmh)
    }

    private func createFixtureV3DB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 1, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let schema = """
        CREATE TABLE ways (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          highway TEXT,
          street_name TEXT,
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
          approx_heading_deg REAL,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE areas (
          row_id INTEGER PRIMARY KEY,
          area_id TEXT NOT NULL UNIQUE,
          geometry_type TEXT,
          name TEXT,
          place TEXT,
          boundary TEXT,
          admin_level TEXT,
          residential TEXT,
          points_json TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE areas_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '100', 'residential', 'Fixture Main Street', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 13.4050, 52.5200, 13.4060, 52.5210);
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.4050, 13.4060, 52.5200, 52.5210);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '100', '[[52.5200,13.4050],[52.5210,13.4060]]');
        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '200', 'residential', 'Fixture Side Street', NULL, '50', NULL, NULL, NULL, NULL, 45.0, 13.4072, 52.5218, 13.4080, 52.5222);
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (2, 13.4072, 13.4080, 52.5218, 52.5222);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '200', '[[52.5218,13.4072],[52.5222,13.4080]]');
        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, 'w:400', 'Polygon', 'Fixture City', 'city', 'administrative', '8', NULL, NULL, 13.4040, 52.5190, 13.4090, 52.5240);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, 'w:410', 'Polygon', 'Fixture Residential Zone', NULL, NULL, NULL, 'yes', '[[13.4050,52.5200],[13.4062,52.5200],[13.4062,52.5212],[13.4050,52.5212],[13.4050,52.5200]]', 13.4050, 52.5200, 13.4062, 52.5212);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (2, 13.4050, 13.4062, 52.5200, 52.5212);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 2, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createHeadingDisambiguationFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 101, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let schema = """
        CREATE TABLE ways (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          highway TEXT,
          street_name TEXT,
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
          approx_heading_deg REAL,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, 'A1', 'residential', 'East-West Way', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 13.0000, 51.9999, 13.0100, 52.0001);
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.0000, 13.0100, 51.9999, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, 'A1', '[[52.0000,13.0000],[52.0000,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, 'B1', 'residential', 'North-South Way', NULL, '50', NULL, NULL, NULL, NULL, 0.0, 13.0049, 51.9950, 13.0051, 52.0050);
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (2, 13.0049, 13.0051, 51.9950, 52.0050);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, 'B1', '[[51.9950,13.0050],[52.0050,13.0050]]');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 102, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createLegacyFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 103, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let schema = """
        CREATE TABLE ways (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          highway TEXT,
          street_name TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE areas (
          row_id INTEGER PRIMARY KEY,
          area_id TEXT NOT NULL UNIQUE,
          geometry_type TEXT,
          name TEXT,
          place TEXT,
          boundary TEXT,
          admin_level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE areas_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, maxspeed, maxspeed_type, source_maxspeed, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '100', 'residential', 'Legacy Main Street', '30', NULL, NULL, 13.4050, 52.5200, 13.4060, 52.5210);
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.4050, 13.4060, 52.5200, 52.5210);

        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, 'w:400', 'Polygon', 'Legacy City', 'city', 'administrative', '8', 13.4040, 52.5190, 13.4090, 52.5240);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 104, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func assertDBIntegrity(_ url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open_v2(url.path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 20, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(url.path)"])
        }
        defer { sqlite3_close(db) }

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "PRAGMA quick_check(1)", -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw NSError(domain: "SpeedConsumerTests", code: 21, userInfo: [NSLocalizedDescriptionKey: "prepare quick_check failed"])
        }
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_step(stmt) == SQLITE_ROW else {
            throw NSError(domain: "SpeedConsumerTests", code: 22, userInfo: [NSLocalizedDescriptionKey: "quick_check returned no row"])
        }
        let quickCheck = String(cString: sqlite3_column_text(stmt, 0))
        XCTAssertEqual(quickCheck.lowercased(), "ok", "sqlite quick_check failed: \(quickCheck)")
    }

    private func readFirstWayRow(_ url: URL) throws -> WayRow {
        var db: OpaquePointer?
        guard sqlite3_open_v2(url.path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 23, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(url.path)"])
        }
        defer { sqlite3_close(db) }

        let sql = "SELECT row_id, way_id, min_lat, min_lon FROM ways ORDER BY row_id LIMIT 1"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw NSError(domain: "SpeedConsumerTests", code: 24, userInfo: [NSLocalizedDescriptionKey: "prepare first row query failed"])
        }
        defer { sqlite3_finalize(stmt) }

        guard sqlite3_step(stmt) == SQLITE_ROW else {
            throw NSError(domain: "SpeedConsumerTests", code: 25, userInfo: [NSLocalizedDescriptionKey: "ways table is empty"])
        }
        let rowID = sqlite3_column_int64(stmt, 0)
        let wayID = String(cString: sqlite3_column_text(stmt, 1))
        let minLat = sqlite3_column_double(stmt, 2)
        let minLon = sqlite3_column_double(stmt, 3)
        return WayRow(rowID: rowID, wayID: wayID, minLat: minLat, minLon: minLon)
    }

    private func fixtureURL(named name: String) throws -> URL {
        let filename = name as NSString
        let resource = filename.deletingPathExtension
        let ext = filename.pathExtension
        let bundle = Bundle(for: type(of: self))
        if let url = bundle.url(
            forResource: resource,
            withExtension: ext.isEmpty ? nil : ext
        ) {
            return url
        }
        if let url = bundle.url(
            forResource: resource,
            withExtension: ext.isEmpty ? nil : ext,
            subdirectory: "TestFixtures"
        ) {
            return url
        }
        throw NSError(
            domain: "SpeedConsumerTests",
            code: 26,
            userInfo: [NSLocalizedDescriptionKey: "Missing test fixture \(name) in test bundle"]
        )
    }

    private func bundledSpeedDBURL() -> URL? {
        if let url = Bundle.main.url(forResource: "speeds_v3", withExtension: "sqlite") {
            return url
        }
        return Bundle(for: SpeedConsumerAppDelegate.self).url(forResource: "speeds_v3", withExtension: "sqlite")
    }

    private func readWaySpeedTags(dbURL: URL, wayID: String) throws -> (highway: String?, maxspeed: String, maxspeedType: String?, sourceMaxspeed: String?) {
        var db: OpaquePointer?
        let encodedPath = dbURL.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbURL.path
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 27, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(dbURL.path)"])
        }
        defer { sqlite3_close(db) }

        let escapedWayID = wayID.replacingOccurrences(of: "'", with: "''")
        let sql = "SELECT highway, maxspeed, maxspeed_type, source_maxspeed FROM ways WHERE way_id = '\(escapedWayID)' LIMIT 1"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw NSError(domain: "SpeedConsumerTests", code: 28, userInfo: [NSLocalizedDescriptionKey: "prepare speed tag query failed"])
        }
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_step(stmt) == SQLITE_ROW else {
            throw NSError(domain: "SpeedConsumerTests", code: 29, userInfo: [NSLocalizedDescriptionKey: "way_id \(wayID) not found"])
        }

        guard let maxspeedCString = sqlite3_column_text(stmt, 1) else {
            throw NSError(domain: "SpeedConsumerTests", code: 30, userInfo: [NSLocalizedDescriptionKey: "maxspeed is NULL for way_id \(wayID)"])
        }

        let highway = sqlite3_column_text(stmt, 0).map { String(cString: $0) }
        let maxspeed = String(cString: maxspeedCString)
        let maxspeedType = sqlite3_column_text(stmt, 2).map { String(cString: $0) }
        let sourceMaxspeed = sqlite3_column_text(stmt, 3).map { String(cString: $0) }
        return (highway: highway, maxspeed: maxspeed, maxspeedType: maxspeedType, sourceMaxspeed: sourceMaxspeed)
    }

    private func readCandidateWayIDs(
        dbURL: URL,
        lat: Double,
        lon: Double,
        radiusM: Double,
        maxCandidates: Int
    ) throws -> [String] {
        var db: OpaquePointer?
        let encodedPath = dbURL.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbURL.path
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 31, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(dbURL.path)"])
        }
        defer { sqlite3_close(db) }

        let degLat = radiusM / 111_132.0
        let cosLat = max(0.173648, abs(cos(lat * .pi / 180.0)))
        let degLon = radiusM / (111_320.0 * cosLat)
        let minLon = lon - degLon
        let maxLon = lon + degLon
        let minLat = lat - degLat
        let maxLat = lat + degLat

        let sql = """
        SELECT w.way_id
        FROM ways_rtree r
        JOIN ways w ON w.row_id = r.row_id
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
        LIMIT ?5
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw NSError(domain: "SpeedConsumerTests", code: 32, userInfo: [NSLocalizedDescriptionKey: "prepare candidate query failed"])
        }
        defer { sqlite3_finalize(stmt) }

        sqlite3_bind_double(stmt, 1, maxLon)
        sqlite3_bind_double(stmt, 2, minLon)
        sqlite3_bind_double(stmt, 3, maxLat)
        sqlite3_bind_double(stmt, 4, minLat)
        sqlite3_bind_int64(stmt, 5, Int64(maxCandidates))

        var wayIDs: [String] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            guard let cText = sqlite3_column_text(stmt, 0) else {
                continue
            }
            wayIDs.append(String(cString: cText))
        }
        return wayIDs
    }

    private func isAutoTapSyncEnabled(env: [String: String]) -> Bool {
        if env["SPEEDCONSUMER_TEST_AUTOTAP_SYNC"] == "1" {
            return true
        }
        let infoFlag = (Bundle.main.infoDictionary?["YouSpeedTestAutoTapSync"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return infoFlag == "1"
    }

    private func waitForTapDrivenSyncActivation(
        manager: V3BundleManager,
        timeoutSeconds: TimeInterval
    ) async throws -> Bool {
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: .default)
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            if let state = try await manager.activeState(),
               let dbURL = try await manager.activeDatabaseURL(),
               FileManager.default.fileExists(atPath: dbURL.path) {
                let size = (try? fileSize(dbURL)) ?? 0
                let activatedManifestURL = supportDir
                    .appendingPathComponent("bundles", isDirectory: true)
                    .appendingPathComponent(state.bundleVersion, isDirectory: true)
                    .appendingPathComponent("bundle-manifest.v3.json")
                let hasActivatedManifest = FileManager.default.fileExists(atPath: activatedManifestURL.path)
                let isSeedBundle = state.bundleVersion == "seed"
                if size > 0 && !isSeedBundle && hasActivatedManifest {
                    print("REAL_RELEASE_AUTOTAP_ACTIVATED version=\(state.bundleVersion) db=\(dbURL.lastPathComponent) size=\(size)")
                    return true
                }
            }
            try await Task.sleep(nanoseconds: 2_000_000_000)
        }
        return false
    }

    private func embeddedGitHubReleaseToken() -> String {
        let info = Bundle.main.infoDictionary ?? [:]
        let tokenCandidates = ["YOUSPEED_RELEASE_READ_TOKEN", "YouSpeedGitHubReleaseToken", "GITHUB_RELEASE_TOKEN"]
        return tokenCandidates
            .compactMap { info[$0] as? String }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && !$0.contains("$(") } ?? ""
    }

    private func embeddedManifestURL() -> URL? {
        let info = Bundle.main.infoDictionary ?? [:]
        let manifestCandidates = ["YouSpeedV3ManifestURL", "YouSpeedBundleManifestURL"]
        let manifestRaw = manifestCandidates
            .compactMap { info[$0] as? String }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && !$0.contains("$(") }
        guard let manifestRaw,
              let manifestURL = URL(string: manifestRaw),
              let scheme = manifestURL.scheme?.lowercased(),
              scheme == "http" || scheme == "https" else {
            return nil
        }
        return manifestURL
    }

    private func fileSize(_ url: URL) throws -> Int64 {
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        let sizeNum = attrs[.size] as? NSNumber
        return sizeNum?.int64Value ?? 0
    }

    func testReleaseManifestFilenamesAndURLsReachable_onDevice() async throws {
#if targetEnvironment(simulator)
        throw XCTSkip("Connected-device only test")
#else
        let info = Bundle.main.infoDictionary ?? [:]
        let tokenCandidates = ["YOUSPEED_RELEASE_READ_TOKEN", "YouSpeedGitHubReleaseToken", "GITHUB_RELEASE_TOKEN"]
        let token = tokenCandidates
            .compactMap { info[$0] as? String }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && !$0.contains("$(") } ?? ""
        guard !token.isEmpty else {
            throw XCTSkip("Missing embedded GitHub release token in app Info.plist")
        }
        let manifestCandidates = ["YouSpeedV3ManifestURL", "YouSpeedBundleManifestURL"]
        let manifestRaw = manifestCandidates
            .compactMap { info[$0] as? String }
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty && !$0.contains("$(") }
        guard let manifestRaw,
              let manifestURL = URL(string: manifestRaw),
              let scheme = manifestURL.scheme?.lowercased(),
              scheme == "http" || scheme == "https" else {
            throw XCTSkip("Missing manifest URL in app Info.plist")
        }

        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 120
        config.timeoutIntervalForResource = 300
        let session = URLSession(configuration: config)

        let manifestFetchURL = try await resolveReleaseAssetAPIURL(
            fromGitHubReleaseURL: manifestURL,
            token: token,
            session: session
        ) ?? manifestURL

        var manifestRequest = URLRequest(url: manifestFetchURL)
        manifestRequest.setValue("YouSpeedConsumerTests/1.0", forHTTPHeaderField: "User-Agent")
        manifestRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        manifestRequest.setValue("application/octet-stream", forHTTPHeaderField: "Accept")

        let (manifestData, manifestResponse) = try await session.data(for: manifestRequest)
        guard let manifestHTTP = manifestResponse as? HTTPURLResponse else {
            XCTFail("Non-HTTP response for manifest: \(manifestFetchURL.absoluteString)")
            return
        }
        print("RELEASE_MANIFEST_CHECK status=\(manifestHTTP.statusCode) url=\(manifestFetchURL.absoluteString)")
        XCTAssertTrue((200...299).contains(manifestHTTP.statusCode), "Manifest status=\(manifestHTTP.statusCode) url=\(manifestFetchURL.absoluteString)")

        let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: manifestData)
        var artifacts: [BundleArtifact] = []
        if let parts = manifest.dbParts, !parts.isEmpty {
            artifacts.append(contentsOf: parts)
        } else {
            artifacts.append(manifest.db)
        }
        if let deltaIndex = manifest.deltaIndex {
            artifacts.append(deltaIndex)
        }

        XCTAssertFalse(artifacts.isEmpty, "No downloadable artifacts found in manifest")

        for artifact in artifacts {
            let resolvedURL = URL(string: artifact.file, relativeTo: manifestURL)?.absoluteURL
                ?? URL(string: artifact.file)
                ?? URL(string: artifact.url ?? "")
            guard let rawURL = resolvedURL else {
                XCTFail("Unable to resolve URL for artifact file=\(artifact.file) url=\(artifact.url ?? "<nil>")")
                continue
            }

            let candidateURL: URL
            if rawURL.host?.lowercased().contains("github.com") == true {
                if let apiURL = try await resolveReleaseAssetAPIURL(
                    fromGitHubReleaseURL: rawURL,
                    token: token,
                    session: session
                ) {
                    candidateURL = apiURL
                } else {
                    candidateURL = rawURL
                    print("RELEASE_ARTIFACT_CHECK fallback=direct file=\(artifact.file) url=\(rawURL.absoluteString)")
                }
            } else {
                candidateURL = rawURL
            }

            var req = URLRequest(url: candidateURL)
            req.setValue("YouSpeedConsumerTests/1.0", forHTTPHeaderField: "User-Agent")
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            req.setValue("application/octet-stream", forHTTPHeaderField: "Accept")
            req.setValue("bytes=0-0", forHTTPHeaderField: "Range")

            let (_, response) = try await session.data(for: req)
            guard let http = response as? HTTPURLResponse else {
                XCTFail("Non-HTTP response for artifact=\(artifact.file) url=\(candidateURL.absoluteString)")
                continue
            }

            print("RELEASE_ARTIFACT_CHECK file=\(artifact.file) status=\(http.statusCode) url=\(candidateURL.absoluteString)")
            XCTAssertTrue(
                http.statusCode == 200 || http.statusCode == 206,
                "Artifact unreachable file=\(artifact.file) status=\(http.statusCode) url=\(candidateURL.absoluteString)"
            )
        }
#endif
    }

    private func resolveReleaseAssetAPIURL(fromGitHubReleaseURL url: URL, token: String, session: URLSession) async throws -> URL? {
        guard let host = url.host?.lowercased(),
              host == "github.com" || host == "www.github.com" else {
            return url
        }
        let parts = url.path.split(separator: "/", omittingEmptySubsequences: true)
        guard parts.count >= 6,
              parts[2] == "releases",
              parts[3] == "download" else {
            return url
        }

        let owner = String(parts[0])
        let repo = String(parts[1])
        let tag = String(parts[4])
        let assetName = parts[5...].joined(separator: "/")
        guard !owner.isEmpty, !repo.isEmpty, !tag.isEmpty, !assetName.isEmpty else {
            return nil
        }

        guard let tagAPIURL = URL(string: "https://api.github.com/repos/\(owner)/\(repo)/releases/tags/\(tag)") else {
            return nil
        }
        var req = URLRequest(url: tagAPIURL)
        req.setValue("YouSpeedConsumerTests/1.0", forHTTPHeaderField: "User-Agent")
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            return nil
        }

        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let assets = json?["assets"] as? [[String: Any]] ?? []
        let assetID = assets.first(where: { ($0["name"] as? String) == assetName })?["id"] as? Int
        guard let assetID else {
            return nil
        }
        return URL(string: "https://api.github.com/repos/\(owner)/\(repo)/releases/assets/\(assetID)")
    }

    private func loadReplayExpectations(url: URL) throws -> [ReplayExpectation] {
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode([ReplayExpectation].self, from: data)
    }

    private func parseGPXTrack(url: URL) throws -> [TrackPoint] {
        let data = try Data(contentsOf: url)
        let delegate = GPXTrackParserDelegate()
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse() else {
            let message = parser.parserError?.localizedDescription ?? "unknown GPX parser error"
            throw NSError(domain: "SpeedConsumerTests", code: 10, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return delegate.points
    }

    private func parseKMLTrack(url: URL) throws -> [TrackPoint] {
        let data = try Data(contentsOf: url)
        let delegate = KMLTrackParserDelegate()
        let parser = XMLParser(data: data)
        parser.delegate = delegate
        guard parser.parse() else {
            let message = parser.parserError?.localizedDescription ?? "unknown KML parser error"
            throw NSError(domain: "SpeedConsumerTests", code: 11, userInfo: [NSLocalizedDescriptionKey: message])
        }
        return delegate.points
    }

    private func runReplayAssertion(track: [TrackPoint], expected: [ReplayExpectation], radiusM: Double) throws {
        XCTAssertEqual(track.count, expected.count, "Track and expected output count mismatch")

        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-replay-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let service = V3SpeedLimitService(dbPath: sourceDB.path)

        for index in track.indices {
            let point = track[index]
            let expectedPoint = expected[index]
            let result = try service.lookupSpeedLimit(
                lat: point.lat,
                lon: point.lon,
                radiusM: radiusM,
                maxCandidates: 64
            )
            XCTAssertEqual(
                result.speedLimitKmh,
                expectedPoint.expectedSpeedKmh,
                "Unexpected speed limit for track index \(index) lat=\(point.lat) lon=\(point.lon)"
            )
            XCTAssertEqual(
                result.wayID,
                expectedPoint.expectedWayID,
                "Unexpected way ID for track index \(index) lat=\(point.lat) lon=\(point.lon)"
            )
        }
    }
}

private struct TrackPoint {
    let lat: Double
    let lon: Double
}

private struct ReplayExpectation: Codable {
    let expectedWayID: String?
    let expectedSpeedKmh: Int?

    enum CodingKeys: String, CodingKey {
        case expectedWayID = "expected_way_id"
        case expectedSpeedKmh = "expected_speed_kmh"
    }
}

private struct WayRow {
    let rowID: Int64
    let wayID: String
    let minLat: Double
    let minLon: Double
}

private final class MockURLProtocol: URLProtocol {
    static var responses: [String: (status: Int, body: Data)] = [:]
    static var requiredAuthorizationPrefixByURL: [String: String] = [:]

    override class func canInit(with request: URLRequest) -> Bool {
        guard let scheme = request.url?.scheme?.lowercased() else { return false }
        return scheme == "http" || scheme == "https"
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard
            let url = request.url,
            let response = Self.responses[url.absoluteString]
        else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable))
            return
        }

        if let expectedPrefix = Self.requiredAuthorizationPrefixByURL[url.absoluteString] {
            let actual = request.value(forHTTPHeaderField: "Authorization") ?? ""
            guard actual.hasPrefix(expectedPrefix) else {
                client?.urlProtocol(self, didFailWithError: URLError(.userAuthenticationRequired))
                return
            }
        }

        guard let http = HTTPURLResponse(
            url: url,
            statusCode: response.status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Length": "\(response.body.count)"]
        ) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }

        client?.urlProtocol(self, didReceive: http, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: response.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

private final class OneShotLocationDelegate: NSObject, CLLocationManagerDelegate {
    var onResult: ((Result<CLLocation, Error>) -> Void)?
    var onAuthorizationChange: ((CLAuthorizationStatus) -> Void)?

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        onAuthorizationChange?(manager.authorizationStatus)
    }

    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else {
            onResult?(.failure(NSError(domain: "SpeedConsumerTests", code: 3, userInfo: [NSLocalizedDescriptionKey: "Location update was empty"])))
            onResult = nil
            return
        }
        onResult?(.success(location))
        onResult = nil
    }

    func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        onResult?(.failure(error))
        onResult = nil
    }
}

private final class GPXTrackParserDelegate: NSObject, XMLParserDelegate {
    var points: [TrackPoint] = []

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        guard elementName == "trkpt",
              let latRaw = attributeDict["lat"], let lonRaw = attributeDict["lon"],
              let lat = Double(latRaw), let lon = Double(lonRaw) else {
            return
        }
        points.append(TrackPoint(lat: lat, lon: lon))
    }
}

private final class KMLTrackParserDelegate: NSObject, XMLParserDelegate {
    var points: [TrackPoint] = []
    private var inCoordinates = false
    private var coordinatesBuffer = ""

    func parser(
        _ parser: XMLParser,
        didStartElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?,
        attributes attributeDict: [String: String] = [:]
    ) {
        if elementName == "coordinates" {
            inCoordinates = true
            coordinatesBuffer = ""
        }
    }

    func parser(_ parser: XMLParser, foundCharacters string: String) {
        guard inCoordinates else {
            return
        }
        coordinatesBuffer.append(string)
    }

    func parser(
        _ parser: XMLParser,
        didEndElement elementName: String,
        namespaceURI: String?,
        qualifiedName qName: String?
    ) {
        guard elementName == "coordinates", inCoordinates else {
            return
        }
        inCoordinates = false

        let tuples = coordinatesBuffer.split(whereSeparator: \.isWhitespace)
        for tuple in tuples {
            let components = tuple.split(separator: ",", omittingEmptySubsequences: true)
            guard components.count >= 2,
                  let lon = Double(components[0]),
                  let lat = Double(components[1]) else {
                continue
            }
            points.append(TrackPoint(lat: lat, lon: lon))
        }
    }
}
