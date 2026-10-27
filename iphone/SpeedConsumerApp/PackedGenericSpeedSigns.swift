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
        enum CodingKeys: String, CodingKey {
            case direction, proof
            case wayID = "way_id"
            case sourceVertexOrdinal = "source_vertex_ordinal"
            case chainageM = "chainage_m"
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
