import Foundation

@_silgen_name("ysp_nodes_open")
private func packedNodesOpen(_ path: UnsafePointer<CChar>, _ cacheBytes: UInt64,
                             _ error: UnsafeMutablePointer<CChar>, _ errorSize: Int) -> UnsafeMutableRawPointer?
@_silgen_name("ysp_nodes_json")
private func packedNodesJSON(_ handle: UnsafeMutableRawPointer, _ nodeID: UnsafePointer<CChar>,
                             _ error: UnsafeMutablePointer<CChar>, _ errorSize: Int) -> UnsafeMutablePointer<CChar>?
@_silgen_name("ysp_nodes_query_json")
private func packedNodesQuery(_ handle: UnsafeMutableRawPointer, _ lat: Double, _ lon: Double, _ radius: Double,
                              _ error: UnsafeMutablePointer<CChar>, _ errorSize: Int) -> UnsafeMutablePointer<CChar>?
@_silgen_name("ysp_nodes_close")
private func packedNodesClose(_ handle: UnsafeMutableRawPointer)
@_silgen_name("ysp_nodes_free")
private func packedNodesFree(_ value: UnsafeMutableRawPointer?)

/// Source observations, including generic/variable limits and unsupported tags.
/// An explicit way membership never establishes facing direction or passage.
struct GenericSpeedSignNode: Decodable, Sendable {
    struct Membership: Decodable, Sendable {
        let wayID: Int64
        let sourceVertexOrdinal: Int
        let chainageM: Double
        let direction: String
        let proof: String
        let coordinateVerified: Bool?
        enum CodingKeys: String, CodingKey {
            case direction, proof
            case wayID = "way_id"
            case sourceVertexOrdinal = "source_vertex_ordinal"
            case chainageM = "chainage_m"
            case coordinateVerified = "coordinate_verified"
        }
    }
    let osmNodeID: Int64
    let sourceID: String
    let latitude: Double
    let longitude: Double
    let tags: [String: String]
    let memberships: [Membership]
    let bindingStatus: String
    enum CodingKeys: String, CodingKey {
        case latitude, longitude, tags, memberships
        case osmNodeID = "osm_node_id"
        case sourceID = "source_id"
        case bindingStatus = "binding_status"
    }
}

/// Exact OSM artwork is a presentation observation, never a new road rule.
enum PackedOSMSpeedEndPresentation {
    static func lookup(nodes: [GenericSpeedSignNode], catalog: TrafficSignPresentationCatalog,
                       wayID: String?, points: [(Double, Double)], lat: Double, lon: Double,
                       heading: Double?, headingAccuracy: Double?, accuracy: Double, matchStable: Bool,
                       observedAt: Date?, now: Date = Date(), sourceGeneration: String) -> InventorySignLookup? {
        guard let snapshotSHA256 = nodeSnapshotSHA256(generation: sourceGeneration),
              matchStable, let wayID, let osmWayID = Int64(wayID),
              accuracy.isFinite, (0...25).contains(accuracy),
              let observedAt, observedAt.timeIntervalSince1970.isFinite,
              (-1...3).contains(now.timeIntervalSince(observedAt)),
              let projection = InventorySignBundle.projection(lat: lat, lon: lon, points: points),
              let direction = InventorySignBundle.travelDirection(projection: projection, heading: heading,
                                                                  headingAccuracy: headingAccuracy) else { return nil }
        let tag = direction == 1 ? "traffic_sign:forward" : "traffic_sign:backward"
        let signs = nodes.compactMap { node -> InventoryTrafficSign? in
            guard node.latitude.isFinite, node.longitude.isFinite,
                  node.memberships.contains(where: {
                      $0.wayID == osmWayID && $0.proof == "explicit_source_way_node_membership" && $0.coordinateVerified == true
                  }), let raw = node.tags[tag], let code = exactCode(raw),
                  let artwork = catalog.sign(for: code), artwork.displayEligible, let path = artwork.imagePath else { return nil }
            let distance = InventorySignBundle.distance(lat, lon, node.latitude, node.longitude)
            guard distance <= 10, let speed = Double(code.dropFirst("DE:278-".count)) else { return nil }
            return InventoryTrafficSign(signID: "osm:\(node.osmNodeID):\(direction):\(code)", sourceID: "osm-traffic-sign",
                recordKey: String(node.osmNodeID), snapshotSHA256: snapshotSHA256, code: code, kind: "speed_limit_end",
                numericValue: speed, unit: "km/h", parameterStatus: "parsed_source_value",
                latitude: node.latitude, longitude: node.longitude, radiusM: 10, pictogramCode: code, pictogramPath: path,
                modelClasses: [], distanceM: distance, associatedWayID: wayID, associatedDirection: direction,
                associationStatus: "accepted", associatedHeadingDeg: projection.heading)
        }.sorted { ($0.distanceM, $0.signID) < ($1.distanceM, $1.signID) }
        guard !signs.isEmpty else { return nil }
        return InventorySignLookup(signs: signs, activeRule: nil, wayID: wayID, direction: direction,
                                   chainageM: projection.chainage, boundaries: [])
    }

    private static func nodeSnapshotSHA256(generation: String) -> String? {
        let components = generation.split(separator: ":", omittingEmptySubsequences: false)
        guard components.count == 4, components[0] == "ysp-base-v1",
              components.dropFirst().allSatisfy({ $0.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil }) else { return nil }
        return String(components[3])
    }

    private static func exactCode(_ raw: String) -> String? {
        var country: String?
        var codes = Set<String>()
        for part in raw.split(separator: ";") {
            let token = part.trimmingCharacters(in: .whitespacesAndNewlines)
            let full: String
            if let colon = token.firstIndex(of: ":") {
                country = String(token[..<colon]); full = token
            } else if let country { full = country + ":" + token }
            else { continue }
            guard full.hasPrefix("DE:278") else { continue }
            guard let value = InventorySpeedEndCode.number(full) else { return nil }
            codes.insert("DE:278-\(value)")
        }
        return codes.count == 1 ? codes.first : nil
    }
}

/// Session-owned native reader. No mapping of the node file is retained.
final class PackedGenericSpeedSignSource: @unchecked Sendable {
    private let handle: UnsafeMutableRawPointer

    init(url: URL) throws {
        var error = [CChar](repeating: 0, count: 1024)
        guard let handle = url.path.withCString({ packedNodesOpen($0, 512 * 1024, &error, 1024) }) else {
            throw ConsumerAppError.sqlite("Packed node open failed: \(String(cString: error))")
        }
        self.handle = handle
    }
    deinit { packedNodesClose(handle) }

    static func installedSource(contextURL: URL) throws -> PackedGenericSpeedSignSource? {
        let manifestURL = contextURL.deletingLastPathComponent().appendingPathComponent("bundle-manifest.v3.json")
        guard FileManager.default.fileExists(atPath: manifestURL.path) else { return nil }
        let data = try Data(contentsOf: manifestURL)
        guard data.count <= 1024 * 1024,
              let manifest = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let base = manifest["packed_base"] as? [String: Any],
              let nodes = base["nodes"] as? [String: Any], let filename = nodes["file"] as? String else { return nil }
        guard !filename.isEmpty, filename == URL(fileURLWithPath: filename).lastPathComponent,
              !filename.contains("\\"), filename != ".", filename != ".." else {
            throw ConsumerAppError.invalidManifest("Invalid packed node filename")
        }
        return try PackedGenericSpeedSignSource(url: contextURL.deletingLastPathComponent().appendingPathComponent(filename))
    }

    /// Exact original record JSON is retained for amendment provenance/import.
    func sourceJSON(nodeID: String) throws -> String? {
        guard let id = Int64(nodeID), id > 0 else { throw ConsumerAppError.sqlite("Invalid source node ID") }
        var error = [CChar](repeating: 0, count: 1024)
        let value = String(id).withCString { packedNodesJSON(handle, $0, &error, 1024) }
        guard let value else { throw ConsumerAppError.sqlite("Packed node lookup failed: \(String(cString: error))") }
        defer { packedNodesFree(UnsafeMutableRawPointer(value)) }
        let json = String(cString: value)
        return json == "null" ? nil : json
    }

    func nearby(lat: Double, lon: Double, radiusM: Double) throws -> [GenericSpeedSignNode] {
        var error = [CChar](repeating: 0, count: 1024)
        guard let value = packedNodesQuery(handle, lat, lon, radiusM, &error, 1024) else {
            throw ConsumerAppError.sqlite("Packed node spatial query failed: \(String(cString: error))")
        }
        defer { packedNodesFree(UnsafeMutableRawPointer(value)) }
        let data = Data(bytes: value, count: strlen(value))
        return try JSONDecoder().decode([GenericSpeedSignNode].self, from: data)
    }
}
