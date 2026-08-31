import Foundation
import Security
import UIKit

struct PanoramaxTokenResponse: Decodable {
    let id: String
    let jwtToken: String
    let links: [Link]

    struct Link: Decodable {
        let href: URL
        let rel: String
    }

    enum CodingKeys: String, CodingKey {
        case id
        case jwtToken = "jwt_token"
        case links
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        jwtToken = try container.decode(String.self, forKey: .jwtToken)
        links = try container.decodeIfPresent([Link].self, forKey: .links) ?? []
    }

    var claimURL: URL? {
        links.first(where: { $0.rel == "claim" })?.href
    }
}

@MainActor
final class PanoramaxAccountModel: ObservableObject {
    @Published var instanceOrigin: String {
        didSet {
            UserDefaults.standard.set(instanceOrigin, forKey: Self.originDefaultsKey)
            updateConnectionState()
        }
    }
    @Published private(set) var status = "Nicht verbunden"
    @Published private(set) var isConnected = false
    @Published private(set) var tokenID: String?

    private static let originDefaultsKey = "youspeed.panoramax.instance_origin"
    private let credentials = PanoramaxCredentialStore()

    init() {
        instanceOrigin = UserDefaults.standard.string(forKey: Self.originDefaultsKey) ?? "https://panoramax.openstreetmap.fr"
        updateConnectionState()
    }

    func connect() {
        let origin = normalizedOrigin
        guard let origin else {
            status = "Gueltige HTTPS-Instanz eingeben"
            return
        }
        status = "Verbindung wird vorbereitet"
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let response = try await Self.generateToken(origin: origin)
                try credentials.save(token: response.jwtToken, tokenID: response.id, origin: origin)
                tokenID = response.id
                isConnected = false
                status = "Claim-Link im Browser bestaetigen"
                if let claimURL = response.claimURL {
                    await UIApplication.shared.open(claimURL)
                }
            } catch {
                status = "Verbindung fehlgeschlagen: \(error.localizedDescription)"
            }
        }
    }

    func validateConnection() {
        guard let origin = normalizedOrigin,
              let token = credentials.token(for: origin) else {
            updateConnectionState()
            return
        }
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await Self.validate(token: token, origin: origin)
                isConnected = true
                status = "Verbunden"
            } catch {
                isConnected = false
                status = "Noch nicht bestaetigt oder abgelaufen"
            }
        }
    }

    func disconnect() {
        guard let origin = normalizedOrigin else {
            updateConnectionState()
            return
        }
        let token = credentials.token(for: origin)
        let existingTokenID = credentials.tokenID(for: origin)
        credentials.delete(origin: origin)
        tokenID = nil
        isConnected = false
        status = "Getrennt"
        if let token, let existingTokenID {
            Task {
                try? await Self.revoke(token: token, tokenID: existingTokenID, origin: origin)
            }
        }
    }

    var normalizedOrigin: URL? {
        var value = instanceOrigin.trimmingCharacters(in: .whitespacesAndNewlines)
        if !value.isEmpty, !value.contains("://") {
            value = "https://\(value)"
        }
        guard let url = URL(string: value),
              url.scheme?.lowercased() == "https",
              let host = url.host, !host.isEmpty,
              url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else {
            return nil
        }
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.path = ""
        components?.port = url.port
        return components?.url
    }

    func tokenForUpload() -> String? {
        guard let origin = normalizedOrigin else { return nil }
        return credentials.token(for: origin)
    }

    private func updateConnectionState() {
        guard let origin = normalizedOrigin,
              credentials.token(for: origin) != nil else {
            tokenID = nil
            isConnected = false
            status = "Nicht verbunden"
            return
        }
        isConnected = false
        tokenID = credentials.tokenID(for: origin)
        status = "Token vorhanden – Verbindung pruefen"
    }

    private static func generateToken(origin: URL) async throws -> PanoramaxTokenResponse {
        var request = URLRequest(url: origin.appendingPathComponent("api/auth/tokens/generate"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        try validateHTTP(response)
        return try JSONDecoder().decode(PanoramaxTokenResponse.self, from: data)
    }

    private static func validate(token: String, origin: URL) async throws {
        var request = URLRequest(url: origin.appendingPathComponent("api/users/me"))
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (_, response) = try await URLSession.shared.data(for: request)
        try validateHTTP(response)
    }

    private static func revoke(token: String, tokenID: String, origin: URL) async throws {
        var request = URLRequest(url: origin.appendingPathComponent("api/users/me/tokens/\(tokenID)"))
        request.httpMethod = "DELETE"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (_, response) = try await URLSession.shared.data(for: request)
        try validateHTTP(response)
    }

    private static func validateHTTP(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw AccountError.httpStatus((response as? HTTPURLResponse)?.statusCode ?? -1)
        }
    }

    enum AccountError: LocalizedError {
        case invalidOrigin
        case httpStatus(Int)

        var errorDescription: String? {
            switch self {
            case .invalidOrigin:
                return "Ungueltige Panoramax-Instanz"
            case .httpStatus(let status):
                return "HTTP \(status)"
            }
        }
    }
}

struct PanoramaxServerPreset: Identifiable, Hashable {
    let id: String
    let name: String
    let origin: String
}

enum PanoramaxServerCatalog {
    static let presets: [PanoramaxServerPreset] = [
        PanoramaxServerPreset(id: "OSM-FR", name: "OpenStreetMap France", origin: "https://panoramax.openstreetmap.fr"),
        PanoramaxServerPreset(id: "MapComplete", name: "MapComplete", origin: "https://panoramax.mapcomplete.org"),
        PanoramaxServerPreset(id: "IGN", name: "IGN", origin: "https://panoramax.ign.fr"),
        PanoramaxServerPreset(id: "Multimob", name: "Multimob", origin: "https://panoramax.multimob.be"),
        PanoramaxServerPreset(id: "Wales", name: "Panoramax Wales", origin: "https://www.panoramax.wales"),
        PanoramaxServerPreset(id: "NL", name: "Netherlands", origin: "https://nl.panoramax.xyz"),
        PanoramaxServerPreset(id: "Basi", name: "Basi.re", origin: "https://panoramax.basi.re"),
        PanoramaxServerPreset(id: "Bustikiller", name: "Bustikiller", origin: "https://panoramax.bustikiller.com"),
        PanoramaxServerPreset(id: "OSM-HR", name: "OSM Croatia", origin: "https://panoramax.osm-hr.org"),
        PanoramaxServerPreset(id: "OSM-TW", name: "OSM Taiwan", origin: "https://panoramax.osm.tw"),
        PanoramaxServerPreset(id: "KoenHabets", name: "Koen Habets", origin: "https://panoramax.koenhabets.nl"),
        PanoramaxServerPreset(id: "Libre", name: "Libre Argentina", origin: "https://panoramax.libre.net.ar"),
        PanoramaxServerPreset(id: "Mahdi", name: "Mahdi", origin: "https://pano.mahdi.cz"),
        PanoramaxServerPreset(id: "Locus", name: "Locus", origin: "https://pano.locus.sbs"),
        PanoramaxServerPreset(id: "Kasik", name: "Kasik GIS", origin: "https://pano.kasik-gis.eu"),
        PanoramaxServerPreset(id: "Fulda", name: "OSM Fulda", origin: "https://panorama.osm-fulda.de"),
        PanoramaxServerPreset(id: "Burakonder", name: "Burak Onder", origin: "https://panoramax.burakonder.net"),
        PanoramaxServerPreset(id: "OSM-BE", name: "OSM Belgium", origin: "https://panoramax.osm.be"),
        PanoramaxServerPreset(id: "SereneDeluge", name: "Serene Deluge", origin: "https://panoramax.serenedeluge.se"),
        PanoramaxServerPreset(id: "Ulm", name: "Ulm", origin: "https://panoramax-ulm.jjbaur.de"),
        PanoramaxServerPreset(id: "BikeSpace", name: "Bike Space Project", origin: "https://panoramax.bikespaceproject.ca")
    ]
}

private final class PanoramaxCredentialStore {
    private let service = "de.youspeed.panoramax"

    func save(token: String, tokenID: String, origin: URL) throws {
        let account = origin.absoluteString
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: Data(token.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        SecItemDelete(query as CFDictionary)
        guard SecItemAdd(query as CFDictionary, nil) == errSecSuccess else {
            throw PanoramaxAccountModel.AccountError.invalidOrigin
        }
        UserDefaults.standard.set(tokenID, forKey: tokenIDKey(for: origin))
    }

    func token(for origin: URL) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: origin.absoluteString,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    func tokenID(for origin: URL) -> String? {
        UserDefaults.standard.string(forKey: tokenIDKey(for: origin))
    }

    func delete(origin: URL) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: origin.absoluteString
        ]
        SecItemDelete(query as CFDictionary)
        UserDefaults.standard.removeObject(forKey: tokenIDKey(for: origin))
    }

    private func tokenIDKey(for origin: URL) -> String {
        "youspeed.panoramax.token_id.\(origin.absoluteString)"
    }
}
