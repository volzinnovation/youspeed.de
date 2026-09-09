import Foundation

/// Offline extract coverage, available before a map database is installed.
/// Extract countries are download candidates, not administrative borders.
struct RegionalPackCatalog: Decodable, Sendable {
    struct Region: Decodable, Sendable {
        let id: String
        let country: String
        let region: String
        let bbox: [Double]
        let polygons: [[[[Double]]]]

        var area: Double { (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) }

        func contains(longitude: Double, latitude: Double) -> Bool {
            guard longitude.isFinite, latitude.isFinite,
                  (-180...180).contains(longitude), (-90...90).contains(latitude),
                  longitude >= bbox[0], longitude <= bbox[2],
                  latitude >= bbox[1], latitude <= bbox[3] else { return false }
            return polygons.contains { polygon in
                Self.inRing(longitude, latitude, polygon[0]) &&
                    !polygon.dropFirst().contains { Self.inRing(longitude, latitude, $0) }
            }
        }

        private static func inRing(_ x: Double, _ y: Double, _ ring: [[Double]]) -> Bool {
            var inside = false
            for i in 0..<(ring.count - 1) {
                let a = ring[i], b = ring[i + 1]
                let dx = b[0] - a[0], dy = b[1] - a[1]
                // Duplicate vertices are common in source geometry. A zero
                // length edge must not report every point as on its boundary.
                if dx == 0 && dy == 0 { continue }
                let cross = (x - a[0]) * dy - (y - a[1]) * dx
                if abs(cross) <= 1e-12 && x >= min(a[0], b[0]) && x <= max(a[0], b[0]) &&
                    y >= min(a[1], b[1]) && y <= max(a[1], b[1]) { return true }
                if (a[1] > y) != (b[1] > y), x < dx * (y - a[1]) / dy + a[0] {
                    inside.toggle()
                }
            }
            return inside
        }
    }

    let schemaVersion: Int
    let boundaryKind: String
    let regions: [Region]

    static func decode(_ data: Data) throws -> Self {
        guard data.count <= 8_000_000 else { throw DiscoveryError.invalidCatalog }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let result = try decoder.decode(Self.self, from: data)
        guard result.schemaVersion == 1, result.boundaryKind == "buffered_extract_coverage",
              !result.regions.isEmpty, result.regions.count <= 1000,
              Set(result.regions.map(\.id)).count == result.regions.count else { throw DiscoveryError.invalidCatalog }
        for region in result.regions {
            guard region.country.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil,
                  region.bbox.count == 4, region.bbox.allSatisfy(\.isFinite),
                  region.bbox[0] < region.bbox[2], region.bbox[1] < region.bbox[3],
                  !region.polygons.isEmpty else { throw DiscoveryError.invalidCatalog }
            for polygon in region.polygons {
                guard !polygon.isEmpty else { throw DiscoveryError.invalidCatalog }
                for ring in polygon {
                    guard ring.count >= 4, ring.first == ring.last else { throw DiscoveryError.invalidCatalog }
                    for point in ring {
                        guard point.count == 2, point.allSatisfy(\.isFinite),
                              (-180...180).contains(point[0]), (-90...90).contains(point[1]),
                              point[0] >= region.bbox[0], point[0] <= region.bbox[2],
                              point[1] >= region.bbox[1], point[1] <= region.bbox[3] else { throw DiscoveryError.invalidCatalog }
                    }
                }
            }
        }
        return result
    }

    static func bundled(_ bundle: Bundle = .main) -> Self? {
        guard let url = bundle.url(forResource: "catalog-v1", withExtension: "json", subdirectory: "RegionalCoverage"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? decode(data)
    }

    func matches(longitude: Double, latitude: Double) -> [Region] {
        regions.filter { $0.contains(longitude: longitude, latitude: latitude) }.sorted {
            $0.area == $1.area ? $0.id < $1.id : $0.area < $1.area
        }
    }
}

enum DiscoveryError: Error { case invalidCatalog, untrustedRegistry, invalidRegistry }

/// Deterministic location/map-context selection. A border transition suspends
/// inference immediately and needs three fixes over 15 seconds before switching.
struct TrafficSignCountrySelection {
    private(set) var activeCountry: String?
    private var pendingCountry: String?
    private var pendingSince: Double = 0
    private var pendingFixes = 0
    private var lastTimestamp: Double = -.infinity

    mutating func update(countries: Set<String>, timestamp: Double, override: String? = nil) -> String? {
        guard timestamp.isFinite, timestamp > lastTimestamp else { return nil }
        lastTimestamp = timestamp
        if let override {
            guard override.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil else { return nil }
            activeCountry = override
            pendingCountry = nil
            return override
        }
        guard countries.count == 1, let country = countries.first,
              country.range(of: "^[A-Z]{2}$", options: .regularExpression) != nil else {
            pendingCountry = nil
            return nil
        }
        if activeCountry == nil || activeCountry == country {
            activeCountry = country
            pendingCountry = nil
            return country
        }
        if pendingCountry != country {
            pendingCountry = country
            pendingSince = timestamp
            pendingFixes = 1
        } else {
            pendingFixes += 1
        }
        if pendingFixes >= 3 && timestamp - pendingSince >= 15 {
            activeCountry = country
            pendingCountry = nil
            return country
        }
        return nil
    }
}

enum FirstLocationPackPolicy {
    static func acceptsFix(latitude: Double, longitude: Double, accuracy: Double, timestamp: Double, now: Double) -> Bool {
        [latitude, longitude, accuracy, timestamp, now].allSatisfy(\.isFinite) &&
            (-90...90).contains(latitude) && (-180...180).contains(longitude) &&
            (0...100).contains(accuracy) && (0...30).contains(now - timestamp)
    }
}
