import Foundation
import CryptoKit

/// Discovery never activates a runtime. The installer must verify the referenced
/// delivery envelope, all files, licenses and acceptance evidence independently.
struct TrafficSignCountryPackRegistry: Decodable, Sendable {
    struct ArtifactReference: Decodable, Sendable {
        let url: String
        let sha256: String
        let sizeBytes: Int
    }
    struct Compatibility: Decodable, Sendable {
        struct Platform: Decodable, Sendable {
            let platform: String
            let minimumRuntime: String
        }
        let minimumAppVersion: String
        let maximumAppVersion: String
        let taxonomyVersion: String
        let preprocessingVersion: String
        let platforms: [Platform]
    }
    struct Pack: Decodable, Sendable {
        let packId: String
        let version: Int
        let countries: [String]
        let rollout: String
        let manifest: ArtifactReference?
        let compatibility: Compatibility
        let calibrated: Bool
        let reason: String
        let supersedes: [Int]
        let rollbackVersion: Int?
    }
    struct Decision: Equatable {
        let state: String
        let packId: String?
        let version: Int?
        // Discovery is never permission for live speed overrides.
        let overrideEligible = false
    }
    let schemaVersion: Int
    let generation: Int
    let environment: String
    let expiresAt: Int
    let packs: [Pack]

    /// Trust pins must be shipped/reviewed out of band, never read from the
    /// downloaded index. No production remote pin or endpoint is enabled yet.
    static func decodeTrusted(_ data: Data, trustedSHA256: Set<String>, minimumGeneration: Int = 1, allowFixtures: Bool = false) throws -> Self {
        guard data.count <= 1_048_576 else { throw DiscoveryError.invalidRegistry }
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard trustedSHA256.contains(digest) else { throw DiscoveryError.untrustedRegistry }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let result = try decoder.decode(Self.self, from: data)
        guard result.schemaVersion == 1, (1...Int(Int32.max)).contains(result.generation),
              result.generation >= minimumGeneration, result.expiresAt > 0, result.expiresAt <= 4_102_444_800,
              ["fixture", "production"].contains(result.environment),
              allowFixtures || result.environment == "production", result.packs.count <= 256,
              Set(result.packs.map { "\($0.packId):\($0.version)" }).count == result.packs.count else { throw DiscoveryError.invalidRegistry }
        for pack in result.packs {
            let c = pack.compatibility
            guard pack.packId.range(of: "^[a-z0-9][a-z0-9._-]{0,95}$", options: .regularExpression) != nil,
                  (1...Int(Int32.max)).contains(pack.version), !pack.countries.isEmpty, pack.countries.count <= 16,
                  Set(pack.countries).count == pack.countries.count,
                  pack.countries.allSatisfy({ $0.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil }),
                  ["evaluation", "shadow", "canary", "available", "withdrawn"].contains(pack.rollout),
                  let minimum = numericVersion(c.minimumAppVersion), let maximum = numericVersion(c.maximumAppVersion), minimum <= maximum,
                  !c.taxonomyVersion.isEmpty, !c.preprocessingVersion.isEmpty, !pack.reason.isEmpty,
                  !c.platforms.isEmpty, c.platforms.count <= 2,
                  Set(c.platforms.map(\.platform)).count == c.platforms.count,
                  c.platforms.allSatisfy({ ["ios", "android"].contains($0.platform) && numericVersion($0.minimumRuntime) != nil }),
                  Set(pack.supersedes).count == pack.supersedes.count,
                  pack.supersedes.allSatisfy({ $0 > 0 && $0 < pack.version }),
                  pack.rollbackVersion.map({ $0 > 0 && $0 < pack.version }) ?? true else { throw DiscoveryError.invalidRegistry }
            if let ref = pack.manifest {
                guard (1...1_048_576).contains(ref.sizeBytes),
                      ref.sha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
                      ref.url.range(of: "^https://[a-z0-9.-]+/[A-Za-z0-9/_.-]+$", options: .regularExpression) != nil,
                      ref.url.count <= 2048, ref.url.contains("/\(ref.sha256)/"),
                      !ref.url.split(separator: "/").contains("..") else { throw DiscoveryError.invalidRegistry }
            }
        }
        return result
    }

    static func bundled(_ bundle: Bundle = .main) -> Self? {
        guard let url = bundle.url(forResource: "country-pack-registry-v1", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        // The signed application bundle is the trust root for this inventory.
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        return try? decodeTrusted(data, trustedSHA256: [digest])
    }

    func decision(country: String?, platform: String, appVersion: String, runtimeVersion: String,
                  taxonomy: String = "tsr-semantic-v1", preprocessing: String = "vision-scale-fit-rgb-v1", now: Int) -> Decision {
        func result(_ state: String, _ pack: Pack? = nil) -> Decision { Decision(state: state, packId: pack?.packId, version: pack?.version) }
        guard now >= 0, now < expiresAt else { return result("registry_expired") }
        guard let country else { return result("country_unresolved") }
        let candidates = packs.filter { $0.countries.contains(country) }
        // A country cannot silently choose between competing independently named packs.
        guard Set(candidates.map(\.packId)).count <= 1 else { return result("ambiguous_pack") }
        guard let pack = candidates.max(by: { $0.version < $1.version }) else { return result("unavailable") }
        if pack.rollout == "withdrawn" { return result("withdrawn", pack) }
        guard let app = Self.numericVersion(appVersion), let runtime = Self.numericVersion(runtimeVersion),
              let minimum = Self.numericVersion(pack.compatibility.minimumAppVersion),
              let maximum = Self.numericVersion(pack.compatibility.maximumAppVersion), app >= minimum, app <= maximum,
              pack.compatibility.taxonomyVersion == taxonomy, pack.compatibility.preprocessingVersion == preprocessing,
              let target = pack.compatibility.platforms.first(where: { $0.platform == platform }),
              let minimumRuntime = Self.numericVersion(target.minimumRuntime), runtime >= minimumRuntime else { return result("incompatible", pack) }
        guard pack.manifest != nil else { return result("unavailable", pack) }
        if environment == "fixture" { return result("fixture_only", pack) }
        if !pack.calibrated || ["evaluation", "shadow"].contains(pack.rollout) { return result("shadow", pack) }
        if pack.rollout == "canary" { return result("canary_not_enrolled", pack) }
        return result("downloadable", pack)
    }

    // 1.1 and 1.1.0 are equal for the installed app/OS; registry versions are
    // validated separately by the release schema. Suffixes are never stripped.
    private static func numericVersion(_ raw: String) -> Int64? {
        guard raw.range(of: "^[0-9]{1,6}(\\.[0-9]{1,6}){0,2}$", options: .regularExpression) != nil else { return nil }
        var parts = raw.split(separator: ".").compactMap { Int64($0) }
        while parts.count < 3 { parts.append(0) }
        return parts[0] * 1_000_000_000_000 + parts[1] * 1_000_000 + parts[2]
    }
}
