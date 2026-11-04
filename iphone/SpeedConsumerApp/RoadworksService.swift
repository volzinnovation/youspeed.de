import Foundation
import Combine
import CoreLocation
import SwiftUI

/// Independent public-data download. No location or installation identity is sent.
@MainActor final class RoadworksService: ObservableObject {
    static let shared = RoadworksService()
    @Published private(set) var enabled: Bool
    @Published private(set) var status = "off"
    @Published private(set) var card: RoadworksRelevance.Card?
    @Published private(set) var nearby: [(RoadworksAdvisory.Feature, Double)] = []
    private var cache = RoadworksSnapshotCache()
    private var manifest: RoadworksAdvisory.Manifest?
    private var receivedUptime = ProcessInfo.processInfo.systemUptime
    private var relevance = RoadworksRelevance()
    private var fix: RoadworksRelevance.Fix?
    private var driving = false, foreground = false
    private var task: Task<Void, Never>?
    private var heartbeat: Task<Void, Never>?
    private var transportState: String?
    private var generation = 0
    private var nextAttempt = 0.0
    private var failures = 0
    private var etag: String?
    private let origin = "https://live-eu.woladen.de"
    private let directory: URL
    private let disk: RoadworksDiskStore
    typealias Download = @Sendable (URL, String?, Int) async throws -> (bytes: Data, response: HTTPURLResponse)
    private let download: Download
    private let defaults: UserDefaults
    var sourceAgeMinutes: Int? {
        sourceAgeMinutes(for: card?.feature.advisorySource ?? "bemas")
    }
    func sourceAgeMinutes(for sourceID: String) -> Int? {
        manifest?.ageMinutes(sourceID: sourceID, receivedUptime: receivedUptime, nowUptime: ProcessInfo.processInfo.systemUptime)
    }
    func sourceStatus(for sourceID: String) -> RoadworksAdvisory.Freshness {
        manifest?.freshness(sourceID: sourceID, receivedUptime: receivedUptime, nowUptime: ProcessInfo.processInfo.systemUptime) ?? .unavailable
    }
    var sources: [RoadworksAdvisory.Source] { manifest?.sourceRecords ?? [] }
    func sourceAttribution(for sourceID: String) -> [String: String] {
        sources.first(where: { $0.id == sourceID })?.attribution ?? [:]
    }

    init(directory: URL? = nil, defaults: UserDefaults = .standard, download: Download? = nil) {
        self.defaults = defaults; self.enabled = defaults.bool(forKey: "youspeed.roadworks.enabled")
        self.download = download ?? Self.fetch
        self.directory = directory ?? FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("Roadworks", isDirectory: true)
        self.disk = RoadworksDiskStore(directory: self.directory)
        // A restored cache has unknown freshness until a trusted server clock is obtained.
        for name in ["manifest.json", "previous-manifest.json"] {
            guard let data = try? Data(contentsOf: self.directory.appendingPathComponent(name)),
                  let restored = try? RoadworksAdvisory.parseManifest(data) else { continue }
            if let id = restored.snapshotID {
                guard let bytes = try? Data(contentsOf: self.directory.appendingPathComponent(id + ".json")),
                      (try? cache.install(bytes, manifest: restored)) != nil else { continue }
            }
            manifest = restored; receivedUptime = -.infinity; status = enabled ? "unknown" : "off"
            break
        }
    }
    func setEnabled(_ value: Bool) {
        enabled = value; defaults.set(value, forKey: "youspeed.roadworks.enabled")
        generation += 1; task?.cancel(); task = nil; relevance.reset(); card = nil; nearby = []; transportState = nil
        if !value { heartbeat?.cancel(); heartbeat = nil }
        status = value ? "unavailable" : "off"; nextAttempt = 0
        if value { session(driving: driving, foreground: foreground); refresh(explicit: true) }
    }
    func clearCache() {
        generation += 1; task?.cancel(); task = nil; manifest = nil; etag = nil; transportState = nil
        relevance.reset(); card = nil; nearby = []
        cache = RoadworksSnapshotCache()
        let epoch = generation
        Task { await disk.clear(epoch: epoch) }
        status = enabled ? "unavailable" : "off"
    }
    func update(location: CLLocation) {
        fix = .init(point: .init(latitude: location.coordinate.latitude, longitude: location.coordinate.longitude), at: location.timestamp, accuracyM: location.horizontalAccuracy)
        evaluate()
    }
    func session(driving: Bool, foreground: Bool) {
        let entered = driving && foreground && !(self.driving && self.foreground)
        self.driving = driving; self.foreground = foreground
        if !driving || !foreground {
            if task != nil { generation += 1; task?.cancel(); task = nil }
            relevance.reset(); card = nil
            heartbeat?.cancel(); heartbeat = nil
        }
        if enabled && driving && foreground && heartbeat == nil {
            heartbeat = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
                    guard let self, self.enabled, self.driving, self.foreground else { return }
                    self.evaluate(); self.refresh()
                }
            }
        }
        if entered { nextAttempt = 0 }
        evaluate()
        if driving && foreground { refresh() }
    }
    private func evaluate() {
        let nowUptime = ProcessInfo.processInfo.systemUptime
        let freshness = manifest?.freshness(receivedUptime: receivedUptime, nowUptime: nowUptime) ?? .unavailable
        if enabled && task == nil { status = transportState ?? (fix == nil ? "no_gps" : freshness.rawValue) }
        let statuses = Dictionary(uniqueKeysWithValues: sources.map { ($0.id, sourceStatus(for: $0.id)) })
        card = relevance.update(snapshot: cache.snapshot, freshness: freshness, fix: fix, now: Date(), enabled: enabled, driving: driving, foreground: foreground, sourceFreshness: statuses,
            eligibilityNow: manifest?.trustedNow(receivedUptime: receivedUptime, nowUptime: nowUptime))
        if enabled, manifest?.enabled == true, let point = fix?.point {
            nearby = (cache.snapshot?.features ?? []).map { ($0, RoadworksAdvisory.distance(from: point, to: $0)) }
                .filter { $0.1 <= 5000 }.sorted { ($0.1, $0.0.id) < ($1.1, $1.0.id) }
        } else { nearby = [] }
    }
    func refresh(explicit: Bool = false) {
        guard enabled, task == nil, explicit || driving && foreground,
              explicit || ProcessInfo.processInfo.systemUptime >= nextAttempt else { return }
        if !explicit {
            guard let point = fix?.point, (47.4...49.9).contains(point.latitude), (7.3...10.7).contains(point.longitude) else { return }
        }
        let token = generation, validator = etag
        status = "loading"
        nextAttempt = ProcessInfo.processInfo.systemUptime + 300 + Double.random(in: 0...15)
        task = Task { [weak self] in
            guard let self else { return }
            var retryAfter = 0.0
            do {
                let reply = try await download(URL(string: origin + "/youspeed/live/v2/regions/DE-BW")!, validator, 262_144)
                if let raw = reply.response.value(forHTTPHeaderField: "Retry-After") {
                    retryAfter = Double(raw) ?? Self.httpDate(raw).map { max(0, $0.timeIntervalSinceNow) } ?? 0
                }
                if (400..<500).contains(reply.response.statusCode), ![408, 429].contains(reply.response.statusCode) { retryAfter = max(300, retryAfter) }
                guard !Task.isCancelled, token == generation else { return }
                if reply.response.statusCode == 304 {
                    guard let manifest else { throw URLError(.badServerResponse) }
                    guard manifest.schemaVersion == 2 else { throw RoadworksAdvisory.Failure.unsupportedVersion }
                    failures = 0; task = nil; transportState = nil; evaluate(); return
                }
                guard reply.response.statusCode == 200 else { throw URLError(.badServerResponse) }
                var candidate = try RoadworksAdvisory.parseManifest(reply.bytes)
                guard candidate.schemaVersion == 2 else { throw RoadworksAdvisory.Failure.unsupportedVersion }
                if let date = reply.response.value(forHTTPHeaderField: "Date").flatMap(Self.httpDate) {
                    candidate = try candidate.validatedHTTPClock(date: date, age: Double(reply.response.value(forHTTPHeaderField: "Age") ?? "0") ?? 0)
                }
                let snapshotBytes: Data?
                if candidate.enabled, let id = candidate.snapshotID, let path = candidate.snapshotPath {
                    if cache.snapshot?.id == id { snapshotBytes = cache.bytes }
                    else {
                        let snapshot = try await download(URL(string: origin + path)!, nil, 8_388_608)
                        guard snapshot.response.statusCode == 200 else { throw URLError(.badServerResponse) }
                        snapshotBytes = snapshot.bytes
                    }
                } else { snapshotBytes = nil }
                guard !Task.isCancelled, token == generation else { return }
                let previousID = manifest?.snapshotID
                let validated = try await Task.detached(priority: .utility) {
                    let cached = RoadworksSnapshotCache()
                    if let bytes = snapshotBytes { try cached.install(bytes, manifest: candidate) }
                    return cached
                }.value
                guard !Task.isCancelled, token == generation else { return }
                guard try await disk.promote(epoch: token, bytes: snapshotBytes, candidate: candidate, manifestBytes: reply.bytes, previousID: previousID) else { return }
                guard !Task.isCancelled, token == generation else { return }
                if snapshotBytes != nil { cache = validated }
                manifest = candidate; receivedUptime = ProcessInfo.processInfo.systemUptime
                etag = reply.response.value(forHTTPHeaderField: "ETag"); failures = 0; task = nil; transportState = nil; evaluate()
            } catch {
                guard token == generation else { return }
                failures += 1; task = nil
                nextAttempt = ProcessInfo.processInfo.systemUptime + max(retryAfter, [30.0, 120, 300][min(2, failures - 1)]) + Double.random(in: 0...5)
                transportState = error as? RoadworksAdvisory.Failure == .unsupportedVersion ? "update_required" : cache.snapshot == nil ? "unavailable" : "offline"
                evaluate()
            }
        }
    }
    private nonisolated static func httpDate(_ raw: String) -> Date? {
        let formatter = DateFormatter(); formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0); formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return formatter.date(from: raw)
    }
    private nonisolated static func fetch(url: URL, etag: String?, limit: Int) async throws -> (bytes: Data, response: HTTPURLResponse) {
        guard url.scheme == "https", url.host == "live-eu.woladen.de", url.user == nil, url.password == nil, url.query == nil,
              url.path.hasPrefix("/youspeed/live/v2/regions/DE-BW") else { throw URLError(.unsupportedURL) }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
        request.setValue("application/json, application/geo+json", forHTTPHeaderField: "Accept")
        if let etag { request.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil; config.urlCredentialStorage = nil; config.urlCache = nil
        let session = URLSession(configuration: config, delegate: RoadworksRedirectGuard(), delegateQueue: nil); defer { session.invalidateAndCancel() }
        let (stream, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.url?.host == url.host,
              response.url?.path == url.path, response.expectedContentLength <= 2_097_152 else { throw URLError(.badServerResponse) }
        var bytes = Data()
        for try await byte in stream {
            try Task.checkCancellation()
            guard bytes.count < limit else { throw URLError(.dataLengthExceedsMaximum) }
            bytes.append(byte)
        }
        return (bytes, response)
    }
}

/// Serial storage ownership ensures Clear wins over an earlier in-flight parse/write.
actor RoadworksDiskStore {
    private let directory: URL
    private var minimumEpoch = 0
    private var latestAppliedEpoch = 0
    init(directory: URL) { self.directory = directory }
    func clear(epoch: Int) {
        minimumEpoch = max(minimumEpoch, epoch)
        guard epoch >= latestAppliedEpoch else { return }
        try? FileManager.default.removeItem(at: directory)
    }
    func promote(epoch: Int, bytes: Data?, candidate: RoadworksAdvisory.Manifest, manifestBytes: Data, previousID: String?) throws -> Bool {
        guard epoch >= minimumEpoch else { return false }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        if let bytes, let id = candidate.snapshotID { try bytes.write(to: directory.appendingPathComponent(id + ".json"), options: .atomic) }
        if let old = try? Data(contentsOf: directory.appendingPathComponent("manifest.json")) { try old.write(to: directory.appendingPathComponent("previous-manifest.json"), options: .atomic) }
        try manifestBytes.write(to: directory.appendingPathComponent("manifest.json"), options: .atomic)
        let keep = Set([candidate.snapshotID, previousID].compactMap { $0 }.map { $0 + ".json" } + ["manifest.json", "previous-manifest.json"])
        for file in (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? [] where !keep.contains(file.lastPathComponent) { try? FileManager.default.removeItem(at: file) }
        latestAppliedEpoch = epoch
        return true
    }
}

private final class RoadworksRedirectGuard: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

func roadworksText(_ en: String, _ de: String, _ fr: String, _ nl: String) -> String {
    let language = Locale.preferredLanguages.first?.prefix(2) ?? "en"
    return language == "de" ? de : language == "fr" ? fr : language == "nl" ? nl : en
}

func roadworksStatusText(_ status: String) -> String {
    switch status {
    case "off": return roadworksText("Off", "Aus", "Désactivé", "Uit")
    case "loading": return roadworksText("Updating reports…", "Meldungen werden aktualisiert…", "Actualisation des signalements…", "Meldingen worden bijgewerkt…")
    case "fresh": return roadworksText("Reports available", "Meldungen verfügbar", "Signalements disponibles", "Meldingen beschikbaar")
    case "delayed": return roadworksText("Publisher updates delayed", "Aktualisierung des Anbieters verzögert", "Mises à jour du fournisseur retardées", "Updates van de bron vertraagd")
    case "offline": return roadworksText("Offline · saved reports", "Offline · gespeicherte Meldungen", "Hors ligne · signalements enregistrés", "Offline · opgeslagen meldingen")
    case "no_gps": return roadworksText("Location unavailable · parked BW download available", "Standort fehlt · BW-Download im Stand verfügbar", "Position indisponible · téléchargement BW à l’arrêt", "Locatie niet beschikbaar · BW-download bij stilstand")
    case "update_required": return roadworksText("App update required for these reports", "App-Update für diese Meldungen erforderlich", "Mise à jour de l’app nécessaire", "App-update nodig voor deze meldingen")
    case "requested", "approved": return roadworksText("Reported as planned", "Als geplant gemeldet", "Signalé comme prévu", "Gemeld als gepland")
    case "implemented": return roadworksText("Reported as in effect", "Als wirksam gemeldet", "Signalé comme en cours", "Gemeld als van kracht")
    case "reported": return roadworksText("Reported by publisher", "Vom Anbieter gemeldet", "Signalé par le fournisseur", "Gemeld door de bron")
    case "resolved": return roadworksText("Report periods available", "Meldezeiträume verfügbar", "Périodes du signalement disponibles", "Meldingsperioden beschikbaar")
    case "unavailable": return roadworksText("Reports unavailable", "Meldungen nicht verfügbar", "Signalements indisponibles", "Meldingen niet beschikbaar")
    default: return roadworksText("Report availability or period uncertain", "Verfügbarkeit oder Meldezeitraum ungewiss", "Disponibilité ou période du signalement incertaine", "Beschikbaarheid of meldingsperiode onzeker")
    }
}

private func roadworksKindText(_ kind: String) -> String {
    switch kind {
    case "closure": return roadworksText("Reported closure", "Gemeldete Sperrung", "Fermeture signalée", "Gemelde afsluiting")
    case "roadworks": return roadworksText("Reported roadworks", "Gemeldete Baustelle", "Travaux signalés", "Gemelde wegwerkzaamheden")
    case "incident": return roadworksText("Reported incident", "Gemeldetes Verkehrsereignis", "Incident signalé", "Gemeld verkeersincident")
    case "hazard": return roadworksText("Reported hazard", "Gemeldete Gefahr", "Danger signalé", "Gemeld gevaar")
    case "congestion": return roadworksText("Reported congestion", "Gemeldeter Stau", "Embouteillage signalé", "Gemelde file")
    default: return roadworksText("Report type uncertain", "Meldungsart ungewiss", "Type de signalement incertain", "Soort melding onzeker")
    }
}

private func roadworksSourceText(_ sourceID: String) -> String {
    switch sourceID {
    case "bemas": return "BEMaS · MobiData BW"
    case "incidents-bw": return roadworksText("BW traffic incidents", "BW-Verkehrsmeldungen", "Incidents routiers BW", "BW-verkeersmeldingen")
    case "autobahn-short-term": return roadworksText("Autobahn short-term works", "Autobahn-Tagesbaustellen", "Travaux autoroutiers de courte durée", "Kortdurende snelwegwerkzaamheden")
    case "autobahn-long-term": return roadworksText("Autobahn long-term works", "Autobahn-Dauerbaustellen", "Travaux autoroutiers de longue durée", "Langdurige snelwegwerkzaamheden")
    default: return sourceID
    }
}

private func roadworksAgeText(_ age: Int?) -> String {
    let title = roadworksText("Source age", "Alter der Quelldaten", "Âge des données source", "Leeftijd brongegevens")
    guard let age else { return title + ": " + roadworksText("unknown", "unbekannt", "inconnu", "onbekend") }
    return title + ": \(age) min"
}

private func roadworksDirectionText(_ direction: String) -> String {
    let value = direction == "unknown"
        ? roadworksText("unknown", "unbekannt", "inconnu", "onbekend")
        : direction == "one_direction"
            ? roadworksText("one direction", "eine Richtung", "un seul sens", "één richting") : direction
    let source = direction == "both"
        ? roadworksText("Publisher: both directions", "Anbieter: beide Richtungen", "Fournisseur : deux sens", "Bron: beide richtingen")
        : roadworksText("Publisher direction", "Richtungsangabe des Anbieters", "Sens indiqué par le fournisseur", "Richting volgens de bron") + ": " + value
    return source + " · " + roadworksText("Your road/direction is unverified", "Eigene Straße/Fahrtrichtung nicht bestätigt", "Votre route et votre sens ne sont pas vérifiés", "Uw weg/rijrichting is niet bevestigd")
}

private func roadworksValidityText(_ feature: RoadworksAdvisory.Feature) -> String {
    guard feature.validityBasis == "reported_active" else { return "\(feature.outer.start.formatted()) – \(feature.outer.end.formatted())" }
    let expiry = feature.outer.end.formatted()
    var text = roadworksText("Source reports active; report expires ", "Quelle meldet aktiv; Meldung verfällt ",
        "Source : actif ; le signalement expire le ", "Bron meldt actief; melding vervalt ") + expiry
    if feature.sourceValidityStart != nil || feature.sourceValidityEnd != nil {
        let missing = roadworksText("not specified", "nicht angegeben", "non précisée", "niet opgegeven")
        text += "\n" + roadworksText("Original source time specification: ", "Ursprüngliche Zeitangabe der Quelle: ",
            "Période d’origine de la source : ", "Oorspronkelijke bronperiode: ")
            + (feature.sourceValidityStart?.formatted() ?? missing) + " – " + (feature.sourceValidityEnd?.formatted() ?? missing)
    }
    return text
}

struct RoadworksSettingsSection: View {
    @ObservedObject private var service: RoadworksService
    @MainActor init(service: RoadworksService? = nil) {
        _service = ObservedObject(wrappedValue: service ?? .shared)
    }
    var body: some View {
        Section(roadworksText("Live road advisories", "Live-Verkehrsmeldungen", "Signalements routiers en direct", "Actuele verkeersmeldingen")) {
            Toggle(roadworksText("Reported road advisories in BW", "Gemeldete Straßenereignisse in BW", "Signalements routiers en BW", "Verkeersmeldingen in BW"), isOn: Binding(get: { service.enabled }, set: { service.setEnabled($0) }))
                .accessibilityIdentifier("settings.roadworks.enabled")
            Text(roadworksText("Optional internet updates over Wi-Fi or cellular. Proximity stays on your phone. Coverage is partial and reports may be delayed. No speed limit is inferred.", "Optionale Updates über WLAN oder Mobilfunk. Die Nähe wird auf dem Telefon berechnet. Daten sind unvollständig und können verspätet sein. Daraus wird kein Tempolimit abgeleitet.", "Mises à jour facultatives par Wi-Fi ou réseau mobile. La proximité est calculée sur le téléphone. Données partielles et parfois retardées. Aucun changement de limitation.", "Optionele updates via wifi of mobiel. Nabijheid wordt op de telefoon berekend. Gegevens zijn onvolledig en kunnen vertraagd zijn. Geen invloed op de snelheidslimiet.")).font(.caption)
            if service.enabled {
                Text(roadworksStatusText(service.status)).font(.caption).accessibilityIdentifier("settings.roadworks.status")
                ForEach(service.sources, id: \.id) { source in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(roadworksSourceText(source.id)).font(.caption.bold())
                        Text(roadworksStatusText(source.enabled ? service.sourceStatus(for: source.id).rawValue : "off") + " · " + roadworksAgeText(service.sourceAgeMinutes(for: source.id))).font(.caption)
                        if !source.attribution.isEmpty {
                            Text([source.attribution["provider"], source.attribution["license_id"], source.attribution["dataset_url"], source.attribution["license_url"], source.attribution["changes"]].compactMap { $0 }.joined(separator: " · ")).font(.caption)
                        }
                    }.accessibilityElement(children: .combine)
                }
                Button(roadworksText("Refresh BW data", "BW-Daten aktualisieren", "Actualiser les données BW", "BW-gegevens vernieuwen")) { service.refresh(explicit: true) }
                Button(roadworksText("Clear cached data", "Gespeicherte Daten löschen", "Effacer le cache", "Cache wissen")) { service.clearCache() }
                if service.nearby.isEmpty, ["fresh", "delayed"].contains(service.status) {
                    Text(roadworksText("No reported road advisories nearby in the available data (5 km).", "In den verfügbaren Daten keine gemeldeten Straßenereignisse in der Nähe (5 km).", "Aucun signalement routier à proximité dans les données disponibles (5 km).", "Geen verkeersmeldingen in de beschikbare gegevens in de buurt (5 km)." )).font(.caption)
                }
                ForEach(service.nearby, id: \.0.id) { feature, distance in
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(feature.roadLabel) · \(Int(distance.rounded())) m").font(.headline)
                        Text(roadworksKindText(feature.kind)).font(.subheadline)
                        Text(roadworksSourceText(feature.advisorySource) + " · " + roadworksStatusText(service.sourceStatus(for: feature.advisorySource).rawValue) + " · " + roadworksAgeText(service.sourceAgeMinutes(for: feature.advisorySource))).font(.caption)
                        Text(roadworksText("Source description (German)", "Quellbeschreibung (Deutsch)", "Description source (allemand)", "Bronbeschrijving (Duits)")).font(.caption)
                        Text(feature.description)
                        Text(roadworksValidityText(feature)).font(.caption)
                        Text("MobiData BW · \(roadworksStatusText(feature.operatorStatus)) · \(roadworksStatusText(feature.scheduleStatus))").font(.caption)
                        Text(roadworksDirectionText(feature.direction)).font(.caption)
                        Text(roadworksText("Source ID", "Quell-ID", "Identifiant source", "Bron-ID") + ": " + feature.id).font(.caption).textSelection(.enabled)
                        if let sourceID = feature.sourceID { Text(sourceID).font(.caption).textSelection(.enabled) }
                    }.accessibilityElement(children: .combine)
                }
                if service.sources.first?.attribution.isEmpty == true { Text("Verkehrsministerium Baden-Württemberg · BEMaS via MobiData BW · dl-de/by-2-0").font(.caption) }
            }
        }
    }
}

struct RoadworksDrivingAdvisoryView: View {
    @ObservedObject private var service: RoadworksService
    @MainActor init(service: RoadworksService? = nil) {
        _service = ObservedObject(wrappedValue: service ?? .shared)
    }
    var body: some View {
        if let card = service.card {
            let heading = roadworksText("Reported nearby", "In der Nähe gemeldet", "Signalé à proximité", "In de buurt gemeld")
            let distance = "\(Int((card.distanceM / 10).rounded(.up)) * 10) m"
            let delay = card.freshness == .delayed ? roadworksText("delayed", "verzögert", "retardé", "vertraagd") : ""
            let offline = service.status == "offline" ? roadworksText("offline", "offline", "hors ligne", "offline") : ""
            let summary = [heading, roadworksKindText(card.feature.kind), distance].joined(separator: " · ")
            let metadata = [roadworksSourceText(card.feature.advisorySource),
                            roadworksAgeText(service.sourceAgeMinutes(for: card.feature.advisorySource)), delay, offline]
                .filter { !$0.isEmpty }.joined(separator: " · ")
            VStack(spacing: 2) {
                Text(summary)
                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("dashboard.roadworks.summary")
                Text(metadata)
                    .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("dashboard.roadworks.metadata")
                if !card.feature.roadLabel.isEmpty {
                    Text(card.feature.roadLabel).lineLimit(1).truncationMode(.tail)
                        .accessibilityIdentifier("dashboard.roadworks.road")
                }
            }
            .font(.caption).multilineTextAlignment(.center)
            .accessibilityElement(children: .combine).accessibilityIdentifier("dashboard.roadworks")
        }
    }
}
