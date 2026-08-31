import XCTest
@testable import SpeedConsumer
import CryptoKit
import SQLite3
import CoreLocation
import zlib
#if canImport(UIKit)
import UIKit
#endif

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

final class SpeedConsumerTests: XCTestCase {
    func testParseExplicitSpeed() {
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed("30"), 30)
        XCTAssertEqual(V3SpeedLimitService.parseExplicitSpeed("80 km/h"), 80)
        XCTAssertNil(V3SpeedLimitService.parseExplicitSpeed("signals"))
    }

    func testDeriveSpeedLimitFallbacks() {
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: "DE:urban", sourceMaxspeed: nil, highway: nil), 50)
        XCTAssertEqual(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: nil, sourceMaxspeed: "DE:rural", highway: nil), 100)
        XCTAssertNil(V3SpeedLimitService.deriveSpeedLimitKmh(maxspeed: nil, maxspeedType: nil, sourceMaxspeed: nil, highway: "motorway"))
    }

    func testGermanLowSpeedLimitImpliesInsideCity() {
        XCTAssertTrue(V3SpeedLimitService.germanLowSpeedLimitImpliesInsideCity(countryCode: "DEU", speedKmh: 30))
        XCTAssertFalse(V3SpeedLimitService.germanLowSpeedLimitImpliesInsideCity(countryCode: "DEU", speedKmh: 50))
        XCTAssertFalse(V3SpeedLimitService.germanLowSpeedLimitImpliesInsideCity(countryCode: "NLD", speedKmh: 30))
    }

    func testDeriveSpeedLimitDoesNotInventMandatoryMotorwayLimitFromInheritedTags() {
        XCTAssertNil(
            V3SpeedLimitService.deriveSpeedLimitKmh(
                maxspeed: nil,
                maxspeedType: "DE:motorway",
                sourceMaxspeed: nil,
                highway: "motorway"
            )
        )
    }

    func testExplicitUnlimitedTagSuppressesMotorwayFallback() {
        XCTAssertTrue(V3SpeedLimitService.isUnlimitedSpeedTag(" none "))
        XCTAssertNil(
            V3SpeedLimitService.deriveSpeedLimitKmh(
                maxspeed: "none",
                maxspeedType: nil,
                sourceMaxspeed: nil,
                highway: "motorway"
            )
        )
    }

    func testFilteredDisplaySpeedUsesDerivedBelowLowSpeedThreshold() {
        XCTAssertEqual(
            DriveSessionViewModel.filteredDisplaySpeedKmh(
                rawSpeedKmh: 3.8,
                fallbackDerivedSpeedKmh: 1.8,
                speedAccuracyKmh: nil,
                previousDisplaySpeedKmh: 7.2
            ),
            1.8,
            accuracy: 0.0001
        )
        XCTAssertEqual(
            DriveSessionViewModel.filteredDisplaySpeedKmh(
                rawSpeedKmh: 5.4,
                fallbackDerivedSpeedKmh: 0,
                speedAccuracyKmh: 2.0,
                previousDisplaySpeedKmh: 0
            ),
            0,
            accuracy: 0.0001
        )
    }

    func testFilteredDisplaySpeedUsesRawGpsAtOrAboveThreshold() {
        XCTAssertEqual(
            DriveSessionViewModel.filteredDisplaySpeedKmh(
                rawSpeedKmh: 7.0,
                fallbackDerivedSpeedKmh: 2.8,
                speedAccuracyKmh: nil,
                previousDisplaySpeedKmh: 0
            ),
            7.0,
            accuracy: 0.0001
        )
        XCTAssertEqual(
            DriveSessionViewModel.filteredDisplaySpeedKmh(
                rawSpeedKmh: 12.4,
                fallbackDerivedSpeedKmh: 4.2,
                speedAccuracyKmh: nil,
                previousDisplaySpeedKmh: 0
            ),
            12.4,
            accuracy: 0.0001
        )
    }

    func testFilteredDisplaySpeedStillClampsNonPositiveValues() {
        XCTAssertEqual(
            DriveSessionViewModel.filteredDisplaySpeedKmh(
                rawSpeedKmh: 0,
                fallbackDerivedSpeedKmh: 0,
                speedAccuracyKmh: nil,
                previousDisplaySpeedKmh: 0
            ),
            0
        )
        XCTAssertEqual(
            DriveSessionViewModel.filteredDisplaySpeedKmh(
                rawSpeedKmh: -1,
                fallbackDerivedSpeedKmh: -2,
                speedAccuracyKmh: nil,
                previousDisplaySpeedKmh: 0
            ),
            0,
            accuracy: 0.0001
        )
    }

    func testDerivedSpeedUsesDistanceAndElapsedTime() {
        XCTAssertEqual(
            DriveSessionViewModel.derivedSpeedKmh(distanceM: 50, elapsedSeconds: 5),
            36,
            accuracy: 0.0001
        )
    }

    func testDerivedSpeedSubtractsAccuracyAllowance() {
        XCTAssertEqual(
            DriveSessionViewModel.derivedSpeedKmh(distanceM: 12, elapsedSeconds: 3, accuracyAllowanceM: 5),
            8.4,
            accuracy: 0.0001
        )
        XCTAssertEqual(
            DriveSessionViewModel.derivedSpeedKmh(distanceM: 4, elapsedSeconds: 3, accuracyAllowanceM: 5),
            0,
            accuracy: 0.0001
        )
    }

    func testTunnelModeTrackerFollowsTunnelSegmentTag() {
        var tracker = TunnelModeTracker()
        XCTAssertEqual(tracker.state, .inactive)

        tracker.consumeFix(isTunnelSegment: true)
        XCTAssertEqual(tracker.state, .active)
        XCTAssertTrue(tracker.isTunnelModeActive)

        tracker.consumeFix(isTunnelSegment: false)
        XCTAssertEqual(tracker.state, .inactive)
        XCTAssertFalse(tracker.isTunnelModeActive)
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

    func testLoadBundledFranceAndSwitzerlandRules() throws {
        let bundle = Bundle(for: SpeedConsumerAppDelegate.self)
        let france = try SpeedPenaltyRuleSet.loadBundled(named: "FRA-rules", bundle: bundle)
        let switzerland = try SpeedPenaltyRuleSet.loadBundled(named: "CHE-rules", bundle: bundle)

        XCTAssertEqual(france.countryCode, "FRA")
        XCTAssertEqual(france.currencyCode, "EUR")
        XCTAssertGreaterThanOrEqual(france.bands.count, 6)

        let franceUrbanLow = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 4,
            rules: france,
            insideCity: true
        )
        let franceRuralLow = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 4,
            rules: france,
            insideCity: false
        )
        let franceOffence = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 55,
            rules: france,
            insideCity: true
        )

        XCTAssertEqual(franceUrbanLow?.moneyFineEUR, 135)
        XCTAssertEqual(franceUrbanLow?.penaltyPoints, 0)
        XCTAssertEqual(franceRuralLow?.moneyFineEUR, 68)
        XCTAssertEqual(franceOffence?.penaltyPoints, 6)
        XCTAssertEqual(franceOffence?.moneyFineEUR, 300)
        XCTAssertEqual(franceOffence?.conditionalDrivingBanMonths, 36)

        XCTAssertEqual(switzerland.countryCode, "CHE")
        XCTAssertEqual(switzerland.currencyCode, "CHF")
        XCTAssertGreaterThanOrEqual(switzerland.bands.count, 10)

        let swissUrbanFine = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 8,
            rules: switzerland,
            insideCity: true
        )
        let swissRuralFine = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 8,
            rules: switzerland,
            insideCity: false
        )
        let swissUrbanWithdrawal = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 22,
            rules: switzerland,
            insideCity: true
        )
        let swissRuralWithdrawal = SpeedPenaltyRuleEngine.resolveNotice(
            overspeedKmh: 27,
            rules: switzerland,
            insideCity: false
        )

        XCTAssertEqual(swissUrbanFine?.moneyFineEUR, 120)
        XCTAssertEqual(swissRuralFine?.moneyFineEUR, 100)
        XCTAssertEqual(swissUrbanWithdrawal?.drivingBanMonths, 1)
        XCTAssertEqual(swissRuralWithdrawal?.drivingBanMonths, 1)
    }

    func testLoadBundledTopCountryBundleTargetsConfig() throws {
        let config = try V3BundleTargetsConfig.loadBundled(bundle: Bundle(for: SpeedConsumerAppDelegate.self))
        XCTAssertEqual(config.format, "youspeed.v3.bundle.targets")
        XCTAssertEqual(config.schemaVersion, 1)
        XCTAssertEqual(config.variant, "v3")
        XCTAssertGreaterThanOrEqual(config.countries.count, 11)

        let germany = try XCTUnwrap(config.country(countryID: "germany"))
        XCTAssertEqual(germany.countryCode, "DEU")
        XCTAssertEqual(germany.mode, "regional_shards")
        XCTAssertTrue(germany.regions.contains(where: { $0.regionID == "bayern" }))
        XCTAssertTrue(germany.regions.contains(where: { $0.regionID == "berlin" }))

        let netherlands = try XCTUnwrap(config.country(countryID: "netherlands"))
        XCTAssertEqual(netherlands.countryCode, "NLD")
        XCTAssertEqual(netherlands.mode, "single_country")

        let france = try XCTUnwrap(config.country(countryID: "france"))
        XCTAssertEqual(france.countryCode, "FRA")
        XCTAssertEqual(france.mode, "regional_shards")
        XCTAssertEqual(france.regions.count, 26)
        XCTAssertTrue(france.regions.contains(where: { $0.regionID == "ile-de-france" }))
        XCTAssertTrue(france.regions.contains(where: { $0.regionID == "rhone-alpes" }))

        let switzerland = try XCTUnwrap(config.country(countryID: "switzerland"))
        XCTAssertEqual(switzerland.countryCode, "CHE")
        XCTAssertEqual(switzerland.mode, "single_country")

        XCTAssertNil(config.country(countryID: "united-kingdom"))
    }

    func testBundleTargetConfigBuildsTop10ManifestEndpoints() throws {
        let config = try V3BundleTargetsConfig.loadBundled(bundle: Bundle(for: SpeedConsumerAppDelegate.self))
        let endpoints = config.manifestEndpoints(preferredCountryCode: "DEU")

        XCTAssertGreaterThanOrEqual(endpoints.count, 20)
        XCTAssertEqual(endpoints.first?.countryCode, "DEU")

        let germanyBayernURL = URL(
            string: "https://github.com/volzinnovation/youspeed.de/releases/download/bayern/bayern_manifest.json"
        )!
        XCTAssertTrue(endpoints.contains(where: { $0.manifestURL == germanyBayernURL }))
        let germanyBadenWuerttembergURL = URL(
            string: "https://github.com/volzinnovation/youspeed.de/releases/download/baden-wuerttemberg/baden-wuerttemberg_manifest.json"
        )!
        XCTAssertTrue(endpoints.contains(where: { $0.manifestURL == germanyBadenWuerttembergURL }))
        let invalidGermanyCountryFallbackURL = URL(
            string: "https://github.com/volzinnovation/youspeed.de/releases/download/germany/germany_manifest.json"
        )!
        XCTAssertFalse(endpoints.contains(where: { $0.manifestURL == invalidGermanyCountryFallbackURL }))

        let netherlandsManifestURL = URL(
            string: "https://github.com/volzinnovation/youspeed.de/releases/download/netherlands/netherlands_manifest.json"
        )!
        XCTAssertTrue(endpoints.contains(where: { $0.manifestURL == netherlandsManifestURL }))

        let netherlandsEndpoints = endpoints.filter { $0.countryCode.uppercased() == "NLD" }
        XCTAssertEqual(netherlandsEndpoints.count, 1)
        XCTAssertEqual(netherlandsEndpoints.first?.regionID, "netherlands")

        let franceEndpoints = endpoints.filter { $0.countryCode.uppercased() == "FRA" }
        XCTAssertEqual(franceEndpoints.count, 26)
        XCTAssertTrue(franceEndpoints.contains(where: { $0.regionID == "france/ile-de-france" }))
        XCTAssertTrue(
            franceEndpoints.contains {
                $0.manifestURL == URL(
                    string: "https://github.com/volzinnovation/youspeed.de/releases/download/ile-de-france/ile-de-france_manifest.json"
                )!
            }
        )

        let swissManifestURL = URL(
            string: "https://github.com/volzinnovation/youspeed.de/releases/download/switzerland/switzerland_manifest.json"
        )!
        XCTAssertTrue(endpoints.contains(where: { $0.manifestURL == swissManifestURL }))

        let germanyEndpoints = endpoints.filter { $0.countryCode.uppercased() == "DEU" }
        XCTAssertGreaterThan(germanyEndpoints.count, 1)
        XCTAssertTrue(germanyEndpoints.contains(where: { $0.regionID == "germany/bayern" }))
    }

    func testLegalTextIsBundledIntoAppResources() throws {
        let bundle = Bundle(for: SpeedConsumerAppDelegate.self)
        let url = try XCTUnwrap(
            bundle.url(forResource: "legal", withExtension: "txt"),
            "Bundled legal.txt not found in app resources"
        )
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertTrue(text.contains("OpenStreetMap"), "Expected bundled legal text contents")
        XCTAssertTrue(text.contains("commons.wikimedia.org/wiki/File:Zeichen_242.1"), "Expected Commons attribution in legal text")
    }

    func testPedestrianZoneSignAssetIsBundled() throws {
        #if canImport(UIKit)
        let bundle = Bundle(for: SpeedConsumerAppDelegate.self)
        XCTAssertNotNil(
            UIImage(named: "PedestrianZoneSign", in: bundle, compatibleWith: nil),
            "Expected bundled pedestrian-zone sign asset"
        )
        #endif
    }

    func testPedestrianScreenshotFixtureUsesWalkingPacePresentation() {
        let fixture = AppScreenshotState.pedestrianZone.fixture
        XCTAssertEqual(fixture.currentSpeedKmh, 5)
        XCTAssertNil(fixture.speedLimitKmh)
        XCTAssertEqual(fixture.speedLimitDisplayText, "Schritt")
        XCTAssertEqual(fixture.streetName, "Im Kloster")
        XCTAssertEqual(fixture.cityName, "Bad Herrenalb")
    }

    func testMatcherStartupProfileMigratesLegacyDefaultToM2() {
        XCTAssertEqual(MatcherDebugProfile.resolveInitialProfile(storedRawValue: "m1", forcedVersion: 0), .m2)
        XCTAssertEqual(MatcherDebugProfile.resolveInitialProfile(storedRawValue: nil, forcedVersion: 0), .m2)
    }

    func testMatcherStartupProfilePreservesExplicitProfileAfterMigration() {
        XCTAssertEqual(
            MatcherDebugProfile.resolveInitialProfile(
                storedRawValue: MatcherDebugProfile.m4.rawValue,
                forcedVersion: MatcherDebugProfile.forcedProfileVersion
            ),
            .m4
        )
    }

    func testMatcherProfilesFollowPaperLadder() {
        XCTAssertEqual(MatcherDebugProfile.m1.debugLabel, "M1 Connected baseline")
        XCTAssertEqual(MatcherDebugProfile.m2.debugLabel, "M2 Nearest + street-ref continuity")
        XCTAssertEqual(MatcherDebugProfile.m3.debugLabel, "M3 M2 + connected-candidate gate")
        XCTAssertEqual(MatcherDebugProfile.m4.matchingModel, .corridorHMMRawMiniHMM)
        XCTAssertEqual(MatcherDebugProfile.m5.matchingModel, .corridorHMM)
        XCTAssertEqual(MatcherDebugProfile.m6.debugLabel, "M6 M2 + urban consecutive distance-gap release")
        XCTAssertEqual(MatcherDebugProfile.m6.matchingModel, .simpleSpeedRefUrbanReleaseHeuristic)
        XCTAssertEqual(MatcherDebugProfile.m7.debugLabel, "M7 M6 + 10m search window")
        XCTAssertEqual(MatcherDebugProfile.m7.matchingModel, .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic)
        XCTAssertEqual(MatcherDebugProfile.m8.debugLabel, "M8 M6 + no-ref street-name continuity")
        XCTAssertEqual(MatcherDebugProfile.m8.matchingModel, .simpleSpeedRefStreetNameFallbackHeuristic)
        XCTAssertEqual(MatcherDebugProfile.m9.debugLabel, "M9 M8 + guarded stale-ref suppression")
        XCTAssertEqual(MatcherDebugProfile.m9.matchingModel, .simpleSpeedRefStreetNameGuardHeuristic)
        XCTAssertEqual(MatcherDebugProfile.m10.debugLabel, "M10 M9 + node-direction-aware junction release")
        XCTAssertEqual(MatcherDebugProfile.m10.matchingModel, .simpleSpeedRefStreetNameGuardNodeAwareHeuristic)
        XCTAssertEqual(MatcherDebugProfile.m11.debugLabel, "M11 M10 + topology-only particle sequence")
        XCTAssertEqual(MatcherDebugProfile.m11.matchingModel, .simpleSequenceParticleHeuristic)
        XCTAssertEqual(MatcherDebugProfile.m12.debugLabel, "M12 M11 + 10-fix HMM/Viterbi")
        XCTAssertEqual(MatcherDebugProfile.m12.matchingModel, .simpleSequenceViterbiHeuristic)
    }

    func testAllConfiguredBundlesSyncAndDeleteViaMockTransport() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-all-bundles-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)
        let sourceSHA = sha256Hex(sourceData)

        let config = try V3BundleTargetsConfig.loadBundled(bundle: Bundle(for: SpeedConsumerAppDelegate.self))
        let endpoints = config.manifestEndpoints(preferredCountryCode: "DEU")
        XCTAssertFalse(endpoints.isEmpty)

        var responses: [String: (status: Int, body: Data)] = [:]
        let encoder = JSONEncoder()
        for (index, endpoint) in endpoints.enumerated() {
            let dbFile = "\(endpoint.manifestRegion)-\(index).sqlite"
            let dbURL = URL(string: "https://speedconsumer.test/\(dbFile)")!
            let manifest = V3BundleManifest(
                format: "youspeed.v3.bundle.manifest",
                schemaVersion: 1,
                variant: "v3",
                region: endpoint.manifestRegion,
                countryCode: endpoint.countryCode,
                bundleVersion: "2026-03-03-\(String(format: "%03d", index))",
                createdAtUTC: "2026-03-03T00:00:00Z",
                minAppVersion: "1.0.0",
                db: BundleArtifact(
                    file: dbFile,
                    bytes: Int64(sourceData.count),
                    sha256: sourceSHA,
                    url: dbURL.absoluteString
                ),
                dbParts: nil,
                deltaIndex: nil
            )
            responses[endpoint.manifestURL.absoluteString] = (status: 200, body: try encoder.encode(manifest))
            responses[dbURL.absoluteString] = (status: 200, body: sourceData)
        }

        MockURLProtocol.responses = responses
        defer {
            MockURLProtocol.responses = [:]
        }

        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: sessionConfig)
        let manager = V3BundleManager(fileManager: fm, session: session)

        for endpoint in endpoints {
            let result = try await manager.syncFromManifestURL(endpoint.manifestURL)
            XCTAssertEqual(result.mode, .fullDownload, "Expected full download for \(endpoint.manifestRegion)")

            let removed = try await manager.removeDownloadedBundles(forManifestRegion: endpoint.manifestRegion)
            XCTAssertEqual(removed, 1, "Expected exactly one removed bundle for \(endpoint.manifestRegion)")
        }

        let remaining = try await manager.listDownloadedBundles()
        XCTAssertTrue(remaining.isEmpty, "Expected no remaining bundles after delete cycle")
    }

    func testDownloadAdjacentBundlesAndCrossOverByB10Way17721265() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-adjacent-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let bwSourceDB = tempDir.appendingPathComponent("bw_fixture.sqlite")
        let rpSourceDB = tempDir.appendingPathComponent("rp_fixture.sqlite")
        try createAdjacentBundleFixtureDB(at: bwSourceDB, fixture: .badenWuerttemberg)
        try createAdjacentBundleFixtureDB(at: rpSourceDB, fixture: .rheinlandPfalz)

        let bwData = try Data(contentsOf: bwSourceDB)
        let rpData = try Data(contentsOf: rpSourceDB)

        let bwManifestURL = URL(string: "https://speedconsumer.test/baden-wuerttemberg_manifest.json")!
        let rpManifestURL = URL(string: "https://speedconsumer.test/rheinland-pfalz_manifest.json")!
        let bwDBURL = URL(string: "https://speedconsumer.test/DEU-bw-latest.speeds_v3.sqlite")!
        let rpDBURL = URL(string: "https://speedconsumer.test/DEU-rp-latest.speeds_v3.sqlite")!

        let bwManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "baden-wuerttemberg",
            countryCode: "DEU",
            bundleVersion: "2026-03-04-bw",
            createdAtUTC: "2026-03-04T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-bw-latest.speeds_v3.sqlite",
                bytes: Int64(bwData.count),
                sha256: sha256Hex(bwData),
                url: bwDBURL.absoluteString
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: BundleCoverageBBox(minLon: 8.40, minLat: 49.00, maxLon: 8.50, maxLat: 49.20),
                poly: nil
            )
        )
        let rpManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "rheinland-pfalz",
            countryCode: "DEU",
            bundleVersion: "2026-03-04-rp",
            createdAtUTC: "2026-03-04T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-rp-latest.speeds_v3.sqlite",
                bytes: Int64(rpData.count),
                sha256: sha256Hex(rpData),
                url: rpDBURL.absoluteString
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: BundleCoverageBBox(minLon: 8.50, minLat: 49.00, maxLon: 8.62, maxLat: 49.20),
                poly: nil
            )
        )

        MockURLProtocol.responses = [
            bwManifestURL.absoluteString: (status: 200, body: try JSONEncoder().encode(bwManifest)),
            rpManifestURL.absoluteString: (status: 200, body: try JSONEncoder().encode(rpManifest)),
            bwDBURL.absoluteString: (status: 200, body: bwData),
            rpDBURL.absoluteString: (status: 200, body: rpData),
        ]
        defer {
            MockURLProtocol.responses = [:]
        }

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let manager = V3BundleManager(fileManager: fm, session: session)

        _ = try await manager.syncFromManifestURL(bwManifestURL)
        _ = try await manager.syncFromManifestURL(rpManifestURL)

        let fallbackDBPath = try await manager.activeDatabaseURL()?.path

        func lookupAt(lat: Double, lon: Double) async throws -> (LocalBundleRoute, SpeedLimitResult) {
            guard let route = try await manager.resolveLocalBundleRoute(lat: lat, lon: lon, fallbackDBPath: fallbackDBPath) else {
                XCTFail("Expected route for lat=\(lat), lon=\(lon)")
                throw NSError(domain: "SpeedConsumerTests", code: 3001)
            }
            let service = V3SpeedLimitService(dbPath: route.dbPath)
            let result = try service.lookupSpeedLimit(lat: lat, lon: lon, radiusM: 120.0, maxCandidates: 128)
            return (route, result)
        }

        let bwLocal = try await lookupAt(lat: 49.060, lon: 8.440)
        XCTAssertEqual(bwLocal.0.region, "baden-wuerttemberg")
        XCTAssertEqual(bwLocal.1.wayID, "17721266")
        XCTAssertEqual(bwLocal.1.speedLimitKmh, 70)

        let bwB10 = try await lookupAt(lat: 49.120, lon: 8.492)
        XCTAssertEqual(bwB10.0.region, "baden-wuerttemberg")
        XCTAssertEqual(bwB10.1.wayID, "17721265")
        XCTAssertEqual(bwB10.1.speedLimitKmh, 30)
        XCTAssertTrue((bwB10.1.streetName ?? "").contains("B10"))

        let rpB10 = try await lookupAt(lat: 49.120, lon: 8.508)
        XCTAssertEqual(rpB10.0.region, "rheinland-pfalz")
        XCTAssertEqual(rpB10.1.wayID, "27721265")
        XCTAssertEqual(rpB10.1.speedLimitKmh, 50)
        XCTAssertTrue((rpB10.1.streetName ?? "").contains("B10"))

        let rpLocal = try await lookupAt(lat: 49.070, lon: 8.570)
        XCTAssertEqual(rpLocal.0.region, "rheinland-pfalz")
        XCTAssertEqual(rpLocal.1.wayID, "27721266")
        XCTAssertEqual(rpLocal.1.speedLimitKmh, 80)

        let bwCrossBack = try await lookupAt(lat: 49.120, lon: 8.495)
        XCTAssertEqual(bwCrossBack.0.region, "baden-wuerttemberg")
        XCTAssertEqual(bwCrossBack.1.wayID, "17721265")
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

        let repeatBandInner = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 28, rules: rules, insideCity: true)
        let repeatBandOuter = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 28, rules: rules, insideCity: false)
        XCTAssertEqual(repeatBandInner?.drivingBanMonths, 0)
        XCTAssertEqual(repeatBandOuter?.drivingBanMonths, 0)
        XCTAssertNil(repeatBandInner?.conditionalDrivingBanMonths)
        XCTAssertNil(repeatBandOuter?.conditionalDrivingBanMonths)

        let innerHigh = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 31, rules: rules, insideCity: true)
        let outerHigh = SpeedPenaltyRuleEngine.resolveNotice(overspeedKmh: 31, rules: rules, insideCity: false)
        XCTAssertEqual(innerHigh?.penaltyPoints, 2)
        XCTAssertEqual(outerHigh?.penaltyPoints, 1)
        XCTAssertEqual(innerHigh?.drivingBanMonths, 1)
        XCTAssertEqual(outerHigh?.drivingBanMonths, 1)
        XCTAssertNil(outerHigh?.conditionalDrivingBanMonths)

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
          "country_code": "DEU",
          "bundle_version": "2026-02-24",
          "created_at_utc": "2026-02-24T00:00:00Z",
          "min_app_version": "1.0.0",
          "db": {
            "file": "DEU-latest.speeds_v3.sqlite",
            "bytes": 123,
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "url": "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.speeds_v3.sqlite"
          },
          "penalty_rules": {
            "file": "DEU-rules.json",
            "bytes": 1234,
            "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
            "url": "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-rules.json"
          },
          "delta_index": null
        }
        """
        let data = Data(raw.utf8)
        let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: data)
        XCTAssertEqual(manifest.variant, "v3")
        XCTAssertEqual(manifest.bundleVersion, "2026-02-24")
        XCTAssertEqual(manifest.countryCode, "DEU")
        XCTAssertEqual(manifest.db.file, "DEU-latest.speeds_v3.sqlite")
        XCTAssertEqual(manifest.penaltyRules?.file, "DEU-rules.json")
    }

    func testDecodeBundleManifestCoverage() throws {
        let raw = """
        {
          "format": "youspeed.v3.bundle.manifest",
          "schema_version": 1,
          "variant": "v3",
          "region": "germany-baden-wuerttemberg",
          "bundle_version": "2026-03-02",
          "created_at_utc": "2026-03-02T00:00:00Z",
          "min_app_version": "1.0.0",
          "db": {
            "file": "DEU-latest.speeds_v3.sqlite",
            "bytes": 123,
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "url": null
          },
          "coverage": {
            "bbox": {
              "min_lon": 8.0,
              "min_lat": 47.0,
              "max_lon": 10.0,
              "max_lat": 49.0
            },
            "poly": {
              "file": "germany-baden-wuerttemberg.poly",
              "bytes": 512,
              "sha256": "abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd",
              "url": null
            }
          }
        }
        """
        let data = Data(raw.utf8)
        let manifest = try JSONDecoder().decode(V3BundleManifest.self, from: data)
        XCTAssertEqual(manifest.region, "germany-baden-wuerttemberg")
        XCTAssertEqual(manifest.coverage?.bbox.minLon, 8.0)
        XCTAssertEqual(manifest.coverage?.bbox.maxLat, 49.0)
        XCTAssertEqual(manifest.coverage?.poly?.file, "germany-baden-wuerttemberg.poly")
    }

    func testResolveLocalBundleRouteUsesCoveragePolygons() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundlesRoot = supportDir.appendingPathComponent("bundles", isDirectory: true)
        let bwDir = bundlesRoot.appendingPathComponent("deu-bw-2026-03-02", isDirectory: true)
        let byDir = bundlesRoot.appendingPathComponent("deu-by-2026-03-02", isDirectory: true)
        try fm.createDirectory(at: bwDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: byDir, withIntermediateDirectories: true)

        let bwDB = bwDir.appendingPathComponent("DEU-latest.speeds_v3.sqlite")
        let byDB = byDir.appendingPathComponent("DEU-latest.speeds_v3.sqlite")
        try createFixtureV3DB(at: bwDB)
        try createFixtureV3DB(at: byDB)

        let bwPoly = bwDir.appendingPathComponent("deu-bw.poly")
        let byPoly = byDir.appendingPathComponent("deu-by.poly")
        let bwPolyText = """
        deu-bw
        1
          8.0 48.0
          9.0 48.0
          9.0 49.0
          8.0 49.0
          8.0 48.0
        END
        END
        """
        let byPolyText = """
        deu-by
        1
          11.0 48.0
          12.0 48.0
          12.0 49.0
          11.0 49.0
          11.0 48.0
        END
        END
        """
        try Data(bwPolyText.utf8).write(to: bwPoly, options: .atomic)
        try Data(byPolyText.utf8).write(to: byPoly, options: .atomic)

        let bwCoverage = BundleCoverage(
            bbox: BundleCoverageBBox(minLon: 8.0, minLat: 48.0, maxLon: 9.0, maxLat: 49.0),
            poly: BundleArtifact(
                file: bwPoly.lastPathComponent,
                bytes: Int64((try Data(contentsOf: bwPoly)).count),
                sha256: sha256Hex(try Data(contentsOf: bwPoly)),
                url: nil
            )
        )
        let byCoverage = BundleCoverage(
            bbox: BundleCoverageBBox(minLon: 11.0, minLat: 48.0, maxLon: 12.0, maxLat: 49.0),
            poly: BundleArtifact(
                file: byPoly.lastPathComponent,
                bytes: Int64((try Data(contentsOf: byPoly)).count),
                sha256: sha256Hex(try Data(contentsOf: byPoly)),
                url: nil
            )
        )

        let bwManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "deu-bw",
            countryCode: "DEU",
            bundleVersion: "2026-03-02",
            createdAtUTC: "2026-03-02T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-latest.speeds_v3.sqlite",
                bytes: try fileSize(bwDB),
                sha256: sha256Hex(try Data(contentsOf: bwDB)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: bwCoverage
        )
        let byManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "deu-by",
            countryCode: "DEU",
            bundleVersion: "2026-03-02",
            createdAtUTC: "2026-03-02T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-latest.speeds_v3.sqlite",
                bytes: try fileSize(byDB),
                sha256: sha256Hex(try Data(contentsOf: byDB)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: byCoverage
        )

        try JSONEncoder().encode(bwManifest).write(
            to: bwDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )
        try JSONEncoder().encode(byManifest).write(
            to: byDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let bwRoute = try await manager.resolveLocalBundleRoute(lat: 48.5, lon: 8.5, fallbackDBPath: nil)
        XCTAssertEqual(bwRoute?.region, "deu-bw")
        XCTAssertEqual(bwRoute?.countryCode, "DEU")
        assertPathEqual(bwRoute?.dbPath, bwDB.path)

        let byRoute = try await manager.resolveLocalBundleRoute(lat: 48.5, lon: 11.5, fallbackDBPath: nil)
        XCTAssertEqual(byRoute?.region, "deu-by")
        XCTAssertEqual(byRoute?.countryCode, "DEU")
        assertPathEqual(byRoute?.dbPath, byDB.path)

        let fallbackRoute = try await manager.resolveLocalBundleRoute(lat: 47.0, lon: 7.0, fallbackDBPath: bwDB.path)
        assertPathEqual(fallbackRoute?.dbPath, bwDB.path)
    }

    func testResolveLocalBundleRouteUsesEmbeddedCoveragePolysWhenDownloadedPolyMissing() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundlesRoot = supportDir.appendingPathComponent("bundles", isDirectory: true)
        let bwDir = bundlesRoot.appendingPathComponent("z-bw", isDirectory: true)
        let rpDir = bundlesRoot.appendingPathComponent("a-rp", isDirectory: true)
        try fm.createDirectory(at: bwDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: rpDir, withIntermediateDirectories: true)

        let bwDB = bwDir.appendingPathComponent("baden-wuerttemberg.sqlite")
        let rpDB = rpDir.appendingPathComponent("rheinland-pfalz.sqlite")
        try createFixtureV3DB(at: bwDB)
        try createFixtureV3DB(at: rpDB)

        let sharedBBox = BundleCoverageBBox(minLon: 7.0, minLat: 47.0, maxLon: 10.5, maxLat: 50.0)
        let polyChecksum = String(repeating: "0", count: 64)
        let bwManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "z-bw",
            countryCode: "DEU",
            bundleVersion: "2026-03-17",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: bwDB.lastPathComponent,
                bytes: try fileSize(bwDB),
                sha256: sha256Hex(try Data(contentsOf: bwDB)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: sharedBBox,
                poly: BundleArtifact(
                    file: "baden-wuerttemberg.poly",
                    bytes: 1,
                    sha256: polyChecksum,
                    url: nil
                )
            )
        )
        let rpManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "a-rp",
            countryCode: "DEU",
            bundleVersion: "2026-03-17",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: rpDB.lastPathComponent,
                bytes: try fileSize(rpDB),
                sha256: sha256Hex(try Data(contentsOf: rpDB)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: sharedBBox,
                poly: BundleArtifact(
                    file: "rheinland-pfalz.poly",
                    bytes: 1,
                    sha256: polyChecksum,
                    url: nil
                )
            )
        )

        try JSONEncoder().encode(bwManifest).write(
            to: bwDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )
        try JSONEncoder().encode(rpManifest).write(
            to: rpDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )

        let manager = V3BundleManager(
            fileManager: fm,
            session: URLSession(configuration: .ephemeral),
            resourceBundle: Bundle(for: SpeedConsumerAppDelegate.self)
        )
        let route = try await manager.resolveLocalBundleRoute(
            lat: 48.80117,
            lon: 8.44278,
            fallbackDBPath: rpDB.path
        )
        XCTAssertEqual(route?.region, "z-bw")
        assertPathEqual(route?.dbPath, bwDB.path)
    }

    func testResolveLocalBundleRouteFallsBackToBBoxWhenCoveragePolyIsUnavailable() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundleDir = supportDir
            .appendingPathComponent("bundles", isDirectory: true)
            .appendingPathComponent("bbox-only", isDirectory: true)
        try fm.createDirectory(at: bundleDir, withIntermediateDirectories: true)

        let dbURL = bundleDir.appendingPathComponent("bbox-only.sqlite")
        try createFixtureV3DB(at: dbURL)
        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "bbox-only",
            countryCode: "DEU",
            bundleVersion: "2026-03-17",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: dbURL.lastPathComponent,
                bytes: try fileSize(dbURL),
                sha256: sha256Hex(try Data(contentsOf: dbURL)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: BundleCoverageBBox(minLon: 8.0, minLat: 48.0, maxLon: 9.0, maxLat: 49.0),
                poly: BundleArtifact(
                    file: "missing.poly",
                    bytes: 1,
                    sha256: String(repeating: "0", count: 64),
                    url: nil
                )
            )
        )
        try JSONEncoder().encode(manifest).write(
            to: bundleDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let route = try await manager.resolveLocalBundleRoute(lat: 48.5, lon: 8.5, fallbackDBPath: nil)
        XCTAssertEqual(route?.region, "bbox-only")
        assertPathEqual(route?.dbPath, dbURL.path)
    }

    func testResolveLocalBundleRoutePrefersMoreSpecificCoverageOverFallbackDB() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundlesRoot = supportDir.appendingPathComponent("bundles", isDirectory: true)
        let broadDir = bundlesRoot.appendingPathComponent("broad", isDirectory: true)
        let narrowDir = bundlesRoot.appendingPathComponent("narrow", isDirectory: true)
        try fm.createDirectory(at: broadDir, withIntermediateDirectories: true)
        try fm.createDirectory(at: narrowDir, withIntermediateDirectories: true)

        let broadDB = broadDir.appendingPathComponent("broad.sqlite")
        let narrowDB = narrowDir.appendingPathComponent("narrow.sqlite")
        try createFixtureV3DB(at: broadDB)
        try createFixtureV3DB(at: narrowDB)

        let broadManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "broad",
            countryCode: "DEU",
            bundleVersion: "2026-03-17",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: broadDB.lastPathComponent,
                bytes: try fileSize(broadDB),
                sha256: sha256Hex(try Data(contentsOf: broadDB)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: BundleCoverageBBox(minLon: 7.0, minLat: 47.0, maxLon: 10.0, maxLat: 50.0),
                poly: nil
            )
        )
        let narrowManifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "narrow",
            countryCode: "DEU",
            bundleVersion: "2026-03-17",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: narrowDB.lastPathComponent,
                bytes: try fileSize(narrowDB),
                sha256: sha256Hex(try Data(contentsOf: narrowDB)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            coverage: BundleCoverage(
                bbox: BundleCoverageBBox(minLon: 8.2, minLat: 48.6, maxLon: 8.7, maxLat: 49.0),
                poly: nil
            )
        )

        try JSONEncoder().encode(broadManifest).write(
            to: broadDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )
        try JSONEncoder().encode(narrowManifest).write(
            to: narrowDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let route = try await manager.resolveLocalBundleRoute(
            lat: 48.80117,
            lon: 8.44278,
            fallbackDBPath: broadDB.path
        )
        XCTAssertEqual(route?.region, "narrow")
        assertPathEqual(route?.dbPath, narrowDB.path)
    }

    func testResolvePenaltyRuleContextUsesManifestCountryAndRulesFile() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let bundleDir = supportDir
            .appendingPathComponent("bundles", isDirectory: true)
            .appendingPathComponent("nld-2026-03-02", isDirectory: true)
        try fm.createDirectory(at: bundleDir, withIntermediateDirectories: true)
        let dbURL = bundleDir.appendingPathComponent("NLD-latest.speeds_v3.sqlite")
        try createFixtureV3DB(at: dbURL)

        let rulesURL = bundleDir.appendingPathComponent("NLD-rules.json")
        try Data(
            """
            {
              "format":"youspeed.penalty.rules",
              "schema_version":1,
              "country_code":"NLD",
              "country_name":"Netherlands",
              "currency_code":"EUR",
              "bands":[]
            }
            """.utf8
        ).write(to: rulesURL, options: .atomic)

        let rulesData = try Data(contentsOf: rulesURL)
        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "netherlands",
            countryCode: "NLD",
            bundleVersion: "2026-03-02",
            createdAtUTC: "2026-03-02T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: dbURL.lastPathComponent,
                bytes: try fileSize(dbURL),
                sha256: sha256Hex(try Data(contentsOf: dbURL)),
                url: nil
            ),
            dbParts: nil,
            deltaIndex: nil,
            penaltyRules: BundleArtifact(
                file: rulesURL.lastPathComponent,
                bytes: Int64(rulesData.count),
                sha256: sha256Hex(rulesData),
                url: nil
            ),
            coverage: nil
        )
        try JSONEncoder().encode(manifest).write(
            to: bundleDir.appendingPathComponent("bundle-manifest.v3.json"),
            options: .atomic
        )

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let context = try await manager.resolvePenaltyRuleContext(forDBPath: dbURL.path)
        XCTAssertEqual(context?.countryCode, "NLD")
        XCTAssertEqual(context?.rulesFileName, "NLD-rules.json")
        assertPathEqual(context?.rulesPath, rulesURL.path)
    }

    @MainActor
    func testDefaultManifestURLFromInfoDictionary() {
        let raw = "https://github.com/volzinnovation/youspeed.de/releases/download/karlsruhe-regbez/karlsruhe-regbez_manifest.json"
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
                "YouSpeedV3ManifestURL": "$(YOUSPEED_V3_MANIFEST_URL)",
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

    @MainActor
    func testDefaultManifestEndpointsPreferBundledGermanyTargetsWhenExplicitOverrideIsUnset() {
        let bundle = Bundle(for: SpeedConsumerAppDelegate.self)

        let endpoints = DriveSessionViewModel.defaultManifestEndpoints(
            bundle: bundle,
            preferredCountryCode: "DEU"
        )
        XCTAssertFalse(endpoints.isEmpty)
        XCTAssertEqual(endpoints.first?.countryCode, "DEU")

        let config = try? V3BundleTargetsConfig.loadBundled(bundle: bundle)
        let bundledEndpoints = config?.manifestEndpoints(preferredCountryCode: "DEU") ?? []
        XCTAssertFalse(bundledEndpoints.isEmpty)
        XCTAssertTrue(endpoints.starts(with: bundledEndpoints, by: { $0.manifestURL == $1.manifestURL }))
    }

    @MainActor
    func testClearDrivingLogsUsesTimestampPrefixedMatcherLogFilename() throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let viewModel = DriveSessionViewModel()
        viewModel.clearDrivingLogs()

        let firstLogURL = URL(fileURLWithPath: try XCTUnwrap(
            viewModel.matchLogPath.isEmpty ? nil : viewModel.matchLogPath,
            "Expected matcher log path after clearing driving logs"
        ))
        XCTAssertTrue(fm.fileExists(atPath: firstLogURL.path))
        XCTAssertNotNil(
            firstLogURL.lastPathComponent.range(
                of: #"^\d{8}_\d{6}_\d{3}(?:_[0-9]+)?_drive_match_log\.ndjson$"#,
                options: .regularExpression
            )
        )

        viewModel.clearDrivingLogs()
        let secondLogURL = URL(fileURLWithPath: try XCTUnwrap(
            viewModel.matchLogPath.isEmpty ? nil : viewModel.matchLogPath,
            "Expected matcher log path after rotating driving logs"
        ))
        XCTAssertTrue(fm.fileExists(atPath: secondLogURL.path))
        XCTAssertNotEqual(firstLogURL, secondLogURL)
    }

    @MainActor
    func testViewModelInitClearsExistingDrivingLogs() throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        try fm.createDirectory(at: supportDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let gpsLogURL = supportDir.appendingPathComponent("gps_fix_log.csv")
        let staleMatchLogURL = supportDir.appendingPathComponent("20260312_000427_801_drive_match_log.ndjson")
        let anotherStaleMatchLogURL = supportDir.appendingPathComponent("20260312_000427_802_drive_match_log.ndjson")
        try Data("stale gps".utf8).write(to: gpsLogURL)
        try Data("{\"stale\":true}\n".utf8).write(to: staleMatchLogURL)
        try Data("{\"stale\":true}\n".utf8).write(to: anotherStaleMatchLogURL)

        let viewModel = DriveSessionViewModel()

        XCTAssertEqual(try String(contentsOf: gpsLogURL, encoding: .utf8).components(separatedBy: "\n").first, "fix_id,timestamp_utc,lat,lon,speed_kmh,hacc_m,vacc_m,course_deg,status,way_id,street_name,city_name,inside_city,city_source,city_resolve_ms,city_candidate_boundaries,city_containing_boundaries,city_place_candidates,speed_limit_kmh,query_ms,candidate_count,speed_candidate_count,nearest_candidate_m,nearest_speed_candidate_m,error")
        XCTAssertFalse(fm.fileExists(atPath: staleMatchLogURL.path))
        XCTAssertFalse(fm.fileExists(atPath: anotherStaleMatchLogURL.path))

        let currentMatchLogURL = URL(fileURLWithPath: try XCTUnwrap(
            viewModel.matchLogPath.isEmpty ? nil : viewModel.matchLogPath,
            "Expected current matcher log path after launch reset"
        ))
        XCTAssertTrue(fm.fileExists(atPath: currentMatchLogURL.path))
        XCTAssertEqual(try String(contentsOf: currentMatchLogURL, encoding: .utf8), "")
    }

    func testFlushLocalContributionStateRemovesLocalCorrectionArtifacts() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }
        try fm.createDirectory(at: supportDir, withIntermediateDirectories: true)

        let files = [
            supportDir.appendingPathComponent("local_corrections.sqlite"),
            supportDir.appendingPathComponent("local_corrections.sqlite-shm"),
            supportDir.appendingPathComponent("local_overrides.sqlite"),
            supportDir.appendingPathComponent("local_observation_store.sqlite-wal"),
            supportDir.appendingPathComponent("local_overlay_cache.sqlite"),
            supportDir.appendingPathComponent("osm-editor-export-outbox.sqlite"),
        ]
        for file in files {
            try Data("test".utf8).write(to: file)
        }
        let exportDir = supportDir.appendingPathComponent("osm-editor-packages", isDirectory: true)
        try fm.createDirectory(at: exportDir, withIntermediateDirectories: true)
        try Data("pkg".utf8).write(to: exportDir.appendingPathComponent("candidate.osc"))

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let removedCount = try await manager.flushLocalContributionState()

        XCTAssertEqual(removedCount, files.count + 1)
        for file in files {
            XCTAssertFalse(fm.fileExists(atPath: file.path), "expected removed file \(file.lastPathComponent)")
        }
        XCTAssertFalse(fm.fileExists(atPath: exportDir.path), "expected removed export directory")
    }

    func testFlushLocalContributionStateKeepsActiveBundleStateAndDatabase() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }
        try fm.createDirectory(at: supportDir, withIntermediateDirectories: true)

        let bundlesDir = supportDir.appendingPathComponent("bundles/2026-02-27", isDirectory: true)
        try fm.createDirectory(at: bundlesDir, withIntermediateDirectories: true)
        let activeDB = bundlesDir.appendingPathComponent("DEU-latest.speeds_v3.sqlite")
        try Data("runtime-db".utf8).write(to: activeDB)

        let activeState = ActiveBundleState(
            region: "DEU",
            bundleVersion: "2026-02-27",
            dbFileName: "DEU-latest.speeds_v3.sqlite",
            activatedAtUTC: "2026-02-27T00:00:00Z"
        )
        let activeStateData = try JSONEncoder().encode(activeState)
        try activeStateData.write(to: supportDir.appendingPathComponent("active_bundle.json"), options: .atomic)

        let removableFile = supportDir.appendingPathComponent("local_corrections.sqlite")
        try Data("local".utf8).write(to: removableFile)

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let removedCount = try await manager.flushLocalContributionState()

        XCTAssertGreaterThanOrEqual(removedCount, 1)
        XCTAssertFalse(fm.fileExists(atPath: removableFile.path), "expected local correction file to be removed")
        XCTAssertTrue(fm.fileExists(atPath: activeDB.path), "active runtime database must remain")
        XCTAssertTrue(
            fm.fileExists(atPath: supportDir.appendingPathComponent("active_bundle.json").path),
            "active bundle state must remain"
        )
    }

    func testLocalObservationStoreLockCurrentSpeedCreatesNeedsReviewObservation() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("speedconsumer-localobs-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }

        let defaultsName = "SpeedConsumerTests.localobs.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: defaultsName) else {
            XCTFail("failed to create isolated defaults suite")
            return
        }
        defaults.removePersistentDomain(forName: defaultsName)
        defer { defaults.removePersistentDomain(forName: defaultsName) }

        let store = LocalObservationStore(
            fileManager: fm,
            userDefaults: defaults,
            bundle: Bundle(for: SpeedConsumerAppDelegate.self),
            rootDirectoryOverride: root
        )

        let context = LocalObservationCaptureContext(
            lat: 48.8011149,
            lon: 8.442695,
            headingDeg: 92.0,
            roadCandidateIDs: ["17721265"],
            cityContext: "Karlsruhe",
            streetContext: "Dobler Strasse",
            confidenceCalibrated: 0.9,
            sourceVersion: "seed"
        )
        let observation = try await store.lockCurrentSpeed(speedKmh: 64, context: context)

        XCTAssertEqual(observation.modality, .lock_current_speed)
        XCTAssertEqual(observation.intentType, .lock_speed_snapshot)
        XCTAssertEqual(observation.value, "64")
        XCTAssertEqual(observation.state, .needsReview)
        XCTAssertEqual(observation.roadCandidateIDs, ["17721265"])
        XCTAssertNil(observation.oldSpeedKmh)
        XCTAssertEqual(observation.newSpeedKmh, 64)
    }

    func testLocalObservationStoreCaptureApproveAndExportFlow() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("speedconsumer-localobs-export-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }

        let defaultsName = "SpeedConsumerTests.localobs.export.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: defaultsName) else {
            XCTFail("failed to create isolated defaults suite")
            return
        }
        defaults.removePersistentDomain(forName: defaultsName)
        defer { defaults.removePersistentDomain(forName: defaultsName) }

        let fixedDate = Date(timeIntervalSince1970: 1_770_000_000)
        let store = LocalObservationStore(
            fileManager: fm,
            userDefaults: defaults,
            bundle: Bundle(for: SpeedConsumerAppDelegate.self),
            rootDirectoryOverride: root,
            nowProvider: { fixedDate }
        )

        let context = LocalObservationCaptureContext(
            lat: 48.8011149,
            lon: 8.442695,
            headingDeg: 90.0,
            roadCandidateIDs: ["17721265"],
            cityContext: "Karlsruhe",
            streetContext: "Dobler Strasse",
            confidenceCalibrated: 0.88,
            sourceVersion: "2026-02-27"
        )
        let captured = try await store.captureVoiceCommand(command: "Tempo 30", context: context)
        XCTAssertEqual(captured.state, .needsReview)
        XCTAssertEqual(captured.intentType, .set_maxspeed)
        XCTAssertEqual(captured.value, "30")

        let approved = try await store.reviewAndApproveProposal(observationID: captured.id)
        XCTAssertEqual(approved.state, .approvedForExport)

        let export = try await store.exportProposalAsOscPackage(observationID: captured.id)
        XCTAssertTrue(fm.fileExists(atPath: export.changesFile.path))
        XCTAssertTrue(fm.fileExists(atPath: export.reviewFile.path))
        XCTAssertTrue(fm.fileExists(atPath: export.readmeFile.path))

        let osc = try String(contentsOf: export.changesFile, encoding: .utf8)
        XCTAssertTrue(osc.contains("<osmChange"))
        XCTAssertTrue(osc.contains("<way id=\"17721265\">"))
        XCTAssertTrue(osc.contains("<tag k=\"maxspeed\" v=\"30\"/>"))

        let review = try String(contentsOf: export.reviewFile, encoding: .utf8)
        XCTAssertTrue(review.contains("\"export_id\""))
        XCTAssertTrue(review.contains("\"observation_ids\""))
        XCTAssertTrue(review.contains("17721265"))

        let all = try await store.fetchObservations(limit: 5)
        XCTAssertEqual(all.first(where: { $0.id == captured.id })?.state, .exportedOsc)
    }

    func testLocalObservationStoreBulkExportAndDeleteFlow() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("speedconsumer-localobs-bulk-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }

        let defaultsName = "SpeedConsumerTests.localobs.bulk.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: defaultsName) else {
            XCTFail("failed to create isolated defaults suite")
            return
        }
        defaults.removePersistentDomain(forName: defaultsName)
        defer { defaults.removePersistentDomain(forName: defaultsName) }

        let store = LocalObservationStore(
            fileManager: fm,
            userDefaults: defaults,
            bundle: Bundle(for: SpeedConsumerAppDelegate.self),
            rootDirectoryOverride: root
        )

        let contextA = LocalObservationCaptureContext(
            lat: 48.8011149,
            lon: 8.442695,
            headingDeg: nil,
            roadCandidateIDs: ["17721265"],
            cityContext: "Karlsruhe",
            streetContext: "Dobler Strasse",
            confidenceCalibrated: 0.9,
            sourceVersion: "seed"
        )
        let contextB = LocalObservationCaptureContext(
            lat: 48.801234,
            lon: 8.442901,
            headingDeg: nil,
            roadCandidateIDs: ["69233057"],
            cityContext: "Karlsruhe",
            streetContext: "Kullenmuehle",
            confidenceCalibrated: 0.84,
            sourceVersion: "seed"
        )

        let first = try await store.recordSpeedLimitChange(oldSpeedKmh: 30, newMaxspeedValue: "40", context: contextA)
        let second = try await store.recordSpeedLimitChange(oldSpeedKmh: 50, newMaxspeedValue: "60", context: contextB)
        XCTAssertEqual(first.oldSpeedKmh, 30)
        XCTAssertEqual(first.newSpeedKmh, 40)
        XCTAssertEqual(second.oldSpeedKmh, 50)
        XCTAssertEqual(second.newSpeedKmh, 60)

        let bulk = try await store.exportAllLocalObservationsAsOsc()
        XCTAssertEqual(bulk.includedCount, 2)
        XCTAssertTrue(fm.fileExists(atPath: bulk.changesFile.path))

        let osc = try String(contentsOf: bulk.changesFile, encoding: .utf8)
        XCTAssertTrue(osc.contains("<way id=\"17721265\">"))
        XCTAssertTrue(osc.contains("<tag k=\"maxspeed\" v=\"40\"/>"))
        XCTAssertTrue(osc.contains("<way id=\"69233057\">"))
        XCTAssertTrue(osc.contains("<tag k=\"maxspeed\" v=\"60\"/>"))

        try await store.deleteObservation(observationID: first.id)
        let afterSingleDelete = try await store.fetchObservations(limit: 10)
        XCTAssertFalse(afterSingleDelete.contains(where: { $0.id == first.id }))

        let removed = try await store.deleteAllObservations()
        XCTAssertGreaterThanOrEqual(removed, 1)
        let afterDeleteAll = try await store.fetchObservations(limit: 10)
        XCTAssertTrue(afterDeleteAll.isEmpty)
    }

    func testLocalObservationStoreBulkExportSupportsWalkValue() async throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("speedconsumer-localobs-walk-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }

        let defaultsName = "SpeedConsumerTests.localobs.walk.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: defaultsName) else {
            XCTFail("failed to create isolated defaults suite")
            return
        }
        defaults.removePersistentDomain(forName: defaultsName)
        defer { defaults.removePersistentDomain(forName: defaultsName) }

        let store = LocalObservationStore(
            fileManager: fm,
            userDefaults: defaults,
            bundle: Bundle(for: SpeedConsumerAppDelegate.self),
            rootDirectoryOverride: root
        )

        let context = LocalObservationCaptureContext(
            lat: 48.8011149,
            lon: 8.442695,
            headingDeg: nil,
            roadCandidateIDs: ["17721265"],
            cityContext: "Karlsruhe",
            streetContext: "Dobler Strasse",
            confidenceCalibrated: 0.9,
            sourceVersion: "seed"
        )

        let observation = try await store.recordSpeedLimitChange(oldSpeedKmh: 30, newMaxspeedValue: "walk", context: context)
        XCTAssertEqual(observation.value, "walk")
        XCTAssertNil(observation.newSpeedKmh)

        let bulk = try await store.exportAllLocalObservationsAsOsc()
        let osc = try String(contentsOf: bulk.changesFile, encoding: .utf8)
        XCTAssertTrue(osc.contains("<way id=\"17721265\">"))
        XCTAssertTrue(osc.contains("<tag k=\"maxspeed\" v=\"walk\"/>"))
    }

    @MainActor
    func testSpeedCaptureCanSucceedTwiceInARow() async throws {
        let viewModel = DriveSessionViewModel()
        try await viewModel.testResetLocalObservationStore()

        viewModel.speedLimitKmh = 50
        viewModel.limitWayID = "17721265"
        viewModel.limitStreetName = "Dobler Strasse"
        viewModel.limitCityName = "Bad Herrenalb"
        viewModel.currentLatitude = 48.797626
        viewModel.currentLongitude = 8.437309
        viewModel.activeBundleVersion = "seed"

        try await viewModel.testSimulateRecognizedSpeedCapture(transcript: "dreissig")

        XCTAssertEqual(viewModel.speedCaptureMode, .idle)
        XCTAssertFalse(viewModel.testSpeedCaptureDidResolve)
        XCTAssertEqual(viewModel.testSpeedCaptureLatestTranscript, "")

        let afterFirstCapture = try await viewModel.testStoredLocalObservations()
        XCTAssertEqual(afterFirstCapture.count, 1)
        XCTAssertEqual(afterFirstCapture.first?.value, "30")
        XCTAssertEqual(afterFirstCapture.first?.roadCandidateIDs, ["17721265"])

        try await viewModel.testSimulateRecognizedSpeedCapture(transcript: "vierzig")

        XCTAssertEqual(viewModel.speedCaptureMode, .idle)
        XCTAssertFalse(viewModel.testSpeedCaptureDidResolve)
        XCTAssertEqual(viewModel.testSpeedCaptureLatestTranscript, "")

        let afterSecondCapture = try await viewModel.testStoredLocalObservations()
        XCTAssertEqual(afterSecondCapture.count, 2)
        XCTAssertEqual(afterSecondCapture.first?.value, "40")
        XCTAssertEqual(afterSecondCapture.first?.roadCandidateIDs, ["17721265"])
        XCTAssertEqual(afterSecondCapture.dropFirst().first?.value, "30")

        try await viewModel.testResetLocalObservationStore()
    }

    @MainActor
    func testSpeedCaptureWalkShowsWalkingPaceLabel() async throws {
        let viewModel = DriveSessionViewModel()
        try await viewModel.testResetLocalObservationStore()

        viewModel.speedLimitKmh = 30
        viewModel.limitWayID = "17721265"
        viewModel.limitStreetName = "Dobler Strasse"
        viewModel.limitCityName = "Bad Herrenalb"
        viewModel.currentLatitude = 48.797626
        viewModel.currentLongitude = 8.437309
        viewModel.activeBundleVersion = "seed"

        try await viewModel.testSimulateRecognizedSpeedCapture(transcript: "fussgaengerzone")

        XCTAssertNil(viewModel.speedLimitKmh)
        XCTAssertEqual(viewModel.speedLimitDisplayText, "Schritt")

        let stored = try await viewModel.testStoredLocalObservations()
        XCTAssertEqual(stored.first?.value, "walk")

        try await viewModel.testResetLocalObservationStore()
    }

    @MainActor
    func testActiveLocalSpeedCorrectionExpiresOnNextWayID() async throws {
        let viewModel = DriveSessionViewModel()
        try await viewModel.testResetLocalObservationStore()

        viewModel.testSetActiveLocalSpeedCorrection(wayID: "17721265", value: "30", numericSpeedKmh: 30)

        XCTAssertNil(viewModel.testApplyActiveLocalSpeedCorrection(wayID: nil))
        XCTAssertEqual(viewModel.testActiveLocalSpeedCorrectionWayID, "17721265")

        XCTAssertEqual(viewModel.testApplyActiveLocalSpeedCorrection(wayID: "17721265"), "30")
        XCTAssertEqual(viewModel.testActiveLocalSpeedCorrectionWayID, "17721265")

        XCTAssertNil(viewModel.testApplyActiveLocalSpeedCorrection(wayID: "17721266"))
        XCTAssertNil(viewModel.testActiveLocalSpeedCorrectionWayID)

        try await viewModel.testResetLocalObservationStore()
    }

    func testResolveLocalSpeedOverridesUsesLatestAndSkipsDiscarded() async {
        let base = "2026-03-08T00:00:00.000Z"
        let observations: [LocalObservation] = [
            LocalObservation(
                id: "obs-latest",
                modality: .lock_current_speed,
                intentType: .set_maxspeed,
                value: "40",
                lat: 48.801,
                lon: 8.443,
                headingDeg: nil,
                roadCandidateIDs: ["17721265"],
                cityContext: "Karlsruhe",
                streetContext: "Dobler Strasse",
                capturedAtUTC: base,
                confidenceCalibrated: 0.9,
                sourceVersion: "seed",
                state: .localOnly,
                devicePseudoID: "device-a",
                updatedAtUTC: base,
                exportID: nil,
                oldSpeedKmh: 30,
                newSpeedKmh: 40
            ),
            LocalObservation(
                id: "obs-discarded",
                modality: .lock_current_speed,
                intentType: .set_maxspeed,
                value: "60",
                lat: 48.801,
                lon: 8.443,
                headingDeg: nil,
                roadCandidateIDs: ["17721265"],
                cityContext: "Karlsruhe",
                streetContext: "Dobler Strasse",
                capturedAtUTC: "2026-03-07T00:00:00.000Z",
                confidenceCalibrated: 0.8,
                sourceVersion: "seed",
                state: .discarded,
                devicePseudoID: "device-a",
                updatedAtUTC: "2026-03-07T00:00:00.000Z",
                exportID: nil,
                oldSpeedKmh: 30,
                newSpeedKmh: 60
            ),
            LocalObservation(
                id: "obs-second-way",
                modality: .voice_command,
                intentType: .set_maxspeed,
                value: "50",
                lat: 48.802,
                lon: 8.444,
                headingDeg: nil,
                roadCandidateIDs: ["69233057"],
                cityContext: "Karlsruhe",
                streetContext: "Kullenmuehle",
                capturedAtUTC: "2026-03-07T10:00:00.000Z",
                confidenceCalibrated: 0.84,
                sourceVersion: "seed",
                state: .needsReview,
                devicePseudoID: "device-a",
                updatedAtUTC: "2026-03-07T10:00:00.000Z",
                exportID: nil,
                oldSpeedKmh: nil,
                newSpeedKmh: 50
            ),
        ]

        let resolved = await MainActor.run {
            DriveSessionViewModel.resolveLocalSpeedOverrides(from: observations)
        }
        XCTAssertEqual(resolved["17721265"], 40)
        XCTAssertEqual(resolved["69233057"], 50)
        XCTAssertEqual(resolved.count, 2)
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

    func testCompressedBundleSyncAndFirstQuery() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-gzip-tests-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)
        let sourceSHA = sha256Hex(sourceData)
        let gzipData = try gzipCompressedData(sourceData)

        let manifestURL = URL(string: "https://speedconsumer.test/DEU-gzip.bundle-manifest.v3.json")!
        let dbURL = URL(string: "https://speedconsumer.test/DEU-gzip.speeds_v3.sqlite.gz")!

        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "DEU",
            bundleVersion: "2026-03-17-gzip",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-gzip.speeds_v3.sqlite",
                bytes: Int64(gzipData.count),
                sha256: sha256Hex(gzipData),
                url: dbURL.absoluteString,
                compression: "gzip",
                uncompressedBytes: Int64(sourceData.count),
                uncompressedSHA256: sourceSHA
            ),
            dbParts: nil,
            deltaIndex: nil
        )

        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 200, body: try JSONEncoder().encode(manifest)),
            dbURL.absoluteString: (status: 200, body: gzipData),
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
        XCTAssertEqual(sync.bundleVersion, "2026-03-17-gzip")

        guard let dbURL = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after compressed sync")
            return
        }
        XCTAssertTrue(fm.fileExists(atPath: dbURL.path))
        let assembledData = try Data(contentsOf: dbURL)
        XCTAssertEqual(sourceData.count, assembledData.count)
        XCTAssertEqual(sourceSHA, sha256Hex(assembledData))
        try assertDBIntegrity(dbURL)
    }

    func testCompressedMultipartBundleSyncAndFirstQuery() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-gzip-multipart-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)
        let sourceSHA = sha256Hex(sourceData)
        let gzipData = try gzipCompressedData(sourceData)

        let splitAt = max(1, gzipData.count / 2)
        let part1Data = gzipData.subdata(in: 0..<splitAt)
        let part2Data = gzipData.subdata(in: splitAt..<gzipData.count)

        let manifestURL = URL(string: "https://speedconsumer.test/DEU-gzip-multipart.bundle-manifest.v3.json")!
        let part1URL = URL(string: "https://speedconsumer.test/DEU-gzip.speeds_v3.sqlite.gz.part001")!
        let part2URL = URL(string: "https://speedconsumer.test/DEU-gzip.speeds_v3.sqlite.gz.part002")!

        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "DEU",
            bundleVersion: "2026-03-17-gzip-multipart",
            createdAtUTC: "2026-03-17T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-gzip.speeds_v3.sqlite",
                bytes: Int64(gzipData.count),
                sha256: sha256Hex(gzipData),
                url: nil,
                compression: "gzip",
                uncompressedBytes: Int64(sourceData.count),
                uncompressedSHA256: sourceSHA
            ),
            dbParts: [
                BundleArtifact(
                    file: "DEU-gzip.speeds_v3.sqlite.gz.part001",
                    bytes: Int64(part1Data.count),
                    sha256: sha256Hex(part1Data),
                    url: part1URL.absoluteString
                ),
                BundleArtifact(
                    file: "DEU-gzip.speeds_v3.sqlite.gz.part002",
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
        XCTAssertEqual(sync.bundleVersion, "2026-03-17-gzip-multipart")

        guard let dbURL = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after compressed multipart sync")
            return
        }
        XCTAssertTrue(fm.fileExists(atPath: dbURL.path))
        let assembledData = try Data(contentsOf: dbURL)
        XCTAssertEqual(sourceData.count, assembledData.count)
        XCTAssertEqual(sourceSHA, sha256Hex(assembledData))
        try assertDBIntegrity(dbURL)
    }

    func testLookupTreatsExplicitUnlimitedMotorwayAsMatchedUnlimitedState() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-unlimited-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: dbURL)
        try executeSQL(
            at: dbURL,
            sql: """
            UPDATE ways
            SET highway='motorway', street_name='Autobahn 8', ref='A 8', maxspeed='none'
            WHERE way_id='100';
            """
        )

        let service = V3SpeedLimitService(dbPath: dbURL.path)
        let result = try service.lookupSpeedLimit(
            lat: 52.5205,
            lon: 13.4055,
            radiusM: 250.0,
            maxCandidates: 64,
            headingDeg: 45.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 148.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "100")
        XCTAssertNil(result.speedLimitKmh)
        XCTAssertEqual(result.isUnlimitedSpeedLimit, true)
        XCTAssertEqual(result.streetName, "Autobahn 8 (A 8)")
        XCTAssertEqual(result.speedCandidateCount, 1)
    }

    func testLookupDoesNotCollapseUnsignedMotorwayToGenericOutOfCityFallback() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-unsigned-motorway-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: dbURL)
        try executeSQL(
            at: dbURL,
            sql: """
            UPDATE ways
            SET highway='motorway',
                street_name='Autobahn 8',
                ref='A 8',
                maxspeed=NULL,
                maxspeed_type='DE:motorway',
                source_maxspeed=NULL
            WHERE way_id='100';

            UPDATE areas
            SET points_json='[[13.4050,52.5200],[13.4062,52.5200],[13.4062,52.5204],[13.4054,52.5204],[13.4054,52.5212],[13.4050,52.5212],[13.4050,52.5200]]'
            WHERE row_id=2;
            """
        )

        let service = V3SpeedLimitService(dbPath: dbURL.path)
        let result = try service.lookupSpeedLimit(
            lat: 52.5205,
            lon: 13.4055,
            radiusM: 250.0,
            maxCandidates: 64,
            headingDeg: 45.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 118.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "100")
        XCTAssertEqual(result.highway, "motorway")
        XCTAssertEqual(result.insideCity, false)
        XCTAssertNil(result.speedLimitKmh)
        XCTAssertNotEqual(result.isUnlimitedSpeedLimit, true)
    }

    func testSeedBundleSyncAppliesZlibCompressedDeltaChain() async throws {
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

        let seedDB = seedDir.appendingPathComponent("fixture-seed.sqlite")
        try createFixtureV3DB(at: seedDB)
        let seedState = ActiveBundleState(
            region: "DEU",
            bundleVersion: "seed",
            dbFileName: seedDB.lastPathComponent,
            activatedAtUTC: "2026-03-04T00:00:00Z",
            dbPath: seedDB.path
        )
        try JSONEncoder().encode(seedState).write(
            to: supportDir.appendingPathComponent("active_bundle.json"),
            options: .atomic
        )

        let seedData = try Data(contentsOf: seedDB)
        let manifestURL = URL(string: "https://speedconsumer.test/DEU-latest.bundle-manifest.v3.json")!
        let dbURL = URL(string: "https://speedconsumer.test/DEU-latest.speeds_v3.sqlite")!
        let deltaIndexURL = URL(string: "https://speedconsumer.test/DEU-latest.delta-index.v3.json")!
        let deltaManifest1URL = URL(string: "https://speedconsumer.test/deltas/seed_to_2026-03-01.json")!
        let deltaManifest2URL = URL(string: "https://speedconsumer.test/deltas/2026-03-01_to_2026-03-02.json")!
        let patch1URL = URL(string: "https://speedconsumer.test/deltas/seed_to_2026-03-01.sql.zlib")!
        let patch2URL = URL(string: "https://speedconsumer.test/deltas/2026-03-01_to_2026-03-02.sql.zlib")!

        let patch1SQL = """
        BEGIN IMMEDIATE;
        UPDATE ways
           SET maxspeed='42',
               street_name='Delta Step One'
         WHERE way_id='100';
        COMMIT;
        """
        let patch2SQL = """
        BEGIN IMMEDIATE;
        UPDATE ways
           SET maxspeed='45',
               street_name='Delta Step Two'
         WHERE way_id='100';
        COMMIT;
        """
        let patch1Data = try zlibCompressedData(Data(patch1SQL.utf8))
        let patch2Data = try zlibCompressedData(Data(patch2SQL.utf8))

        let manifest = V3BundleManifest(
            format: "youspeed.v3.bundle.manifest",
            schemaVersion: 1,
            variant: "v3",
            region: "DEU",
            bundleVersion: "2026-03-02",
            createdAtUTC: "2026-03-02T00:00:00Z",
            minAppVersion: "1.0.0",
            db: BundleArtifact(
                file: "DEU-latest.speeds_v3.sqlite",
                bytes: Int64(seedData.count),
                sha256: sha256Hex(seedData),
                url: dbURL.absoluteString
            ),
            dbParts: nil,
            deltaIndex: BundleArtifact(
                file: "DEU-latest.delta-index.v3.json",
                bytes: 0,
                sha256: String(repeating: "0", count: 64),
                url: deltaIndexURL.absoluteString
            )
        )
        let deltaIndex = V3DeltaIndex(
            format: "youspeed.v3.delta.index",
            schemaVersion: 1,
            count: 2,
            entries: [
                V3DeltaIndex.Entry(
                    fromBundleVersion: "seed",
                    toBundleVersion: "2026-03-01",
                    region: "DEU",
                    deltaManifestFile: "deltas/seed_to_2026-03-01.json"
                ),
                V3DeltaIndex.Entry(
                    fromBundleVersion: "2026-03-01",
                    toBundleVersion: "2026-03-02",
                    region: "DEU",
                    deltaManifestFile: "deltas/2026-03-01_to_2026-03-02.json"
                ),
            ]
        )
        let deltaManifest1 = """
        {
          "format": "youspeed.v3.delta.manifest",
          "schema_version": 1,
          "region": "DEU",
          "from_bundle_version": "seed",
          "to_bundle_version": "2026-03-01",
          "created_at_utc": "2026-03-01T01:00:00Z",
          "patch": {
            "file": "seed_to_2026-03-01.sql.zlib",
            "bytes": \(patch1Data.count),
            "sha256": "\(sha256Hex(patch1Data))",
            "url": "\(patch1URL.absoluteString)",
            "compression": "zlib"
          },
          "stats": {
            "changed_way_count": 1,
            "ways_added": 0,
            "ways_removed": 0,
            "ways_modified": 1,
            "delete_way_count": 0,
            "insert_way_count": 0,
            "skipped_insert_way_count": 0
          }
        }
        """
        let deltaManifest2 = """
        {
          "format": "youspeed.v3.delta.manifest",
          "schema_version": 1,
          "region": "DEU",
          "from_bundle_version": "2026-03-01",
          "to_bundle_version": "2026-03-02",
          "created_at_utc": "2026-03-02T01:00:00Z",
          "patch": {
            "file": "2026-03-01_to_2026-03-02.sql.zlib",
            "bytes": \(patch2Data.count),
            "sha256": "\(sha256Hex(patch2Data))",
            "url": "\(patch2URL.absoluteString)",
            "compression": "zlib"
          },
          "stats": {
            "changed_way_count": 1,
            "ways_added": 0,
            "ways_removed": 0,
            "ways_modified": 1,
            "delete_way_count": 0,
            "insert_way_count": 0,
            "skipped_insert_way_count": 0
          }
        }
        """

        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 200, body: try JSONEncoder().encode(manifest)),
            deltaIndexURL.absoluteString: (status: 200, body: try JSONEncoder().encode(deltaIndex)),
            deltaManifest1URL.absoluteString: (status: 200, body: Data(deltaManifest1.utf8)),
            deltaManifest2URL.absoluteString: (status: 200, body: Data(deltaManifest2.utf8)),
            patch1URL.absoluteString: (status: 200, body: patch1Data),
            patch2URL.absoluteString: (status: 200, body: patch2Data),
        ]
        defer {
            MockURLProtocol.responses = [:]
        }

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        let manager = V3BundleManager(fileManager: fm, session: session)

        let sync = try await manager.syncFromManifestURL(manifestURL)
        XCTAssertEqual(sync.mode, .deltaPatch)
        XCTAssertEqual(sync.bundleVersion, "2026-03-02")

        guard let activeDB = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active DB after delta chain sync")
            return
        }
        let service = V3SpeedLimitService(dbPath: activeDB.path)
        let result = try service.lookupSpeedLimit(
            lat: 52.5205,
            lon: 13.4055,
            radiusM: 250.0,
            maxCandidates: 64
        )
        XCTAssertEqual(result.wayID, "100")
        XCTAssertEqual(result.speedLimitKmh, 45)
        XCTAssertEqual(result.streetName, "Delta Step Two")
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

        let seedDB = seedDir.appendingPathComponent("karlsruhe-regbez_speeds.sqlite")
        try createFixtureV3DB(at: seedDB)

        let activeState = ActiveBundleState(
            region: "unknown",
            bundleVersion: "seed",
            dbFileName: "karlsruhe-regbez_speeds.sqlite",
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
        let bundledSeed = appBundle.url(forResource: "karlsruhe-regbez_speeds", withExtension: "sqlite")
        guard bundledSeed != nil else {
            throw XCTSkip("Bundled seed DB not found")
        }

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let result = try await manager.bootstrapSeedIfNeeded(bundle: appBundle)

        XCTAssertEqual(result.bundleVersion, "seed")
        let copiedSeedDB = supportDir
            .appendingPathComponent("bundles", isDirectory: true)
            .appendingPathComponent("seed", isDirectory: true)
            .appendingPathComponent("karlsruhe-regbez_speeds.sqlite")
        let state = try await manager.activeState()
        XCTAssertEqual(state?.bundleVersion, "seed")

        assertPathEqual(result.dbPath, bundledSeed?.path)
        XCTAssertEqual(result.details, "seed bundle referenced")
        assertPathEqual(state?.dbPath, bundledSeed?.path)
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
        let copiedSeedDB = seedDir.appendingPathComponent("karlsruhe-regbez_speeds.sqlite")
        try createFixtureV3DB(at: copiedSeedDB)

        let legacySeedState = ActiveBundleState(
            region: "unknown",
            bundleVersion: "seed",
            dbFileName: "karlsruhe-regbez_speeds.sqlite",
            activatedAtUTC: "2026-02-25T00:00:00Z"
        )
        try JSONEncoder().encode(legacySeedState).write(
            to: supportDir.appendingPathComponent("active_bundle.json"),
            options: .atomic
        )

        let appBundle = Bundle(for: SpeedConsumerAppDelegate.self)
        let bundledSeed = appBundle.url(forResource: "karlsruhe-regbez_speeds", withExtension: "sqlite")
        guard bundledSeed != nil else {
            throw XCTSkip("Bundled seed DB not found")
        }

        let manager = V3BundleManager(fileManager: fm, session: URLSession(configuration: .ephemeral))
        let result = try await manager.bootstrapSeedIfNeeded(bundle: appBundle)

        XCTAssertEqual(result.bundleVersion, "seed")
        let state = try await manager.activeState()
        assertPathEqual(result.dbPath, bundledSeed?.path)
        XCTAssertFalse(fm.fileExists(atPath: copiedSeedDB.path), "Legacy copied seed should be removed after migration")
        assertPathEqual(state?.dbPath, bundledSeed?.path)
    }

    @MainActor
    func testSyncDownloadsPublicGitHubReleaseURLsDirectly() async throws {
        let fm = FileManager.default
        let supportDir = try V3BundleManager.applicationSupportDirectory(fileManager: fm)
        if fm.fileExists(atPath: supportDir.path) {
            try fm.removeItem(at: supportDir)
        }
        defer {
            try? fm.removeItem(at: supportDir)
        }

        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-public-release-tests-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let sourceDB = tempDir.appendingPathComponent("fixture.sqlite")
        try createFixtureV3DB(at: sourceDB)
        let sourceData = try Data(contentsOf: sourceDB)

        let manifestURL = URL(string: "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.bundle-manifest.v3.json")!
        let dbURL = URL(string: "https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest/DEU-latest.speeds_v3.sqlite")!
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

        MockURLProtocol.responses = [
            manifestURL.absoluteString: (status: 200, body: manifestData),
            dbURL.absoluteString: (status: 200, body: sourceData),
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

    func testBundledDriveLogSequenceUsesThreeWayGateForFutureStableNearestRoadSwitch() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["1037006038", "16634524", "209270485"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required drive-log regression ways: \(missingWayIDs.sorted())")
        }

        let logURL = try privateDriveMatchLogURL(environmentKey: "YOUSPEED_TEST_THREE_WAY_LOG")
        let entries = try loadDriveMatchLogEntries(url: logURL, fixIDRange: 34 ... 44)
        XCTAssertEqual(entries.count, 11, "Expected exact drive-log window for the three-way gate regression")

        let targetFixID = 38
        let futureStableWayID = "16634524"
        let futureEntries = entries.filter { $0.fixID > targetFixID && $0.fixID <= 44 }
        XCTAssertFalse(futureEntries.isEmpty, "Need future fixes to establish the hindsight label")
        XCTAssertTrue(
            futureEntries.allSatisfy { $0.result?.wayID == futureStableWayID },
            "Future fixes should stay on the hindsight label road"
        )

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var state = BundledMatchContextState()
        for entry in entries where entry.fixID < targetFixID {
            let priorResult = try XCTUnwrap(entry.result, "Expected matched drive-log result for fix \(entry.fixID)")
            state.record(
                priorResult,
                lat: entry.lat,
                lon: entry.lon,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
        }

        let target = try XCTUnwrap(entries.first(where: { $0.fixID == targetFixID }))
        let result = try service.lookupSpeedLimit(
            lat: target.lat,
            lon: target.lon,
            radiusM: 50.0,
            maxCandidates: 64,
            matchContext: state.context,
            headingDeg: target.courseDeg,
            headingAccuracyDeg: 10.0,
            speedKmh: target.speedKmh,
            horizontalAccuracyM: target.horizontalAccM,
            gpsSignalBars: target.gpsSignalBars
        )

        XCTAssertEqual(result.wayID, futureStableWayID)
        XCTAssertTrue(
            result.selectionTrace.contains {
                ($0.step == "three_way_gate" || $0.step == "heuristic") && $0.detail.contains(futureStableWayID)
            },
            "Expected the matcher to settle on the hindsight-stable correction path"
        )
    }

    func testBundledDriveLogRejectsDisconnectedLoffenauHopAfterWarmup() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["16654539", "206811642", "723188219"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required Loffenau regression ways: \(missingWayIDs.sorted())")
        }

        let logURL = try privateDriveMatchLogURL(environmentKey: "YOUSPEED_TEST_LOFFENAU_LOG")
        let entries = try loadDriveMatchLogEntries(url: logURL)
        let targetFixID = 2497
        let target = try XCTUnwrap(
            entries.first(where: { $0.fixID == targetFixID }),
            "Expected Loffenau regression fix \(targetFixID)"
        )
        XCTAssertEqual(target.result?.wayID, "16654539", "Fixture should capture the disconnected service-road hop")

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var state = BundledMatchContextState()
        for entry in entries where entry.fixID < targetFixID {
            let priorResult = try XCTUnwrap(entry.result, "Expected matched drive-log result for fix \(entry.fixID)")
            state.record(
                priorResult,
                lat: entry.lat,
                lon: entry.lon,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
        }
        XCTAssertGreaterThanOrEqual(state.matchedFixCount, 3, "Regression should run after graph-gate warmup")

        let result = try service.lookupSpeedLimit(
            lat: target.lat,
            lon: target.lon,
            radiusM: 50.0,
            maxCandidates: 64,
            matchContext: state.context,
            headingDeg: target.courseDeg,
            headingAccuracyDeg: 10.0,
            speedKmh: target.speedKmh,
            horizontalAccuracyM: target.horizontalAccM,
            gpsSignalBars: target.gpsSignalBars
        )

        XCTAssertNotEqual(result.wayID, "16654539")
        XCTAssertTrue(
            Set(["206811642", "723188219"]).contains(result.wayID ?? ""),
            "Expected a connected L564 continuation instead of the disconnected service road"
        )
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "road_graph_gate" && $0.detail.contains("disconnected candidates")
            },
            "Expected road graph gate trace for disconnected Loffenau hop"
        )
    }

    func testBundledLookupUsesAdminPolygonAtLoffenauRegressionFix() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let logURL = try privateDriveMatchLogURL(environmentKey: "YOUSPEED_TEST_LOFFENAU_LOG")
        let entries = try loadDriveMatchLogEntries(url: logURL)
        let target = try XCTUnwrap(
            entries.first(where: { $0.fixID == 2497 }),
            "Expected bundled Loffenau replay fix"
        )

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let result = try service.lookupSpeedLimit(
            lat: target.lat,
            lon: target.lon,
            radiusM: 50.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Gernsbach (Landkreis Rastatt)")
        XCTAssertEqual(result.cityPlaceName, "Gernsbach")
        XCTAssertEqual(result.cityDistrictName, "Landkreis Rastatt")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
    }

    func testBundledLookupResolvesLoffenauViaAdminPolygon() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let result = try service.lookupSpeedLimit(
            lat: 48.7739967,
            lon: 8.3807646,
            radiusM: 50.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Loffenau (Landkreis Rastatt)")
        XCTAssertEqual(result.cityPlaceName, "Loffenau")
        XCTAssertEqual(result.cityDistrictName, "Landkreis Rastatt")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
    }

    func testBundledDriveLogsAcrossAllInspectorLogsMeetHindsightThresholds() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let logURLs = try allInspectorDriveMatchLogURLs()
        XCTAssertFalse(logURLs.isEmpty, "Expected drive logs in inspector/logs")

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var aggregate = DriveLogReplayMetrics()
        var perLogSummaries: [String] = []

        for logURL in logURLs {
            let entries = try loadDriveMatchLogEntries(url: logURL)
            XCTAssertFalse(entries.isEmpty, "Expected non-empty drive log at \(logURL.lastPathComponent)")

            var state = BundledMatchContextState()
            var logMetrics = DriveLogReplayMetrics()
            for (index, entry) in entries.enumerated() {
                let result = try service.lookupSpeedLimit(
                    lat: entry.lat,
                    lon: entry.lon,
                    radiusM: 50.0,
                    maxCandidates: 64,
                    matchContext: state.context,
                    headingDeg: entry.courseDeg,
                    headingAccuracyDeg: 10.0,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )

                logMetrics.replayedFixCount += 1
                if result.selectionTrace.contains(where: { $0.step == "three_way_gate" }) {
                    logMetrics.usedThreeWayGateCount += 1
                }

                if let pseudoLabelWayID = hindsightPseudoLabelWayID(
                    in: entries,
                    at: index,
                    futureWindow: 5,
                    minFutureRunLength: 5,
                    minAgreementRatio: 0.8
                ) {
                    let selectedWayID = entries[index].result?.wayID
                    let predictedMatches = result.wayID == pseudoLabelWayID
                    let isChangedExample = selectedWayID != pseudoLabelWayID
                    logMetrics.pseudoLabelExampleCount += 1
                    logMetrics.correctPseudoLabelCount += predictedMatches ? 1 : 0
                    if isChangedExample {
                        logMetrics.changedExampleCount += 1
                        logMetrics.changedCorrectCount += predictedMatches ? 1 : 0
                    } else {
                        logMetrics.unchangedExampleCount += 1
                        logMetrics.unchangedCorrectCount += predictedMatches ? 1 : 0
                    }
                }

                state.record(
                    result,
                    lat: entry.lat,
                    lon: entry.lon,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )
            }

            aggregate.formUnion(logMetrics)
            perLogSummaries.append(
                "\(logURL.lastPathComponent)"
                    + " pseudo=\(logMetrics.pseudoLabelExampleCount)"
                    + " acc=\(String(format: "%.4f", logMetrics.accuracy))"
                    + " changed=\(logMetrics.changedExampleCount)"
                    + " changedRecall=\(String(format: "%.4f", logMetrics.changedRecall))"
                    + " unchangedAcc=\(String(format: "%.4f", logMetrics.unchangedAccuracy))"
                    + " gate=\(logMetrics.usedThreeWayGateCount)"
            )
        }

        print(
            "aggregate_replay pseudo=\(aggregate.pseudoLabelExampleCount)"
                + " acc=\(String(format: "%.4f", aggregate.accuracy))"
                + " changed=\(aggregate.changedExampleCount)"
                + " changedRecall=\(String(format: "%.4f", aggregate.changedRecall))"
                + " unchangedAcc=\(String(format: "%.4f", aggregate.unchangedAccuracy))"
                + " gate=\(aggregate.usedThreeWayGateCount)"
        )
        print("aggregate_replay_logs \(perLogSummaries.joined(separator: " | "))")

        XCTAssertGreaterThanOrEqual(
            aggregate.pseudoLabelExampleCount,
            4000,
            "Expected broad hindsight coverage across all inspector logs. Per-log: \(perLogSummaries.joined(separator: " | "))"
        )
        XCTAssertGreaterThanOrEqual(
            aggregate.accuracy,
            0.92,
            "Aggregate hindsight accuracy regressed. Per-log: \(perLogSummaries.joined(separator: " | "))"
        )
        XCTAssertGreaterThanOrEqual(
            aggregate.changedRecall,
            0.19,
            "Aggregate changed-example recall regressed. Per-log: \(perLogSummaries.joined(separator: " | "))"
        )
        XCTAssertGreaterThanOrEqual(
            aggregate.unchangedAccuracy,
            0.979,
            "Aggregate unchanged-example accuracy regressed. Per-log: \(perLogSummaries.joined(separator: " | "))"
        )
        XCTAssertGreaterThan(
            aggregate.usedThreeWayGateCount,
            500,
            "Expected three-way gate to activate while replaying inspector logs"
        )
    }

    func testBenchmarkEndToEndLookupLatency_usingBundledDBAndReplayTrack() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let track = try parseGPXTrack(url: fixtureURL(named: "replay_track.gpx"))
        XCTAssertFalse(track.isEmpty, "Replay track fixture must contain at least one point")

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var e2eMs: [Double] = []
        var serviceMs: [Double] = []
        var cityMs: [Double] = []
        e2eMs.reserveCapacity(track.count * 20)
        serviceMs.reserveCapacity(track.count * 20)
        cityMs.reserveCapacity(track.count * 20)

        // Warmup pass to stabilize caches and first-open effects.
        for point in track {
            _ = try service.lookupSpeedLimit(lat: point.lat, lon: point.lon, radiusM: 120.0, maxCandidates: 64)
        }

        for _ in 0..<20 {
            for point in track {
                let started = DispatchTime.now().uptimeNanoseconds
                let result = try service.lookupSpeedLimit(
                    lat: point.lat,
                    lon: point.lon,
                    radiusM: 120.0,
                    maxCandidates: 64
                )

                // Include app-facing post-processing payload projection to approximate
                // fix->UI handoff cost, not only pure DB query timing.
                let speedText = result.speedLimitKmh.map(String.init) ?? "nil"
                let wayText = result.wayID ?? "nil"
                let streetText = result.streetName ?? "nil"
                let cityText = result.cityName ?? "nil"
                let insideCityText = result.insideCity.map { $0 ? "1" : "0" } ?? "nil"
                _ = "\(speedText)|\(wayText)|\(streetText)|\(cityText)|\(insideCityText)"

                let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000.0
                e2eMs.append(elapsedMs)
                serviceMs.append(result.queryTimeMs)
                cityMs.append(result.cityResolveMs)
            }
        }

        func percentile(_ values: [Double], _ p: Double) -> Double {
            guard !values.isEmpty else { return 0.0 }
            let sorted = values.sorted()
            let idx = Int((Double(sorted.count - 1) * p).rounded(.toNearestOrEven))
            return sorted[min(max(idx, 0), sorted.count - 1)]
        }

        let e2eMedian = percentile(e2eMs, 0.50)
        let e2eP95 = percentile(e2eMs, 0.95)
        let serviceMedian = percentile(serviceMs, 0.50)
        let serviceP95 = percentile(serviceMs, 0.95)
        let cityMedian = percentile(cityMs, 0.50)
        let cityP95 = percentile(cityMs, 0.95)

        print(
            String(
                format: "APP_E2E_BENCH n=%d e2e_ms_median=%.3f e2e_ms_p95=%.3f service_ms_median=%.3f service_ms_p95=%.3f city_ms_median=%.3f city_ms_p95=%.3f",
                e2eMs.count,
                e2eMedian,
                e2eP95,
                serviceMedian,
                serviceP95,
                cityMedian,
                cityP95
            )
        )

        XCTAssertGreaterThan(e2eMedian, 0.0)
        XCTAssertLessThan(e2eP95, 250.0, "Unexpectedly high p95 end-to-end lookup latency")
    }

    func testBenchmarkBundledFieldReplayTunnelAndMotorwayMetrics() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let logURLs = try allInspectorDriveMatchLogURLs()
        XCTAssertFalse(logURLs.isEmpty, "Expected drive logs in inspector/logs")

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let focusWayID = "313127285"
        var replayedFixCount = 0
        var portalEligibleTunnelFixCount = 0
        var selectedTunnelFixCount = 0
        var motorwayFixCount = 0
        var motorwayLinkFixCount = 0
        var focusReplayCandidateFixCount = 0
        var focusReplaySelectedFixCount = 0
        var focusLoggedCandidateFixCount = 0
        var focusLoggedSelectedFixCount = 0
        var perLogSummaries: [String] = []

        for logURL in logURLs {
            let entries = try loadDriveMatchLogEntries(url: logURL)
            XCTAssertFalse(entries.isEmpty, "Expected non-empty drive log at \(logURL.lastPathComponent)")

            var state = BundledMatchContextState()
            var logReplayedFixCount = 0
            var logPortalEligibleTunnelFixCount = 0
            var logSelectedTunnelFixCount = 0
            var logMotorwayFixCount = 0
            var logMotorwayLinkFixCount = 0
            var logFocusReplayCandidateFixCount = 0
            var logFocusReplaySelectedFixCount = 0
            var logFocusLoggedCandidateFixCount = 0
            var logFocusLoggedSelectedFixCount = 0

            for entry in entries {
                if entry.result?.candidateTraces.contains(where: { $0.wayID == focusWayID }) == true {
                    focusLoggedCandidateFixCount += 1
                    logFocusLoggedCandidateFixCount += 1
                }
                if entry.result?.wayID == focusWayID {
                    focusLoggedSelectedFixCount += 1
                    logFocusLoggedSelectedFixCount += 1
                }
                let result = try service.lookupSpeedLimit(
                    lat: entry.lat,
                    lon: entry.lon,
                    radiusM: 50.0,
                    maxCandidates: 64,
                    matchContext: state.context,
                    headingDeg: entry.courseDeg,
                    headingAccuracyDeg: 10.0,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )

                replayedFixCount += 1
                logReplayedFixCount += 1
                if result.candidateTraces.contains(where: { $0.wayID == focusWayID }) {
                    focusReplayCandidateFixCount += 1
                    logFocusReplayCandidateFixCount += 1
                }
                if result.wayID == focusWayID {
                    focusReplaySelectedFixCount += 1
                    logFocusReplaySelectedFixCount += 1
                }
                if hasPortalEligibleTunnelCandidate(result) {
                    portalEligibleTunnelFixCount += 1
                    logPortalEligibleTunnelFixCount += 1
                }
                if result.isTunnelSegment {
                    selectedTunnelFixCount += 1
                    logSelectedTunnelFixCount += 1
                }
                switch result.highway {
                case "motorway":
                    motorwayFixCount += 1
                    logMotorwayFixCount += 1
                case "motorway_link":
                    motorwayLinkFixCount += 1
                    logMotorwayLinkFixCount += 1
                default:
                    break
                }

                state.record(
                    result,
                    lat: entry.lat,
                    lon: entry.lon,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )
            }

            perLogSummaries.append(
                "\(logURL.lastPathComponent)"
                    + " replayed=\(logReplayedFixCount)"
                    + " portalTunnel=\(logPortalEligibleTunnelFixCount)"
                    + " selectedTunnel=\(logSelectedTunnelFixCount)"
                    + " motorway=\(logMotorwayFixCount)"
                    + " motorwayLink=\(logMotorwayLinkFixCount)"
                    + " focusReplayCand=\(logFocusReplayCandidateFixCount)"
                    + " focusReplaySel=\(logFocusReplaySelectedFixCount)"
                    + " focusLoggedCand=\(logFocusLoggedCandidateFixCount)"
                    + " focusLoggedSel=\(logFocusLoggedSelectedFixCount)"
            )
        }

        print(
            "FIELD_REPLAY corridor replayed=\(replayedFixCount)"
                + " portal_tunnel=\(portalEligibleTunnelFixCount)"
                + " selected_tunnel=\(selectedTunnelFixCount)"
                + " motorway=\(motorwayFixCount)"
                + " motorway_link=\(motorwayLinkFixCount)"
        )
        print(
            "FIELD_REPLAY_WAY \(focusWayID)"
                + " replay_candidate=\(focusReplayCandidateFixCount)"
                + " replay_selected=\(focusReplaySelectedFixCount)"
                + " logged_candidate=\(focusLoggedCandidateFixCount)"
                + " logged_selected=\(focusLoggedSelectedFixCount)"
        )
        print("FIELD_REPLAY_LOGS \(perLogSummaries.joined(separator: " | "))")

        XCTAssertGreaterThan(replayedFixCount, 0)
    }

    func testBenchmarkGeomDriveLogsReplayDiagnostics() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let logURLs = try geomInspectorDriveMatchLogURLs()
        XCTAssertFalse(logURLs.isEmpty, "Expected geom drive logs in inspector/logs/geom")

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var aggregate = DriveLogReplayMetrics()
        var aggregateLoggedComparable = 0
        var aggregateLoggedAgreement = 0
        var aggregateReplayTunnelFixCount = 0
        var aggregateLoggedTunnelFixCount = 0
        var aggregateReplayPortalEligibleTunnelFixCount = 0
        var aggregateLoggedPortalEligibleTunnelFixCount = 0
        var aggregateReplayWayOscillationCount = 0
        var aggregateLoggedWayOscillationCount = 0
        var aggregateReplaySameRefOscillationCount = 0
        var aggregateLoggedSameRefOscillationCount = 0
        var perLogSummaries: [String] = []

        for logURL in logURLs {
            let entries = try loadDriveMatchLogEntries(url: logURL)
                .sorted {
                    if $0.fixID != $1.fixID {
                        return $0.fixID < $1.fixID
                    }
                    return $0.timestampUTC < $1.timestampUTC
                }
            XCTAssertFalse(entries.isEmpty, "Expected non-empty geom drive log at \(logURL.lastPathComponent)")

            var state = BundledMatchContextState()
            var logMetrics = DriveLogReplayMetrics()
            var loggedWayIDs: [String?] = []
            var replayWayIDs: [String?] = []
            var loggedRefs: [String?] = []
            var replayRefs: [String?] = []
            var logLoggedComparable = 0
            var logLoggedAgreement = 0
            var logReplayTunnelFixCount = 0
            var logLoggedTunnelFixCount = 0
            var logReplayPortalEligibleTunnelFixCount = 0
            var logLoggedPortalEligibleTunnelFixCount = 0
            var mismatchSamples: [String] = []
            var tunnelFailureRanges: [String] = []
            var replayTunnelSamples: [String] = []
            var currentTunnelFailureStartFixID: Int?
            var currentTunnelFailureLength = 0
            var currentTunnelFailureRecovered = false

            func finishTunnelFailureRangeIfNeeded(endFixID: Int) {
                if let startFixID = currentTunnelFailureStartFixID,
                   currentTunnelFailureLength >= 3,
                   !currentTunnelFailureRecovered,
                   tunnelFailureRanges.count < 4 {
                    tunnelFailureRanges.append("\(startFixID)-\(endFixID)")
                }
                currentTunnelFailureStartFixID = nil
                currentTunnelFailureLength = 0
                currentTunnelFailureRecovered = false
            }

            for (index, entry) in entries.enumerated() {
                let result = try service.lookupSpeedLimit(
                    lat: entry.lat,
                    lon: entry.lon,
                    radiusM: 50.0,
                    maxCandidates: 64,
                    matchContext: state.context,
                    headingDeg: entry.courseDeg,
                    headingAccuracyDeg: 10.0,
                    speedKmh: entry.speedKmh,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )

                logMetrics.replayedFixCount += 1
                if result.selectionTrace.contains(where: { $0.step == "three_way_gate" }) {
                    logMetrics.usedThreeWayGateCount += 1
                }
                if let pseudoLabelWayID = hindsightPseudoLabelWayID(
                    in: entries,
                    at: index,
                    futureWindow: 5,
                    minFutureRunLength: 5,
                    minAgreementRatio: 0.8
                ) {
                    let predictedMatches = result.wayID == pseudoLabelWayID
                    let isChangedExample = entry.result?.wayID != pseudoLabelWayID
                    logMetrics.pseudoLabelExampleCount += 1
                    logMetrics.correctPseudoLabelCount += predictedMatches ? 1 : 0
                    if isChangedExample {
                        logMetrics.changedExampleCount += 1
                        logMetrics.changedCorrectCount += predictedMatches ? 1 : 0
                    } else {
                        logMetrics.unchangedExampleCount += 1
                        logMetrics.unchangedCorrectCount += predictedMatches ? 1 : 0
                    }
                }

                let loggedWayID = entry.result?.wayID
                loggedWayIDs.append(loggedWayID)
                replayWayIDs.append(result.wayID)
                loggedRefs.append(entry.result?.streetRef)
                replayRefs.append(result.streetRef)

                if let loggedWayID {
                    logLoggedComparable += 1
                    if loggedWayID == result.wayID {
                        logLoggedAgreement += 1
                    } else if mismatchSamples.count < 6 {
                        mismatchSamples.append(
                            "fix \(entry.fixID) \(loggedWayID)->\(result.wayID ?? "nil") ref \(entry.result?.streetRef ?? "-")->\(result.streetRef ?? "-")"
                        )
                    }
                }

                if entry.result?.isTunnelSegment == true {
                    logLoggedTunnelFixCount += 1
                }
                if hasPortalEligibleTunnelCandidate(entry.result) {
                    logLoggedPortalEligibleTunnelFixCount += 1
                }
                if hasPortalEligibleTunnelCandidate(result) {
                    logReplayPortalEligibleTunnelFixCount += 1
                    if currentTunnelFailureStartFixID == nil {
                        currentTunnelFailureStartFixID = entry.fixID
                    }
                    currentTunnelFailureLength += 1
                } else {
                    finishTunnelFailureRangeIfNeeded(endFixID: entries[max(index - 1, 0)].fixID)
                }
                if result.isTunnelSegment {
                    logReplayTunnelFixCount += 1
                    currentTunnelFailureRecovered = true
                    if replayTunnelSamples.count < 6 {
                        replayTunnelSamples.append(
                            "fix \(entry.fixID) way \(result.wayID ?? "nil") logged=\(entry.result?.wayID ?? "nil") portal=\(hasPortalEligibleTunnelCandidate(result))"
                        )
                    }
                }

                state.record(
                    result,
                    lat: entry.lat,
                    lon: entry.lon,
                    horizontalAccuracyM: entry.horizontalAccM,
                    gpsSignalBars: entry.gpsSignalBars
                )
            }
            if let lastFixID = entries.last?.fixID {
                finishTunnelFailureRangeIfNeeded(endFixID: lastFixID)
            }

            let replayWayOscillationCount = countABAOscillations(replayWayIDs)
            let loggedWayOscillationCount = countABAOscillations(loggedWayIDs)
            let replaySameRefOscillationCount = countSameRefABAOscillations(
                wayIDs: replayWayIDs,
                refs: replayRefs
            )
            let loggedSameRefOscillationCount = countSameRefABAOscillations(
                wayIDs: loggedWayIDs,
                refs: loggedRefs
            )
            let loggedAgreementRatio = logLoggedComparable > 0
                ? Double(logLoggedAgreement) / Double(logLoggedComparable)
                : 0.0

            aggregate.formUnion(logMetrics)
            aggregateLoggedComparable += logLoggedComparable
            aggregateLoggedAgreement += logLoggedAgreement
            aggregateReplayTunnelFixCount += logReplayTunnelFixCount
            aggregateLoggedTunnelFixCount += logLoggedTunnelFixCount
            aggregateReplayPortalEligibleTunnelFixCount += logReplayPortalEligibleTunnelFixCount
            aggregateLoggedPortalEligibleTunnelFixCount += logLoggedPortalEligibleTunnelFixCount
            aggregateReplayWayOscillationCount += replayWayOscillationCount
            aggregateLoggedWayOscillationCount += loggedWayOscillationCount
            aggregateReplaySameRefOscillationCount += replaySameRefOscillationCount
            aggregateLoggedSameRefOscillationCount += loggedSameRefOscillationCount

            perLogSummaries.append(
                "\(logURL.lastPathComponent)"
                    + " fixes=\(entries.count)"
                    + " logAgree=\(String(format: "%.4f", loggedAgreementRatio))"
                    + " hindsight=\(String(format: "%.4f", logMetrics.accuracy))"
                    + " changedRecall=\(String(format: "%.4f", logMetrics.changedRecall))"
                    + " unchangedAcc=\(String(format: "%.4f", logMetrics.unchangedAccuracy))"
                    + " replayPortalTunnel=\(logReplayPortalEligibleTunnelFixCount)"
                    + " loggedPortalTunnel=\(logLoggedPortalEligibleTunnelFixCount)"
                    + " replayTunnel=\(logReplayTunnelFixCount)"
                    + " loggedTunnel=\(logLoggedTunnelFixCount)"
                    + " wayABA=\(replayWayOscillationCount)/\(loggedWayOscillationCount)"
                    + " sameRefABA=\(replaySameRefOscillationCount)/\(loggedSameRefOscillationCount)"
                    + " tunnelMiss=\(tunnelFailureRanges.isEmpty ? "none" : tunnelFailureRanges.joined(separator: ","))"
                    + " replayTunnelFixes=\(replayTunnelSamples.isEmpty ? "none" : replayTunnelSamples.joined(separator: "; "))"
                    + " mismatches=\(mismatchSamples.isEmpty ? "none" : mismatchSamples.joined(separator: "; "))"
            )
        }

        let aggregateLoggedAgreementRatio = aggregateLoggedComparable > 0
            ? Double(aggregateLoggedAgreement) / Double(aggregateLoggedComparable)
            : 0.0
        print(
            "GEOM_REPLAY aggregate fixes=\(aggregate.replayedFixCount)"
                + " logAgree=\(String(format: "%.4f", aggregateLoggedAgreementRatio))"
                + " hindsight=\(String(format: "%.4f", aggregate.accuracy))"
                + " changedRecall=\(String(format: "%.4f", aggregate.changedRecall))"
                + " unchangedAcc=\(String(format: "%.4f", aggregate.unchangedAccuracy))"
                + " replayPortalTunnel=\(aggregateReplayPortalEligibleTunnelFixCount)"
                + " loggedPortalTunnel=\(aggregateLoggedPortalEligibleTunnelFixCount)"
                + " replayTunnel=\(aggregateReplayTunnelFixCount)"
                + " loggedTunnel=\(aggregateLoggedTunnelFixCount)"
                + " wayABA=\(aggregateReplayWayOscillationCount)/\(aggregateLoggedWayOscillationCount)"
                + " sameRefABA=\(aggregateReplaySameRefOscillationCount)/\(aggregateLoggedSameRefOscillationCount)"
        )
        print("GEOM_REPLAY_LOGS \(perLogSummaries.joined(separator: " | "))")

        XCTAssertGreaterThan(aggregate.replayedFixCount, 0)
    }

    func testBenchmarkWalkingSpeedReplayDiagnostics() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let logURL = try privateDriveMatchLogURL(environmentKey: "YOUSPEED_TEST_WALKING_LOG")
        let entries = try loadDriveMatchLogEntries(url: logURL)
            .sorted {
                if $0.fixID != $1.fixID {
                    return $0.fixID < $1.fixID
                }
                return $0.timestampUTC < $1.timestampUTC
            }
        XCTAssertFalse(entries.isEmpty, "Expected non-empty walking drive log at \(logURL.lastPathComponent)")

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let lowSpeedThresholdKmh = 8.0
        var state = BundledMatchContextState()
        var logComparable = 0
        var logAgreement = 0
        var lowSpeedFixCount = 0
        var loggedStickyCount = 0
        var replayStickyCount = 0
        var loggedStrongStickyCount = 0
        var replayStrongStickyCount = 0
        var loggedContinuityCounter: [String: Int] = [:]
        var replayContinuityCounter: [String: Int] = [:]
        var samples: [String] = []

        func nearestTrace(in traces: [MatchCandidateTrace]) -> MatchCandidateTrace? {
            traces.min {
                if $0.distanceM != $1.distanceM {
                    return $0.distanceM < $1.distanceM
                }
                let lhsGeometry = $0.geometryScore ?? .infinity
                let rhsGeometry = $1.geometryScore ?? .infinity
                if lhsGeometry != rhsGeometry {
                    return lhsGeometry < rhsGeometry
                }
                return ($0.wayID ?? "") < ($1.wayID ?? "")
            }
        }

        func continuityName(for trace: MatchCandidateTrace?) -> String {
            trace?.continuityClass ?? "none"
        }

        func recordStickyEvent(
            label: String,
            speedKmh: Double,
            entry: DriveMatchLogEntry,
            selected: MatchCandidateTrace?,
            best: MatchCandidateTrace?,
            counter: inout [String: Int],
            stickyCount: inout Int,
            strongStickyCount: inout Int
        ) {
            guard let selected, let best, selected.wayID != best.wayID else {
                return
            }
            guard continuityName(for: selected) != "none" else {
                return
            }
            stickyCount += 1
            counter[continuityName(for: selected), default: 0] += 1
            let selectedDistance = selected.distanceM
            let bestDistance = best.distanceM
            if selectedDistance >= bestDistance + 10.0 {
                strongStickyCount += 1
            }
            if samples.count < 8 {
                let speedText = String(format: "%.2f", speedKmh)
                let selectedDistanceText = String(format: "%.2f", selectedDistance)
                let bestDistanceText = String(format: "%.2f", bestDistance)
                let selectedScoreText = String(format: "%.2f", selected.geometryScore ?? selected.distanceM)
                let bestScoreText = String(format: "%.2f", best.geometryScore ?? best.distanceM)
                let sample =
                    "\(label) fix \(entry.fixID)"
                    + " speed=\(speedText)"
                    + " selected=\(selected.wayID ?? "nil")/\(continuityName(for: selected))"
                    + " dist=\(selectedDistanceText)"
                    + " raw=\(selectedScoreText)"
                    + " best=\(best.wayID ?? "nil")/\(continuityName(for: best))"
                    + " bestDist=\(bestDistanceText)"
                    + " bestRaw=\(bestScoreText)"
                    + " logged=\(entry.result?.wayID ?? "nil")"
                samples.append(sample)
            }
        }

        for entry in entries {
            let result = try service.lookupSpeedLimit(
                lat: entry.lat,
                lon: entry.lon,
                radiusM: 50.0,
                maxCandidates: 64,
                matchContext: state.context,
                headingDeg: entry.courseDeg,
                headingAccuracyDeg: 10.0,
                speedKmh: entry.speedKmh,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )

            if let loggedWayID = entry.result?.wayID {
                logComparable += 1
                if loggedWayID == result.wayID {
                    logAgreement += 1
                }
            }

            if entry.speedKmh <= lowSpeedThresholdKmh {
                lowSpeedFixCount += 1
                let loggedSelected = entry.result?.candidateTraces.first(where: { $0.isSelected })
                let loggedBest = nearestTrace(in: entry.result?.candidateTraces ?? [])
                recordStickyEvent(
                    label: "logged",
                    speedKmh: entry.speedKmh,
                    entry: entry,
                    selected: loggedSelected,
                    best: loggedBest,
                    counter: &loggedContinuityCounter,
                    stickyCount: &loggedStickyCount,
                    strongStickyCount: &loggedStrongStickyCount
                )

                let replaySelected = result.candidateTraces.first(where: { $0.isSelected })
                let replayBest = nearestTrace(in: result.candidateTraces)
                recordStickyEvent(
                    label: "replay",
                    speedKmh: entry.speedKmh,
                    entry: entry,
                    selected: replaySelected,
                    best: replayBest,
                    counter: &replayContinuityCounter,
                    stickyCount: &replayStickyCount,
                    strongStickyCount: &replayStrongStickyCount
                )
            }

            state.record(
                result,
                lat: entry.lat,
                lon: entry.lon,
                horizontalAccuracyM: entry.horizontalAccM,
                gpsSignalBars: entry.gpsSignalBars
            )
        }

        let logAgreementRatio = logComparable > 0 ? Double(logAgreement) / Double(logComparable) : 0.0
        func formatCounter(_ counter: [String: Int]) -> String {
            counter.keys.sorted().map { "\($0)=\(counter[$0] ?? 0)" }.joined(separator: ",")
        }

        print(
            "WALKING_REPLAY"
                + " fixes=\(entries.count)"
                + " low_speed_fixes=\(lowSpeedFixCount)"
                + " logAgree=\(String(format: "%.4f", logAgreementRatio))"
                + " loggedSticky=\(loggedStickyCount)"
                + " replaySticky=\(replayStickyCount)"
                + " loggedStrongSticky=\(loggedStrongStickyCount)"
                + " replayStrongSticky=\(replayStrongStickyCount)"
                + " loggedContinuity=\(formatCounter(loggedContinuityCounter))"
                + " replayContinuity=\(formatCounter(replayContinuityCounter))"
        )
        print("WALKING_REPLAY_SAMPLES \(samples.isEmpty ? "none" : samples.joined(separator: " | "))")

        XCTAssertGreaterThan(entries.count, 0)
    }

    func testBenchmarkMatchingProfiles_commonScoreComparison() throws {
        let env = ProcessInfo.processInfo.environment
        let fileManager = FileManager.default
        let baselinePath = env["SPEEDCONSUMER_BASELINE_DB_PATH"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        let corridorPath = env["SPEEDCONSUMER_CORRIDOR_DB_PATH"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallbackBaselinePath = "/tmp/karlsruhe-regbez-baseline.sqlite"
        let fallbackCorridorPath = "/tmp/karlsruhe-regbez-corridor.sqlite"
        let resolvedBaselinePath: String?
        if let baselinePath, !baselinePath.isEmpty {
            resolvedBaselinePath = baselinePath
        } else if fileManager.fileExists(atPath: fallbackBaselinePath) {
            resolvedBaselinePath = fallbackBaselinePath
        } else {
            resolvedBaselinePath = nil
        }
        let resolvedCorridorPath: String?
        if let corridorPath, !corridorPath.isEmpty {
            resolvedCorridorPath = corridorPath
        } else if fileManager.fileExists(atPath: fallbackCorridorPath) {
            resolvedCorridorPath = fallbackCorridorPath
        } else {
            resolvedCorridorPath = nil
        }
        guard let resolvedBaselinePath, let resolvedCorridorPath else {
            throw XCTSkip("Build /tmp/karlsruhe-regbez-baseline.sqlite and /tmp/karlsruhe-regbez-corridor.sqlite first")
        }

        let baselineURL = URL(fileURLWithPath: resolvedBaselinePath)
        let corridorURL = URL(fileURLWithPath: resolvedCorridorPath)
        let logURLs = try allInspectorDriveMatchLogURLs()
        let geomLogURLs = try geomInspectorDriveMatchLogURLs()
        let track = try parseGPXTrack(url: fixtureURL(named: "replay_track.gpx"))
        let focusWayID = "313127285"

        func percentile(_ values: [Double], _ p: Double) -> Double {
            guard !values.isEmpty else { return 0.0 }
            let sorted = values.sorted()
            let idx = Int((Double(sorted.count - 1) * p).rounded(.toNearestOrEven))
            return sorted[min(max(idx, 0), sorted.count - 1)]
        }

        func profileBundleBytes(_ url: URL) throws -> UInt64 {
            let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
            return (attributes[.size] as? NSNumber)?.uint64Value ?? 0
        }

        struct ReplayExampleOutcome {
            let isChangedExample: Bool
            let predictedMatches: Bool
        }

        struct AggregateReplaySummary {
            let metrics: DriveLogReplayMetrics
            let focusReplayCandidate: Int
            let focusReplaySelected: Int
            let focusReplayCandidateOutsideLog3: Int
            let focusReplaySelectedOutsideLog3: Int
            let selectedTunnel: Int
            let outcomes: [String: ReplayExampleOutcome]
        }

        func runAggregateReplay(service: V3SpeedLimitService) throws -> AggregateReplaySummary {
            var aggregate = DriveLogReplayMetrics()
            var focusReplayCandidate = 0
            var focusReplaySelected = 0
            var focusReplayCandidateOutsideLog3 = 0
            var focusReplaySelectedOutsideLog3 = 0
            var selectedTunnel = 0
            var outcomes: [String: ReplayExampleOutcome] = [:]

            for logURL in logURLs {
                let entries = try loadDriveMatchLogEntries(url: logURL)
                var state = BundledMatchContextState()
                let isOtherLog = !logURL.lastPathComponent.contains("drive_match_log-3")
                for (index, entry) in entries.enumerated() {
                    let result = try service.lookupSpeedLimit(
                        lat: entry.lat,
                        lon: entry.lon,
                        radiusM: 50.0,
                        maxCandidates: 64,
                        matchContext: state.context,
                        headingDeg: entry.courseDeg,
                        headingAccuracyDeg: 10.0,
                        speedKmh: entry.speedKmh,
                        horizontalAccuracyM: entry.horizontalAccM,
                        gpsSignalBars: entry.gpsSignalBars
                    )

                    aggregate.replayedFixCount += 1
                    if result.selectionTrace.contains(where: { $0.step == "three_way_gate" }) {
                        aggregate.usedThreeWayGateCount += 1
                    }
                    if result.selectionTrace.contains(where: { $0.step == "same_ref_bounce_gate" }) {
                        aggregate.usedSameRefBounceGateCount += 1
                    }
                    if result.selectionTrace.contains(where: { $0.step == "anti_aba_hysteresis" }) {
                        aggregate.usedAntiABAHysteresisCount += 1
                    }
                    if let pseudoLabelWayID = hindsightPseudoLabelWayID(
                        in: entries,
                        at: index,
                        futureWindow: 5,
                        minFutureRunLength: 5,
                        minAgreementRatio: 0.8
                    ) {
                        let selectedWayID = entry.result?.wayID
                        let predictedMatches = result.wayID == pseudoLabelWayID
                        let isChangedExample = selectedWayID != pseudoLabelWayID
                        aggregate.pseudoLabelExampleCount += 1
                        aggregate.correctPseudoLabelCount += predictedMatches ? 1 : 0
                        if isChangedExample {
                            aggregate.changedExampleCount += 1
                            aggregate.changedCorrectCount += predictedMatches ? 1 : 0
                        } else {
                            aggregate.unchangedExampleCount += 1
                            aggregate.unchangedCorrectCount += predictedMatches ? 1 : 0
                        }
                        outcomes["\(logURL.lastPathComponent)#\(entry.fixID)"] = ReplayExampleOutcome(
                            isChangedExample: isChangedExample,
                            predictedMatches: predictedMatches
                        )
                    }

                    if result.candidateTraces.contains(where: { $0.wayID == focusWayID }) {
                        focusReplayCandidate += 1
                        if isOtherLog {
                            focusReplayCandidateOutsideLog3 += 1
                        }
                    }
                    if result.wayID == focusWayID {
                        focusReplaySelected += 1
                        if isOtherLog {
                            focusReplaySelectedOutsideLog3 += 1
                        }
                    }
                    if result.isTunnelSegment {
                        selectedTunnel += 1
                    }

                    state.record(
                        result,
                        lat: entry.lat,
                        lon: entry.lon,
                        horizontalAccuracyM: entry.horizontalAccM,
                        gpsSignalBars: entry.gpsSignalBars
                    )
                }
            }

            return AggregateReplaySummary(
                metrics: aggregate,
                focusReplayCandidate: focusReplayCandidate,
                focusReplaySelected: focusReplaySelected,
                focusReplayCandidateOutsideLog3: focusReplayCandidateOutsideLog3,
                focusReplaySelectedOutsideLog3: focusReplaySelectedOutsideLog3,
                selectedTunnel: selectedTunnel,
                outcomes: outcomes
            )
        }

        func runGeomReplay(service: V3SpeedLimitService) throws -> (logAgreement: Double, replayTunnel: Int, replayWayABA: Int, replaySameRefABA: Int) {
            var comparable = 0
            var agreement = 0
            var replayTunnel = 0
            var replayWayIDs: [String?] = []
            var replayRefs: [String?] = []

            for logURL in geomLogURLs {
                let entries = try loadDriveMatchLogEntries(url: logURL)
                    .sorted {
                        if $0.fixID != $1.fixID {
                            return $0.fixID < $1.fixID
                        }
                        return $0.timestampUTC < $1.timestampUTC
                    }
                var state = BundledMatchContextState()
                var logWayIDs: [String?] = []
                var logRefs: [String?] = []
                var replayLogWayIDs: [String?] = []
                var replayLogRefs: [String?] = []
                for entry in entries {
                    let result = try service.lookupSpeedLimit(
                        lat: entry.lat,
                        lon: entry.lon,
                        radiusM: 50.0,
                        maxCandidates: 64,
                        matchContext: state.context,
                        headingDeg: entry.courseDeg,
                        headingAccuracyDeg: 10.0,
                        speedKmh: entry.speedKmh,
                        horizontalAccuracyM: entry.horizontalAccM,
                        gpsSignalBars: entry.gpsSignalBars
                    )
                    if let loggedWayID = entry.result?.wayID {
                        comparable += 1
                        agreement += loggedWayID == result.wayID ? 1 : 0
                    }
                    if result.isTunnelSegment {
                        replayTunnel += 1
                    }
                    logWayIDs.append(entry.result?.wayID)
                    logRefs.append(entry.result?.streetRef)
                    replayLogWayIDs.append(result.wayID)
                    replayLogRefs.append(result.streetRef)
                    state.record(
                        result,
                        lat: entry.lat,
                        lon: entry.lon,
                        horizontalAccuracyM: entry.horizontalAccM,
                        gpsSignalBars: entry.gpsSignalBars
                    )
                }
                replayWayIDs.append(contentsOf: replayLogWayIDs)
                replayRefs.append(contentsOf: replayLogRefs)
                _ = countABAOscillations(logWayIDs)
                _ = countSameRefABAOscillations(wayIDs: logWayIDs, refs: logRefs)
            }

            return (
                logAgreement: comparable > 0 ? Double(agreement) / Double(comparable) : 0.0,
                replayTunnel: replayTunnel,
                replayWayABA: countABAOscillations(replayWayIDs),
                replaySameRefABA: countSameRefABAOscillations(wayIDs: replayWayIDs, refs: replayRefs)
            )
        }

        func runLatency(service: V3SpeedLimitService) throws -> (e2eMedian: Double, serviceP95: Double) {
            var e2eMs: [Double] = []
            var serviceMs: [Double] = []
            for point in track {
                _ = try service.lookupSpeedLimit(lat: point.lat, lon: point.lon, radiusM: 120.0, maxCandidates: 64)
            }
            for _ in 0..<10 {
                for point in track {
                    let started = DispatchTime.now().uptimeNanoseconds
                    let result = try service.lookupSpeedLimit(lat: point.lat, lon: point.lon, radiusM: 120.0, maxCandidates: 64)
                    _ = "\(result.speedLimitKmh.map(String.init) ?? "nil")|\(result.wayID ?? "nil")"
                    e2eMs.append(Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000.0)
                    serviceMs.append(result.queryTimeMs)
                }
            }
            return (
                e2eMedian: percentile(e2eMs, 0.50),
                serviceP95: percentile(serviceMs, 0.95)
            )
        }

        struct ProfileSummary {
            let label: String
            let bytes: UInt64
            let replay: DriveLogReplayMetrics
            let geomLogAgreement: Double
            let geomReplayTunnel: Int
            let geomWayABA: Int
            let geomSameRefABA: Int
            let latencyE2EMedian: Double
            let latencyServiceP95: Double
            let focusReplayCandidate: Int
            let focusReplaySelected: Int
            let focusReplayCandidateOutsideLog3: Int
            let focusReplaySelectedOutsideLog3: Int
            let selectedTunnel: Int
            let replayOutcomes: [String: ReplayExampleOutcome]

            var accuracyComposite: Double {
                (0.50 * replay.accuracy) + (0.25 * replay.changedRecall) + (0.25 * replay.unchangedAccuracy)
            }
        }

        struct ProfileDeltaSummary {
            let label: String
            let correctedExamples: Int
            let regressedExamples: Int
            let netCorrections: Int
            let correctedChangedExamples: Int
            let regressedChangedExamples: Int
            let netChangedCorrections: Int
            let correctedUnchangedExamples: Int
            let regressedUnchangedExamples: Int
            let netUnchangedCorrections: Int
            let geomWayABADelta: Int
            let geomSameRefABADelta: Int
            let accuracyDelta: Double
            let changedRecallDelta: Double
            let unchangedAccuracyDelta: Double
            let commonScoreDelta: Double
        }

        func summarize(label: String, dbURL: URL, model: V3SpeedLimitService.MatchingModel) throws -> ProfileSummary {
            let service = V3SpeedLimitService(dbPath: dbURL.path, matchingModel: model)
            let replay = try runAggregateReplay(service: service)
            let geom = try runGeomReplay(service: service)
            let latency = try runLatency(service: service)
            return ProfileSummary(
                label: label,
                bytes: try profileBundleBytes(dbURL),
                replay: replay.metrics,
                geomLogAgreement: geom.logAgreement,
                geomReplayTunnel: geom.replayTunnel,
                geomWayABA: geom.replayWayABA,
                geomSameRefABA: geom.replaySameRefABA,
                latencyE2EMedian: latency.e2eMedian,
                latencyServiceP95: latency.serviceP95,
                focusReplayCandidate: replay.focusReplayCandidate,
                focusReplaySelected: replay.focusReplaySelected,
                focusReplayCandidateOutsideLog3: replay.focusReplayCandidateOutsideLog3,
                focusReplaySelectedOutsideLog3: replay.focusReplaySelectedOutsideLog3,
                selectedTunnel: replay.selectedTunnel,
                replayOutcomes: replay.outcomes
            )
        }

        func commonScore(for profile: ProfileSummary, bestLatencyP95: Double, minBytes: UInt64) -> Double {
            let latencyScore = bestLatencyP95 > 0 ? bestLatencyP95 / profile.latencyServiceP95 : 0.0
            let sizeScore = profile.bytes > 0 ? Double(minBytes) / Double(profile.bytes) : 0.0
            return 100.0 * (
                (0.70 * profile.accuracyComposite) +
                (0.20 * latencyScore) +
                (0.10 * sizeScore)
            )
        }

        func deltaSummary(
            from base: ProfileSummary,
            to candidate: ProfileSummary,
            bestLatencyP95: Double,
            minBytes: UInt64
        ) -> ProfileDeltaSummary {
            var correctedExamples = 0
            var regressedExamples = 0
            var correctedChangedExamples = 0
            var regressedChangedExamples = 0
            var correctedUnchangedExamples = 0
            var regressedUnchangedExamples = 0

            for key in base.replayOutcomes.keys.sorted() {
                guard let baseOutcome = base.replayOutcomes[key],
                      let candidateOutcome = candidate.replayOutcomes[key] else {
                    continue
                }
                if !baseOutcome.predictedMatches && candidateOutcome.predictedMatches {
                    correctedExamples += 1
                    if baseOutcome.isChangedExample {
                        correctedChangedExamples += 1
                    } else {
                        correctedUnchangedExamples += 1
                    }
                } else if baseOutcome.predictedMatches && !candidateOutcome.predictedMatches {
                    regressedExamples += 1
                    if baseOutcome.isChangedExample {
                        regressedChangedExamples += 1
                    } else {
                        regressedUnchangedExamples += 1
                    }
                }
            }

            return ProfileDeltaSummary(
                label: candidate.label,
                correctedExamples: correctedExamples,
                regressedExamples: regressedExamples,
                netCorrections: correctedExamples - regressedExamples,
                correctedChangedExamples: correctedChangedExamples,
                regressedChangedExamples: regressedChangedExamples,
                netChangedCorrections: correctedChangedExamples - regressedChangedExamples,
                correctedUnchangedExamples: correctedUnchangedExamples,
                regressedUnchangedExamples: regressedUnchangedExamples,
                netUnchangedCorrections: correctedUnchangedExamples - regressedUnchangedExamples,
                geomWayABADelta: candidate.geomWayABA - base.geomWayABA,
                geomSameRefABADelta: candidate.geomSameRefABA - base.geomSameRefABA,
                accuracyDelta: candidate.replay.accuracy - base.replay.accuracy,
                changedRecallDelta: candidate.replay.changedRecall - base.replay.changedRecall,
                unchangedAccuracyDelta: candidate.replay.unchangedAccuracy - base.replay.unchangedAccuracy,
                commonScoreDelta: commonScore(for: candidate, bestLatencyP95: bestLatencyP95, minBytes: minBytes) -
                    commonScore(for: base, bestLatencyP95: bestLatencyP95, minBytes: minBytes)
            )
        }

        let baseline = try summarize(label: "baseline", dbURL: baselineURL, model: .connectedBaseline)
        let simpleSpeedRef = try summarize(label: "simple_speed_ref", dbURL: baselineURL, model: .simpleSpeedRefHeuristic)
        let simpleSpeedRefConnected = try summarize(
            label: "simple_speed_ref_connected",
            dbURL: baselineURL,
            model: .simpleSpeedRefConnectedHeuristic
        )
        let corridorRawMiniHMM = try summarize(label: "corridor_raw_mini_hmm", dbURL: corridorURL, model: .corridorHMMRawMiniHMM)
        let corridorNoThreeWay = try summarize(label: "corridor_no_three_way", dbURL: corridorURL, model: .corridorHMMNoThreeWayGate)
        let corridorNoSameRefBounce = try summarize(label: "corridor_no_same_ref_bounce", dbURL: corridorURL, model: .corridorHMMNoSameRefBounceGate)
        let corridorAntiABA = try summarize(label: "corridor_anti_aba", dbURL: corridorURL, model: .corridorHMMAntiABAHysteresis)
        let corridor = try summarize(label: "corridor", dbURL: corridorURL, model: .corridorHMM)
        let profiles = [
            baseline,
            simpleSpeedRef,
            simpleSpeedRefConnected,
            corridorRawMiniHMM,
            corridorNoThreeWay,
            corridorNoSameRefBounce,
            corridorAntiABA,
            corridor,
        ]
        let bestLatencyP95 = profiles.map(\.latencyServiceP95).min() ?? 1.0
        let minBytes = profiles.map(\.bytes).min() ?? 1
        let corridorReplayKeys = Set(corridor.replayOutcomes.keys)

        for profile in profiles {
            XCTAssertEqual(Set(profile.replayOutcomes.keys), corridorReplayKeys)
            let commonScore = commonScore(for: profile, bestLatencyP95: bestLatencyP95, minBytes: minBytes)
            print(
                "MODEL_PROFILE \(profile.label)"
                    + " bytes=\(profile.bytes)"
                    + " acc=\(String(format: "%.4f", profile.replay.accuracy))"
                    + " changedRecall=\(String(format: "%.4f", profile.replay.changedRecall))"
                    + " unchangedAcc=\(String(format: "%.4f", profile.replay.unchangedAccuracy))"
                    + " accuracyComposite=\(String(format: "%.4f", profile.accuracyComposite))"
                    + " threeWayGate=\(profile.replay.usedThreeWayGateCount)"
                    + " sameRefBounceGate=\(profile.replay.usedSameRefBounceGateCount)"
                    + " antiABAHysteresis=\(profile.replay.usedAntiABAHysteresisCount)"
                    + " geomLogAgree=\(String(format: "%.4f", profile.geomLogAgreement))"
                    + " geomReplayTunnel=\(profile.geomReplayTunnel)"
                    + " geomWayABA=\(profile.geomWayABA)"
                    + " geomSameRefABA=\(profile.geomSameRefABA)"
                    + " e2eMedianMs=\(String(format: "%.3f", profile.latencyE2EMedian))"
                    + " serviceP95Ms=\(String(format: "%.3f", profile.latencyServiceP95))"
                    + " selectedTunnel=\(profile.selectedTunnel)"
                    + " focusCand=\(profile.focusReplayCandidate)"
                    + " focusSel=\(profile.focusReplaySelected)"
                    + " focusCandOtherLogs=\(profile.focusReplayCandidateOutsideLog3)"
                    + " focusSelOtherLogs=\(profile.focusReplaySelectedOutsideLog3)"
                    + " commonScore=\(String(format: "%.2f", commonScore))"
            )
        }

        for candidate in [simpleSpeedRef, simpleSpeedRefConnected, corridorNoThreeWay, corridorNoSameRefBounce, corridorAntiABA] {
            let delta = deltaSummary(
                from: corridor,
                to: candidate,
                bestLatencyP95: bestLatencyP95,
                minBytes: minBytes
            )
            print(
                "PROFILE_DELTA corridor->\(delta.label)"
                    + " corrected=\(delta.correctedExamples)"
                    + " regressed=\(delta.regressedExamples)"
                    + " net=\(delta.netCorrections)"
                    + " correctedChanged=\(delta.correctedChangedExamples)"
                    + " regressedChanged=\(delta.regressedChangedExamples)"
                    + " netChanged=\(delta.netChangedCorrections)"
                    + " correctedUnchanged=\(delta.correctedUnchangedExamples)"
                    + " regressedUnchanged=\(delta.regressedUnchangedExamples)"
                    + " netUnchanged=\(delta.netUnchangedCorrections)"
                    + " geomWayABADelta=\(delta.geomWayABADelta)"
                    + " geomSameRefABADelta=\(delta.geomSameRefABADelta)"
                    + " accDelta=\(String(format: "%.4f", delta.accuracyDelta))"
                    + " changedRecallDelta=\(String(format: "%.4f", delta.changedRecallDelta))"
                    + " unchangedAccDelta=\(String(format: "%.4f", delta.unchangedAccuracyDelta))"
                    + " commonScoreDelta=\(String(format: "%.2f", delta.commonScoreDelta))"
            )
        }

        XCTAssertGreaterThan(baseline.replay.replayedFixCount, 0)
        XCTAssertGreaterThan(corridor.replay.replayedFixCount, 0)
    }

    func testRealReleaseSyncAssembleAndLookup_whenEnabled() async throws {
        let env = ProcessInfo.processInfo.environment
        if env["SPEEDCONSUMER_SKIP_REAL_RELEASE_SYNC"] == "1" {
            throw XCTSkip("SPEEDCONSUMER_SKIP_REAL_RELEASE_SYNC=1")
        }
        let autoTapSyncEnabled = isAutoTapSyncEnabled(env: env)
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
            let manifestURL = embeddedManifestURL()
                ?? URL(string: "https://github.com/volzinnovation/youspeed.de/releases/download/baden-wuerttemberg/baden-wuerttemberg_manifest.json")!
            let sync = try await manager.syncFromManifestURL(manifestURL)
            XCTAssertTrue([BundleSyncResult.Mode.fullDownload, BundleSyncResult.Mode.upToDate].contains(sync.mode))
        }

        guard let dbURL = try await manager.activeDatabaseURL() else {
            XCTFail("Expected active database URL after real release sync")
            return
        }
        guard try await manager.activeState() != nil else {
            XCTFail("Expected active bundle state after real release sync")
            return
        }
        let activatedManifestURL = dbURL
            .deletingLastPathComponent()
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
        #if targetEnvironment(simulator)
        throw XCTSkip("Connected-device only test")
        #else
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled karlsruhe-regbez_speeds.sqlite not found in test host app")
        }

        guard CLLocationManager.locationServicesEnabled() else {
            throw XCTSkip("Location services are disabled on this device")
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
        let location: CLLocation
        switch locationResult {
        case .success(let value):
            location = value
        case .failure(let error):
            if let clError = error as? CLError {
                throw XCTSkip("Location fix unavailable (\(clError.errorCode)): \(clError.localizedDescription)")
            }
            throw error
        }

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
        #endif
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

    func testBundledSchemaIncludesTunnelAndResidentialContextColumns() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        let wayColumns = try readColumnNames(dbURL: bundledDB, table: "ways")
        let requiredWay = Set(["service", "tunnel"])
        let missingWay = requiredWay.subtracting(wayColumns)
        if !missingWay.isEmpty {
            throw XCTSkip("Bundled seed DB was built before context-schema extension; missing ways columns: \(missingWay.sorted())")
        }

        let areaColumns = try readColumnNames(dbURL: bundledDB, table: "areas")
        let requiredArea = Set(["residential", "points_json"])
        let missingArea = requiredArea.subtracting(areaColumns)
        if !missingArea.isEmpty {
            throw XCTSkip("Bundled seed DB was built before context-schema extension; missing areas columns: \(missingArea.sorted())")
        }
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
            preferredWayID: "1001",
            headingDeg: 0.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 40.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(turnedResult.wayID, "1002")
        XCTAssertEqual(turnedResult.speedLimitKmh, 50)
        XCTAssertEqual(turnedResult.service, "main")

        let lowSpeedResult = try service.lookupSpeedLimit(
            lat: 52.0,
            lon: 13.005,
            radiusM: 80.0,
            maxCandidates: 32,
            preferredWayID: "1001",
            headingDeg: 0.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 2.0,
            horizontalAccuracyM: 5.0
        )
        let noHeadingLowSpeedResult = try service.lookupSpeedLimit(
            lat: 52.0,
            lon: 13.005,
            radiusM: 80.0,
            maxCandidates: 32,
            preferredWayID: "1001",
            headingDeg: nil,
            headingAccuracyDeg: nil,
            speedKmh: 2.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(lowSpeedResult.wayID, noHeadingLowSpeedResult.wayID)
        XCTAssertEqual(lowSpeedResult.speedLimitKmh, noHeadingLowSpeedResult.speedLimitKmh)
    }

    func testLookupKeepsStraightContinuationWhenSpeedDropsButHeadingStillMatchesMainline() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-turn-feasibility-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("turn_feasibility_fixture.sqlite")
        try createTurnFeasibilityFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.05006,
            lon: 13.00418,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "11001",
                recentWayIDs: ["11001"],
                preferredStreetRef: nil,
                recentStreetRefs: [],
                recentHypotheses: [
                    WayMatchHypothesis(
                        wayID: "11001",
                        streetRef: nil,
                        highway: "primary",
                        cumulativeCost: 4.0,
                        emissionScore: 4.0,
                        endpointProximityM: 2.0,
                        startLat: 52.05000,
                        startLon: 13.0000,
                        endLat: 52.05000,
                        endLon: 13.0040,
                        isTunnel: false
                    )
                ]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 18.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "11002")
        XCTAssertNotEqual(result.wayID, "11003")
    }

    func testLookupSwitchesToSharpTurnWhenHeadingDivergesTowardConnectedBranch() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-turn-feasibility-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("turn_feasibility_fixture.sqlite")
        try createTurnFeasibilityFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.05006,
            lon: 13.00418,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "11001",
                recentWayIDs: ["11001"],
                preferredStreetRef: nil,
                recentStreetRefs: [],
                recentHypotheses: [
                    WayMatchHypothesis(
                        wayID: "11001",
                        streetRef: nil,
                        highway: "primary",
                        cumulativeCost: 4.0,
                        emissionScore: 4.0,
                        endpointProximityM: 2.0,
                        startLat: 52.05000,
                        startLon: 13.0000,
                        endLat: 52.05000,
                        endLon: 13.0040,
                        isTunnel: false
                    )
                ]
            ),
            headingDeg: 0.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 18.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "11003")
    }

    func testSimpleSameRefMatcherKeepsStraightContinuationWhenLowSpeedHeadingStaysOnMainline() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-low-speed-junction-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("low_speed_junction_fixture.sqlite")
        try createLowSpeedSameRefJunctionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardHeuristic
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.06001,
            lon: 13.00413,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "12001",
                recentWayIDs: ["12001"],
                recentFixes: [
                    WayMatchRecentFix(lat: 52.06000, lon: 13.00400),
                ],
                preferredStreetRef: "B463",
                activeStreetRef: "B463",
                recentStreetRefs: ["B463"]
            ),
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )

        XCTAssertEqual(result.wayID, "12002")
        XCTAssertFalse(
            result.selectionTrace.contains { $0.step == "simple_low_speed_same_ref_junction_release" }
        )
    }

    func testSimpleSameRefMatcherPromotesLinkedTurnBeforeItBecomesNearestAtLowSpeed() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-low-speed-junction-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("low_speed_junction_fixture.sqlite")
        try createLowSpeedSameRefJunctionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardHeuristic
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.06001,
            lon: 13.00413,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "12001",
                recentWayIDs: ["12001"],
                recentFixes: [
                    WayMatchRecentFix(lat: 52.05995, lon: 13.00413),
                ],
                preferredStreetRef: "B463",
                activeStreetRef: "B463",
                recentStreetRefs: ["B463"]
            ),
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )

        XCTAssertEqual(result.wayID, "12003")
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "simple_low_speed_same_ref_junction_release" &&
                    $0.detail.contains("12003")
            }
        )
    }

    func testNodeAwareLowSpeedJunctionMatcherPromotesCurvedTurnUsingSharedNodeDirection() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-low-speed-junction-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("low_speed_junction_fixture.sqlite")
        try createLowSpeedSameRefJunctionFixtureDB(at: dbURL, useCurvedTurn: true)
        let m9 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardHeuristic
        )
        let m10 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardNodeAwareHeuristic
        )

        let context = WayMatchContext(
            preferredWayID: "12001",
            recentWayIDs: ["12001"],
            recentFixes: [
                WayMatchRecentFix(lat: 52.05995, lon: 13.00413),
            ],
            preferredStreetRef: "B463",
            activeStreetRef: "B463",
            recentStreetRefs: ["B463"]
        )

        let m9Result = try m9.lookupSpeedLimit(
            lat: 52.06001,
            lon: 13.00413,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )
        XCTAssertEqual(m9Result.wayID, "12002")
        XCTAssertFalse(
            m9Result.selectionTrace.contains { $0.step == "simple_low_speed_same_ref_junction_release" }
        )

        let m10Result = try m10.lookupSpeedLimit(
            lat: 52.06001,
            lon: 13.00413,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )
        XCTAssertEqual(m10Result.wayID, "12003")
        XCTAssertTrue(
            m10Result.selectionTrace.contains {
                $0.step == "simple_low_speed_same_ref_junction_release" &&
                    $0.detail.contains("12003") &&
                    $0.detail.contains("12001")
            }
        )
    }

    func testNodeAwareLowSpeedJunctionProbeExplainsBlockedPreTurnCandidate() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-low-speed-junction-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("low_speed_junction_fixture.sqlite")
        try createLowSpeedSameRefJunctionFixtureDB(at: dbURL, useCurvedTurn: true)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardNodeAwareHeuristic
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.06000,
            lon: 13.00392,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "12001",
                recentWayIDs: ["12001"],
                preferredStreetRef: "B463",
                activeStreetRef: "B463",
                recentStreetRefs: ["B463"]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )

        XCTAssertEqual(result.wayID, "12001")
        XCTAssertFalse(
            result.selectionTrace.contains { $0.step == "simple_low_speed_same_ref_junction_release" }
        )
        XCTAssertTrue(result.candidateTraces.contains(where: { $0.wayID == "12003" }))
        let probe = try XCTUnwrap(
            result.selectionTrace.first(where: { $0.step == "simple_low_speed_same_ref_probe" })
        )
        XCTAssertTrue(probe.detail.contains("candidate=12003"))
        XCTAssertTrue(probe.detail.contains("blocked="))
        XCTAssertTrue(probe.detail.contains("candidate_geometry_rank="))
        XCTAssertTrue(probe.detail.contains("candidate_trace_rank="))
    }

    func testSequenceParticleMatcherPromotesTurnWithoutWayLinksUsingMotionHeading() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-sequence-particle-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("low_speed_junction_fixture.sqlite")
        try createLowSpeedSameRefJunctionFixtureDB(at: dbURL, useCurvedTurn: true, includeWayLinks: false)
        let m10 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardNodeAwareHeuristic
        )
        let m11 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSequenceParticleHeuristic
        )

        let context = WayMatchContext(
            preferredWayID: "12001",
            preferredHighway: "primary",
            preferredEndpointProximityM: 3.0,
            recentWayIDs: ["12001"],
            recentFixes: [
                WayMatchRecentFix(lat: 52.05995, lon: 13.00413),
            ],
            preferredStreetRef: "B463",
            activeStreetRef: "B463",
            recentStreetRefs: ["B463"]
        )

        let m10Result = try m10.lookupSpeedLimit(
            lat: 52.06001,
            lon: 13.00413,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )
        XCTAssertEqual(m10Result.wayID, "12002")

        let m11Result = try m11.lookupSpeedLimit(
            lat: 52.06001,
            lon: 13.00413,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )
        XCTAssertEqual(m11Result.wayID, "12003")
        XCTAssertTrue(
            m11Result.selectionTrace.contains {
                $0.step == "simple_sequence_particle_switch" &&
                    $0.detail.contains("12003")
            }
        )
        XCTAssertTrue(m11Result.matchHypotheses.contains { $0.wayID == "12003" })
    }

    func testSequenceViterbiMatcherUsesRollingFixWindowWithoutWayLinks() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-sequence-viterbi-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("low_speed_junction_fixture.sqlite")
        try createLowSpeedSameRefJunctionFixtureDB(at: dbURL, useCurvedTurn: true, includeWayLinks: false)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSequenceViterbiHeuristic
        )

        let context = WayMatchContext(
            preferredWayID: "12001",
            preferredHighway: "primary",
            preferredEndpointProximityM: 3.0,
            recentWayIDs: ["12001"],
            recentFixes: [
                WayMatchRecentFix(lat: 52.05996, lon: 13.00407, headingDeg: 38.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05992, lon: 13.00400, headingDeg: 39.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05988, lon: 13.00393, headingDeg: 40.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05984, lon: 13.00386, headingDeg: 41.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05980, lon: 13.00379, headingDeg: 42.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05976, lon: 13.00372, headingDeg: 43.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05972, lon: 13.00365, headingDeg: 44.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05968, lon: 13.00358, headingDeg: 45.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.05964, lon: 13.00351, headingDeg: 46.0, headingAccuracyDeg: 5.0, speedKmh: 23.0, horizontalAccuracyM: 6.0, gpsSignalBars: 4),
            ],
            preferredStreetRef: "B463",
            activeStreetRef: "B463",
            recentStreetRefs: ["B463"]
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.06006,
            lon: 13.00412,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: context,
            headingDeg: 46.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 23.0,
            horizontalAccuracyM: 6.0
        )

        let debugSummary = (
            result.selectionTrace.map { "\($0.step)=\($0.detail)" } +
                result.candidateTraces.map {
                    "cand=\($0.wayID ?? "nil") rank=\($0.rank) score=\(String(format: "%.3f", $0.score)) distance=\(String(format: "%.1f", $0.distanceM)) continuity=\($0.continuityClass) selected=\($0.isSelected)"
                }
        ).joined(separator: " | ")

        XCTAssertEqual(result.wayID, "12003", debugSummary)
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "simple_sequence_viterbi_seed" &&
                    $0.detail.contains("history_fixes=9")
            },
            debugSummary
        )
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "simple_sequence_viterbi" &&
                    $0.detail.contains("best_viterbi=12003")
            },
            debugSummary
        )
        XCTAssertTrue(result.matchHypotheses.contains { $0.wayID == "12003" })
    }

    func testSequenceViterbiMatcherUsesRouteRelationContinuityWithoutWayLinks() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-sequence-relation-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("continuity_fixture.sqlite")
        try createMatchContinuityFixtureDB(at: dbURL, includeWayLinks: false)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSequenceViterbiHeuristic
        )

        let baseline = try service.lookupSpeedLimit(
            lat: 52.00000,
            lon: 13.00480,
            radiusM: 40.0,
            maxCandidates: 32,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 38.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(baseline.wayID, "5003")

        let context = WayMatchContext(
            preferredWayID: "5001",
            preferredHighway: "primary",
            preferredEndpointProximityM: 4.0,
            recentWayIDs: ["5001"],
            recentFixes: [
                WayMatchRecentFix(lat: 52.00010, lon: 13.00360, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 38.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.00010, lon: 13.00320, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 38.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.00010, lon: 13.00280, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 38.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.00010, lon: 13.00240, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 38.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
            ],
            preferredStreetRef: "B10",
            activeStreetRef: "B10",
            recentStreetRefs: ["B10"]
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.00000,
            lon: 13.00480,
            radiusM: 40.0,
            maxCandidates: 32,
            matchContext: context,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 38.0,
            horizontalAccuracyM: 5.0
        )

        let debugSummary = (
            result.selectionTrace.map { "\($0.step)=\($0.detail)" } +
                result.candidateTraces.map {
                    "cand=\($0.wayID ?? "nil") rank=\($0.rank) score=\(String(format: "%.3f", $0.score)) continuity=\($0.continuityClass) selected=\($0.isSelected)"
                }
        ).joined(separator: " | ")

        XCTAssertEqual(result.wayID, "5002", debugSummary)
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "simple_sequence_viterbi_seed" &&
                    $0.detail.contains("continuity_available=true")
            },
            debugSummary
        )
        XCTAssertTrue(result.matchHypotheses.contains { $0.wayID == "5002" }, debugSummary)
    }

    func testSequenceViterbiMatcherUsesSameStreetContinuityWithoutWayLinks() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-sequence-same-name-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("continuity_fixture.sqlite")
        try createMatchContinuityFixtureDB(at: dbURL, includeWayLinks: false)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSequenceViterbiHeuristic
        )

        let baseline = try service.lookupSpeedLimit(
            lat: 52.01006,
            lon: 13.00480,
            radiusM: 40.0,
            maxCandidates: 32,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 34.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(baseline.wayID, "6003")

        let context = WayMatchContext(
            preferredWayID: "6001",
            preferredHighway: "secondary",
            preferredEndpointProximityM: 4.0,
            recentWayIDs: ["6001"],
            recentFixes: [
                WayMatchRecentFix(lat: 52.01000, lon: 13.00360, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 34.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.01000, lon: 13.00320, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 34.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.01000, lon: 13.00280, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 34.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
                WayMatchRecentFix(lat: 52.01000, lon: 13.00240, headingDeg: 90.0, headingAccuracyDeg: 5.0, speedKmh: 34.0, horizontalAccuracyM: 5.0, gpsSignalBars: 4),
            ],
            preferredStreetRef: nil,
            preferredStreetName: "History Road",
            recentStreetRefs: []
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.01006,
            lon: 13.00480,
            radiusM: 40.0,
            maxCandidates: 32,
            matchContext: context,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 34.0,
            horizontalAccuracyM: 5.0
        )

        let debugSummary = (
            result.selectionTrace.map { "\($0.step)=\($0.detail)" } +
                result.candidateTraces.map {
                    "cand=\($0.wayID ?? "nil") rank=\($0.rank) score=\(String(format: "%.3f", $0.score)) continuity=\($0.continuityClass) selected=\($0.isSelected)"
                }
        ).joined(separator: " | ")

        XCTAssertEqual(result.wayID, "6002", debugSummary)
        XCTAssertTrue(result.matchHypotheses.contains { $0.wayID == "6002" }, debugSummary)
    }

    func testBundledSeedProvidesWayEndpointsForRollingHMM() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }

        var db: OpaquePointer?
        let encodedPath = bundledDB.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? bundledDB.path
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 110, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(bundledDB.path)"])
        }
        defer { sqlite3_close(db) }

        func scalarInt(_ sql: String) throws -> Int {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                let message = String(cString: sqlite3_errmsg(db))
                throw NSError(domain: "SpeedConsumerTests", code: 111, userInfo: [NSLocalizedDescriptionKey: "prepare failed: \(message)"])
            }
            defer { sqlite3_finalize(stmt) }
            guard sqlite3_step(stmt) == SQLITE_ROW else {
                throw NSError(domain: "SpeedConsumerTests", code: 112, userInfo: [NSLocalizedDescriptionKey: "no row for query: \(sql)"])
            }
            return Int(sqlite3_column_int(stmt, 0))
        }

        func scalarText(_ sql: String) throws -> String? {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
                let message = String(cString: sqlite3_errmsg(db))
                throw NSError(domain: "SpeedConsumerTests", code: 113, userInfo: [NSLocalizedDescriptionKey: "prepare failed: \(message)"])
            }
            defer { sqlite3_finalize(stmt) }
            guard sqlite3_step(stmt) == SQLITE_ROW else {
                return nil
            }
            return sqlite3_column_text(stmt, 0).map { String(cString: $0) }
        }

        XCTAssertEqual(
            try scalarInt("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='way_endpoints'"),
            1
        )
        XCTAssertGreaterThan(try scalarInt("SELECT COUNT(*) FROM way_endpoints"), 0)
        XCTAssertEqual(
            try scalarText("SELECT value FROM metadata WHERE key = 'way_endpoints_mode' LIMIT 1"),
            "coord_key_length_v1"
        )
        XCTAssertEqual(
            try scalarInt("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='way_continuity_group'"),
            1
        )
        XCTAssertEqual(
            try scalarInt("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='way_continuity_membership'"),
            1
        )
        XCTAssertGreaterThan(try scalarInt("SELECT COUNT(*) FROM way_continuity_group"), 0)
        XCTAssertGreaterThan(try scalarInt("SELECT COUNT(*) FROM way_continuity_membership"), 0)
        XCTAssertEqual(
            try scalarText("SELECT value FROM metadata WHERE key = 'way_continuity_mode' LIMIT 1"),
            "route_relation_connected+same_street_name_connected"
        )
    }

    func testLookupCapsCandidateRadiusByHorizontalAccuracy() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-hacc-radius-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("fixture.sqlite")
        try createHorizontalAccuracyRadiusFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let baseline = try service.lookupSpeedLimit(
            lat: 52.00003,
            lon: 13.0050,
            radiusM: 20.0,
            maxCandidates: 32
        )
        XCTAssertEqual(baseline.wayID, "100")
        XCTAssertEqual(baseline.candidateCount, 2)

        let capped = try service.lookupSpeedLimit(
            lat: 52.00003,
            lon: 13.0050,
            radiusM: 20.0,
            maxCandidates: 32,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(capped.wayID, "100")
        XCTAssertEqual(capped.candidateCount, 1)
    }

    func testUrbanReleaseNarrowWindowMatcherCapsSearchRadiusAtTenMeters() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-narrow-window-radius-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("fixture.sqlite")
        try createHorizontalAccuracyRadiusFixtureDB(at: dbURL)

        let baseline = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefUrbanReleaseHeuristic
        )
        let narrowWindow = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefUrbanReleaseNarrowWindowHeuristic
        )

        let baselineResult = try baseline.lookupSpeedLimit(
            lat: 52.00013,
            lon: 13.0050,
            radiusM: 20.0,
            maxCandidates: 32
        )
        XCTAssertEqual(baselineResult.wayID, "200")
        XCTAssertEqual(baselineResult.candidateCount, 2)

        let narrowWindowResult = try narrowWindow.lookupSpeedLimit(
            lat: 52.00013,
            lon: 13.0050,
            radiusM: 20.0,
            maxCandidates: 32
        )
        XCTAssertEqual(narrowWindowResult.wayID, "200")
        XCTAssertEqual(narrowWindowResult.candidateCount, 1)
        XCTAssertTrue(
            narrowWindowResult.selectionTrace.contains {
                $0.detail.contains("candidate_radius_m=10.0")
            }
        )
    }

    func testStreetNameFallbackKeepsSplitNoRefStreetInsteadOfStaleRefRoad() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-street-name-fallback-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("fixture.sqlite")
        try createStreetNameFallbackFixtureDB(at: dbURL)

        let m6 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefUrbanReleaseHeuristic
        )
        let m8 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameFallbackHeuristic
        )
        let m9 = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefStreetNameGuardHeuristic
        )

        let context = WayMatchContext(
            preferredWayID: "200",
            recentWayIDs: ["200", "100"],
            sameRefUrbanReleaseStreak: 0,
            preferredStreetRef: "L564",
            activeStreetRef: nil,
            preferredStreetName: "Bleichweg",
            recentStreetRefs: ["L564"],
            consecutiveNoRefMatchCount: 2
        )

        let baselineResult = try m6.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0070,
            radiusM: 150.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 33.0,
            horizontalAccuracyM: 4.0
        )
        XCTAssertEqual(baselineResult.wayID, "100")

        let fallbackResult = try m8.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0070,
            radiusM: 150.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 33.0,
            horizontalAccuracyM: 4.0
        )
        XCTAssertEqual(fallbackResult.wayID, "300")

        let guardedResult = try m9.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0070,
            radiusM: 150.0,
            maxCandidates: 32,
            matchContext: context,
            speedKmh: 33.0,
            horizontalAccuracyM: 4.0
        )
        XCTAssertEqual(guardedResult.wayID, "300")
    }

    func testLookupDoesNotMarkTunnelSegmentWithoutContinuationContext() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-tunnel-tag-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("heading_fixture.sqlite")
        try createHeadingDisambiguationFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let tunnelMatch = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0001,
            radiusM: 80.0,
            maxCandidates: 32,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 20.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertFalse(tunnelMatch.isTunnelSegment)
    }

    func testM2DoesNotMarkTunnelSegmentWithoutContinuationContext() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-m2-tunnel-tag-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("heading_fixture.sqlite")
        try createHeadingDisambiguationFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefHeuristic
        )

        let tunnelMatch = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0001,
            radiusM: 80.0,
            maxCandidates: 32,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 20.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertFalse(tunnelMatch.isTunnelSegment)
        XCTAssertNotEqual(tunnelMatch.wayID, "1001")
        XCTAssertTrue(
            tunnelMatch.selectionTrace.contains {
                $0.step == "simple_tunnel_selectability_gate"
            }
        )
    }

    func testLookupMarksTunnelSegmentWhenContinuingOnSameRef() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-tunnel-transition-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("tunnel_transition_fixture.sqlite")
        try createTunnelTransitionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0010,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "7001",
                preferredHighway: "primary",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["7001"],
                preferredStreetRef: "B 10",
                recentStreetRefs: ["B 10"]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 20.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "7002")
        XCTAssertTrue(result.isTunnelSegment)
    }

    func testLookupRejectsTunnelEntryFromMiddleWithoutPortalTransition() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-tunnel-transition-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("tunnel_transition_fixture.sqlite")
        try createTunnelTransitionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0015,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "7001",
                preferredHighway: "primary",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["7001"],
                preferredStreetRef: "B 10",
                recentStreetRefs: ["B 10"]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 20.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertNotEqual(result.wayID, "7002")
        XCTAssertFalse(result.isTunnelSegment)
    }

    func testLookupKeepsTunnelModeUntilExitPortalReached() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-tunnel-transition-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("tunnel_transition_fixture.sqlite")
        try createTunnelTransitionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0016,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "7002",
                preferredHighway: "primary",
                preferredEndpointProximityM: 22.0,
                recentWayIDs: ["7002"],
                preferredStreetRef: "B 10",
                recentStreetRefs: ["B 10"],
                recentTunnelCandidateWayIDs: ["7002"],
                recentTunnelCandidateRefs: ["B 10"],
                isInTunnelMode: true
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 20.0,
            horizontalAccuracyM: 18.0
        )
        XCTAssertEqual(result.wayID, "7002")
        XCTAssertTrue(result.isTunnelSegment)
    }

    func testLookupMarksTunnelSegmentAfterSignalLossWhenTunnelWasRecentCandidate() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-tunnel-transition-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("tunnel_transition_fixture.sqlite")
        try createTunnelTransitionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0010,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: nil,
                recentWayIDs: [],
                preferredStreetRef: nil,
                recentStreetRefs: [],
                recentTunnelCandidateWayIDs: ["7002"],
                recentTunnelCandidateRefs: ["B 10"],
                hadRecentGPSSignalLoss: true
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 20.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "7002")
        XCTAssertTrue(result.isTunnelSegment)
    }

    func testLookupPromotesTunnelEntryAfterApproachExposureAndSignalDegradation() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-ambiguous-tunnel-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("ambiguous_tunnel_fixture.sqlite")
        try createAmbiguousTunnelPortalFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let baseContext = WayMatchContext(
            preferredWayID: "7101",
            preferredHighway: "primary",
            preferredEndpointProximityM: 0.0,
            recentWayIDs: ["7101"],
            preferredStreetRef: "B 10",
            recentStreetRefs: ["B 10"],
            recentTunnelCandidateWayIDs: ["7102"],
            recentTunnelCandidateRefs: ["B 10"]
        )

        let surfacePreferred = try service.lookupSpeedLimit(
            lat: 52.01007,
            lon: 13.00105,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: baseContext,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 30.0,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )
        XCTAssertEqual(surfacePreferred.wayID, "7103")
        XCTAssertFalse(surfacePreferred.isTunnelSegment)

        let promotedTunnel = try service.lookupSpeedLimit(
            lat: 52.01007,
            lon: 13.00105,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "7101",
                preferredHighway: "primary",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["7101"],
                preferredStreetRef: "B 10",
                recentStreetRefs: ["B 10"],
                recentTunnelCandidateWayIDs: ["7102"],
                recentTunnelCandidateRefs: ["B 10"],
                recentTunnelApproachWayIDs: ["7102"],
                recentTunnelApproachRefs: ["B 10"],
                tunnelApproachFixCount: 3,
                tunnelApproachBaselineAccuracyM: 5.0,
                tunnelApproachBaselineSignalBars: 4
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 30.0,
            horizontalAccuracyM: 16.0,
            gpsSignalBars: 2
        )

        XCTAssertEqual(promotedTunnel.wayID, "7102")
        XCTAssertTrue(promotedTunnel.isTunnelSegment)
        XCTAssertTrue(
            promotedTunnel.selectionTrace.contains {
                $0.step == "tunnel_entry_gate" && $0.detail.contains("7102")
            }
        )
    }

    func testM2PromotesTunnelEntryAfterApproachExposureAndSignalDegradation() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-m2-ambiguous-tunnel-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("ambiguous_tunnel_fixture.sqlite")
        try createAmbiguousTunnelPortalFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefHeuristic
        )

        let promotedTunnel = try service.lookupSpeedLimit(
            lat: 52.01007,
            lon: 13.00105,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "7101",
                preferredHighway: "primary",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["7101"],
                preferredStreetRef: "B 10",
                activeStreetRef: "B 10",
                recentStreetRefs: ["B 10"],
                recentTunnelCandidateWayIDs: ["7102"],
                recentTunnelCandidateRefs: ["B 10"],
                recentTunnelApproachWayIDs: ["7102"],
                recentTunnelApproachRefs: ["B 10"],
                tunnelApproachFixCount: 3,
                tunnelApproachBaselineAccuracyM: 5.0,
                tunnelApproachBaselineSignalBars: 4
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 30.0,
            horizontalAccuracyM: 16.0,
            gpsSignalBars: 2
        )

        XCTAssertEqual(promotedTunnel.wayID, "7102")
        XCTAssertTrue(promotedTunnel.isTunnelSegment)
        XCTAssertTrue(
            promotedTunnel.selectionTrace.contains {
                $0.step == "tunnel_entry_gate" && $0.detail.contains("7102")
            }
        )
    }

    func testM2KeepsTunnelModeUntilExitPortalAfterGpsReacquisition() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-m2-tunnel-exit-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("ambiguous_tunnel_fixture.sqlite")
        try createAmbiguousTunnelPortalFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefHeuristic
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.01007,
            lon: 13.00105,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "7102",
                preferredHighway: "primary",
                preferredEndpointProximityM: 18.0,
                recentWayIDs: ["7102", "7101"],
                preferredStreetRef: "B 10",
                activeStreetRef: "B 10",
                recentStreetRefs: ["B 10"],
                recentTunnelCandidateWayIDs: ["7102"],
                recentTunnelCandidateRefs: ["B 10"],
                isInTunnelMode: true
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 28.0,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )

        XCTAssertEqual(result.wayID, "7102")
        XCTAssertTrue(result.isTunnelSegment)
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "tunnel_exit_gate" && $0.detail.contains("7102")
            }
        )
    }

    func testLookupCommitsTunnelInsidePersistedCorridorChainWithoutSignalLoss() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-long-tunnel-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("long_tunnel_fixture.sqlite")
        try createLongTunnelCorridorFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        var state = BundledMatchContextState(
            recentWayIDs: ["8101"],
            recentStreetRefs: ["B 10"],
            preferredWayID: "8101",
            preferredHighway: "primary",
            preferredEndpointProximityM: 0.0
        )

        let surfaceResult = try service.lookupSpeedLimit(
            lat: 52.02007,
            lon: 13.00108,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: state.context,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 32.0,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )
        XCTAssertFalse(surfaceResult.isTunnelSegment)
        state.record(
            surfaceResult,
            lat: 52.02007,
            lon: 13.00108,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )
        XCTAssertEqual(state.approachCorridorState?.kind, "tunnel")

        let carriedApproachResult = try service.lookupSpeedLimit(
            lat: 52.02007,
            lon: 13.00170,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: state.context,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 32.0,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )
        XCTAssertFalse(carriedApproachResult.isTunnelSegment)
        state.record(
            carriedApproachResult,
            lat: 52.02007,
            lon: 13.00170,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )
        XCTAssertEqual(state.approachCorridorState?.kind, "tunnel")
        XCTAssertGreaterThanOrEqual(state.approachCorridorFixCount, 2)

        let tunnelResult = try service.lookupSpeedLimit(
            lat: 52.02007,
            lon: 13.00260,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: state.context,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 32.0,
            horizontalAccuracyM: 5.0,
            gpsSignalBars: 4
        )

        XCTAssertEqual(tunnelResult.wayID, "8102")
        XCTAssertTrue(tunnelResult.isTunnelSegment)
        XCTAssertEqual(tunnelResult.activeCorridorState?.kind, "tunnel")
        XCTAssertTrue(
            tunnelResult.selectionTrace.contains {
                ($0.step == "corridor_entry_gate" || $0.step == "final") && $0.detail.contains("8102")
            }
        )
    }

    func testTunnelPortalEligibilityUsesRecentFixMotionProgress() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-portal-progress-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("portal_progress_fixture.sqlite")
        try createAmbiguousTunnelPortalFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        func lookup(recentLon: Double) throws -> MatchCandidateTrace {
            let result = try service.lookupSpeedLimit(
                lat: 52.01000,
                lon: 13.00095,
                radiusM: 80.0,
                maxCandidates: 32,
                matchContext: WayMatchContext(
                    preferredWayID: "7101",
                    preferredHighway: "primary",
                    preferredEndpointProximityM: 0.0,
                    recentWayIDs: ["7101"],
                    recentFixes: [WayMatchRecentFix(lat: 52.01000, lon: recentLon)],
                    preferredStreetRef: "B 10",
                    recentStreetRefs: ["B 10"]
                ),
                headingDeg: 90.0,
                headingAccuracyDeg: 5.0,
                speedKmh: 30.0,
                horizontalAccuracyM: 5.0,
                gpsSignalBars: 4
            )
            return try XCTUnwrap(result.candidateTraces.first(where: { $0.wayID == "7102" }))
        }

        let approachingTrace = try lookup(recentLon: 13.00075)
        let recedingTrace = try lookup(recentLon: 13.00102)

        XCTAssertEqual(approachingTrace.portalEligible, true)
        XCTAssertEqual(recedingTrace.portalEligible, false)
    }

    func testLookupBlocksDirectMotorwayEntryUntilRampTransition() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-motorway-corridor-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("motorway_corridor_fixture.sqlite")
        try createMotorwayCorridorFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.06003,
            lon: 13.00430,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9301",
                preferredHighway: "primary",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["9301"],
                preferredStreetRef: "B 462",
                recentStreetRefs: ["B 462"]
            ),
            headingDeg: 45.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 35.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "9302")
        let directMotorway = try XCTUnwrap(result.candidateTraces.first(where: { $0.wayID == "9303" }))
        XCTAssertEqual(directMotorway.highway, "motorway")
        XCTAssertEqual(directMotorway.corridorSelectable, false)
    }

    func testLookupActivatesMotorwayModeAfterRepeatedEntryProgress() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-motorway-corridor-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("motorway_corridor_fixture.sqlite")
        try createMotorwayCorridorFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let motorwayResult = try service.lookupSpeedLimit(
            lat: 52.06010,
            lon: 13.00595,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9302",
                preferredHighway: "motorway_link",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["9302", "9301"],
                preferredStreetRef: "A 5",
                recentStreetRefs: ["A 5", "B 462"],
                approachCorridorState: CorridorMatchState(
                    kind: "motorway",
                    corridorID: 1,
                    sideNodeKey: "motorway-west",
                    depthM: 24.0,
                    spanM: 411.0,
                    depthNodes: 1,
                    spanNodes: 3
                ),
                approachCorridorFixCount: 2,
                approachCorridorStartDepthM: 12.0,
                approachCorridorStartDepthNodes: 0
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 70.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(motorwayResult.wayID, "9303")
        XCTAssertEqual(motorwayResult.activeCorridorState?.kind, "motorway")
    }

    func testLookupBlocksDirectSurfaceExitWhileMotorwayStateIsActive() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-motorway-corridor-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("motorway_corridor_fixture.sqlite")
        try createMotorwayCorridorFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.06006,
            lon: 13.00672,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9303",
                preferredHighway: "motorway",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["9303"],
                preferredStreetRef: "A 5",
                recentStreetRefs: ["A 5"]
            ),
            headingDeg: 135.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 65.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "9304")
        let directSurface = try XCTUnwrap(result.candidateTraces.first(where: { $0.wayID == "9305" }))
        XCTAssertEqual(directSurface.highway, "secondary")
        XCTAssertEqual(directSurface.corridorSelectable, false)
    }

    func testLookupAllowsSurfaceRoadAfterMotorwayLinkExit() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-motorway-corridor-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("motorway_corridor_fixture.sqlite")
        try createMotorwayCorridorFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.06000,
            lon: 13.00755,
            radiusM: 80.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9304",
                preferredHighway: "motorway_link",
                preferredEndpointProximityM: 0.0,
                recentWayIDs: ["9304", "9303"],
                preferredStreetRef: "A 5",
                recentStreetRefs: ["A 5"]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 25.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "9305")
        let localRoad = try XCTUnwrap(result.candidateTraces.first(where: { $0.wayID == "9305" }))
        XCTAssertEqual(localRoad.corridorSelectable, true)
    }

    func testLookupPrefersSameRefContinuationWhenPreviousWayDropsOutOfRange() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-continuity-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("continuity_fixture.sqlite")
        try createMatchContinuityFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let baseline = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0048,
            radiusM: 40.0,
            maxCandidates: 32,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(baseline.wayID, "5003")

        let result = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0048,
            radiusM: 40.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "5001",
                recentWayIDs: ["5001"],
                preferredStreetRef: "B10",
                recentStreetRefs: ["B10"]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "5002")
        XCTAssertEqual(result.streetRef, "B10")
        XCTAssertEqual(result.speedLimitKmh, 70)
    }

    func testLookupPrefersRecentWayWhenScoresAreCloseAndNoRefMatches() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-continuity-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("continuity_fixture.sqlite")
        try createMatchContinuityFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let baseline = try service.lookupSpeedLimit(
            lat: 52.0100,
            lon: 13.0048,
            radiusM: 40.0,
            maxCandidates: 32,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(baseline.wayID, "6003")

        let result = try service.lookupSpeedLimit(
            lat: 52.0100,
            lon: 13.0048,
            radiusM: 40.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "6001",
                recentWayIDs: ["6002", "6001"],
                preferredStreetRef: nil,
                recentStreetRefs: []
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "6002")
        XCTAssertEqual(result.speedLimitKmh, 80)
    }

    func testLookupPrefersRouteContinuationOverSlightlyCloserSideRoad() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-mini-hmm-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("mini_hmm_fixture.sqlite")
        try createSelectiveMiniHMMFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.02007,
            lon: 13.00425,
            radiusM: 30.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "8001",
                recentWayIDs: ["8001"],
                preferredStreetRef: nil,
                recentStreetRefs: [],
                recentHypotheses: [
                    WayMatchHypothesis(
                        wayID: "8001",
                        streetRef: nil,
                        highway: "primary",
                        cumulativeCost: 6.0,
                        emissionScore: 6.0,
                        endpointProximityM: 1.0,
                        startLat: 52.02000,
                        startLon: 13.0000,
                        endLat: 52.02000,
                        endLon: 13.0040,
                        isTunnel: false
                    )
                ]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 35.0,
            horizontalAccuracyM: nil
        )

        XCTAssertEqual(result.wayID, "8002")
        XCTAssertGreaterThanOrEqual(result.miniHMMCandidateCount, 2)
        XCTAssertTrue(
            result.selectionTrace.contains {
                ($0.step == "heuristic" && $0.detail.contains("selected 8002")) ||
                    ($0.step == "mini_hmm" && $0.detail.contains("selected 8002"))
            }
        )
    }

    func testLookupPrefersWayLinksConnectedContinuationOverCloserUnrelatedRoad() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-way-links-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("way_links_fixture.sqlite")
        try createWayLinksTransitionFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.03018,
            lon: 13.00485,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9001",
                recentWayIDs: ["9001"],
                preferredStreetRef: nil,
                recentStreetRefs: [],
                recentHypotheses: [
                    WayMatchHypothesis(
                        wayID: "9001",
                        streetRef: nil,
                        highway: "primary",
                        cumulativeCost: 4.0,
                        emissionScore: 4.0,
                        endpointProximityM: 2.0,
                        startLat: 52.03000,
                        startLon: 13.0000,
                        endLat: 52.03000,
                        endLon: 13.0030,
                        isTunnel: false
                    )
                ]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 35.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "9002")
        XCTAssertTrue(result.usedMiniHMM)
        XCTAssertGreaterThanOrEqual(result.miniHMMCandidateCount, 2)
    }

    func testLookupRejectsDisconnectedHopAfterWarmupWhenWayLinksAvailable() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-road-graph-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("road_graph_fixture.sqlite")
        try createDisconnectedHopFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.04305,
            lon: 13.00025,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9201",
                recentWayIDs: ["9201"],
                preferredStreetRef: "L564",
                recentStreetRefs: ["L564"],
                recentHypotheses: [
                    WayMatchHypothesis(
                        wayID: "9201",
                        streetRef: "L564",
                        highway: "secondary",
                        cumulativeCost: 4.0,
                        emissionScore: 4.0,
                        endpointProximityM: 2.0,
                        startLat: 52.04000,
                        startLon: 13.0000,
                        endLat: 52.04300,
                        endLon: 13.0000,
                        isTunnel: false
                    )
                ],
                matchedFixCount: 4
            ),
            headingDeg: 0.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 25.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertNotEqual(result.wayID, "9203")
        XCTAssertEqual(result.wayID, "9202")
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "road_graph_gate" && $0.detail.contains("disconnected candidates")
            }
        )
    }

    func testCandidateTraceScoresRankSameRefBeforeBestGeometricRoad() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-trace-ranking-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("trace_ranking_fixture.sqlite")
        try createTraceRankingFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.04004,
            lon: 13.00435,
            radiusM: 50.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9101",
                recentWayIDs: ["9101"],
                preferredStreetRef: "K1",
                recentStreetRefs: ["K1"]
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 35.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "9102")
        XCTAssertGreaterThanOrEqual(result.candidateTraces.count, 3)
        guard result.candidateTraces.count >= 3 else {
            return
        }

        let topWayIDs = Array(result.candidateTraces.prefix(3).compactMap(\.wayID))
        XCTAssertEqual(topWayIDs, ["9101", "9102", "9103"])
        XCTAssertEqual(result.candidateTraces[0].continuityClass, "preferredWay")
        XCTAssertEqual(result.candidateTraces[1].continuityClass, "sameRef")
        XCTAssertEqual(result.candidateTraces[2].continuityClass, "none")
        let bestGeometric = try XCTUnwrap(result.candidateTraces.first(where: { $0.wayID == "9103" }))
        let sameRef = try XCTUnwrap(result.candidateTraces.first(where: { $0.wayID == "9102" }))
        XCTAssertLessThan(sameRef.score, bestGeometric.score)
    }

    func testM2RouteClassGuardPrefersSameRefContinuationOverCloserServiceParallel() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-m2-route-class-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("same_ref_parallel_fixture.sqlite")
        try createSameRefParallelRouteClassFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(
            dbPath: dbURL.path,
            matchingModel: .simpleSpeedRefHeuristic
        )

        let result = try service.lookupSpeedLimit(
            lat: 52.07005,
            lon: 13.00435,
            radiusM: 45.0,
            maxCandidates: 32,
            matchContext: WayMatchContext(
                preferredWayID: "9401",
                preferredHighway: "tertiary",
                preferredEndpointProximityM: 1.0,
                recentWayIDs: ["9401"],
                preferredStreetRef: "K 1",
                activeStreetRef: "K 1",
                recentStreetRefs: ["K 1"],
                matchedFixCount: 3
            ),
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 32.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "9402")
        XCTAssertNotEqual(result.wayID, "9403")
        XCTAssertTrue(
            result.selectionTrace.contains {
                $0.step == "simple_same_ref_route_class_guard" &&
                    $0.detail.contains("9402") &&
                    $0.detail.contains("9403")
            }
        )
    }

    func testCandidateTraceScoreAppliesContinuityBandsBeforeGeometry() {
        let maxGeometryScore = 157.973936450404
        let preferred = V3SpeedLimitService.candidateTraceScore(
            geometryScore: 56.572183972077575,
            continuityClass: "preferredWay",
            maxGeometryScore: maxGeometryScore
        )
        let sameRef = V3SpeedLimitService.candidateTraceScore(
            geometryScore: 157.973936450404,
            continuityClass: "sameRef",
            maxGeometryScore: maxGeometryScore
        )
        let bestGeometric = V3SpeedLimitService.candidateTraceScore(
            geometryScore: 0.7896197961348994,
            continuityClass: "none",
            maxGeometryScore: maxGeometryScore
        )
        let worseGeometric = V3SpeedLimitService.candidateTraceScore(
            geometryScore: 134.3135929253142,
            continuityClass: "none",
            maxGeometryScore: maxGeometryScore
        )

        XCTAssertLessThan(preferred, sameRef)
        XCTAssertLessThan(sameRef, bestGeometric)
        XCTAssertLessThan(bestGeometric, worseGeometric)
    }

    func testBundledL564RouteHysteresisRejectsTemporarySwitchToRisswasenweg() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["52869774", "1316349759", "206811644", "16657591", "1220097540"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required route ways: \(missingWayIDs.sorted())")
        }

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var recentWayIDs: [String] = []
        var recentStreetRefs: [String] = []
        var recentHypotheses: [WayMatchHypothesis] = []
        var preferredWayID: String?
        var preferredHighway: String?
        var preferredEndpointProximityM: Double?

        func record(_ result: SpeedLimitResult) {
            if let wayID = result.wayID {
                recentWayIDs.removeAll(where: { $0 == wayID })
                recentWayIDs.insert(wayID, at: 0)
                if recentWayIDs.count > 5 {
                    recentWayIDs.removeLast(recentWayIDs.count - 5)
                }
                preferredWayID = wayID
            }
            preferredHighway = result.highway
            preferredEndpointProximityM = result.matchedEndpointProximityM
            for ref in V3SpeedLimitService.normalizedRefTokens(result.streetRef) {
                recentStreetRefs.removeAll(where: { $0 == ref })
                recentStreetRefs.insert(ref, at: 0)
                if recentStreetRefs.count > 6 {
                    recentStreetRefs.removeLast(recentStreetRefs.count - 6)
                }
            }
            recentHypotheses = result.matchHypotheses
        }

        func context() -> WayMatchContext? {
            guard preferredWayID != nil || !recentWayIDs.isEmpty || !recentStreetRefs.isEmpty || !recentHypotheses.isEmpty else {
                return nil
            }
            return WayMatchContext(
                preferredWayID: preferredWayID,
                preferredHighway: preferredHighway,
                preferredEndpointProximityM: preferredEndpointProximityM,
                recentWayIDs: recentWayIDs,
                preferredStreetRef: recentStreetRefs.first,
                recentStreetRefs: recentStreetRefs,
                recentHypotheses: recentHypotheses
            )
        }

        let first = try service.lookupSpeedLimit(
            lat: 48.77670,
            lon: 8.40306,
            radiusM: 40.0,
            maxCandidates: 64,
            matchContext: context(),
            headingDeg: 180.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(first.wayID, "52869774")
        XCTAssertEqual(first.streetRef, "L 564")
        record(first)

        let second = try service.lookupSpeedLimit(
            lat: 48.77632,
            lon: 8.40311,
            radiusM: 40.0,
            maxCandidates: 64,
            matchContext: context(),
            headingDeg: 180.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(second.wayID, "1316349759")
        XCTAssertEqual(second.streetRef, "L 564")
        record(second)

        let ambiguousCandidateWayIDs = try readCandidateWayIDs(
            dbURL: bundledDB,
            lat: 48.77600,
            lon: 8.40300,
            radiusM: 40.0,
            maxCandidates: 16
        )
        XCTAssertTrue(
            ambiguousCandidateWayIDs.contains("16657591"),
            "Expected the nearby side road candidate to be part of the ambiguous candidate set"
        )
        XCTAssertTrue(
            ambiguousCandidateWayIDs.contains("206811644"),
            "Expected the intended southbound continuation to be part of the ambiguous candidate set"
        )

        let ambiguous = try service.lookupSpeedLimit(
            lat: 48.77600,
            lon: 8.40300,
            radiusM: 40.0,
            maxCandidates: 64,
            matchContext: context(),
            headingDeg: 180.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(ambiguous.wayID, "206811644")
        XCTAssertEqual(ambiguous.streetRef, "L 564")
        XCTAssertNotEqual(ambiguous.wayID, "16657591")
        XCTAssertGreaterThanOrEqual(ambiguous.miniHMMCandidateCount, 2)
        XCTAssertFalse(ambiguous.matchHypotheses.isEmpty)
        record(ambiguous)

        let fourth = try service.lookupSpeedLimit(
            lat: 48.77440,
            lon: 8.40360,
            radiusM: 50.0,
            maxCandidates: 64,
            matchContext: context(),
            headingDeg: 210.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 45.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(fourth.wayID, "1220097540")
        XCTAssertEqual(fourth.streetRef, "L 564")
    }

    func testBundledGernsbachSurfaceSequenceRejectsNearbyTunnelMatch() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["209270482", "1251752493", "1252070523", "1036502006", "1251752490", "209270485", "1037006038", "4287421"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required tunnel regression ways: \(missingWayIDs.sorted())")
        }

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var recentWayIDs: [String] = []
        var recentStreetRefs: [String] = []
        var recentHypotheses: [WayMatchHypothesis] = []
        var recentTunnelCandidateWayIDs: [String] = []
        var recentTunnelCandidateRefs: [String] = []
        var preferredWayID: String?
        var preferredHighway: String?
        var preferredEndpointProximityM: Double?

        func record(_ result: SpeedLimitResult) {
            if let wayID = result.wayID {
                recentWayIDs.removeAll(where: { $0 == wayID })
                recentWayIDs.insert(wayID, at: 0)
                if recentWayIDs.count > 5 {
                    recentWayIDs.removeLast(recentWayIDs.count - 5)
                }
                preferredWayID = wayID
            }
            preferredHighway = result.highway
            preferredEndpointProximityM = result.matchedEndpointProximityM
            for ref in V3SpeedLimitService.normalizedRefTokens(result.streetRef) {
                recentStreetRefs.removeAll(where: { $0 == ref })
                recentStreetRefs.insert(ref, at: 0)
                if recentStreetRefs.count > 6 {
                    recentStreetRefs.removeLast(recentStreetRefs.count - 6)
                }
            }
            recentHypotheses = result.matchHypotheses
            recentTunnelCandidateWayIDs = result.nearbyTunnelCandidateWayIDs
            recentTunnelCandidateRefs = result.nearbyTunnelCandidateRefs
        }

        func context() -> WayMatchContext? {
            guard preferredWayID != nil ||
                    !recentWayIDs.isEmpty ||
                    !recentStreetRefs.isEmpty ||
                    !recentHypotheses.isEmpty ||
                    !recentTunnelCandidateWayIDs.isEmpty ||
                    !recentTunnelCandidateRefs.isEmpty else {
                return nil
            }
            return WayMatchContext(
                preferredWayID: preferredWayID,
                preferredHighway: preferredHighway,
                preferredEndpointProximityM: preferredEndpointProximityM,
                recentWayIDs: recentWayIDs,
                preferredStreetRef: recentStreetRefs.first,
                recentStreetRefs: recentStreetRefs,
                recentTunnelCandidateWayIDs: recentTunnelCandidateWayIDs,
                recentTunnelCandidateRefs: recentTunnelCandidateRefs,
                recentHypotheses: recentHypotheses
            )
        }

        let samples: [(allowedWayIDs: Set<String>, lat: Double, lon: Double, headingDeg: Double)] = [
            (["209270482"], 48.7656588, 8.3370405, 337.0),
            (["209270481", "1251752493"], 48.7670444, 8.3362234, 336.0),
            (["1251752493", "1252070523"], 48.7671638, 8.3360973, 330.0),
            (["1036502006"], 48.7677662, 8.3357282, 0.0),
            (["1251752490"], 48.7678893, 8.3357290, 336.0),
            (["209270485"], 48.7681050, 8.3357090, 0.0),
            (["1037006038"], 48.7683400, 8.3357540, 0.0),
        ]

        for (index, sample) in samples.enumerated() {
            let candidateWayIDs = try readCandidateWayIDs(
                dbURL: bundledDB,
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 80.0,
                maxCandidates: 64
            )
            XCTAssertTrue(
                candidateWayIDs.contains("4287421"),
                "Expected Tunnel Gernsbach to remain in the nearby candidate set at step \(index)"
            )

            let result = try service.lookupSpeedLimit(
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 80.0,
                maxCandidates: 64,
                matchContext: context(),
                headingDeg: sample.headingDeg,
                headingAccuracyDeg: 10.0,
                speedKmh: 35.0,
                horizontalAccuracyM: 5.0
            )

            XCTAssertTrue(
                sample.allowedWayIDs.contains(result.wayID ?? ""),
                "Unexpected way match at step \(index): got \(result.wayID ?? "nil") tunnel=\(result.isTunnelSegment)"
            )
            XCTAssertFalse(result.isTunnelSegment, "Surface route should not flip into tunnel mode at step \(index)")
            XCTAssertNotEqual(result.wayID, "4287421")
            record(result)
        }
    }

    func testBundledKarlsruheSchwarzwaldstrasseSurfaceSequenceRejectsNearbyTunnelMatch() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["4211746", "4251707", "172291916", "297763318"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required Karlsruhe tunnel regression ways: \(missingWayIDs.sorted())")
        }

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var state = BundledMatchContextState()
        let tunnelWayID = "4251707"
        let samples: [(allowedWayIDs: Set<String>, lat: Double, lon: Double, headingDeg: Double)] = [
            (["172291916", "297763318"], 48.99270, 8.39664, 330.0),
            (["172291916", "297763318"], 48.99255, 8.39675, 330.0),
            (["4211746"], 48.99170, 8.39740, 140.0),
        ]

        for (index, sample) in samples.enumerated() {
            let candidateWayIDs = try readCandidateWayIDs(
                dbURL: bundledDB,
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 60.0,
                maxCandidates: 64
            )
            XCTAssertTrue(
                candidateWayIDs.contains(tunnelWayID),
                "Expected Schwarzwaldstraße tunnel candidate near the surface route at step \(index)"
            )

            let result = try service.lookupSpeedLimit(
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 60.0,
                maxCandidates: 64,
                matchContext: state.context,
                headingDeg: sample.headingDeg,
                headingAccuracyDeg: 10.0,
                speedKmh: 35.0,
                horizontalAccuracyM: 5.0
            )

            XCTAssertTrue(sample.allowedWayIDs.contains(result.wayID ?? ""), "Unexpected Karlsruhe surface match at step \(index)")
            XCTAssertEqual(result.streetName, "Schwarzwaldstraße (L 561)")
            XCTAssertFalse(result.isTunnelSegment, "Surface route above Schwarzwaldstraße tunnel should not enter tunnel mode at step \(index)")
            XCTAssertNotEqual(result.wayID, tunnelWayID)
            state.record(
                result,
                lat: sample.lat,
                lon: sample.lon,
                horizontalAccuracyM: 5.0,
                gpsSignalBars: 4
            )
        }
    }

    func testBundledKarlsruheNaechstenbacherWegSerpentineSequenceMaintainsCurvedRouteContinuity() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["3060540", "43211799", "3060541", "327126761"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required Karlsruhe serpentine regression ways: \(missingWayIDs.sorted())")
        }

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        var state = BundledMatchContextState()
        let competingWayID = "327126761"
        let samples: [(wayID: String, lat: Double, lon: Double, headingDeg: Double, expectsParallelCandidate: Bool)] = [
            ("3060540", 49.56495, 8.66620, 38.0, false),
            ("3060540", 49.56593, 8.66742, 38.0, false),
            ("3060540", 49.56721, 8.66838, 40.0, false),
            ("43211799", 49.56982, 8.66841, 355.0, true),
            ("3060541", 49.57222, 8.66843, 25.0, true),
        ]

        for (index, sample) in samples.enumerated() {
            let candidateWayIDs = try readCandidateWayIDs(
                dbURL: bundledDB,
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 60.0,
                maxCandidates: 64
            )
            if sample.expectsParallelCandidate {
                XCTAssertTrue(
                    candidateWayIDs.contains(competingWayID),
                    "Expected nearby competing hillside road candidate along the serpentine route at step \(index)"
                )
            }

            let result = try service.lookupSpeedLimit(
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 60.0,
                maxCandidates: 64,
                matchContext: state.context,
                headingDeg: sample.headingDeg,
                headingAccuracyDeg: 12.0,
                speedKmh: 30.0,
                horizontalAccuracyM: 5.0
            )

            XCTAssertEqual(result.wayID, sample.wayID, "Unexpected serpentine route match at step \(index)")
            XCTAssertEqual(result.streetName, "Nächstenbacher Weg")
            state.record(
                result,
                lat: sample.lat,
                lon: sample.lon,
                horizontalAccuracyM: 5.0,
                gpsSignalBars: 4
            )
        }
    }

    func testBundledKarlsruheParallelStreetCorridorKeepsCorrectStreetSelection() throws {
        guard let bundledDB = bundledSpeedDBURL() else {
            throw XCTSkip("Bundled speeds_v3.sqlite not found in test host app")
        }
        let requiredWayIDs = ["3100823", "3533236", "41174446"]
        let presentWayIDs = try readPresentWayIDs(dbURL: bundledDB, wayIDs: requiredWayIDs)
        let missingWayIDs = Set(requiredWayIDs).subtracting(presentWayIDs)
        if !missingWayIDs.isEmpty {
            throw XCTSkip("Bundled seed DB does not contain required Karlsruhe parallel-street regression ways: \(missingWayIDs.sorted())")
        }

        let service = V3SpeedLimitService(dbPath: bundledDB.path)
        let samples: [(wayID: String, streetName: String, lat: Double, lon: Double, headingDeg: Double, nearbyWayIDs: [String])] = [
            ("3100823", "Vincentiusstraße", 48.99790, 8.38962, 185.0, ["3533236"]),
            ("3533236", "Salierstraße", 48.99680, 8.38914, 185.0, ["3100823", "41174446"]),
            ("41174446", "Michaelstraße", 48.99620, 8.38946, 185.0, ["3533236"]),
        ]

        for (index, sample) in samples.enumerated() {
            let candidateWayIDs = try readCandidateWayIDs(
                dbURL: bundledDB,
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 70.0,
                maxCandidates: 64
            )
            for nearbyWayID in sample.nearbyWayIDs {
                XCTAssertTrue(
                    candidateWayIDs.contains(nearbyWayID),
                    "Expected nearby parallel street candidate \(nearbyWayID) at step \(index)"
                )
            }

            let result = try service.lookupSpeedLimit(
                lat: sample.lat,
                lon: sample.lon,
                radiusM: 70.0,
                maxCandidates: 64,
                preferredWayID: nil,
                headingDeg: sample.headingDeg,
                headingAccuracyDeg: 8.0,
                speedKmh: 30.0,
                horizontalAccuracyM: 5.0
            )

            XCTAssertEqual(result.wayID, sample.wayID, "Unexpected parallel-street match at step \(index)")
            XCTAssertEqual(result.streetName, sample.streetName)
        }
    }

    func testLookupIgnoresTrafficSignFallbackForCityClassification() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-sign-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_sign_fixture.sqlite")
        try createCitySignFallbackFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let inner = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0021,
            radiusM: 120.0,
            maxCandidates: 32,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 40.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(inner.wayID, "3001")
        XCTAssertNil(inner.insideCity)
        XCTAssertEqual(inner.speedLimitKmh, 100)

        let outer = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0079,
            radiusM: 120.0,
            maxCandidates: 32,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 40.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(outer.wayID, "3001")
        XCTAssertNil(outer.insideCity)
        XCTAssertEqual(outer.speedLimitKmh, 100)
    }

    func testLookupCityClassificationPrefersInCityHighwayOverResidentialPolygon() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-precedence-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_precedence_fixture.sqlite")
        try createCityClassificationPrecedenceFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.0006,
            lon: 13.0042,
            radiusM: 120.0,
            maxCandidates: 64,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 30.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "4001")
        XCTAssertEqual(result.citySource, "highway_class_in_city")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupCityClassificationUsesResidentialPolygonForOtherHighways() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-precedence-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_precedence_fixture.sqlite")
        try createCityClassificationPrecedenceFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 52.00085,
            lon: 13.00495,
            radiusM: 120.0,
            maxCandidates: 64,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 30.0,
            horizontalAccuracyM: 5.0
        )
        XCTAssertEqual(result.wayID, "4002")
        XCTAssertEqual(result.citySource, "residential_polygon")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupGermanBelow50SpeedLimitMarksInsideCity() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-low-speed-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_low_speed_fixture.sqlite")
        try createGermanLowSpeedHeuristicFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path, countryCode: "DEU")

        let result = try service.lookupSpeedLimit(
            lat: 52.0000,
            lon: 13.0020,
            radiusM: 120.0,
            maxCandidates: 32,
            preferredWayID: nil,
            headingDeg: 90.0,
            headingAccuracyDeg: 5.0,
            speedKmh: 30.0,
            horizontalAccuracyM: 5.0
        )

        XCTAssertEqual(result.wayID, "4101")
        XCTAssertEqual(result.speedLimitKmh, 30)
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "de_speed_limit_lt_50")
    }

    func testLookupCityNearestFallbackPrefersCityOverCloserVillage() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-nearest-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_nearest_fixture.sqlite")
        try createNearestPlaceFallbackFixtureDB(
            at: dbURL,
            fixLat: 48.9205,
            fixLon: 8.6692,
            primaryPlaceName: "Pforzheim",
            primaryPlaceType: "city",
            primaryLon: 8.7025509,
            primaryLat: 48.890934,
            secondaryPlaceName: "Ispringen",
            secondaryPlaceType: "village",
            secondaryLon: 8.6690154,
            secondaryLat: 48.9205599
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.9205,
            lon: 8.6692,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Pforzheim")
        XCTAssertEqual(result.insideCity, false)
        XCTAssertEqual(result.citySource, "place_nearest")
    }

    func testLookupCityNearestFallbackPrefersTownOverCloserHamlet() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-nearest-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_nearest_fixture.sqlite")
        try createNearestPlaceFallbackFixtureDB(
            at: dbURL,
            fixLat: 48.8101,
            fixLon: 8.4426,
            primaryPlaceName: "Bad Herrenalb",
            primaryPlaceType: "town",
            primaryLon: 8.4382557,
            primaryLat: 48.7990507,
            secondaryPlaceName: "Kullenmühle",
            secondaryPlaceType: "hamlet",
            secondaryLon: 8.442564,
            secondaryLat: 48.8101385
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.8101,
            lon: 8.4426,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Bad Herrenalb")
        XCTAssertEqual(result.insideCity, false)
        XCTAssertEqual(result.citySource, "place_nearest")
    }

    func testLookupCityPolygonUsesAdminLevel6BoundaryWhenNoLevel8Exists() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-polygon-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_polygon_fixture.sqlite")
        try createCityPolygonFixtureDB(
            at: dbURL,
            fixLat: 48.890934,
            fixLon: 8.7025509,
            adminLevel6Name: "Pforzheim"
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.890934,
            lon: 8.7025509,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Pforzheim")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupCityPolygonFormatsAdminLevel8WithAdminLevel6Qualifier() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-polygon-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_polygon_fixture.sqlite")
        try createCityPolygonFixtureDB(
            at: dbURL,
            fixLat: 48.9233,
            fixLon: 8.6735,
            adminLevel6Name: "Enzkreis",
            adminLevel8Name: "Ispringen"
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.9233,
            lon: 8.6735,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Ispringen (Enzkreis)")
        XCTAssertEqual(result.cityPlaceName, "Ispringen")
        XCTAssertEqual(result.cityDistrictName, "Enzkreis")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupCityPolygonFormatsAdminLevel9WithAdminLevel6Qualifier() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-polygon-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_polygon_fixture.sqlite")
        try createCityPolygonFixtureDB(
            at: dbURL,
            fixLat: 48.890934,
            fixLon: 8.7025509,
            adminLevel6Name: "Enzkreis",
            adminLevel8Name: "Pforzheim",
            adminLevel9Name: "Buechenbronn"
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.890934,
            lon: 8.7025509,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Pforzheim - Buechenbronn (Enzkreis)")
        XCTAssertEqual(result.cityPlaceName, "Pforzheim - Buechenbronn")
        XCTAssertEqual(result.cityDistrictName, "Enzkreis")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupCityPolygonUsesAdminLevel9WhenNoAdminLevel8Exists() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-polygon-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_polygon_fixture.sqlite")
        try createCityPolygonFixtureDB(
            at: dbURL,
            fixLat: 48.8101,
            fixLon: 8.4426,
            adminLevel8Name: nil,
            adminLevel9Name: "Kullenmühle",
            fallbackPlaceName: "Bad Herrenalb",
            fallbackPlaceType: "town",
            fallbackPlaceLon: 8.4382557,
            fallbackPlaceLat: 48.7990507
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.8101,
            lon: 8.4426,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Kullenmühle")
        XCTAssertEqual(result.cityPlaceName, "Kullenmühle")
        XCTAssertNil(result.cityDistrictName)
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupCityPolygonFallsBackToAreasWhenPolygonTablesAreEmpty() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-polygon-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_polygon_fixture.sqlite")
        try createCityPolygonFixtureDB(
            at: dbURL,
            fixLat: 48.890934,
            fixLon: 8.7025509,
            adminLevel6Name: "Pforzheim",
            includePolygonBoundaryRows: false,
            includeAreaAdminRows: true
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.890934,
            lon: 8.7025509,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Pforzheim")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupCityPolygonFallsBackToAreasWhenPolygonRowsHaveNoRings() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-city-polygon-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("city_polygon_fixture.sqlite")
        try createCityPolygonFixtureDB(
            at: dbURL,
            fixLat: 48.890934,
            fixLon: 8.7025509,
            adminLevel6Name: "Pforzheim",
            includePolygonRings: false,
            includeAreaAdminRows: true
        )
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        let result = try service.lookupSpeedLimit(
            lat: 48.890934,
            lon: 8.7025509,
            radiusM: 120.0,
            maxCandidates: 64
        )

        XCTAssertEqual(result.cityName, "Pforzheim")
        XCTAssertEqual(result.insideCity, true)
        XCTAssertEqual(result.citySource, "admin_polygon")
        XCTAssertEqual(result.speedLimitKmh, 50)
    }

    func testLookupFailsForLegacySchemaWithoutWayGeomAndApproxHeading() throws {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory.appendingPathComponent("speedconsumer-legacy-\(UUID().uuidString)", isDirectory: true)
        try fm.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer {
            try? fm.removeItem(at: tempDir)
        }

        let dbURL = tempDir.appendingPathComponent("legacy_fixture.sqlite")
        try createLegacyFixtureDB(at: dbURL)
        let service = V3SpeedLimitService(dbPath: dbURL.path)

        XCTAssertThrowsError(
            try service.lookupSpeedLimit(
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
        )
    }

    private enum AdjacentBundleFixture {
        case badenWuerttemberg
        case rheinlandPfalz
    }

    private func createAdjacentBundleFixtureDB(at url: URL, fixture: AdjacentBundleFixture) throws {
        try createFixtureV3DB(at: url)
        switch fixture {
        case .badenWuerttemberg:
            try executeSQL(
                at: url,
                sql: """
                UPDATE ways
                SET way_id='17721265', highway='primary', street_name='Bundesstrasse 10', ref='B10', maxspeed='30',
                    min_lon=8.4600, min_lat=49.1000, max_lon=8.4990, max_lat=49.1400
                WHERE row_id=1;
                UPDATE ways_rtree
                SET way_id=17721265, min_lon=8.4600, max_lon=8.4990, min_lat=49.1000, max_lat=49.1400
                WHERE way_id=100;
                UPDATE way_geom
                SET way_id='17721265', points_json='[[49.1000,8.4600],[49.1400,8.4990]]'
                WHERE row_id=1;
                UPDATE ways
                SET way_id='17721266', highway='secondary', street_name='Landstrasse BW', ref='L605', maxspeed='70',
                    min_lon=8.4300, min_lat=49.0500, max_lon=8.4500, max_lat=49.0700
                WHERE row_id=2;
                UPDATE ways_rtree
                SET way_id=17721266, min_lon=8.4300, max_lon=8.4500, min_lat=49.0500, max_lat=49.0700
                WHERE way_id=200;
                UPDATE way_geom
                SET way_id='17721266', points_json='[[49.0500,8.4300],[49.0700,8.4500]]'
                WHERE row_id=2;
                UPDATE areas SET name='Baden-Wuerttemberg Teststadt' WHERE row_id=1;
                """
            )
        case .rheinlandPfalz:
            try executeSQL(
                at: url,
                sql: """
                UPDATE ways
                SET way_id='27721265', highway='primary', street_name='Bundesstrasse 10', ref='B10', maxspeed='50',
                    min_lon=8.5010, min_lat=49.1000, max_lon=8.5400, max_lat=49.1400
                WHERE row_id=1;
                UPDATE ways_rtree
                SET way_id=27721265, min_lon=8.5010, max_lon=8.5400, min_lat=49.1000, max_lat=49.1400
                WHERE way_id=100;
                UPDATE way_geom
                SET way_id='27721265', points_json='[[49.1000,8.5010],[49.1400,8.5400]]'
                WHERE row_id=1;
                UPDATE ways
                SET way_id='27721266', highway='secondary', street_name='Landstrasse RP', ref='L493', maxspeed='80',
                    min_lon=8.5600, min_lat=49.0600, max_lon=8.5800, max_lat=49.0800
                WHERE row_id=2;
                UPDATE ways_rtree
                SET way_id=27721266, min_lon=8.5600, max_lon=8.5800, min_lat=49.0600, max_lat=49.0800
                WHERE way_id=200;
                UPDATE way_geom
                SET way_id='27721266', points_json='[[49.0600,8.5600],[49.0800,8.5800]]'
                WHERE row_id=2;
                UPDATE areas SET name='Rheinland-Pfalz Teststadt' WHERE row_id=1;
                """
            )
        }
    }

    private func executeSQL(at url: URL, sql: String) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 120, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 121, userInfo: [NSLocalizedDescriptionKey: "sqlite exec failed: \(err)"])
        }
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
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
          parking TEXT,
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
        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '100', 'residential', 'Fixture Main Street', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.4050, 52.5200, 13.4060, 52.5210);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (100, 13.4050, 13.4060, 52.5200, 52.5210);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '100', '[[52.5200,13.4050],[52.5210,13.4060]]');
        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '200', 'residential', 'Fixture Side Street', NULL, '50', NULL, NULL, NULL, NULL, 45.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.4072, 52.5218, 13.4080, 52.5222);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (200, 13.4072, 13.4080, 52.5218, 52.5222);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '200', '[[52.5218,13.4072],[52.5222,13.4080]]');
        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, 'w:400', 'Polygon', 'Fixture City', 'city', 'administrative', '8', NULL, NULL, NULL, 13.4040, 52.5190, 13.4090, 52.5240);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, 'w:410', 'Polygon', 'Fixture Residential Zone', NULL, NULL, NULL, 'yes', NULL, '[[13.4050,52.5200],[13.4062,52.5200],[13.4062,52.5212],[13.4050,52.5212],[13.4050,52.5200]]', 13.4050, 52.5200, 13.4062, 52.5212);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (2, 13.4050, 13.4062, 52.5200, 52.5212);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 2, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createHorizontalAccuracyRadiusFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 90, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '100', 'residential', 'Near Road', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.00000, 13.0100, 52.00000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (100, 13.0000, 13.0100, 52.00000, 52.00000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '100', '[[52.00000,13.0000],[52.00000,13.0100]]');
        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '200', 'residential', 'Far Road', NULL, '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.00009, 13.0100, 52.00009);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (200, 13.0000, 13.0100, 52.00009, 52.00009);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '200', '[[52.00009,13.0000],[52.00009,13.0100]]');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 91, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createStreetNameFallbackFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 92, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, approx_heading_deg, service, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '100', 'secondary', 'Ettlinger Straße', 'L 564', '50', 90.0, 'main', 13.0000, 52.00090, 13.0100, 52.00090);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (100, 13.0000, 13.0100, 52.00090, 52.00090);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '100', '[[52.00090,13.0000],[52.00090,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, approx_heading_deg, service, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '200', 'residential', 'Bleichweg', NULL, '30', 90.0, 'main', 13.0000, 52.00000, 13.0050, 52.00000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (200, 13.0000, 13.0050, 52.00000, 52.00000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '200', '[[52.00000,13.0000],[52.00000,13.0050]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, approx_heading_deg, service, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '300', 'residential', 'Bleichweg', NULL, '30', 90.0, 'main', 13.0050, 52.00000, 13.0100, 52.00000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (300, 13.0050, 13.0100, 52.00000, 52.00000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '300', '[[52.00000,13.0050],[52.00000,13.0100]]');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 93, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '1001', 'residential', 'East-West Way', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'parking_aisle', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0000, 51.9999, 13.0100, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1001, 13.0000, 13.0100, 51.9999, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '1001', '[[52.0000,13.0000],[52.0000,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '1002', 'residential', 'North-South Way', NULL, '50', NULL, NULL, NULL, NULL, 0.0, 'main', NULL, 'yes', NULL, NULL, '1', NULL, 13.0049, 51.9950, 13.0051, 52.0050);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1002, 13.0049, 13.0051, 51.9950, 52.0050);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '1002', '[[51.9950,13.0050],[52.0050,13.0050]]');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 102, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createTurnFeasibilityFixtureDB(at url: URL) throws {
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
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
          approx_heading_deg REAL,
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '11001', 'primary', 'Mainline West', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.05000, 13.0040, 52.05000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (11001, 13.0000, 13.0040, 52.05000, 52.05000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '11001', '[[52.05000,13.0000],[52.05000,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '11002', 'primary', 'Mainline East', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0041, 52.05000, 13.0100, 52.05000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (11002, 13.0041, 13.0100, 52.05000, 52.05000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '11002', '[[52.05000,13.0041],[52.05000,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '11003', 'tertiary', 'North Branch', NULL, '30', NULL, NULL, NULL, NULL, 0.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0041, 52.05000, 13.0041, 52.0560);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (11003, 13.0041, 13.0041, 52.05000, 52.0560);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '11003', '[[52.05000,13.0041],[52.0560,13.0041]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (11001, 11002, 0, 'shared_endpoint'),
          (11002, 11001, 0, 'shared_endpoint'),
          (11001, 11003, 0, 'shared_endpoint'),
          (11003, 11001, 0, 'shared_endpoint');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 104, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createLowSpeedSameRefJunctionFixtureDB(
        at url: URL,
        useCurvedTurn: Bool = false,
        includeWayLinks: Bool = true
    ) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 104, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let turnApproxHeading = useCurvedTurn ? 48.0 : 0.0
        let turnMaxLon = useCurvedTurn ? 13.0118 : 13.0041
        let turnPointsJSON = useCurvedTurn
            ? "[[52.06000,13.0041],[52.06150,13.0041],[52.0660,13.0118]]"
            : "[[52.06000,13.0041],[52.0660,13.0041]]"
        let sharedNodeKey = "130041000:520600000"
        let westNodeKey = "130000000:520600000"
        let eastNodeKey = "130100000:520600000"
        let turnEndNodeKey = useCurvedTurn ? "130118000:520660000" : sharedNodeKey
        let wayLinksSchema = includeWayLinks ? """
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        """ : ""
        let wayLinksSeed = includeWayLinks ? """
        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind, shared_node_key, shared_lon, shared_lat)
        VALUES
          (12001, 12002, 1, 'shared_endpoint', '\(sharedNodeKey)', 13.0041, 52.06000),
          (12002, 12001, 1, 'shared_endpoint', '\(sharedNodeKey)', 13.0041, 52.06000),
          (12001, 12003, 0, 'shared_endpoint', '\(sharedNodeKey)', 13.0041, 52.06000),
          (12003, 12001, 0, 'shared_endpoint', '\(sharedNodeKey)', 13.0041, 52.06000);
        """ : ""

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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_endpoints (
          way_id INTEGER PRIMARY KEY,
          ref_norm TEXT,
          highway TEXT,
          tunnel_flag INTEGER NOT NULL DEFAULT 0,
          start_node_key TEXT NOT NULL,
          start_lon REAL NOT NULL,
          start_lat REAL NOT NULL,
          end_node_key TEXT NOT NULL,
          end_lon REAL NOT NULL,
          end_lat REAL NOT NULL,
          way_length_m REAL NOT NULL
        );
        \(wayLinksSchema)

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '12001', 'primary', 'Jahnstraße', 'B463', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.06000, 13.0041, 52.06000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (12001, 13.0000, 13.0041, 52.06000, 52.06000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '12001', '[[52.06000,13.0000],[52.06000,13.0041]]');
        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES (12001, 'B463', 'primary', 0, '\(westNodeKey)', 13.0000, 52.06000, '\(sharedNodeKey)', 13.0041, 52.06000, 280.3);

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '12002', 'primary', 'Werderbrücke', 'B463', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0041, 52.06000, 13.0100, 52.06000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (12002, 13.0041, 13.0100, 52.06000, 52.06000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '12002', '[[52.06000,13.0041],[52.06000,13.0100]]');
        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES (12002, 'B463', 'primary', 0, '\(sharedNodeKey)', 13.0041, 52.06000, '\(eastNodeKey)', 13.0100, 52.06000, 404.5);

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '12003', 'secondary', 'Calwer Straße', 'L1135', '30', NULL, NULL, NULL, NULL, \(turnApproxHeading), 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0041, 52.06000, \(turnMaxLon), 52.0660);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (12003, 13.0041, \(turnMaxLon), 52.06000, 52.0660);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '12003', '\(turnPointsJSON)');
        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES (12003, 'L1135', 'secondary', 0, '\(sharedNodeKey)', 13.0041, 52.06000, '\(turnEndNodeKey)', \(turnMaxLon), 52.0660, \(useCurvedTurn ? 711.0 : 667.2));
        \(wayLinksSeed)
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 105, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createMatchContinuityFixtureDB(at url: URL, includeWayLinks: Bool = true) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 104, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let wayLinksSchema = includeWayLinks ? """
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        """ : ""

        let wayLinksInserts = includeWayLinks ? """
        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (5001, 5002, 1, 'shared_endpoint'),
          (5002, 5001, 1, 'shared_endpoint'),
          (6001, 6002, 0, 'shared_endpoint'),
          (6002, 6001, 0, 'shared_endpoint');
        """ : ""

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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        \(wayLinksSchema)
        CREATE TABLE way_endpoints (
          way_id INTEGER PRIMARY KEY,
          ref_norm TEXT,
          highway TEXT,
          tunnel_flag INTEGER NOT NULL DEFAULT 0,
          start_node_key TEXT NOT NULL,
          start_lon REAL NOT NULL,
          start_lat REAL NOT NULL,
          end_node_key TEXT NOT NULL,
          end_lon REAL NOT NULL,
          end_lat REAL NOT NULL,
          way_length_m REAL NOT NULL
        );
        CREATE TABLE way_continuity_group (
          continuity_group_id INTEGER PRIMARY KEY,
          continuity_kind TEXT NOT NULL,
          source_relation_id INTEGER,
          ref_norm TEXT,
          street_name_norm TEXT,
          member_count INTEGER NOT NULL
        );
        CREATE TABLE way_continuity_membership (
          way_id INTEGER NOT NULL,
          continuity_group_id INTEGER NOT NULL,
          continuity_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, continuity_group_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '5001', 'primary', 'Bundesstrasse 10 West', 'B10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.0001, 13.0040, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5001, 13.0000, 13.0040, 52.0001, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '5001', '[[52.0001,13.0000],[52.0001,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '5002', 'primary', 'Bundesstrasse 10 East', 'B10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.0001, 13.0100, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5002, 13.0043, 13.0100, 52.0001, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '5002', '[[52.0001,13.0043],[52.0001,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '5003', 'residential', 'Nearby Side Road', NULL, '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.00004, 13.0100, 52.00004);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5003, 13.0043, 13.0100, 52.00004, 52.00004);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '5003', '[[52.00004,13.0043],[52.00004,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (4, '6001', 'secondary', 'History Road', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.0100, 13.0040, 52.0100);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (6001, 13.0000, 13.0040, 52.0100, 52.0100);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (4, '6001', '[[52.0100,13.0000],[52.0100,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (5, '6002', 'secondary', 'History Road', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.01009, 13.0100, 52.01009);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (6002, 13.0043, 13.0100, 52.01009, 52.01009);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (5, '6002', '[[52.01009,13.0043],[52.01009,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (6, '6003', 'tertiary', 'Competing Road', NULL, '60', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.01006, 13.0100, 52.01006);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (6003, 13.0043, 13.0100, 52.01006, 52.01006);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (6, '6003', '[[52.01006,13.0043],[52.01006,13.0100]]');

        INSERT INTO way_endpoints(way_id, ref_norm, highway, tunnel_flag, start_node_key, start_lon, start_lat, end_node_key, end_lon, end_lat, way_length_m)
        VALUES
          (5001, 'B10', 'primary', 0, 'n5001s', 13.0000, 52.0001, 'n5001e', 13.0040, 52.0001, 274.0),
          (5002, 'B10', 'primary', 0, 'n5002s', 13.0043, 52.0001, 'n5002e', 13.0100, 52.0001, 391.0),
          (5003, '', 'residential', 0, 'n5003s', 13.0043, 52.00004, 'n5003e', 13.0100, 52.00004, 391.0),
          (6001, '', 'secondary', 0, 'n6001s', 13.0000, 52.0100, 'n6001e', 13.0040, 52.0100, 274.0),
          (6002, '', 'secondary', 0, 'n6002s', 13.0043, 52.01009, 'n6002e', 13.0100, 52.01009, 391.0),
          (6003, '', 'tertiary', 0, 'n6003s', 13.0043, 52.01006, 'n6003e', 13.0100, 52.01006, 391.0);

        INSERT INTO way_continuity_group(continuity_group_id, continuity_kind, source_relation_id, ref_norm, street_name_norm, member_count)
        VALUES
          (1, 'route_relation_connected', 9001, 'B10', 'bundesstrasse 10', 2),
          (2, 'same_street_name_connected', NULL, '', 'history road', 2);

        INSERT INTO way_continuity_membership(way_id, continuity_group_id, continuity_kind)
        VALUES
          (5001, 1, 'route_relation_connected'),
          (5002, 1, 'route_relation_connected'),
          (6001, 2, 'same_street_name_connected'),
          (6002, 2, 'same_street_name_connected');
        \(wayLinksInserts)
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 105, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createSelectiveMiniHMMFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 118, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, linked_way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '8001', 'primary', 'Mainline West', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.02000, 13.0040, 52.02000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (8001, 13.0000, 13.0040, 52.02000, 52.02000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '8001', '[[52.02000,13.0000],[52.02000,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '8002', 'primary', 'Mainline East', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0042, 52.02010, 13.0100, 52.02010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (8002, 13.0042, 13.0100, 52.02010, 52.02010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '8002', '[[52.02010,13.0042],[52.02010,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '8003', 'tertiary', 'Side Road', NULL, '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0042, 52.02005, 13.0100, 52.02005);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (8003, 13.0042, 13.0100, 52.02005, 52.02005);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '8003', '[[52.02005,13.0042],[52.02005,13.0100]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (8001, 8002, 0, 'shared_endpoint'),
          (8002, 8001, 0, 'shared_endpoint');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 119, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createTunnelTransitionFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 122, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, linked_way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '7001', 'primary', 'Surface Approach', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 51.99995, 13.0009, 52.00005);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7001, 13.0000, 13.0009, 51.99995, 52.00005);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '7001', '[[52.0000,13.0000],[52.0000,13.0009]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '7002', 'primary', 'Tunnel Section', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0010, 51.99995, 13.0020, 52.00005);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7002, 13.0010, 13.0020, 51.99995, 52.00005);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '7002', '[[52.0000,13.0010],[52.0000,13.0020]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '7003', 'primary', 'Surface Parallel', 'B 36', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0010, 52.00020, 13.0020, 52.00030);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7003, 13.0010, 13.0020, 52.00020, 52.00030);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '7003', '[[52.00025,13.0010],[52.00025,13.0020]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (7001, 7002, 1, 'shared_endpoint'),
          (7002, 7001, 1, 'shared_endpoint');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 123, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createAmbiguousTunnelPortalFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 123, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '7101', 'primary', 'Surface Approach', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.01000, 13.0009, 52.01000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7101, 13.0000, 13.0009, 52.01000, 52.01000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '7101', '[[52.01000,13.0000],[52.01000,13.0009]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '7102', 'primary', 'Tunnel Section', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0010, 52.01000, 13.0020, 52.01000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7102, 13.0010, 13.0020, 52.01000, 52.01000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '7102', '[[52.01000,13.0010],[52.01000,13.0020]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '7103', 'primary', 'Surface Continuation', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0010, 52.01008, 13.0020, 52.01008);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (7103, 13.0010, 13.0020, 52.01008, 52.01008);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '7103', '[[52.01008,13.0010],[52.01008,13.0020]]');

        INSERT INTO corridor_progress(corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m, start_depth_nodes, end_depth_nodes, corridor_span_m, corridor_span_nodes)
        VALUES
          ('tunnel', 1, 'tunnel-west', 7102, 0.0, 68.5, 1, 3, 68.5, 3),
          ('tunnel', 1, 'tunnel-east', 7102, 68.5, 0.0, 3, 1, 68.5, 3);

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind, shared_node_key, shared_lon, shared_lat)
        VALUES
          (7101, 7102, 1, 'shared_endpoint', 'tunnel-west', 13.0010, 52.01000),
          (7102, 7101, 1, 'shared_endpoint', 'tunnel-west', 13.0010, 52.01000),
          (7101, 7103, 1, 'shared_endpoint', 'surface-branch', 13.0010, 52.01004),
          (7103, 7101, 1, 'shared_endpoint', 'surface-branch', 13.0010, 52.01004);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 124, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createLongTunnelCorridorFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 124, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '8101', 'primary', 'Surface Approach', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.02000, 13.0010, 52.02000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (8101, 13.0000, 13.0010, 52.02000, 52.02000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '8101', '[[52.02000,13.0000],[52.02000,13.0010]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '8102', 'primary', 'Tunnel Mainline', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', 'yes', NULL, NULL, 'underground', '-1', NULL, 13.0010, 52.02000, 13.0040, 52.02000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (8102, 13.0010, 13.0040, 52.02000, 52.02000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '8102', '[[52.02000,13.0010],[52.02000,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '8103', 'primary', 'Surface Bypass', 'B 10', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0010, 52.02008, 13.0040, 52.02008);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (8103, 13.0010, 13.0040, 52.02008, 52.02008);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '8103', '[[52.02008,13.0010],[52.02008,13.0040]]');

        INSERT INTO corridor_progress(corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m, start_depth_nodes, end_depth_nodes, corridor_span_m, corridor_span_nodes)
        VALUES
          ('tunnel', 1, 'tunnel-west', 8102, 0.0, 205.5, 1, 5, 205.5, 5),
          ('tunnel', 1, 'tunnel-east', 8102, 205.5, 0.0, 5, 1, 205.5, 5);

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind, shared_node_key, shared_lon, shared_lat)
        VALUES
          (8101, 8102, 1, 'shared_endpoint', 'tunnel-west', 13.0010, 52.02000),
          (8102, 8101, 1, 'shared_endpoint', 'tunnel-west', 13.0010, 52.02000),
          (8101, 8103, 1, 'shared_endpoint', 'surface-branch', 13.0010, 52.02004),
          (8103, 8101, 1, 'shared_endpoint', 'surface-branch', 13.0010, 52.02004);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 125, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createMotorwayCorridorFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 123, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          shared_node_key TEXT,
          shared_lon REAL,
          shared_lat REAL,
          PRIMARY KEY(way_id, linked_way_id)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL DEFAULT 0,
          end_depth_nodes INTEGER NOT NULL DEFAULT 0,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '9301', 'primary', 'Surface Approach', 'B 462', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.06000, 13.0040, 52.06000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9301, 13.0000, 13.0040, 52.06000, 52.06000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '9301', '[[52.06000,13.0000],[52.06000,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '9302', 'motorway_link', 'Entry Ramp', 'A 5', '80', NULL, NULL, NULL, NULL, 45.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0040, 52.06000, 13.0050, 52.06010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9302, 13.0040, 13.0050, 52.06000, 52.06010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '9302', '[[52.06000,13.0040],[52.06010,13.0050]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '9303', 'motorway', 'Autobahn Mainline', 'A 5', '130', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0040, 52.06010, 13.0100, 52.06010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9303, 13.0040, 13.0100, 52.06010, 52.06010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '9303', '[[52.06010,13.0040],[52.06010,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (4, '9304', 'motorway_link', 'Exit Ramp', 'A 5', '80', NULL, NULL, NULL, NULL, 135.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0064, 52.06000, 13.0074, 52.06010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9304, 13.0064, 13.0074, 52.06000, 52.06010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (4, '9304', '[[52.06010,13.0064],[52.06000,13.0074]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (5, '9305', 'secondary', 'Exit Surface Road', 'K 5', '70', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0074, 52.06000, 13.0110, 52.06000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9305, 13.0074, 13.0110, 52.06000, 52.06000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (5, '9305', '[[52.06000,13.0074],[52.06000,13.0110]]');

        INSERT INTO corridor_progress(corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m, start_depth_nodes, end_depth_nodes, corridor_span_m, corridor_span_nodes)
        VALUES
          ('motorway', 1, 'motorway-west', 9303, 0.0, 411.0, 1, 3, 411.0, 3),
          ('motorway', 1, 'motorway-east', 9303, 411.0, 0.0, 3, 1, 411.0, 3);

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind, shared_node_key, shared_lon, shared_lat)
        VALUES
          (9301, 9302, 0, 'shared_endpoint', 'surface-entry', 13.0040, 52.06000),
          (9302, 9301, 0, 'shared_endpoint', 'surface-entry', 13.0040, 52.06000),
          (9301, 9303, 0, 'shared_endpoint', 'motorway-west', 13.0040, 52.06010),
          (9303, 9301, 0, 'shared_endpoint', 'motorway-west', 13.0040, 52.06010),
          (9302, 9303, 1, 'shared_endpoint', 'motorway-west', 13.0040, 52.06010),
          (9303, 9302, 1, 'shared_endpoint', 'motorway-west', 13.0040, 52.06010),
          (9303, 9304, 1, 'shared_endpoint', 'motorway-east', 13.0064, 52.06010),
          (9304, 9303, 1, 'shared_endpoint', 'motorway-east', 13.0064, 52.06010),
          (9303, 9305, 0, 'shared_endpoint', 'motorway-east', 13.0074, 52.06000),
          (9305, 9303, 0, 'shared_endpoint', 'motorway-east', 13.0074, 52.06000),
          (9304, 9305, 0, 'shared_endpoint', 'surface-exit', 13.0074, 52.06000),
          (9305, 9304, 0, 'shared_endpoint', 'surface-exit', 13.0074, 52.06000);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 124, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createWayLinksTransitionFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 124, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, linked_way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '9001', 'primary', 'Mainline West', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.03000, 13.0030, 52.03000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9001, 13.0000, 13.0030, 52.03000, 52.03000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '9001', '[[52.03000,13.0000],[52.03000,13.0030]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '9002', 'primary', 'Mainline East', NULL, '80', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0045, 52.03018, 13.0090, 52.03018);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9002, 13.0045, 13.0090, 52.03018, 52.03018);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '9002', '[[52.03018,13.0045],[52.03018,13.0090]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '9003', 'tertiary', 'Closer Side Road', NULL, '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.03006, 13.0090, 52.03006);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9003, 13.0043, 13.0090, 52.03006, 52.03006);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '9003', '[[52.03006,13.0043],[52.03006,13.0090]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (9001, 9002, 0, 'shared_endpoint'),
          (9002, 9001, 0, 'shared_endpoint');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 125, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createDisconnectedHopFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 125, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, linked_way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '9201', 'secondary', 'Mainline South', 'L564', '70', NULL, NULL, NULL, NULL, 0.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.04000, 13.0000, 52.04300);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9201, 13.0000, 13.0000, 52.04000, 52.04300);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '9201', '[[52.04000,13.0000],[52.04300,13.0000]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '9202', 'secondary', 'Mainline North', 'L564', '70', NULL, NULL, NULL, NULL, 0.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.04300, 13.0000, 52.04600);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9202, 13.0000, 13.0000, 52.04300, 52.04600);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '9202', '[[52.04300,13.0000],[52.04600,13.0000]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '9203', 'service', 'Parallel Driveway', NULL, '30', NULL, NULL, NULL, NULL, 0.0, 'driveway', NULL, NULL, NULL, NULL, NULL, NULL, 13.00025, 52.04305, 13.00025, 52.04420);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9203, 13.00025, 13.00025, 52.04305, 52.04420);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '9203', '[[52.04305,13.00025],[52.04420,13.00025]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (9201, 9202, 1, 'shared_endpoint'),
          (9202, 9201, 1, 'shared_endpoint');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 126, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createTraceRankingFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 126, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id INTEGER NOT NULL,
          linked_way_id INTEGER NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          link_kind TEXT NOT NULL,
          PRIMARY KEY(way_id, linked_way_id)
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '9101', 'tertiary', 'West Link', 'K1', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.04010, 13.0040, 52.04010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9101, 13.0000, 13.0040, 52.04010, 52.04010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '9101', '[[52.04010,13.0000],[52.04010,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '9102', 'tertiary', 'East Link', 'K1', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.04010, 13.0100, 52.04010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9102, 13.0043, 13.0100, 52.04010, 52.04010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '9102', '[[52.04010,13.0043],[52.04010,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '9103', 'residential', 'Best Geometric', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.04004, 13.0100, 52.04004);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9103, 13.0043, 13.0100, 52.04004, 52.04004);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '9103', '[[52.04004,13.0043],[52.04004,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (4, '9104', 'unclassified', 'Worse Geometric', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0043, 52.03996, 13.0100, 52.03996);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9104, 13.0043, 13.0100, 52.03996, 52.03996);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (4, '9104', '[[52.03996,13.0043],[52.03996,13.0100]]');

        INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind)
        VALUES
          (9101, 9102, 1, 'shared_endpoint'),
          (9102, 9101, 1, 'shared_endpoint');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 127, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createSameRefParallelRouteClassFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 128, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, approx_heading_deg, service, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '9401', 'tertiary', 'Route West', 'K 1', '50', 90.0, 'main', 13.0000, 52.07010, 13.0040, 52.07010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9401, 13.0000, 13.0040, 52.07010, 52.07010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '9401', '[[52.07010,13.0000],[52.07010,13.0040]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, approx_heading_deg, service, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '9402', 'tertiary', 'Route East', 'K 1', '50', 90.0, 'main', 13.0043, 52.07010, 13.0100, 52.07010);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9402, 13.0043, 13.0100, 52.07010, 52.07010);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '9402', '[[52.07010,13.0043],[52.07010,13.0100]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, approx_heading_deg, service, min_lon, min_lat, max_lon, max_lat)
        VALUES (3, '9403', 'service', 'Parallel Service', 'K 1', '30', 90.0, 'driveway', 13.0043, 52.07004, 13.0100, 52.07004);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (9403, 13.0043, 13.0100, 52.07004, 52.07004);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (3, '9403', '[[52.07004,13.0043],[52.07004,13.0100]]');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 129, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
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
          way_id,
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
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (100, 13.4050, 13.4060, 52.5200, 52.5210);

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

    private func createCitySignFallbackFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 105, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
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
          parking TEXT,
          traffic_sign TEXT,
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

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '3001', 'secondary', 'City Boundary Test Way', NULL, NULL, NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 51.9999, 13.0100, 52.0001);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (3001, 13.0000, 13.0100, 51.9999, 52.0001);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '3001', '[[52.0000,13.0000],[52.0000,13.0100]]');

        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, 'n:1001', 'Point', NULL, NULL, NULL, NULL, NULL, NULL, 'DE:310', NULL, 13.0020, 52.0000, 13.0020, 52.0000);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.0020, 13.0020, 52.0000, 52.0000);
        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, 'n:1002', 'Point', NULL, NULL, NULL, NULL, NULL, NULL, 'DE:311', NULL, 13.0080, 52.0000, 13.0080, 52.0000);
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (2, 13.0080, 13.0080, 52.0000, 52.0000);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 106, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createGermanLowSpeedHeuristicFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 107, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '4101', 'secondary', 'Low Speed Test Way', NULL, '30', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0000, 52.0000, 13.0040, 52.0000);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (4101, 13.0000, 13.0040, 52.0000, 52.0000);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '4101', '[[52.0000,13.0000],[52.0000,13.0040]]');
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 108, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createCityClassificationPrecedenceFixtureDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 109, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
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
          parking TEXT,
          traffic_sign TEXT,
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

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '4001', 'service', 'Service Test Way', NULL, NULL, NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0040, 52.0005, 13.0050, 52.0007);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (4001, 13.0040, 13.0050, 52.0005, 52.0007);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '4001', '[[52.0006,13.0040],[52.0006,13.0050]]');

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, '4002', 'secondary', 'Secondary Test Way', NULL, NULL, NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, 13.0040, 52.00075, 13.0050, 52.00095);
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (4002, 13.0040, 13.0050, 52.00075, 52.00095);
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (2, '4002', '[[52.00085,13.0040],[52.00085,13.0050]]');

        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (
          1,
          'w:3001',
          'Polygon',
          'Residential Test Polygon',
          NULL,
          NULL,
          NULL,
          'yes',
          NULL,
          NULL,
          '[[13.0040,52.0000],[13.0050,52.0000],[13.0050,52.0010],[13.0048,52.0010],[13.0048,52.0002],[13.0040,52.0002],[13.0040,52.0000]]',
          13.0040,
          52.0000,
          13.0050,
          52.0010
        );
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, 13.0040, 13.0050, 52.0000, 52.0010);
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 110, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createNearestPlaceFallbackFixtureDB(
        at url: URL,
        fixLat: Double,
        fixLon: Double,
        primaryPlaceName: String,
        primaryPlaceType: String,
        primaryLon: Double,
        primaryLat: Double,
        secondaryPlaceName: String,
        secondaryPlaceType: String,
        secondaryLon: Double,
        secondaryLat: Double
    ) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 109, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let minLon = String(format: "%.7f", fixLon - 0.0010)
        let maxLon = String(format: "%.7f", fixLon + 0.0010)
        let minLat = String(format: "%.7f", fixLat - 0.0002)
        let maxLat = String(format: "%.7f", fixLat + 0.0002)
        let startLon = String(format: "%.7f", fixLon - 0.0010)
        let endLon = String(format: "%.7f", fixLon + 0.0010)
        let wayLat = String(format: "%.7f", fixLat)
        let primaryLonText = String(format: "%.7f", primaryLon)
        let primaryLatText = String(format: "%.7f", primaryLat)
        let secondaryLonText = String(format: "%.7f", secondaryLon)
        let secondaryLatText = String(format: "%.7f", secondaryLat)

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
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
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
          parking TEXT,
          traffic_sign TEXT,
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

        INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, '5001', 'secondary', 'Fallback Test Way', NULL, NULL, NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, \(minLon), \(minLat), \(maxLon), \(maxLat));
        INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (5001, \(minLon), \(maxLon), \(minLat), \(maxLat));
        INSERT INTO way_geom(row_id, way_id, points_json)
        VALUES (1, '5001', '[[\(wayLat),\(startLon)],[\(wayLat),\(endLon)]]');

        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (1, 'n:primary', 'Point', '\(primaryPlaceName)', '\(primaryPlaceType)', NULL, NULL, NULL, NULL, NULL, NULL, \(primaryLonText), \(primaryLatText), \(primaryLonText), \(primaryLatText));
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (1, \(primaryLonText), \(primaryLonText), \(primaryLatText), \(primaryLatText));

        INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
        VALUES (2, 'n:secondary', 'Point', '\(secondaryPlaceName)', '\(secondaryPlaceType)', NULL, NULL, NULL, NULL, NULL, NULL, \(secondaryLonText), \(secondaryLatText), \(secondaryLonText), \(secondaryLatText));
        INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES (2, \(secondaryLonText), \(secondaryLonText), \(secondaryLatText), \(secondaryLatText));
        """

        guard sqlite3_exec(db, schema, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 110, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func createCityPolygonFixtureDB(
        at url: URL,
        fixLat: Double,
        fixLon: Double,
        adminLevel6Name: String? = nil,
        adminLevel8Name: String? = nil,
        adminLevel9Name: String? = nil,
        fallbackPlaceName: String? = nil,
        fallbackPlaceType: String? = nil,
        fallbackPlaceLon: Double? = nil,
        fallbackPlaceLat: Double? = nil,
        includePolygonBoundaryRows: Bool = true,
        includePolygonRings: Bool = true,
        includeAreaAdminRows: Bool = false
    ) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 111, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed"])
        }
        defer { sqlite3_close(db) }

        let wayMinLon = String(format: "%.7f", fixLon - 0.0010)
        let wayMaxLon = String(format: "%.7f", fixLon + 0.0010)
        let wayMinLat = String(format: "%.7f", fixLat - 0.0002)
        let wayMaxLat = String(format: "%.7f", fixLat + 0.0002)
        let wayLat = String(format: "%.7f", fixLat)
        let wayStartLon = String(format: "%.7f", fixLon - 0.0010)
        let wayEndLon = String(format: "%.7f", fixLon + 0.0010)

        let admin6Ring = "[[\(String(format: "%.7f", fixLon - 0.0300)),\(String(format: "%.7f", fixLat - 0.0300))],[\(String(format: "%.7f", fixLon + 0.0300)),\(String(format: "%.7f", fixLat - 0.0300))],[\(String(format: "%.7f", fixLon + 0.0300)),\(String(format: "%.7f", fixLat + 0.0300))],[\(String(format: "%.7f", fixLon - 0.0300)),\(String(format: "%.7f", fixLat + 0.0300))],[\(String(format: "%.7f", fixLon - 0.0300)),\(String(format: "%.7f", fixLat - 0.0300))]]"
        let admin8Ring = "[[\(String(format: "%.7f", fixLon - 0.0200)),\(String(format: "%.7f", fixLat - 0.0200))],[\(String(format: "%.7f", fixLon + 0.0200)),\(String(format: "%.7f", fixLat - 0.0200))],[\(String(format: "%.7f", fixLon + 0.0200)),\(String(format: "%.7f", fixLat + 0.0200))],[\(String(format: "%.7f", fixLon - 0.0200)),\(String(format: "%.7f", fixLat + 0.0200))],[\(String(format: "%.7f", fixLon - 0.0200)),\(String(format: "%.7f", fixLat - 0.0200))]]"
        let admin9Ring = "[[\(String(format: "%.7f", fixLon - 0.0030)),\(String(format: "%.7f", fixLat - 0.0030))],[\(String(format: "%.7f", fixLon + 0.0030)),\(String(format: "%.7f", fixLat - 0.0030))],[\(String(format: "%.7f", fixLon + 0.0030)),\(String(format: "%.7f", fixLat + 0.0030))],[\(String(format: "%.7f", fixLon - 0.0030)),\(String(format: "%.7f", fixLat + 0.0030))],[\(String(format: "%.7f", fixLon - 0.0030)),\(String(format: "%.7f", fixLat - 0.0030))]]"

        var statements: [String] = [
            """
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
              service TEXT,
              tunnel TEXT,
              bridge TEXT,
              covered TEXT,
              location TEXT,
              layer TEXT,
              level TEXT,
              min_lon REAL NOT NULL,
              min_lat REAL NOT NULL,
              max_lon REAL NOT NULL,
              max_lat REAL NOT NULL
            );
            CREATE VIRTUAL TABLE ways_rtree USING rtree(
              way_id,
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
              parking TEXT,
              traffic_sign TEXT,
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
            CREATE TABLE city_boundary (
              row_id INTEGER PRIMARY KEY,
              osm_type TEXT NOT NULL,
              osm_id INTEGER NOT NULL,
              admin_level INTEGER NOT NULL,
              name TEXT,
              min_lon REAL NOT NULL,
              min_lat REAL NOT NULL,
              max_lon REAL NOT NULL,
              max_lat REAL NOT NULL
            );
            CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(
              row_id,
              min_lon, max_lon,
              min_lat, max_lat
            );
            CREATE TABLE city_ring (
              boundary_row_id INTEGER NOT NULL,
              ring_index INTEGER NOT NULL,
              outer_index INTEGER NOT NULL,
              is_hole INTEGER NOT NULL,
              points_json TEXT NOT NULL
            );
            CREATE TABLE city_place (
              row_id INTEGER PRIMARY KEY,
              place TEXT NOT NULL,
              name TEXT NOT NULL,
              lon REAL NOT NULL,
              lat REAL NOT NULL
            );
            CREATE VIRTUAL TABLE city_place_rtree USING rtree(
              row_id,
              min_lon, max_lon,
              min_lat, max_lat
            );

            INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level, min_lon, min_lat, max_lon, max_lat)
            VALUES (1, '6001', 'secondary', 'Polygon Test Way', NULL, NULL, NULL, NULL, NULL, NULL, 90.0, 'main', NULL, NULL, NULL, NULL, NULL, NULL, \(wayMinLon), \(wayMinLat), \(wayMaxLon), \(wayMaxLat));
            INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
            VALUES (6001, \(wayMinLon), \(wayMaxLon), \(wayMinLat), \(wayMaxLat));
            INSERT INTO way_geom(row_id, way_id, points_json)
            VALUES (1, '6001', '[[\(wayLat),\(wayStartLon)],[\(wayLat),\(wayEndLon)]]');
            """
        ]

        if includePolygonBoundaryRows, let adminLevel6Name {
            var sql = """
                INSERT INTO city_boundary(row_id, osm_type, osm_id, admin_level, name, min_lon, min_lat, max_lon, max_lat)
                VALUES (1, 'relation', 6001, 6, '\(adminLevel6Name)', \(String(format: "%.7f", fixLon - 0.0300)), \(String(format: "%.7f", fixLat - 0.0300)), \(String(format: "%.7f", fixLon + 0.0300)), \(String(format: "%.7f", fixLat + 0.0300)));
                INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, \(String(format: "%.7f", fixLon - 0.0300)), \(String(format: "%.7f", fixLon + 0.0300)), \(String(format: "%.7f", fixLat - 0.0300)), \(String(format: "%.7f", fixLat + 0.0300)));
                """
            if includePolygonRings {
                sql += """

                    INSERT INTO city_ring(boundary_row_id, ring_index, outer_index, is_hole, points_json)
                    VALUES (1, 0, 0, 0, '\(admin6Ring)');
                    """
            }
            statements.append(sql)
        }

        if includePolygonBoundaryRows, let adminLevel8Name {
            var sql = """
                INSERT INTO city_boundary(row_id, osm_type, osm_id, admin_level, name, min_lon, min_lat, max_lon, max_lat)
                VALUES (2, 'relation', 8001, 8, '\(adminLevel8Name)', \(String(format: "%.7f", fixLon - 0.0200)), \(String(format: "%.7f", fixLat - 0.0200)), \(String(format: "%.7f", fixLon + 0.0200)), \(String(format: "%.7f", fixLat + 0.0200)));
                INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (2, \(String(format: "%.7f", fixLon - 0.0200)), \(String(format: "%.7f", fixLon + 0.0200)), \(String(format: "%.7f", fixLat - 0.0200)), \(String(format: "%.7f", fixLat + 0.0200)));
                """
            if includePolygonRings {
                sql += """

                    INSERT INTO city_ring(boundary_row_id, ring_index, outer_index, is_hole, points_json)
                    VALUES (2, 0, 0, 0, '\(admin8Ring)');
                    """
            }
            statements.append(sql)
        }

        if includePolygonBoundaryRows, let adminLevel9Name {
            var sql = """
                INSERT INTO city_boundary(row_id, osm_type, osm_id, admin_level, name, min_lon, min_lat, max_lon, max_lat)
                VALUES (3, 'relation', 9001, 9, '\(adminLevel9Name)', \(String(format: "%.7f", fixLon - 0.0030)), \(String(format: "%.7f", fixLat - 0.0030)), \(String(format: "%.7f", fixLon + 0.0030)), \(String(format: "%.7f", fixLat + 0.0030)));
                INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (3, \(String(format: "%.7f", fixLon - 0.0030)), \(String(format: "%.7f", fixLon + 0.0030)), \(String(format: "%.7f", fixLat - 0.0030)), \(String(format: "%.7f", fixLat + 0.0030)));
                """
            if includePolygonRings {
                sql += """

                    INSERT INTO city_ring(boundary_row_id, ring_index, outer_index, is_hole, points_json)
                    VALUES (3, 0, 0, 0, '\(admin9Ring)');
                    """
            }
            statements.append(sql)
        }

        if includeAreaAdminRows, let adminLevel6Name {
            statements.append(
                """
                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
                VALUES (101, 'r:area-6001', 'Polygon', '\(adminLevel6Name)', NULL, 'administrative', '6', NULL, NULL, NULL, '\(admin6Ring)', \(String(format: "%.7f", fixLon - 0.0300)), \(String(format: "%.7f", fixLat - 0.0300)), \(String(format: "%.7f", fixLon + 0.0300)), \(String(format: "%.7f", fixLat + 0.0300)));
                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (101, \(String(format: "%.7f", fixLon - 0.0300)), \(String(format: "%.7f", fixLon + 0.0300)), \(String(format: "%.7f", fixLat - 0.0300)), \(String(format: "%.7f", fixLat + 0.0300)));
                """
            )
        }

        if includeAreaAdminRows, let adminLevel8Name {
            statements.append(
                """
                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
                VALUES (102, 'r:area-8001', 'Polygon', '\(adminLevel8Name)', NULL, 'administrative', '8', NULL, NULL, NULL, '\(admin8Ring)', \(String(format: "%.7f", fixLon - 0.0200)), \(String(format: "%.7f", fixLat - 0.0200)), \(String(format: "%.7f", fixLon + 0.0200)), \(String(format: "%.7f", fixLat + 0.0200)));
                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (102, \(String(format: "%.7f", fixLon - 0.0200)), \(String(format: "%.7f", fixLon + 0.0200)), \(String(format: "%.7f", fixLat - 0.0200)), \(String(format: "%.7f", fixLat + 0.0200)));
                """
            )
        }

        if includeAreaAdminRows, let adminLevel9Name {
            statements.append(
                """
                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json, min_lon, min_lat, max_lon, max_lat)
                VALUES (103, 'r:area-9001', 'Polygon', '\(adminLevel9Name)', NULL, 'administrative', '9', NULL, NULL, NULL, '\(admin9Ring)', \(String(format: "%.7f", fixLon - 0.0030)), \(String(format: "%.7f", fixLat - 0.0030)), \(String(format: "%.7f", fixLon + 0.0030)), \(String(format: "%.7f", fixLat + 0.0030)));
                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (103, \(String(format: "%.7f", fixLon - 0.0030)), \(String(format: "%.7f", fixLon + 0.0030)), \(String(format: "%.7f", fixLat - 0.0030)), \(String(format: "%.7f", fixLat + 0.0030)));
                """
            )
        }

        if let fallbackPlaceName,
           let fallbackPlaceType,
           let fallbackPlaceLon,
           let fallbackPlaceLat {
            let lonText = String(format: "%.7f", fallbackPlaceLon)
            let latText = String(format: "%.7f", fallbackPlaceLat)
            statements.append(
                """
                INSERT INTO city_place(row_id, place, name, lon, lat)
                VALUES (1, '\(fallbackPlaceType)', '\(fallbackPlaceName)', \(lonText), \(latText));
                INSERT INTO city_place_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, \(lonText), \(lonText), \(latText), \(latText));
                """
            )
        }

        let sql = statements.joined(separator: "\n")
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            let err = String(cString: sqlite3_errmsg(db))
            throw NSError(domain: "SpeedConsumerTests", code: 112, userInfo: [NSLocalizedDescriptionKey: "sqlite schema failed: \(err)"])
        }
    }

    private func sha256Hex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private func zlibCompressedData(_ data: Data) throws -> Data {
        if #available(iOS 13.0, macOS 10.15, *) {
            return try (data as NSData).compressed(using: .zlib) as Data
        }
        throw NSError(
            domain: "SpeedConsumerTests",
            code: 109,
            userInfo: [NSLocalizedDescriptionKey: "zlib compression requires iOS 13+"]
        )
    }

    private func gzipCompressedData(_ data: Data) throws -> Data {
        let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent("speedconsumer-gzip-\(UUID().uuidString).gz")
        defer {
            try? FileManager.default.removeItem(at: tempURL)
        }
        var gzipFileHandle: gzFile?
        do {
            gzipFileHandle = gzopen(tempURL.path, "wb")
            guard let handle = gzipFileHandle else {
                throw NSError(
                    domain: "SpeedConsumerTests",
                    code: 110,
                    userInfo: [NSLocalizedDescriptionKey: "Failed to open gzip temp file"]
                )
            }

            var writeError: Error?
            data.withUnsafeBytes { rawBuffer in
                guard let baseAddress = rawBuffer.baseAddress else {
                    return
                }
                var offset = 0
                while offset < data.count {
                    let remaining = min(256 * 1024, data.count - offset)
                    let written = gzwrite(handle, baseAddress.advanced(by: offset), UInt32(remaining))
                    if written <= 0 {
                        var errorCode: Int32 = 0
                        let messagePtr = gzerror(handle, &errorCode)
                        let message = messagePtr.map { String(cString: $0) } ?? "unknown gzip write failure"
                        writeError = NSError(
                            domain: "SpeedConsumerTests",
                            code: 111,
                            userInfo: [NSLocalizedDescriptionKey: "Failed to write gzip data: \(message)"]
                        )
                        break
                    }
                    offset += Int(written)
                }
            }
            if let writeError {
                throw writeError
            }
            guard gzclose(handle) == Z_OK else {
                throw NSError(
                    domain: "SpeedConsumerTests",
                    code: 112,
                    userInfo: [NSLocalizedDescriptionKey: "Failed to finalize gzip output"]
                )
            }
            gzipFileHandle = nil
            return try Data(contentsOf: tempURL)
        } catch {
            if let gzipFileHandle {
                gzclose(gzipFileHandle)
            }
            throw error
        }
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

    private func repoRootURL() -> URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func canonicalPath(_ path: String) -> String {
        URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL.path
    }

    private func assertPathEqual(
        _ actual: String?,
        _ expected: String?,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(
            actual.map(canonicalPath(_:)),
            expected.map(canonicalPath(_:)),
            file: file,
            line: line
        )
    }

    private func privateDriveMatchLogURL(environmentKey: String) throws -> URL {
        guard let rawPath = ProcessInfo.processInfo.environment[environmentKey]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
              !rawPath.isEmpty else {
            throw XCTSkip("Set \(environmentKey) to an untracked local drive-log fixture to run this optional regression")
        }
        let url = URL(fileURLWithPath: rawPath)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw XCTSkip("Optional private drive-log fixture does not exist: \(url.path)")
        }
        return url
    }

    private func allInspectorDriveMatchLogURLs() throws -> [URL] {
        let logsDirectory = repoRootURL()
            .appendingPathComponent("inspector", isDirectory: true)
            .appendingPathComponent("logs", isDirectory: true)
        guard FileManager.default.fileExists(atPath: logsDirectory.path) else {
            throw XCTSkip("Missing optional inspector drive log directory \(logsDirectory.path)")
        }
        let urls = try FileManager.default.contentsOfDirectory(
            at: logsDirectory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        )
            .filter { $0.lastPathComponent.contains("drive_match_log") && $0.pathExtension == "ndjson" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        if urls.isEmpty {
            throw XCTSkip("No optional drive match logs found in \(logsDirectory.path)")
        }
        let filtered = try urls.filter(logContainsFixID(_:))
        if filtered.isEmpty {
            throw XCTSkip("No optional drive match logs with fixID found in \(logsDirectory.path)")
        }
        return filtered
    }

    private func geomInspectorDriveMatchLogURLs() throws -> [URL] {
        let logsRoot = repoRootURL()
            .appendingPathComponent("inspector", isDirectory: true)
            .appendingPathComponent("logs", isDirectory: true)
        let candidateDirectories = [
            logsRoot.appendingPathComponent("geom", isDirectory: true),
            logsRoot.appendingPathComponent("replay_debug", isDirectory: true)
                .appendingPathComponent("geom", isDirectory: true),
        ]
        for logsDirectory in candidateDirectories {
            guard FileManager.default.fileExists(atPath: logsDirectory.path) else {
                continue
            }
            let urls = try FileManager.default.contentsOfDirectory(
                at: logsDirectory,
                includingPropertiesForKeys: nil,
                options: [.skipsHiddenFiles]
            )
                .filter { $0.lastPathComponent.contains("drive_match_log") && $0.pathExtension == "ndjson" }
                .sorted { $0.lastPathComponent < $1.lastPathComponent }
            if !urls.isEmpty {
                let filtered = try urls.filter(logContainsFixID(_:))
                if !filtered.isEmpty {
                    return filtered
                }
            }
        }
        throw XCTSkip("No optional geom drive match logs found in \(candidateDirectories.map(\.path).joined(separator: ", "))")
    }

    private func logContainsFixID(_ url: URL) throws -> Bool {
        let content = try String(contentsOf: url, encoding: .utf8)
        for line in content.split(whereSeparator: \.isNewline) {
            let data = Data(line.utf8)
            guard let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                continue
            }
            return payload["fixID"] != nil
        }
        return false
    }

    private func bundledSpeedDBURL() -> URL? {
        let env = ProcessInfo.processInfo.environment
        if let overridePath = env["SPEEDCONSUMER_BUNDLED_DB_PATH"],
           !overridePath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return URL(fileURLWithPath: overridePath)
        }
        let rawCandidates: [(resource: String, ext: String)] = [
            ("karlsruhe-regbez_speeds", "sqlite"),
            ("speeds_v3", "sqlite"),
            ("DEU-latest.speeds_v3", "sqlite"),
        ]
        for candidate in rawCandidates {
            if let url = Bundle.main.url(forResource: candidate.resource, withExtension: candidate.ext) {
                return url
            }
            if let url = Bundle(for: SpeedConsumerAppDelegate.self).url(forResource: candidate.resource, withExtension: candidate.ext) {
                return url
            }
        }
        return nil
    }

    private func loadDriveMatchLogEntries(url: URL, fixIDRange: ClosedRange<Int>? = nil) throws -> [DriveMatchLogEntry] {
        let decoder = JSONDecoder()
        let content = try String(contentsOf: url, encoding: .utf8)
        return try content
            .split(whereSeparator: \.isNewline)
            .compactMap { line -> DriveMatchLogEntry? in
                let entry = try decoder.decode(DriveMatchLogEntry.self, from: Data(line.utf8))
                if let fixIDRange, !fixIDRange.contains(entry.fixID) {
                    return nil
                }
                return entry
            }
    }

    private func hindsightPseudoLabelWayID(
        in entries: [DriveMatchLogEntry],
        at index: Int,
        futureWindow: Int,
        minFutureRunLength: Int,
        minAgreementRatio: Double
    ) -> String? {
        guard index >= 0, index < entries.count else {
            return nil
        }
        let entry = entries[index]
        guard let rowResult = entry.result else {
            return nil
        }
        let candidateWayIDs = rowResult.candidateTraces.compactMap(\.wayID)
        guard !candidateWayIDs.isEmpty else {
            return nil
        }

        let upperBound = index + 1 + futureWindow
        guard upperBound <= entries.count else {
            return nil
        }
        let futureWayIDs = entries[(index + 1) ..< upperBound].compactMap { $0.result?.wayID }
        guard futureWayIDs.count == futureWindow else {
            return nil
        }

        let agreementThreshold = Int(ceil(Double(futureWindow) * minAgreementRatio))
        let majority = Dictionary(futureWayIDs.map { ($0, 1) }, uniquingKeysWith: +)
            .max { lhs, rhs in
                if lhs.value != rhs.value {
                    return lhs.value < rhs.value
                }
                return lhs.key > rhs.key
            }
        guard let majorityWayID = majority?.key,
              let agreementCount = majority?.value,
              agreementCount >= agreementThreshold,
              candidateWayIDs.contains(majorityWayID) else {
            return nil
        }

        var futureRunLength = 0
        for futureWayID in futureWayIDs {
            guard futureWayID == majorityWayID else {
                break
            }
            futureRunLength += 1
        }
        return futureRunLength >= minFutureRunLength ? majorityWayID : nil
    }

    private func countABAOscillations(_ ids: [String?]) -> Int {
        guard ids.count >= 3 else {
            return 0
        }
        var count = 0
        for index in 2 ..< ids.count {
            guard let lhs = ids[index - 2],
                  let middle = ids[index - 1],
                  let rhs = ids[index] else {
                continue
            }
            if lhs == rhs, lhs != middle {
                count += 1
            }
        }
        return count
    }

    private func countSameRefABAOscillations(
        wayIDs: [String?],
        refs: [String?]
    ) -> Int {
        guard wayIDs.count == refs.count, wayIDs.count >= 3 else {
            return 0
        }
        var count = 0
        for index in 2 ..< wayIDs.count {
            guard let lhsWayID = wayIDs[index - 2],
                  let middleWayID = wayIDs[index - 1],
                  let rhsWayID = wayIDs[index],
                  let lhsRef = refs[index - 2]?.trimmingCharacters(in: .whitespacesAndNewlines),
                  let middleRef = refs[index - 1]?.trimmingCharacters(in: .whitespacesAndNewlines),
                  let rhsRef = refs[index]?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !lhsRef.isEmpty,
                  lhsRef == middleRef,
                  lhsRef == rhsRef else {
                continue
            }
            if lhsWayID == rhsWayID, lhsWayID != middleWayID {
                count += 1
            }
        }
        return count
    }

    private func isPortalEligibleTunnelTrace(_ trace: MatchCandidateTrace) -> Bool {
        let isTunnel = (trace.tunnel ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "yes"
        guard isTunnel else {
            return false
        }
        if let portalEligible = trace.portalEligible {
            return portalEligible
        }
        return (trace.corridorSelectable ?? false) && trace.tunnelSelectable
    }

    private func hasPortalEligibleTunnelCandidate(_ result: SpeedLimitResult?) -> Bool {
        guard let result else {
            return false
        }
        return result.candidateTraces.contains(where: isPortalEligibleTunnelTrace)
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

    private func readPresentWayIDs(dbURL: URL, wayIDs: [String]) throws -> Set<String> {
        let uniqueWayIDs = Array(Set(wayIDs))
        guard !uniqueWayIDs.isEmpty else {
            return []
        }
        var db: OpaquePointer?
        let encodedPath = dbURL.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbURL.path
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 35, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(dbURL.path)"])
        }
        defer { sqlite3_close(db) }

        let placeholders = uniqueWayIDs.enumerated().map { "?\($0.offset + 1)" }.joined(separator: ",")
        let sql = "SELECT way_id FROM ways WHERE way_id IN (\(placeholders))"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw NSError(domain: "SpeedConsumerTests", code: 36, userInfo: [NSLocalizedDescriptionKey: "prepare present way query failed"])
        }
        defer { sqlite3_finalize(stmt) }

        for (index, wayID) in uniqueWayIDs.enumerated() {
            sqlite3_bind_text(stmt, Int32(index + 1), wayID, -1, SQLITE_TRANSIENT)
        }

        var out: Set<String> = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let value = sqlite3_column_text(stmt, 0).map({ String(cString: $0) }) {
                out.insert(value)
            }
        }
        return out
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

        let joinCondition: String
        if try readColumnNames(dbURL: dbURL, table: "ways_rtree").contains("way_id") {
            joinCondition = "w.way_id = r.way_id"
        } else {
            joinCondition = "w.row_id = r.row_id"
        }

        let sql = """
        SELECT w.way_id
        FROM ways_rtree r
        JOIN ways w ON \(joinCondition)
        WHERE r.min_lon <= ?1 AND r.max_lon >= ?2
          AND r.min_lat <= ?3 AND r.max_lat >= ?4
        LIMIT ?5
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            let message = String(cString: sqlite3_errmsg(db))
            throw NSError(
                domain: "SpeedConsumerTests",
                code: 32,
                userInfo: [NSLocalizedDescriptionKey: "prepare candidate query failed: \(message)"]
            )
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

    private struct BundledMatchContextState {
        var recentWayIDs: [String] = []
        var recentFixes: [WayMatchRecentFix] = []
        var recentStreetRefs: [String] = []
        var recentHypotheses: [WayMatchHypothesis] = []
        var recentTunnelCandidateWayIDs: [String] = []
        var recentTunnelCandidateRefs: [String] = []
        var recentTunnelApproachWayIDs: [String] = []
        var recentTunnelApproachRefs: [String] = []
        var preferredWayID: String?
        var preferredHighway: String?
        var preferredEndpointProximityM: Double?
        var matchedFixCount = 0
        var tunnelApproachFixCount = 0
        var tunnelApproachBaselineAccuracyM: Double?
        var tunnelApproachBaselineSignalBars: Int?
        var isInTunnelMode = false
        var isInMotorwayMode = false
        var activeCorridorState: CorridorMatchState?
        var approachCorridorState: CorridorMatchState?
        var approachCorridorFixCount = 0
        var approachCorridorStartDepthM: Double?
        var approachCorridorStartDepthNodes: Int?

        var context: WayMatchContext? {
            guard preferredWayID != nil ||
                    !recentWayIDs.isEmpty ||
                    !recentFixes.isEmpty ||
                    !recentStreetRefs.isEmpty ||
                    !recentHypotheses.isEmpty ||
                    !recentTunnelCandidateWayIDs.isEmpty ||
                    !recentTunnelCandidateRefs.isEmpty ||
                    !recentTunnelApproachWayIDs.isEmpty ||
                    !recentTunnelApproachRefs.isEmpty ||
                    tunnelApproachFixCount > 0 ||
                    isInMotorwayMode ||
                    activeCorridorState != nil ||
                    approachCorridorState != nil ||
                    approachCorridorStartDepthM != nil ||
                    approachCorridorStartDepthNodes != nil ||
                    isInTunnelMode else {
                return nil
            }
            return WayMatchContext(
                preferredWayID: preferredWayID,
                preferredHighway: preferredHighway,
                preferredEndpointProximityM: preferredEndpointProximityM,
                recentWayIDs: recentWayIDs,
                recentFixes: recentFixes,
                preferredStreetRef: recentStreetRefs.first,
                recentStreetRefs: recentStreetRefs,
                recentTunnelCandidateWayIDs: recentTunnelCandidateWayIDs,
                recentTunnelCandidateRefs: recentTunnelCandidateRefs,
                recentTunnelApproachWayIDs: recentTunnelApproachWayIDs,
                recentTunnelApproachRefs: recentTunnelApproachRefs,
                tunnelApproachFixCount: tunnelApproachFixCount,
                tunnelApproachBaselineAccuracyM: tunnelApproachBaselineAccuracyM,
                tunnelApproachBaselineSignalBars: tunnelApproachBaselineSignalBars,
                recentHypotheses: recentHypotheses,
                matchedFixCount: matchedFixCount,
                isInTunnelMode: isInTunnelMode,
                isInMotorwayMode: isInMotorwayMode,
                activeCorridorState: activeCorridorState,
                approachCorridorState: approachCorridorState,
                approachCorridorFixCount: approachCorridorFixCount,
                approachCorridorStartDepthM: approachCorridorStartDepthM,
                approachCorridorStartDepthNodes: approachCorridorStartDepthNodes
            )
        }

        mutating func record(
            _ result: SpeedLimitResult,
            lat: Double? = nil,
            lon: Double? = nil,
            headingDeg: Double? = nil,
            headingAccuracyDeg: Double? = nil,
            speedKmh: Double? = nil,
            horizontalAccuracyM: Double,
            gpsSignalBars: Int
        ) {
            if let wayID = result.wayID {
                matchedFixCount += 1
                recentWayIDs.removeAll(where: { $0 == wayID })
                recentWayIDs.insert(wayID, at: 0)
                if recentWayIDs.count > 5 {
                    recentWayIDs.removeLast(recentWayIDs.count - 5)
                }
                preferredWayID = wayID
            }
            if let lat, let lon {
                recentFixes.insert(
                    WayMatchRecentFix(
                        lat: lat,
                        lon: lon,
                        headingDeg: headingDeg,
                        headingAccuracyDeg: headingAccuracyDeg,
                        speedKmh: speedKmh,
                        horizontalAccuracyM: horizontalAccuracyM,
                        gpsSignalBars: gpsSignalBars
                    ),
                    at: 0
                )
                if recentFixes.count > 10 {
                    recentFixes.removeLast(recentFixes.count - 10)
                }
            }
            preferredHighway = result.highway
            preferredEndpointProximityM = result.matchedEndpointProximityM
            for ref in V3SpeedLimitService.normalizedRefTokens(result.streetRef) {
                recentStreetRefs.removeAll(where: { $0 == ref })
                recentStreetRefs.insert(ref, at: 0)
                if recentStreetRefs.count > 6 {
                    recentStreetRefs.removeLast(recentStreetRefs.count - 6)
                }
            }
            recentHypotheses = result.matchHypotheses
            recentTunnelCandidateWayIDs = result.nearbyTunnelCandidateWayIDs
            recentTunnelCandidateRefs = result.nearbyTunnelCandidateRefs
            updateTunnelApproachState(
                result: result,
                horizontalAccuracyM: horizontalAccuracyM,
                gpsSignalBars: gpsSignalBars
            )
            updateApproachCorridorState(result: result)
            activeCorridorState = result.activeCorridorState
            isInTunnelMode = result.isTunnelSegment
            let resultHighway = result.highway?.lowercased()
            if resultHighway == "motorway" {
                isInMotorwayMode = true
            } else if resultHighway == "motorway_link" {
                isInMotorwayMode = isInMotorwayMode || result.activeCorridorState?.kind == "motorway"
            } else {
                isInMotorwayMode = false
            }
        }

        private mutating func updateTunnelApproachState(
            result: SpeedLimitResult,
            horizontalAccuracyM: Double,
            gpsSignalBars: Int
        ) {
            let approachTraces = result.candidateTraces.filter(Self.isTunnelApproachCandidateTrace)
            guard !result.isTunnelSegment, !approachTraces.isEmpty else {
                recentTunnelApproachWayIDs.removeAll(keepingCapacity: false)
                recentTunnelApproachRefs.removeAll(keepingCapacity: false)
                tunnelApproachFixCount = 0
                tunnelApproachBaselineAccuracyM = nil
                tunnelApproachBaselineSignalBars = nil
                return
            }

            tunnelApproachFixCount += 1
            if horizontalAccuracyM.isFinite, horizontalAccuracyM >= 0 {
                if let baseline = tunnelApproachBaselineAccuracyM {
                    tunnelApproachBaselineAccuracyM = min(baseline, horizontalAccuracyM)
                } else {
                    tunnelApproachBaselineAccuracyM = horizontalAccuracyM
                }
            }
            tunnelApproachBaselineSignalBars = max(tunnelApproachBaselineSignalBars ?? gpsSignalBars, gpsSignalBars)

            recentTunnelApproachWayIDs.removeAll(keepingCapacity: false)
            recentTunnelApproachRefs.removeAll(keepingCapacity: false)
            for trace in approachTraces {
                if let wayID = trace.wayID {
                    recentTunnelApproachWayIDs.removeAll(where: { $0 == wayID })
                    recentTunnelApproachWayIDs.insert(wayID, at: 0)
                    if recentTunnelApproachWayIDs.count > 5 {
                        recentTunnelApproachWayIDs.removeLast(recentTunnelApproachWayIDs.count - 5)
                    }
                }
                for refToken in V3SpeedLimitService.normalizedRefTokens(trace.streetRef) {
                    recentTunnelApproachRefs.removeAll(where: { $0 == refToken })
                    recentTunnelApproachRefs.insert(refToken, at: 0)
                    if recentTunnelApproachRefs.count > 6 {
                        recentTunnelApproachRefs.removeLast(recentTunnelApproachRefs.count - 6)
                    }
                }
            }
        }

        private mutating func updateApproachCorridorState(result: SpeedLimitResult) {
            guard result.activeCorridorState == nil else {
                approachCorridorState = nil
                approachCorridorFixCount = 0
                approachCorridorStartDepthM = nil
                approachCorridorStartDepthNodes = nil
                return
            }
            let corridorTrace = result.candidateTraces.first(where: { trace in
                guard trace.corridorKind != nil,
                      trace.corridorID != nil,
                      trace.corridorSideNodeKey != nil,
                      trace.corridorDepthM != nil,
                      trace.corridorRemainingM != nil,
                      trace.corridorDepthNodes != nil,
                      trace.corridorRemainingNodes != nil else {
                    return false
                }
                guard trace.corridorKind == "tunnel" || trace.corridorKind == "motorway" else {
                    return false
                }
                return trace.corridorEntryZone == true
            }) ?? approachCorridorState.flatMap { currentState in
                result.candidateTraces.first(where: { trace in
                    guard trace.corridorKind == currentState.kind,
                          trace.corridorID == currentState.corridorID,
                          trace.corridorSideNodeKey == currentState.sideNodeKey,
                          let depthM = trace.corridorDepthM,
                          trace.corridorRemainingM != nil,
                          trace.corridorDepthNodes != nil,
                          trace.corridorRemainingNodes != nil else {
                        return false
                    }
                    return depthM + 6.0 >= currentState.depthM
                })
            }
            guard let trace = corridorTrace,
            let corridorKind = trace.corridorKind,
            let corridorID = trace.corridorID,
            let sideNodeKey = trace.corridorSideNodeKey,
            let depthM = trace.corridorDepthM,
            let remainingM = trace.corridorRemainingM,
            let depthNodes = trace.corridorDepthNodes,
            let remainingNodes = trace.corridorRemainingNodes else {
                approachCorridorState = nil
                approachCorridorFixCount = 0
                approachCorridorStartDepthM = nil
                approachCorridorStartDepthNodes = nil
                return
            }

            let nextState = CorridorMatchState(
                kind: corridorKind,
                corridorID: corridorID,
                sideNodeKey: sideNodeKey,
                depthM: depthM,
                spanM: depthM + remainingM,
                depthNodes: depthNodes,
                spanNodes: depthNodes + remainingNodes
            )
            if let currentState = approachCorridorState,
               currentState.kind == nextState.kind,
               currentState.corridorID == nextState.corridorID,
               currentState.sideNodeKey == nextState.sideNodeKey,
               nextState.depthM + 6.0 >= currentState.depthM {
                approachCorridorFixCount += 1
                let startDepthM = approachCorridorStartDepthM ?? currentState.depthM
                approachCorridorStartDepthM = min(startDepthM, nextState.depthM)
                let startDepthNodes = approachCorridorStartDepthNodes ?? currentState.depthNodes
                approachCorridorStartDepthNodes = min(startDepthNodes, nextState.depthNodes)
            } else {
                approachCorridorFixCount = 1
                approachCorridorStartDepthM = nextState.depthM
                approachCorridorStartDepthNodes = nextState.depthNodes
            }
            approachCorridorState = nextState
        }

        private static func isTunnelApproachCandidateTrace(_ trace: MatchCandidateTrace) -> Bool {
            let isTunnel = (trace.tunnel ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "yes"
            return isTunnel && trace.portalEligible == true
        }
    }

    private struct DriveLogReplayMetrics {
        var replayedFixCount = 0
        var pseudoLabelExampleCount = 0
        var correctPseudoLabelCount = 0
        var changedExampleCount = 0
        var changedCorrectCount = 0
        var unchangedExampleCount = 0
        var unchangedCorrectCount = 0
        var usedThreeWayGateCount = 0
        var usedSameRefBounceGateCount = 0
        var usedAntiABAHysteresisCount = 0

        var accuracy: Double {
            guard pseudoLabelExampleCount > 0 else {
                return 0.0
            }
            return Double(correctPseudoLabelCount) / Double(pseudoLabelExampleCount)
        }

        var changedRecall: Double {
            guard changedExampleCount > 0 else {
                return 0.0
            }
            return Double(changedCorrectCount) / Double(changedExampleCount)
        }

        var unchangedAccuracy: Double {
            guard unchangedExampleCount > 0 else {
                return 0.0
            }
            return Double(unchangedCorrectCount) / Double(unchangedExampleCount)
        }

        mutating func formUnion(_ other: DriveLogReplayMetrics) {
            replayedFixCount += other.replayedFixCount
            pseudoLabelExampleCount += other.pseudoLabelExampleCount
            correctPseudoLabelCount += other.correctPseudoLabelCount
            changedExampleCount += other.changedExampleCount
            changedCorrectCount += other.changedCorrectCount
            unchangedExampleCount += other.unchangedExampleCount
            unchangedCorrectCount += other.unchangedCorrectCount
            usedThreeWayGateCount += other.usedThreeWayGateCount
            usedSameRefBounceGateCount += other.usedSameRefBounceGateCount
            usedAntiABAHysteresisCount += other.usedAntiABAHysteresisCount
        }
    }

    private func readColumnNames(dbURL: URL, table: String) throws -> Set<String> {
        var db: OpaquePointer?
        let encodedPath = dbURL.path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? dbURL.path
        let uri = "file:\(encodedPath)?mode=ro&immutable=1"
        guard sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nil) == SQLITE_OK, let db else {
            throw NSError(domain: "SpeedConsumerTests", code: 33, userInfo: [NSLocalizedDescriptionKey: "sqlite open failed for \(dbURL.path)"])
        }
        defer { sqlite3_close(db) }

        var stmt: OpaquePointer?
        let sql = "PRAGMA table_info(\(table));"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw NSError(domain: "SpeedConsumerTests", code: 34, userInfo: [NSLocalizedDescriptionKey: "prepare table_info failed for \(table)"])
        }
        defer { sqlite3_finalize(stmt) }

        var names: Set<String> = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let namePtr = sqlite3_column_text(stmt, 1) {
                names.insert(String(cString: namePtr))
            }
        }
        return names
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
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            if let state = try await manager.activeState(),
               let dbURL = try await manager.activeDatabaseURL(),
               FileManager.default.fileExists(atPath: dbURL.path) {
                let size = (try? fileSize(dbURL)) ?? 0
                let activatedManifestURL = dbURL
                    .deletingLastPathComponent()
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

        var manifestRequest = URLRequest(url: manifestURL)
        manifestRequest.setValue("YouSpeedConsumerTests/1.0", forHTTPHeaderField: "User-Agent")
        manifestRequest.setValue("application/octet-stream", forHTTPHeaderField: "Accept")

        let (manifestData, manifestResponse) = try await session.data(for: manifestRequest)
        guard let manifestHTTP = manifestResponse as? HTTPURLResponse else {
            XCTFail("Non-HTTP response for manifest: \(manifestURL.absoluteString)")
            return
        }
        print("RELEASE_MANIFEST_CHECK status=\(manifestHTTP.statusCode) url=\(manifestURL.absoluteString)")
        XCTAssertTrue((200...299).contains(manifestHTTP.statusCode), "Manifest status=\(manifestHTTP.statusCode) url=\(manifestURL.absoluteString)")

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

            let candidateURL = rawURL

            var req = URLRequest(url: candidateURL)
            req.setValue("YouSpeedConsumerTests/1.0", forHTTPHeaderField: "User-Agent")
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
