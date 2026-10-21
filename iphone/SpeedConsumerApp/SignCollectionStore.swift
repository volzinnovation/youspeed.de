import Foundation
import SQLite3

struct SignCollectionBatch {
    let id: String
    let epoch: Int
    let kind: String
    let body: String
}

struct SignCollectionControl {
    let id: String
    let kind: String
    let body: String
    let receipt: String?
    let response: [String: Any]?

    var isComplete: Bool {
        guard let response else { return false }
        if kind == "deletion" {
            return ["active_data_removed", "archives_purged", "backup_expiry_complete"].allSatisfy {
                SignCollectionJSON.boolean(response[$0]) == true
            }
        }
        return ["recorded", "processing_stop_applied"].contains(response["state"] as? String ?? "")
    }
}

/// One app-private SQLite transaction owns installation identity, lifecycle,
/// control requests and immutable batches. No installation authentication keys.
final class SignCollectionStore: @unchecked Sendable {
    static let maximumEventBytes = 16 * 1024
    private var db: OpaquePointer?
    private let lock = NSRecursiveLock()
    private var sessionClaims: [String: SignCollectionClaim] = [:]
    private var sessionID: String?
    private var promptedScopes = Set<String>()
    private let now: () -> Date
    let gate: SignCollectionContractGate

    init(root: URL, gate: SignCollectionContractGate, now: @escaping () -> Date = Date.init) throws {
        self.gate = gate; self.now = now
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        var excluded = root; var values = URLResourceValues(); values.isExcludedFromBackup = true
        try excluded.setResourceValues(values)
        #if os(iOS)
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: root.path)
        #endif
        guard sqlite3_open_v2(root.appendingPathComponent("collection.sqlite").path, &db, SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX, nil) == SQLITE_OK else { throw SignCollectionError.storage }
        sqlite3_busy_timeout(db, 5_000)
        do {
            try execute("PRAGMA journal_mode=WAL"); try execute("PRAGMA synchronous=FULL"); try execute("PRAGMA secure_delete=ON")
            let version = try rows("PRAGMA user_version").first?.first ?? "0"
            guard ["0", "1"].contains(version) else { throw SignCollectionError.storage }
            try transaction {
                try execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                try execute("CREATE TABLE IF NOT EXISTS controls(sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, receipt TEXT, response TEXT)")
                if version == "1" { for key in ["installation", "epoch", "generation"] { guard try state(key) != nil else { throw SignCollectionError.storage } } }
                try initialize()

            }
        } catch { sqlite3_close(db); db = nil; throw error }
    }

    deinit { sqlite3_close(db) }

    // Schema creation is separate to keep the SQL auditable in both clients.
    private func initialize() throws {
        try execute("CREATE TABLE IF NOT EXISTS identities(id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL)")
        try execute("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, kind TEXT NOT NULL, auth TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending', batch TEXT,not_before REAL NOT NULL DEFAULT 0)")
        try execute("CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, receipt TEXT, response TEXT)")
        try execute("CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, metadata TEXT NOT NULL, bytes BLOB NOT NULL, created REAL NOT NULL, encoded_hash TEXT NOT NULL,handle TEXT,receipt TEXT,response TEXT)")
        try execute("CREATE TABLE IF NOT EXISTS crop_reviews(id TEXT PRIMARY KEY,metadata TEXT NOT NULL,bytes BLOB NOT NULL,auth TEXT NOT NULL,created REAL NOT NULL)")
        if !(try rows("PRAGMA table_info(media)")).contains(where: { $0[1] == "auth" }) { try execute("ALTER TABLE media ADD COLUMN auth TEXT NOT NULL DEFAULT ''") }
        if try state("installation") == nil { try save("installation", SignCollectionJSON.uuid()) }
        try execute("INSERT OR IGNORE INTO state VALUES('epoch','0')")
        try execute("INSERT OR IGNORE INTO state VALUES('generation','0')")
        try execute("PRAGMA user_version=1")
        guard SignCollectionJSON.isUUID(try state("installation") ?? ""), let epoch = Int(try state("epoch") ?? ""), epoch >= 0, epoch <= Int32.max, let generation = Int(try state("generation") ?? ""), generation >= 0, generation <= Int32.max else { throw SignCollectionError.storage }
    }

    var installationID: String { get throws { try locked { try state("installation")! } } }
    var collectionEpoch: Int { get throws { try locked { Int(try state("epoch")!)! } } }

    /// Call with the stable drive/camera-entry ID, never on foreground changes.
    func beginSession(_ id: String) throws {
        try locked {
            guard SignCollectionJSON.isUUID(id) else { throw SignCollectionError.invalidContract }
            if sessionID != id { sessionID = id; sessionClaims.removeAll(); promptedScopes.removeAll() }
        }
    }
    func endSession() { lock.lock(); defer { lock.unlock() }; sessionID = nil; sessionClaims.removeAll(); promptedScopes.removeAll() }

    /// Explicit settings action permits a new question; it never grants consent.
    func allowPromptAgain(scope: String) throws {
        try locked { try save("consent_" + scope, nil); sessionClaims.removeValue(forKey: scope); promptedScopes.remove(scope) }
    }

    func shouldPrompt(scope: String, disclosure: String) throws -> Bool {
        try locked {
            guard gate.verified, sessionID != nil, try state("deletion") == nil, !promptedScopes.contains(scope) else { return false }
            if let remembered = try remembered(scope) {
                // Remembered refusal is never reset by a disclosure revision.
                if remembered.state != "granted" || remembered.disclosureVersion == disclosure { return false }
            }
            promptedScopes.insert(scope)
            return true
        }
    }

    /// The unchecked checkbox remembers neither answer. Dismissal must not call
    /// this method. A granted session claim stays with already-captured events.
    @discardableResult
    func decide(scope: String, disclosure: String, granted: Bool, dontAskAgain: Bool) throws -> SignCollectionClaim {
        try locked {
            guard sessionID != nil, try state("deletion") == nil, (scope == "sign_metadata" || scope == "crop_storage" || (scope.hasPrefix("processor:") && scope.count <= 160)), !disclosure.isEmpty, disclosure.count <= 160 else { throw SignCollectionError.consentRequired }
            return try transaction {
                let generation = Int(try state("generation")!)! + 1
                guard generation <= Int32.max else { throw SignCollectionError.invalidContract }
                let claim = SignCollectionClaim(scope: scope, disclosureVersion: disclosure, decidedAt: SignCollectionJSON.utc(now()), generation: generation, state: granted ? "granted" : "refused")
                try save("authorization_" + scope, SignCollectionJSON.canonical(claim.wire))
                try save("generation", String(generation))
                try save("consent_" + scope, dontAskAgain ? try SignCollectionJSON.canonical(claim.wire) : nil)
                try addControl(kind: "consent", id: SignCollectionJSON.uuid(), claim: claim)
                if !granted { try purge(scope: scope) }
                sessionClaims[scope] = claim
                return claim
            }
        }
    }

    func withdraw(scope: String, disclosure: String) throws {
        try locked { try transaction {
            let generation = Int(try state("generation")!)! + 1
            guard generation <= Int32.max, (scope == "sign_metadata" || scope == "crop_storage" || (scope.hasPrefix("processor:") && scope.count <= 160)) else { throw SignCollectionError.invalidContract }
            let claim = SignCollectionClaim(scope: scope, disclosureVersion: disclosure, decidedAt: SignCollectionJSON.utc(now()), generation: generation, state: "withdrawn")
            try save("authorization_" + scope, SignCollectionJSON.canonical(claim.wire))
            try save("generation", String(generation)); try save("consent_" + scope, SignCollectionJSON.canonical(claim.wire))
            try addControl(kind: "consent", id: SignCollectionJSON.uuid(), claim: claim)
            try purge(scope: scope); sessionClaims.removeValue(forKey: scope)
        } }
    }

    private func remembered(_ scope: String) throws -> SignCollectionClaim? {
        guard let text = try state("consent_" + scope), let o = try SignCollectionJSON.parse(text) as? [String: Any],
              let d = o["disclosure_version"] as? String, let time = o["decided_at"] as? String,
              let generation = o["consent_generation"] as? Int, let s = o["state"] as? String else { return nil }
        return SignCollectionClaim(scope: scope, disclosureVersion: d, decidedAt: time, generation: generation, state: s)
    }

    private func authorization(_ scope: String, disclosure: String) throws -> SignCollectionClaim {
        guard sessionID != nil, try state("deletion") == nil,
              let claim = try sessionClaims[scope] ?? remembered(scope), claim.state == "granted", claim.disclosureVersion == disclosure else { throw SignCollectionError.consentRequired }
        guard let latest = try state("authorization_" + scope), latest == (try SignCollectionJSON.canonical(claim.wire)) else { throw SignCollectionError.consentRequired }
        return claim
    }

    func claim(scope: String, disclosure: String) throws -> SignCollectionClaim { try locked { try authorization(scope, disclosure: disclosure) } }

    func enqueue(kind: String, event: [String: Any], disclosure: String) throws {
        try locked { try transaction {
            guard gate.verified, ["sighting", "correction", "media_status"].contains(kind),
                  let id = event["event_id"] as? String, SignCollectionJSON.isUUID(id), event["schema_version"] as? Int == 1 else { throw SignCollectionError.invalidContract }
            try gate.validate(event, model: kind.replacingOccurrences(of: "_", with: "-"))
            let claim = try authorization("sign_metadata", disclosure: disclosure)
            try enqueueCaptured(kind: kind, event: event, claim: claim.wire)
        } }
    }
    private func enqueueCaptured(kind: String, event: [String: Any], claim: [String: Any]) throws {
            let id = event["event_id"] as! String
            try gate.validate(event, model: kind.replacingOccurrences(of: "_", with: "-"))
            let body = try SignCollectionJSON.canonical(event), digest = SignCollectionJSON.sha256(Data(body.utf8))
            guard body.utf8.count <= Self.maximumEventBytes else { throw SignCollectionError.capacity }
            if let prior = try rows("SELECT epoch,kind,digest FROM identities WHERE id=?", [id]).first {
                guard prior == [try state("epoch")!, kind, digest] else { throw SignCollectionError.invalidContract }; return
            }
            let correction = kind == "correction"
            let stats = try rows("SELECT count(*),COALESCE(sum(length(CAST(body AS BLOB))),0) FROM events WHERE " + (correction ? "kind='correction'" : "kind!='correction'")).first!
            guard Int(stats[0])! < (correction ? 1_000 : 20_000), Int(stats[1])! + body.utf8.count <= (correction ? 5 : 50) * 1024 * 1024 else { throw SignCollectionError.capacity }
            try execute("INSERT INTO events(id,epoch,kind,auth,body,digest,created) VALUES(?,?,?,?,?,?,?)", [id, try state("epoch")!, kind, try SignCollectionJSON.canonical(claim), body, digest, String(now().timeIntervalSince1970)])
            try execute("INSERT INTO identities VALUES(?,?,?,?)", [id, try state("epoch")!, kind, digest])
    }

    /// Persist batches before I/O; one transport request runs at a time.
    /// Persist the batch before I/O; retry this body unchanged after a lost ACK.
    func prepareBatch(maxEvents: Int = 100, maxBytes: Int = 512 * 1024) throws -> SignCollectionBatch? {
        try locked { try transaction {
            guard maxEvents > 0, maxBytes > 0 else { throw SignCollectionError.invalidContract }
            guard try state("deletion") == nil else { throw SignCollectionError.deletionPending }
            let cutoff = String(now().timeIntervalSince1970 - 30 * 86400)
            let expired = Int(try rows("SELECT count(*) FROM events WHERE created<?", [cutoff])[0][0])!
            if expired > 0 {
                try save("expired_events", String(Int(try state("expired_events") ?? "0")! + expired))
                for row in try rows("SELECT DISTINCT batch FROM events WHERE created<? AND batch IS NOT NULL", [cutoff]) {
                    try execute("DELETE FROM batches WHERE id=?", [row[0]])
                    try execute("UPDATE events SET batch=NULL WHERE batch=?", [row[0]])
                }
                try execute("DELETE FROM events WHERE created<?", [cutoff])
            }
            if let row = try rows("SELECT id,epoch,kind,body FROM batches WHERE response IS NULL ORDER BY rowid LIMIT 1").first { return SignCollectionBatch(id: row[0], epoch: Int(row[1])!, kind: row[2], body: row[3]) }
            let ready = String(now().timeIntervalSince1970)
            guard let first = try rows("SELECT kind,auth FROM events WHERE state='pending' AND batch IS NULL AND not_before<=? ORDER BY created,id LIMIT 1", [ready]).first else { return nil }
            let selected = try rows("SELECT id,body FROM events WHERE state='pending' AND batch IS NULL AND kind=? AND auth=? AND not_before<=? ORDER BY created,id LIMIT ?", first + [ready, String(min(100, maxEvents))])
            let id = SignCollectionJSON.uuid(), epoch = Int(try state("epoch")!)!
            var events: [Any] = []; var ids: [String] = []
            var envelope: [String: Any] = ["schema_version": 1, "batch_id": id, "installation_id": try state("installation")!, "collection_epoch": epoch, "collection_authorization": try SignCollectionJSON.parse(first[1])]
            for row in selected {
                let candidate = try SignCollectionJSON.parse(row[1])
                envelope["events"] = events + [candidate]
                if try SignCollectionJSON.canonical(envelope).utf8.count > maxBytes {
                    guard !events.isEmpty else { throw SignCollectionError.capacity }; break
                }
                events.append(candidate); ids.append(row[0])
            }
            envelope["events"] = events
            let body = try SignCollectionJSON.canonical(envelope)
            try execute("INSERT INTO batches(id,epoch,kind,body) VALUES(?,?,?,?)", [id, String(epoch), first[0], body])
            for eventID in ids { try execute("UPDATE events SET batch=? WHERE id=?", [id, eventID]) }
            return SignCollectionBatch(id: id, epoch: epoch, kind: first[0], body: body)
        } }
    }

    func transportRetryDate() throws -> Date {
        try locked { Date(timeIntervalSince1970: Double(try state("transport_retry") ?? "0") ?? 0) }
    }
    func deferTransport(until: Date) throws { try locked { try save("transport_retry", String(until.timeIntervalSince1970)) } }
    func ordinaryRetryDate() throws -> Date { try locked { Date(timeIntervalSince1970: Double(try state("ordinary_retry") ?? "0") ?? 0) } }
    func cropRetryDate() throws -> Date { try locked { Date(timeIntervalSince1970: Double(try state("crop_retry") ?? "0") ?? 0) } }
    func deferCrop(until: Date) throws { try locked { try save("crop_retry", String(until.timeIntervalSince1970)) } }
    func deferOrdinary(until: Date) throws { try locked { try save("ordinary_retry", String(until.timeIntervalSince1970)) } }
    func recordBestEffortFailure(id: String) throws -> Int {
        try locked {
            let key = "capture_attempts_" + id, count = Int(try state(key) ?? "0")! + 1
            try save(key, String(count)); return count
        }
    }
    func finishBestEffortBatch(id: String, dropped: Bool = false) throws {
        try locked { try transaction {
            try execute("DELETE FROM events WHERE batch=?", [id])
            try execute("UPDATE batches SET body='',response=? WHERE id=?", [try SignCollectionJSON.canonical(["state": dropped ? "dropped" : "sent"]), id])
            try execute("DELETE FROM state WHERE key=?", ["capture_attempts_" + id])
        } }
    }
    func finishBestEffortCrop(id: String, dropped: Bool = false) throws {
        try locked { try transaction {
            try execute("UPDATE media SET bytes=X'',metadata='',handle=NULL,receipt=NULL,response=? WHERE id=?", [try SignCollectionJSON.canonical(["state": dropped ? "dropped" : "sent"]), id])
            try execute("DELETE FROM state WHERE key=?", ["capture_attempts_" + id])
        } }
    }
    var deletionIsPending: Bool { get throws { try locked { try state("deletion") != nil } } }

    func quarantineBatch(id: String, code: String) throws {
        try locked { try transaction { try finishFailedBatch(id: id, code: code) } }
    }
    func quarantineControl(id: String, code: String) throws {
        try locked { try transaction {
            guard code.range(of: "^[a-z][a-z0-9_]{0,79}$", options: .regularExpression) != nil,
                  let operation = try controlStatus(id: id) else { throw SignCollectionError.invalidContract }
            var response = operation.response ?? [:]; response["client_error"] = code
            try execute("UPDATE controls SET response=? WHERE id=?", [try SignCollectionJSON.canonical(response), id])
        } }
    }
    private func finishFailedBatch(id: String, code: String) throws {
        guard code.range(of: "^[a-z][a-z0-9_]{0,79}$", options: .regularExpression) != nil else { throw SignCollectionError.invalidContract }
        try execute("UPDATE events SET state='quarantined',batch=NULL WHERE batch=?", [id])
        try execute("UPDATE batches SET body='',response=? WHERE id=? AND response IS NULL", [try SignCollectionJSON.canonical(["transport_error": code]), id])
    }
    /// A 413 replaces only batch IDs. Epoch, authorization and event IDs survive.
    func splitBatch(id: String) throws {
        try locked { try transaction {
            guard let row = try rows("SELECT epoch,kind,body FROM batches WHERE id=? AND response IS NULL", [id]).first else { return }
            var envelope = try SignCollectionJSON.parse(row[2]) as! [String: Any]
            let events = envelope["events"] as! [[String: Any]]
            guard events.count > 1 else { try finishFailedBatch(id: id, code: "request_too_large"); return }
            let middle = events.count / 2
            for part in [Array(events[..<middle]), Array(events[middle...])] {
                let next = SignCollectionJSON.uuid(); envelope["batch_id"] = next; envelope["events"] = part
                try execute("INSERT INTO batches(id,epoch,kind,body) VALUES(?,?,?,?)", [next, row[0], row[1], try SignCollectionJSON.canonical(envelope)])
                for event in part { try execute("UPDATE events SET batch=? WHERE id=? AND batch=?", [next, event["event_id"] as! String, id]) }
            }
            try execute("UPDATE batches SET body='',response=? WHERE id=?", [try SignCollectionJSON.canonical(["transport_error": "request_too_large"]), id])
        } }
    }

    func requestDeletion() throws -> String {
        try locked { try transaction {
            if let pending = try state("deletion") { return pending }
            let id = SignCollectionJSON.uuid()
            let body = try SignCollectionJSON.canonical(["installation_id": try state("installation")!, "collection_epoch": Int(try state("epoch")!)!, "deletion_request_id": id])
            try execute("INSERT INTO controls(id,kind,body) VALUES(?,'deletion',?)", [id, body])
            try save("deletion", id); try purge(scope: "sign_metadata")
            try execute("DELETE FROM state WHERE key LIKE 'consent_%' OR key LIKE 'authorization_%'")
            sessionClaims.removeAll()
            return id
        } }
    }

    /// A receipt acknowledges intake, not completion. Return every unfinished
    /// operation so a worker can poll them fairly and a UI can show each phase.
    func pendingControls() throws -> [SignCollectionControl] {
        try locked {
            let pending = try rows("SELECT id,kind,body,receipt,response FROM controls ORDER BY sequence")
                .map { try control($0) }.filter { !$0.isComplete }
            let barrier = try state("deletion")
            let remaining = pending.filter { $0.id != barrier }
            return pending.filter { $0.id == barrier }
                + remaining.filter { $0.receipt == nil }
                + remaining.filter { $0.receipt != nil }
        }
    }

    func nextControl() throws -> SignCollectionControl? { try pendingControls().first }

    /// Completed operations remain readable after restart and later deletions.
    func controlStatus(id: String) throws -> SignCollectionControl? {
        try locked { try rows("SELECT id,kind,body,receipt,response FROM controls WHERE id=?", [id]).first.map { try control($0) } }
    }
    func controlHistory() throws -> [SignCollectionControl] {
        try locked { try rows("SELECT id,kind,body,receipt,response FROM controls ORDER BY sequence").map { try control($0) } }
    }
    func isAuthorized(scope: String, disclosure: String) -> Bool {
        lock.lock(); defer { lock.unlock() }; return (try? authorization(scope, disclosure: disclosure)) != nil
    }

    private func control(_ row: [String]) throws -> SignCollectionControl {
        let response: [String: Any]?
        if row[4].isEmpty { response = nil }
        else {
            guard let object = try SignCollectionJSON.parse(row[4]) as? [String: Any] else { throw SignCollectionError.storage }
            response = object
        }
        return SignCollectionControl(id: row[0], kind: row[1], body: row[2], receipt: row[3].isEmpty ? nil : row[3], response: response)
    }

    func applyControlReceipt(id: String, response: [String: Any]) throws {
        try locked { try transaction {
            guard let operation = try controlStatus(id: id),
                  let receipt = response["operation_receipt"] as? String, !receipt.isEmpty, receipt.count <= 128,
                  operation.receipt == nil || operation.receipt == receipt else { throw SignCollectionError.invalidReceipt }
            if operation.kind == "deletion" {
                let request = try SignCollectionJSON.parse(operation.body) as! [String: Any]
                guard let requestedEpoch = SignCollectionJSON.integer(request["collection_epoch"]),
                      let next = SignCollectionJSON.integer(response["next_collection_epoch"]),
                      next == requestedEpoch + 1, next <= Int32.max,
                      let removed = SignCollectionJSON.boolean(response["active_data_removed"]),
                      response["state"] as? String == (removed ? "active_data_removed" : "deletion_pending") else { throw SignCollectionError.invalidReceipt }
                for phase in ["active_data_removed", "archives_purged", "backup_expiry_complete"] {
                    if let value = response[phase], SignCollectionJSON.boolean(value) == nil { throw SignCollectionError.invalidReceipt }
                    if SignCollectionJSON.boolean(operation.response?[phase]) == true, SignCollectionJSON.boolean(response[phase]) != true { throw SignCollectionError.invalidReceipt }
                    if phase != "active_data_removed", SignCollectionJSON.boolean(response[phase]) == true, !removed { throw SignCollectionError.invalidReceipt }
                }
                let alreadyRemoved = SignCollectionJSON.boolean(operation.response?["active_data_removed"]) == true
                if alreadyRemoved {
                    guard Int(try state("epoch")!)! >= next else { throw SignCollectionError.invalidReceipt }
                } else {
                    guard try state("deletion") == id, Int(try state("epoch")!)! == requestedEpoch else { throw SignCollectionError.invalidReceipt }
                }
                if removed && !alreadyRemoved {
                    try save("epoch", String(next)); try save("deletion", nil)
                    // Unsent old consent must never replay into a new epoch.
                    // Keep acknowledged operations for polling and phase history.
                    try execute("DELETE FROM controls WHERE kind='consent' AND receipt IS NULL")
                    sessionClaims.removeAll(); sessionID = nil; promptedScopes.removeAll()
                }
            } else {
                guard let status = response["state"] as? String,
                      ["recorded", "processing_stop_pending", "processing_stop_applied"].contains(status) else { throw SignCollectionError.invalidReceipt }
                if operation.isComplete, operation.response?["state"] as? String != status { throw SignCollectionError.invalidReceipt }
            }
            try execute("UPDATE controls SET receipt=?,response=? WHERE id=?", [receipt, try SignCollectionJSON.canonical(response), id])
        } }
    }

    /// Developer diagnostics only; deletion/withdrawal controls are retained.
    func clearPendingForDeveloper() throws { try locked { try transaction { try purge(scope: "sign_metadata") } } }
    func pendingCount() throws -> Int { try locked { Int(try rows("SELECT count(*) FROM events")[0][0])! } }
    func expiredEventCount() throws -> Int { try locked { Int(try state("expired_events") ?? "0")! } }
    func expiredCropCount() throws -> Int { try locked { Int(try state("expired_crops") ?? "0")! } }

    /// Sign sharing includes all automatic crops; no separate user decision.
    func authorizeAutomaticCrops() throws {
        try locked {
            _ = try authorization("sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure)
            if !isAuthorized(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure) {
                _ = try decide(scope: "crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure, granted: true,
                               dontAskAgain: try remembered("sign_metadata") != nil)
            }
        }
    }
    func enqueueCrop(metadata: [String: Any], bytes: Data, disclosure: String, processorDisclosure: String? = nil) throws {
        try locked { try transaction {
            try insertCrop(metadata: metadata, bytes: bytes, disclosure: disclosure, processorDisclosure: processorDisclosure)
        } }
    }
    /// Automatic, separately consented delivery retains the capture-time metadata grant.
    func enqueueAutomaticCrop(metadata: [String: Any], bytes: Data) throws {
        try locked { try transaction {
            let claim = try authorization("sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure)
            guard metadata["privacy_preflight"] as? String == "passed" else { throw SignCollectionError.invalidContract }
            try insertCrop(metadata: metadata, bytes: bytes, disclosure: SignCollectionCapabilities.cropDisclosure, processorDisclosure: nil, trustedEncoding: true)
            try execute("UPDATE media SET auth=? WHERE id=?", [try SignCollectionJSON.canonical(claim.wire), metadata["crop_id"] as! String])
        } }
    }
    /// Upgrade the former review queue with its captured grants, without a new session.
    func migrateAutomaticCrops() throws {
        try locked {
            try expireCrops()
            try transaction {
                guard try state("deletion") == nil else { return }
                while let row = try rows("SELECT id,metadata,auth,created FROM crop_reviews ORDER BY created LIMIT 1").first {
                    guard let bytes = try cropReviews().first?.bytes else { throw SignCollectionError.storage }
                    var metadata = try SignCollectionJSON.parse(row[1]) as! [String: Any]
                    metadata["privacy_preflight"] = "passed"; metadata["redaction_version"] = "metadata-strip-1"
                    try execute("DELETE FROM crop_reviews WHERE id=?", [row[0]])
                    try insertCrop(metadata: metadata, bytes: bytes, disclosure: SignCollectionCapabilities.cropDisclosure, processorDisclosure: nil, captured: true)
                    try execute("UPDATE media SET auth=?,created=? WHERE id=?", [row[2], row[3], row[0]])
                }
            }
        }
    }
    private func insertCrop(metadata: [String: Any], bytes: Data, disclosure: String, processorDisclosure: String?, captured: Bool = false, trustedEncoding: Bool = false) throws {
            if !trustedEncoding { try gate.validate(metadata, model: "crop") }
            guard let encodedHash = metadata["encoded_sha256"] as? String else { throw SignCollectionError.invalidContract }
            guard metadata["installation_id"] as? String == (try state("installation")), metadata["collection_epoch"] as? Int == Int(try state("epoch")!),
                  metadata["byte_length"] as? Int == bytes.count, trustedEncoding || encodedHash == SignCollectionJSON.sha256(bytes) else { throw SignCollectionError.invalidContract }
            if !captured {
                let claim = try authorization("crop_storage", disclosure: disclosure)
                guard try SignCollectionJSON.canonical(metadata["collection_authorization"]!) == SignCollectionJSON.canonical(claim.wire) else { throw SignCollectionError.consentRequired }
            }
            if let processor = metadata["processor_authorization"], !(processor is NSNull) {
                guard let o = processor as? [String: Any], let scope = o["scope"] as? String, scope.hasPrefix("processor:"), let processorDisclosure else { throw SignCollectionError.consentRequired }
                let authorized = try authorization(scope, disclosure: processorDisclosure)
                guard try SignCollectionJSON.canonical(processor) == SignCollectionJSON.canonical(authorized.wire) else { throw SignCollectionError.consentRequired }
            }
            let id = metadata["crop_id"] as! String, text = try SignCollectionJSON.canonical(metadata), digest = try SignCollectionJSON.digest(metadata)
            if let prior = try rows("SELECT epoch,kind,digest FROM identities WHERE id=?", [id]).first {
                guard prior == [try state("epoch")!, "crop", digest] else { throw SignCollectionError.invalidContract }; return
            }
            let size = Int(try rows("SELECT (SELECT COALESCE(sum(length(bytes)),0) FROM media)+(SELECT COALESCE(sum(length(bytes)),0) FROM crop_reviews)")[0][0])!
            guard size + bytes.count <= 1024 * 1024 * 1024 else { throw SignCollectionError.capacity }
            try execute("INSERT INTO media(id,epoch,metadata,created,encoded_hash,bytes) VALUES(?,?,?,?,?,?)", [id, try state("epoch")!, text, String(now().timeIntervalSince1970), encodedHash], blob: bytes)
            try execute("INSERT INTO identities VALUES(?,?,?,?)", [id, try state("epoch")!, "crop", digest])
    }

    // Reviews are local-only; privacy_preflight is asserted only by an explicit approval.
    func stageCrop(metadata: [String: Any], bytes: Data) throws {
        try locked { try transaction {
            guard try state("deletion") == nil else { throw SignCollectionError.deletionPending }
            let cropClaim = try authorization("crop_storage", disclosure: SignCollectionCapabilities.cropDisclosure)
            let metadataClaim = try authorization("sign_metadata", disclosure: SignCollectionCapabilities.metadataDisclosure)
            guard try SignCollectionJSON.canonical(metadata["collection_authorization"]!) == SignCollectionJSON.canonical(cropClaim.wire),
                  metadata["installation_id"] as? String == (try state("installation")), metadata["collection_epoch"] as? Int == Int(try state("epoch")!),
                  metadata["encoded_sha256"] as? String == SignCollectionJSON.sha256(bytes), metadata["byte_length"] as? Int == bytes.count else { throw SignCollectionError.invalidContract }
            var check = metadata; check["privacy_preflight"] = "user_reviewed"; try gate.validate(check, model: "crop")
            let size = Int(try rows("SELECT (SELECT COALESCE(sum(length(bytes)),0) FROM media)+(SELECT COALESCE(sum(length(bytes)),0) FROM crop_reviews)")[0][0])!
            guard size + bytes.count <= 1024 * 1024 * 1024, Int(try rows("SELECT count(*) FROM crop_reviews")[0][0])! < 500 else { throw SignCollectionError.capacity }
            var local = metadata; local.removeValue(forKey: "privacy_preflight")
            try execute("INSERT INTO crop_reviews(id,metadata,auth,created,bytes) VALUES(?,?,?,?,?)", [metadata["crop_id"] as! String, try SignCollectionJSON.canonical(local), try SignCollectionJSON.canonical(metadataClaim.wire), String(now().timeIntervalSince1970)], blob: bytes)
        } }
    }
    func cropReviewCount() throws -> Int { try locked { Int(try rows("SELECT count(*) FROM crop_reviews")[0][0])! } }
    func cropReviews() throws -> [(id: String, bytes: Data)] {
        try locked {
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(db, "SELECT id,bytes FROM crop_reviews ORDER BY created LIMIT 1", -1, &statement, nil) == SQLITE_OK else { throw SignCollectionError.storage }
            defer { sqlite3_finalize(statement) }
            var result: [(String, Data)] = []
            while sqlite3_step(statement) == SQLITE_ROW {
                guard let id = sqlite3_column_text(statement, 0), let data = sqlite3_column_blob(statement, 1) else { throw SignCollectionError.storage }
                result.append((String(cString: id), Data(bytes: data, count: Int(sqlite3_column_bytes(statement, 1)))))
            }
            return result
        }
    }
    func reviewCrop(id: String, approved: Bool) throws {
        try locked { try transaction {
            guard try state("deletion") == nil, let row = try rows("SELECT metadata,auth,created FROM crop_reviews WHERE id=?", [id]).first else { throw SignCollectionError.consentRequired }
            if approved {
                guard Double(row[2])! >= now().timeIntervalSince1970 - 7 * 86400,
                      let bytes = try cropReviews().first(where: { $0.id == id })?.bytes else { throw SignCollectionError.invalidContract }
                var metadata = try SignCollectionJSON.parse(row[0]) as! [String: Any]; metadata["privacy_preflight"] = "user_reviewed"
                // The staged row is purged by every withdrawal/deletion. Its captured claim survives session end.
                try execute("DELETE FROM crop_reviews WHERE id=?", [id])
                try insertCrop(metadata: metadata, bytes: bytes, disclosure: SignCollectionCapabilities.cropDisclosure, processorDisclosure: nil, captured: true)
                try execute("UPDATE media SET auth=?,created=? WHERE id=?", [row[1], row[2], id])
            } else { try execute("DELETE FROM crop_reviews WHERE id=?", [id]) }
            privacyCheckpointNeeded = true
        } }
    }
    private func mediaStatus(metadata: String, auth: String, status: String) throws {
        guard !auth.isEmpty else { return } // Older foundation-only entries have no captured metadata grant.
        let crop = try SignCollectionJSON.parse(metadata) as! [String: Any]
        let event: [String: Any] = ["schema_version": 1, "event_id": SignCollectionJSON.uuid(), "created_at": SignCollectionJSON.utc(now()), "crop_id": crop["crop_id"]!, "observation_id": crop["observation_id"]!, "status": status, "superseded_by": NSNull()]
        try enqueueCaptured(kind: "media_status", event: event, claim: try SignCollectionJSON.parse(auth) as! [String: Any])
    }
    func discardCrop(id: String, status: String = "missing") throws {
        try locked { try transaction {
            if let row = try rows("SELECT metadata,auth FROM media WHERE id=? AND length(bytes)>0", [id]).first {
                try mediaStatus(metadata: row[0], auth: row[1], status: status)
                try execute("UPDATE media SET bytes=X'',metadata='',handle=NULL,response=? WHERE id=?", [try SignCollectionJSON.canonical(["client_error": status]), id])
                privacyCheckpointNeeded = true
            }
        } }
    }
    func expireCrops() throws {
        try locked {
            let cutoff = String(now().timeIntervalSince1970 - 7 * 86400)
            let expired = try rows("SELECT id FROM media WHERE length(bytes)>0 AND created<?", [cutoff])
            for row in expired { try discardCrop(id: row[0], status: "expired") }
            try transaction {
                let reviews = Int(try rows("SELECT count(*) FROM crop_reviews WHERE created<?", [cutoff])[0][0])!
                try execute("DELETE FROM crop_reviews WHERE created<?", [cutoff])
                try save("expired_crops", String(Int(try state("expired_crops") ?? "0")! + expired.count + reviews))
                if reviews > 0 { privacyCheckpointNeeded = true }
            }
        }
    }
    func nextCrop() throws -> (id: String, metadata: String, bytes: Data)? {
        try locked {
            guard try state("deletion") == nil else { throw SignCollectionError.deletionPending }
            guard let row = try rows("SELECT id,metadata FROM media WHERE length(bytes)>0 AND created>=? ORDER BY created,id LIMIT 1", [String(now().timeIntervalSince1970 - 7 * 86400)]).first else { return nil }
            var statement: OpaquePointer?
            guard sqlite3_prepare_v2(db, "SELECT bytes FROM media WHERE id=?", -1, &statement, nil) == SQLITE_OK else { throw SignCollectionError.storage }
            defer { sqlite3_finalize(statement) }
            sqlite3_bind_text(statement, 1, row[0], -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
            guard sqlite3_step(statement) == SQLITE_ROW, let pointer = sqlite3_column_blob(statement, 0) else { throw SignCollectionError.storage }
            let bytes = Data(bytes: pointer, count: Int(sqlite3_column_bytes(statement, 0)))
            return (row[0], row[1], bytes)
        }
    }

    private var privacyCheckpointNeeded = false
    private func purge(scope: String) throws {
        privacyCheckpointNeeded = true
        if scope == "sign_metadata" { try execute("DELETE FROM events"); try execute("DELETE FROM batches") }
        if !scope.hasPrefix("processor:") { try execute("DELETE FROM media"); try execute("DELETE FROM crop_reviews") }
        else {
            for row in try rows("SELECT id,metadata FROM media WHERE metadata!=''") {
                let metadata = try SignCollectionJSON.parse(row[1]) as! [String: Any]
                if (metadata["processor_authorization"] as? [String: Any])?["scope"] as? String == scope { try execute("DELETE FROM media WHERE id=?", [row[0]]) }
            }
        }
    }
    private func addControl(kind: String, id: String, claim: SignCollectionClaim) throws {
        let body = try SignCollectionJSON.canonical(["schema_version": 1, "event_id": id, "installation_id": try state("installation")!, "collection_epoch": Int(try state("epoch")!)!, "collection_authorization": claim.wire])
        try execute("INSERT INTO controls(id,kind,body) VALUES(?,?,?)", [id, kind, body])
    }
    private func state(_ key: String) throws -> String? { try rows("SELECT value FROM state WHERE key=?", [key]).first?.first }
    private func save(_ key: String, _ value: String?) throws {
        if let value { try execute("INSERT OR REPLACE INTO state VALUES(?,?)", [key, value]) }
        else { try execute("DELETE FROM state WHERE key=?", [key]) }
    }
    private func locked<T>(_ body: () throws -> T) rethrows -> T { lock.lock(); defer { lock.unlock() }; return try body() }
    private func transaction<T>(_ body: () throws -> T) throws -> T {
        try execute("BEGIN IMMEDIATE")
        do { let result = try body(); try execute("COMMIT"); if privacyCheckpointNeeded { try execute("PRAGMA wal_checkpoint(TRUNCATE)"); privacyCheckpointNeeded = false }; return result }
        catch { try? execute("ROLLBACK"); privacyCheckpointNeeded = false; throw error }
    }
    private func execute(_ sql: String, _ args: [String] = [], blob: Data? = nil) throws { _ = try rows(sql, args, blob: blob) }
    private func rows(_ sql: String, _ args: [String] = [], blob: Data? = nil) throws -> [[String]] {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &statement, nil) == SQLITE_OK else { throw SignCollectionError.storage }
        defer { sqlite3_finalize(statement) }
        let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
        for (i, arg) in args.enumerated() { guard sqlite3_bind_text(statement, Int32(i + 1), arg, -1, transient) == SQLITE_OK else { throw SignCollectionError.storage } }
        if let blob {
            let code = blob.withUnsafeBytes { sqlite3_bind_blob(statement, Int32(args.count + 1), $0.baseAddress, Int32(blob.count), transient) }
            guard code == SQLITE_OK else { throw SignCollectionError.storage }
        }
        var result: [[String]] = []
        while true {
            let code = sqlite3_step(statement)
            if code == SQLITE_DONE { return result }
            guard code == SQLITE_ROW else { throw SignCollectionError.storage }
            result.append((0..<sqlite3_column_count(statement)).map { column in sqlite3_column_text(statement, column).map { String(cString: $0) } ?? "" })
        }
    }
}
