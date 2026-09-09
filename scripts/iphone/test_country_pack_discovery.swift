import Foundation
import CryptoKit

/// Host-native replay of the same fixtures used by the Android unit tests.
@main
struct CountryPackDiscoveryTests {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let fixtures = root.appendingPathComponent("shared/tsr/fixtures")
        let scenarios = try JSONSerialization.jsonObject(with: Data(contentsOf: fixtures.appendingPathComponent("country-discovery-scenarios-v1.json"))) as! [String: Any]
        let catalog = try RegionalPackCatalog.decode(Data(contentsOf: root.appendingPathComponent("shared/RegionalCoverage/catalog-v1.json")))
        for item in scenarios["regions"] as! [[String: Any]] {
            let found = catalog.matches(longitude: item["longitude"] as! Double, latitude: item["latitude"] as! Double).first?.id
            precondition(found == item["first"] as? String, "Region: \(item["name"]!) got \(String(describing: found))")
        }
        var selection = TrafficSignCountrySelection()
        for item in scenarios["country_transitions"] as! [[String: Any]] {
            let selected = selection.update(countries: Set(item["countries"] as! [String]), timestamp: item["timestamp"] as! Double, override: item["override"] as? String)
            precondition(selected == item["expected"] as? String, "Country transition \(item)")
        }
        let bytes = try Data(contentsOf: fixtures.appendingPathComponent("country-pack-registry-v1.json"))
        let digest = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let registry = try TrafficSignCountryPackRegistry.decodeTrusted(bytes, trustedSHA256: [digest], allowFixtures: true)
        for item in scenarios["registry_decisions"] as! [[String: Any]] {
            var scenarioRegistry = registry
            if let environment = item["environment"] as? String {
                var payload = try JSONSerialization.jsonObject(with: bytes) as! [String: Any]
                payload["environment"] = environment
                var packs = payload["packs"] as! [[String: Any]]
                packs[0]["rollout"] = item["rollout"]
                packs[0]["calibrated"] = item["calibrated"]
                payload["packs"] = packs
                let scenarioBytes = try JSONSerialization.data(withJSONObject: payload)
                let pin = SHA256.hash(data: scenarioBytes).map { String(format: "%02x", $0) }.joined()
                scenarioRegistry = try TrafficSignCountryPackRegistry.decodeTrusted(scenarioBytes, trustedSHA256: [pin])
            }
            for platform in ["ios", "android"] {
                let decision = scenarioRegistry.decision(country: item["country"] as? String, platform: platform, appVersion: item["app_version"] as! String,
                    runtimeVersion: item["runtime_version_\(platform)"] as! String, now: 1_788_710_400)
                precondition(decision.state == item["expected"] as! String, "Registry \(item)")
                precondition(!decision.overrideEligible)
            }
        }
        precondition(registry.decision(country: "DE", platform: "ios", appVersion: "1.1", runtimeVersion: "17", now: registry.expiresAt).state == "registry_expired")
        func rejects(_ operation: () throws -> Void) {
            do { try operation(); preconditionFailure("Expected rejection") } catch { }
        }
        rejects { _ = try TrafficSignCountryPackRegistry.decodeTrusted(bytes, trustedSHA256: []) }
        rejects { _ = try TrafficSignCountryPackRegistry.decodeTrusted(bytes, trustedSHA256: [digest]) }
        rejects { _ = try TrafficSignCountryPackRegistry.decodeTrusted(bytes, trustedSHA256: [digest], minimumGeneration: 2, allowFixtures: true) }
        rejects { _ = try TrafficSignCountryPackRegistry.decodeTrusted(bytes + Data(" ".utf8), trustedSHA256: [digest], allowFixtures: true) }
        let outer = [[0.0,0.0],[4,0],[4,4],[4,4],[0,4],[0,0]]
        let hole = [[1.0,1.0],[2,1],[2,2],[1,2],[1,1]]
        let island = [[6.0,6.0],[7,6],[7,7],[6,7],[6,6]]
        let region = RegionalPackCatalog.Region(id: "test", country: "DE", region: "test", bbox: [0,0,7,7], polygons: [[outer, hole], [island]])
        for (x,y,expected) in [(0.0,2.0,true),(1.5,1.5,false),(1.0,1.0,false),(3.0,3.0,true),(5.0,5.0,false),(6.5,6.5,true)] {
            precondition(region.contains(longitude: x, latitude: y) == expected)
        }
        precondition(!region.contains(longitude: .nan, latitude: 2))
        if CommandLine.arguments.count > 2 {
            let bundle = Bundle(path: CommandLine.arguments[2])!
            precondition(RegionalPackCatalog.bundled(bundle)?.regions.count == catalog.regions.count)
            precondition(TrafficSignCountryPackRegistry.bundled(bundle)?.environment == "production")
        }
        precondition(FirstLocationPackPolicy.acceptsFix(latitude: 49, longitude: 8, accuracy: 20, timestamp: 100, now: 101))
        for (accuracy, timestamp) in [(101.0,100.0),(-1.0,100.0),(20.0,50.0),(20.0,102.0),(Double.nan,100.0)] {
            precondition(!FirstLocationPackPolicy.acceptsFix(latitude: 49, longitude: 8, accuracy: accuracy, timestamp: timestamp, now: 101))
        }
        print("Swift country-pack discovery: shared region, border, registry, trust and first-fix scenarios passed")
    }
}
