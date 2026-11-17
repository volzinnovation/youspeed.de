import AVFoundation
import Foundation
import XCTest
import SQLite3
@testable import SpeedConsumer

final class ExpandedDEClassifierTests: XCTestCase {
    func testBundledClassifierSupportsNewArtworkWithoutInventingPlateContent() throws {
        let candidate = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        XCTAssertEqual(candidate.classLabels.count, 142)
        XCTAssertTrue(candidate.canRecognize("bus:stop"))
        XCTAssertEqual(Array(candidate.classLabels.dropFirst(134)), [
            "city:start", "city:end", "bus:stop", "supplementary:plate", "maxspeed:90",
            "DE:156-10", "DE:325.1", "DE:325.2",
        ])
        XCTAssertEqual(candidate.classLabels[136], "bus:stop")
        XCTAssertEqual(candidate.classLabels[137], "supplementary:plate")
        let bus = try XCTUnwrap(candidate.sign(for: "bus:stop"))
        XCTAssertEqual(bus.signCode, "DE:224")
        XCTAssertEqual(bus.localizedLabel(language: "de"), "Haltestelle")
        XCTAssertNotNil(bus.imageURL())
        XCTAssertEqual(candidate.sign(for: "maxspeed:90")?.signCode, "DE:274-90")
        let plate = try XCTUnwrap(candidate.sign(for: "supplementary:plate"))
        XCTAssertFalse(plate.displayEligible)
        XCTAssertNil(plate.imageURL())
        XCTAssertNil(plate.signCode)
        XCTAssertEqual(plate.localizedLabel(language: "en"), "Supplementary plate (content unresolved)")
        XCTAssertFalse(try XCTUnwrap(candidate.sign(for: "exit")).displayEligible)
        XCTAssertFalse(try XCTUnwrap(candidate.sign(for: "lanes")).displayEligible)
    }

    func testGenericPlateMappingUsesExistingRoleAndUnresolvedContent() throws {
        let url = try XCTUnwrap(Bundle.main.url(forResource: "DE.panoramax-bootstrap", withExtension: "tsrmodelpack", subdirectory: "TSRModelPacks"))
        let pack = try TrafficSignPackJSON.decoder().decode(TrafficSignModelPackManifest.self,
            from: Data(contentsOf: url.appendingPathComponent("manifest.json")))
        let catalog = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        XCTAssertEqual(pack.classMapping.count, 142)
        XCTAssertEqual(pack.classMapping.map(\.classId), catalog.classLabels)
        XCTAssertEqual(pack.classifier?.sourceCheckpoint.sha256, catalog.classifierCheckpointSHA256)
        let mapping = try XCTUnwrap(pack.classMapping.first { $0.classId == "supplementary:plate" })
        XCTAssertEqual(mapping.signRole, .supplementaryPlate)
        XCTAssertEqual(mapping.semantic.kind, .unknown)
        XCTAssertNil(mapping.semantic.value)
        XCTAssertNil(mapping.semantic.unit)
        XCTAssertEqual(mapping.restriction?.kind, .unknown)
        XCTAssertEqual(mapping.restriction?.normalizedValue, "unresolved")
        XCTAssertEqual(mapping.restriction?.isValid, true)
        XCTAssertNil(mapping.restriction?.rawText)
        XCTAssertNil(mapping.restriction?.countrySignCode)
    }
}

final class TrafficSignDocumentationTests: XCTestCase {
    func testReferenceReadsEveryNationalCatalogWithOriginalPictogramsAndSpeech() throws {
        let html = try TrafficSignDocumentationHTML.make(activeCountry: "NLD", locale: "fr")
        let marker = "window.trafficSignDocumentationInput="
        let start = try XCTUnwrap(html.range(of: marker)).upperBound
        let end = try XCTUnwrap(html.range(of: ";</script>", range: start..<html.endIndex)).lowerBound
        let input = try JSONSerialization.jsonObject(with: Data(html[start..<end].utf8)) as! [String: Any]
        XCTAssertEqual(input["activeCountry"] as? String, "NL")
        let catalogs = input["catalogs"] as! [[String: Any]]
        XCTAssertEqual(Set(catalogs.compactMap { $0["country"] as? String }), Set(["DE", "FR", "NL", "BE", "CH"]))
        let images = input["images"] as! [String: String]
        for catalog in catalogs {
            let code = catalog["country"] as! String
            let sourceURL = try XCTUnwrap(Bundle.main.url(forResource: "prolix-\(code.lowercased())-class-catalog-v1", withExtension: "json"))
            let original = try JSONSerialization.jsonObject(with: Data(contentsOf: sourceURL)) as! NSDictionary
            XCTAssertEqual(catalog as NSDictionary, original)
            for sign in catalog["signs"] as! [[String: Any]] where sign["display_eligible"] as? Bool == true {
                let path = sign["image_path"] as! String
                let encoded = try XCTUnwrap(images[path])
                let decoded = try XCTUnwrap(Data(base64Encoded: String(encoded.dropFirst("data:image/png;base64,".count))))
                let source = try Data(contentsOf: Bundle.main.resourceURL!.appendingPathComponent(String(path.dropFirst(4))))
                XCTAssertEqual(decoded, source)
            }
        }
    }
}

final class InventorySpeedEndPictogramTests: XCTestCase {
    private func inventory(code: String, value: Double? = nil, status: String = "not_applicable",
                           unit: String? = nil, pictogramCode: String? = nil,
                           source: String = "mobidata-bw-vzk") -> InventoryTrafficSign {
        .init(signID: "end", sourceID: source, recordKey: "end", snapshotSHA256: "snapshot",
              code: code, kind: "speed_limit_end", numericValue: value, unit: unit,
              parameterStatus: status, latitude: 48, longitude: 8, radiusM: 30,
              pictogramCode: pictogramCode, pictogramPath: nil, modelClasses: [], distanceM: 0)
    }

    func testExactCurveBoardReferenceDoesNotInferRedArrowCameraDirection() throws {
        let catalog = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        let exact = try XCTUnwrap(catalog.sign(forInventory: inventory(code: "DE:625-20", pictogramCode: "DE:625-20")))
        XCTAssertEqual(exact.imagePath, "tsr/sign-pictograms/png/de-625-20.png")
        XCTAssertEqual(exact.localizedLabel(language: "de"), "Richtungstafel in Kurven – rechtsweisend")
        XCTAssertNotNil(exact.imageURL())
        XCTAssertFalse(catalog.canRecognize("DE:625-20"))
        XCTAssertTrue(catalog.canRecognize("arrow:red"))
        let family = try XCTUnwrap(catalog.sign(for: "arrow:red"))
        XCTAssertFalse(family.displayEligible)
        XCTAssertNil(family.imageURL())
        XCTAssertNil(family.signCode)
    }

    func testExactInventoryCodesUseEveryReviewedEndPictogramWithoutCameraClasses() throws {
        let catalog = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        let codes = catalog.signs.compactMap(\.signCode).filter { $0.hasPrefix("DE:278-") }
        XCTAssertTrue(Set([5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
            .map { "DE:278-\($0)" }).isSubset(of: Set(codes)))
        for source in ["mobidata-bw-vzk", "osm"] {
            for code in codes {
                let sign = try XCTUnwrap(catalog.sign(forInventory: inventory(code: code, source: source)))
                XCTAssertEqual(sign.signCode, code)
                XCTAssertNotNil(sign.imageURL(), "Missing shared asset for \(code)")
                XCTAssertFalse(catalog.canRecognize(code), "Inventory artwork must not expand camera classes")
            }
        }
    }

    func testParsedInventoryEndValueSelectsExactArtworkWithoutPictogramMetadata() throws {
        let catalog = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        for source in ["mobidata-bw-vzk", "osm"] {
            let sign = catalog.sign(forInventory: inventory(code: "DE:278", value: 70,
                status: "parsed_source_value", unit: "km/h", source: source))
            XCTAssertEqual(sign?.imagePath, "tsr/sign-pictograms/png/de-278-70.png")
        }
        XCTAssertEqual(catalog.sign(forInventory: inventory(code: "DE:278-30", value: 70,
            status: "parsed_source_value", pictogramCode: "DE:278-70"))?.signCode, "DE:278-30")
        XCTAssertEqual(inventory(code: "DE:278-30", value: 70, status: "parsed_source_value", unit: "mph").parameterText, "30 km/h")
        for code in ["DE:278[70]", "DE:278[70 km/h]", "DE:278-070", "DE:278[070]"] {
            XCTAssertEqual(catalog.sign(forInventory: inventory(code: code, source: "osm"))?.signCode, "DE:278-70")
        }
    }

    func testUnknownInvalidAndUnsupportedEndValuesNeverInventArtwork() throws {
        let catalog = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        for source in ["mobidata-bw-vzk", "osm"] {
            for missing in [inventory(code: "DE:278", pictogramCode: "DE:278-30", source: source),
                            inventory(code: "DE:278", value: 30, status: "missing_value", source: source)] {
                let fallback = try XCTUnwrap(catalog.sign(forInventory: missing))
                XCTAssertEqual(fallback.signCode, "DE:278")
                XCTAssertEqual(fallback.imagePath, "tsr/sign-pictograms/png/de-282.png")
                XCTAssertNotNil(fallback.imageURL())
                XCTAssertFalse(catalog.canRecognize("DE:278"))
            }
        }
        let cases = [
            inventory(code: "DE:278", value: 30, status: "parsed_source_value", unit: "mph"),
            inventory(code: "DE:278", value: 30.5, status: "parsed_source_value"),
            inventory(code: "DE:278", value: .nan, status: "parsed_source_value"),
            inventory(code: "DE:278", value: .infinity, status: "parsed_source_value"),
            inventory(code: "DE:278", value: 35, status: "parsed_source_value"),
            inventory(code: "DE:278-35", pictogramCode: "DE:278-30"),
            inventory(code: "DE:278-invalid", value: 30, status: "parsed_source_value"),
            inventory(code: "DE:278[70 mph]", pictogramCode: "DE:278-70"),
            inventory(code: "DE:278[70.5]", pictogramCode: "DE:278-70"),
            inventory(code: "DE:274", value: 30, status: "parsed_source_value"),
        ]
        for sign in cases { XCTAssertNil(catalog.sign(forInventory: sign), sign.code) }
        XCTAssertEqual(catalog.sign(forInventory: inventory(code: "DE:205", pictogramCode: "DE:205"))?.signCode, "DE:205")
        XCTAssertEqual(catalog.endSign(for: "maxspeed:end")?.signCode, "DE:282")
    }
}

final class PackedOSMSpeedEndPresentationTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 10_000)

    private func lookup(tags: [String: String], proof: String = "explicit_source_way_node_membership",
                        verified: Bool? = true, memberWay: Int = 123, stable: Bool = true,
                        heading: Double = 90, headingAccuracy: Double = 5, accuracy: Double = 5,
                        age: TimeInterval = 0, longitude: Double = 8.0005, generation: String? = nil) throws -> InventorySignLookup? {
        var membership: [String: Any] = ["way_id": memberWay, "source_vertex_ordinal": 1,
            "chainage_m": 37, "direction": "unknown", "proof": proof]
        if let verified { membership["coordinate_verified"] = verified }
        let source: [String: Any] = ["osm_node_id": 456, "source_id": "osm", "latitude": 48,
            "longitude": 8.0005, "tags": tags, "memberships": [membership], "binding_status": "unresolved_direction"]
        let node = try JSONDecoder().decode(GenericSpeedSignNode.self, from: JSONSerialization.data(withJSONObject: source))
        let catalog = try XCTUnwrap(TrafficSignPresentationCatalog.bundled())
        return PackedOSMSpeedEndPresentation.lookup(nodes: [node], catalog: catalog, wayID: "123",
            points: [(48, 8), (48, 8.001)], lat: 48, lon: longitude, heading: heading,
            headingAccuracy: headingAccuracy, accuracy: accuracy, matchStable: stable,
            observedAt: now.addingTimeInterval(-age), now: now,
            sourceGeneration: generation ?? "ysp-base-v1:\(String(repeating: "a", count: 64)):\(String(repeating: "b", count: 64)):\(String(repeating: "c", count: 64))")
    }

    func testExplicitDirectionalOSMEndDisplaysWithoutIntroducingRuleOrBoundary() throws {
        let tags = ["traffic_sign:forward": "DE:274[50];278[70]", "traffic_sign:backward": "DE:278-30"]
        for (heading, code) in [(90.0, "DE:278-70"), (270.0, "DE:278-30")] {
            let result = try XCTUnwrap(lookup(tags: tags, heading: heading))
            let sign = try XCTUnwrap(result.signs.first)
            XCTAssertEqual(sign.code, code)
            XCTAssertEqual(sign.sourceID, "osm-traffic-sign")
            XCTAssertEqual(sign.snapshotSHA256, String(repeating: "c", count: 64))
            XCTAssertTrue(sign.targetMatches(way: result.wayID, direction: result.direction))
            XCTAssertTrue(sign.modelClasses.isEmpty, "Source artwork does not add camera capabilities")
            XCTAssertNil(result.activeRule)
            XCTAssertTrue(result.boundaries.isEmpty, "Display observations must never reset speed state")
        }
    }

    func testMissingDirectionMembershipOrFreshAccurateFixCannotAdmitOSMEnd() throws {
        let tags = ["traffic_sign:forward": "DE:278[70]"]
        XCTAssertNil(try lookup(tags: ["traffic_sign": "DE:278[70]"]))
        XCTAssertNil(try lookup(tags: tags, heading: 270))
        XCTAssertNil(try lookup(tags: tags, memberWay: 999))
        XCTAssertNil(try lookup(tags: tags, verified: false))
        XCTAssertNil(try lookup(tags: tags, verified: nil))
        XCTAssertNil(try lookup(tags: tags, proof: "proximity"))
        XCTAssertNil(try lookup(tags: tags, stable: false))
        XCTAssertNil(try lookup(tags: tags, heading: 180))
        XCTAssertNil(try lookup(tags: tags, headingAccuracy: 36))
        XCTAssertNil(try lookup(tags: tags, accuracy: 26))
        XCTAssertNil(try lookup(tags: tags, age: 4))
        XCTAssertNil(try lookup(tags: tags, age: -2))
        XCTAssertNil(try lookup(tags: tags, longitude: 8.0008))
        XCTAssertNil(try lookup(tags: tags, generation: "unknown"))
    }

    func testAmbiguousGenericMalformedAndUnsupportedOSMEndsRemainUnrendered() throws {
        for value in ["DE:278", "DE:278[35]", "DE:278[70 mph]", "DE:278[70.5]",
                      "DE:278[70];278[30]", "DE:278[70];278", "FR:278[70]", "DE:274[70]"] {
            XCTAssertNil(try lookup(tags: ["traffic_sign:forward": value]), value)
        }
        XCTAssertEqual(try lookup(tags: ["traffic_sign:forward": "DE:278[70 km/h]"])?.signs.first?.code, "DE:278-70")
    }
}

@MainActor
final class UserCorrectionsDisabledTests: XCTestCase {
    func testCorrectionEntryPointsLeaveMicrophoneAndCaptureIdle() {
        let model = DriveSessionViewModel()
        let audio = AVAudioSession.sharedInstance()
        let category = audio.category
        let mode = audio.mode
        model.beginSpeedLimitCapture()
        model.prepareVisionDismissalVoicePermissionsIfNeeded(isStationary: true)
        model.disregardVision()
        XCTAssertEqual(model.speedCaptureMode, .idle)
        XCTAssertFalse(model.canDisregardVision)
        XCTAssertFalse(model.isVisionDismissalListening)
        XCTAssertEqual(audio.category, category)
        XCTAssertEqual(audio.mode, mode)
    }

    func testAutomaticSpeechListenerCannotAcquireMicrophone() {
        let listener = VisionDismissalSpeechListener()
        let audio = AVAudioSession.sharedInstance()
        let category = audio.category
        XCTAssertThrowsError(try listener.start(language: "de-DE") { _, _ in
            XCTFail("Disabled microphone listener delivered a result")
        })
        listener.stop()
        XCTAssertEqual(audio.category, category)
    }
}

final class MapillarySignDisplayTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-11-17T12:00:00Z")!
    private func sign() -> InventoryTrafficSign {
        .init(signID: "mapillary-eval:1", sourceID: "mapillary-eval", recordKey: "1", snapshotSHA256: "sha",
            code: "DE:101", kind: "secondary", numericValue: nil, unit: nil, parameterStatus: "mapillary_inventory_only",
            latitude: 48, longitude: 8, radiusM: 10, pictogramCode: "DE:101", pictogramPath: nil,
            modelClasses: [], distanceM: 0, mapillaryAzimuthDeg: 180, mapillaryLastSeenAt: now.addingTimeInterval(-60))
    }

    func testStrictThirtyDegreeThresholdAndWraparound() {
        let sign = sign()
        for (heading, expected) in [(29.999, true), (30.0, false), (330.0, false), (330.001, true),
                                     (359.0, true), (180.0, false), (Double.nan, false)] {
            XCTAssertEqual(sign.mapillaryDisplayEligible(heading: heading, now: now), expected)
        }
        XCTAssertFalse(sign.mapillaryDisplayEligible(heading: nil, now: now))
        var missing = sign
        missing.mapillaryAzimuthDeg = nil
        XCTAssertFalse(missing.mapillaryDisplayEligible(heading: 0, now: now))
    }

    func testLastSeenTwelveMonthsUnknownAndFuture() throws {
        var sign = sign()
        sign.mapillaryLastSeenAt = ISO8601DateFormatter().date(from: "2025-11-17T12:00:00Z")
        XCTAssertTrue(sign.mapillaryDisplayEligible(heading: 0, now: now))
        sign.mapillaryLastSeenAt = sign.mapillaryLastSeenAt?.addingTimeInterval(-1)
        XCTAssertFalse(sign.mapillaryDisplayEligible(heading: 0, now: now))
        sign.mapillaryLastSeenAt = nil
        XCTAssertFalse(sign.mapillaryDisplayEligible(heading: 0, now: now))
        sign.mapillaryLastSeenAt = now.addingTimeInterval(1)
        XCTAssertFalse(sign.mapillaryDisplayEligible(heading: 0, now: now))
        sign.mapillaryLastSeenAt = ISO8601DateFormatter().date(from: "2024-02-29T12:00:00Z")
        let anniversary = try XCTUnwrap(ISO8601DateFormatter().date(from: "2025-02-28T12:00:00Z"))
        XCTAssertTrue(sign.mapillaryDisplayEligible(heading: 0, now: anniversary))
        XCTAssertFalse(sign.mapillaryDisplayEligible(heading: 0, now: anniversary.addingTimeInterval(1)))
    }

    func testBundleMetadataParsesMillisecondsAndBothProviderISOFormats() throws {
        let expected = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-11-17T12:00:00Z"))
        for raw in [
            #"{"aligned_direction":180,"last_seen_at":1794916800000}"#,
            #"{"aligned_direction":180,"last_seen_at":"2026-11-17T12:00:00+0000"}"#,
            #"{"aligned_direction":180,"last_seen_at":"2026-11-17T12:00:00.000Z"}"#
        ] {
            let parsed = InventoryTrafficSign.mapillaryMetadata(raw)
            XCTAssertEqual(parsed.azimuth, 180)
            XCTAssertEqual(parsed.lastSeen, expected)
        }
        for raw in [nil, "{}", #"{"last_seen_at":true}"#, #"{"last_seen_at":"unknown"}"#] {
            XCTAssertNil(InventoryTrafficSign.mapillaryMetadata(raw).lastSeen)
        }
    }

    func testSourceMetadataRoundTripsThroughTheNativeBundleReader() throws {
        var database: OpaquePointer?
        XCTAssertEqual(sqlite3_open(":memory:", &database), SQLITE_OK)
        let db = try XCTUnwrap(database)
        defer { sqlite3_close(db) }
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let schema = try String(contentsOf: repo.appendingPathComponent("mapdata/spec/traffic_sign_runtime_v1.sql"))
        XCTAssertEqual(sqlite3_exec(db, schema, nil, nil, nil), SQLITE_OK)
        let setup = """
            CREATE TABLE traffic_sign_inventory(source_id TEXT,record_key TEXT,raw_properties_json TEXT);
            INSERT INTO traffic_sign_capability VALUES('version','1'),('inventory_scope','display_only');
            INSERT INTO traffic_sign_runtime VALUES('mapillary-eval:1','mapillary-eval','record','snapshot','DE:101','DE:101','secondary',NULL,NULL,'mapillary_inventory_only',8,48,0,10,'DE:101','tsr/sign-pictograms/png/de-101.png','[]');
            INSERT INTO traffic_sign_association VALUES('mapillary-eval:1','inventory_only',NULL,NULL,NULL,NULL,NULL,'{}');
            INSERT INTO traffic_sign_inventory VALUES('mapillary-eval','record','{"aligned_direction":180,"last_seen_at":1794916800000}');
            """
        XCTAssertEqual(sqlite3_exec(db, setup, nil, nil, nil), SQLITE_OK)
        let lookup = try XCTUnwrap(InventorySignBundle.lookup(db: db, lat: 48, lon: 8, wayID: nil,
            points: [], heading: 0, headingAccuracy: nil, accuracy: 5))
        let sign = try XCTUnwrap(lookup.signs.first)
        XCTAssertEqual(sign.mapillaryAzimuthDeg, 180)
        XCTAssertEqual(sign.mapillaryLastSeenAt, now)
        XCTAssertTrue(sign.mapillaryDisplayEligible(heading: 0, now: now))
        XCTAssertFalse(sign.mapillaryDisplayEligible(heading: 30, now: now))
    }

    func testEncounterFiltersAndRetainedSelectionRechecksHeadingAndAge() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let runtime = InventorySignEncounterRuntime(journal: .init(url: root.appendingPathComponent("events.ndjson")))
        let sign = sign()
        let lookup = InventorySignLookup(signs: [sign], activeRule: nil, wayID: nil, direction: nil, chainageM: nil)
        var selection = InventorySecondaryDisplaySelection()
        runtime.update(lookup, bundle: "bundle", at: now, now: now, cameraEnabled: false,
            cameraAvailable: false, classes: [], heading: 0)
        XCTAssertEqual(runtime.visible, [sign])
        XCTAssertTrue(selection.consume(runtime.visible, at: now))
        XCTAssertTrue(selection.invalidateMapillary(heading: 30, now: now, at: now))
        XCTAssertNil(selection.sign)
        runtime.update(lookup, bundle: "bundle", at: now, now: now, cameraEnabled: false,
            cameraAvailable: false, classes: [], heading: 30)
        XCTAssertTrue(runtime.visible.isEmpty)
        XCTAssertTrue(selection.consume([sign], at: now))
        XCTAssertTrue(selection.invalidateMapillary(heading: nil, now: now, at: now))
        XCTAssertTrue(selection.consume([sign], at: now))
        let expired = try XCTUnwrap(ISO8601DateFormatter().date(from: "2027-11-17T12:00:00Z"))
        XCTAssertTrue(selection.invalidateMapillary(heading: 0, now: expired, at: expired))
    }
}
