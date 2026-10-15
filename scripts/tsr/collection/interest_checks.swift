import Foundation

func runCollectionInterestChecks(contractRoot: URL, outputRoot: URL, fixture: [String: Any]) throws {
    let schema = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("crop-interest-v1.schema.json"), encoding: .utf8)) as! [String: Any]
    let bytes = try Data(contentsOf: contractRoot.appendingPathComponent("fixtures/crop-interest-v1.json"))
    let plan = try SignCollectionInterestPlan(data: bytes, schema: schema)
    let maximum = try SignCollectionInterestPlan(data: Data(contentsOf: contractRoot.appendingPathComponent("fixtures/crop-interest-daily-maximum-v1.json")), schema: schema)
    try check(maximum.document["algorithm_version"] as! String == "daily-maximum-v1" && maximum.rules.values.allSatisfy { $0.numerator == $0.denominator }, "production daily maximum selects every requested encounter")
    var now = plan.generated.addingTimeInterval(60), uptime: TimeInterval = 100
    let path = outputRoot.appendingPathComponent("interest-cache.json")
    try? FileManager.default.removeItem(at: path)
    let store = SignCollectionInterestStore(path: path, schema: schema, now: { now }, uptime: { uptime })
    let identity = plan.rules.keys.first!, observation = "00000000-0000-4000-8000-000000000001"
    try check(store.select(identity, observation: observation).decision == "no_valid_plan", "ordinary crops require a current plan")
    for label in ["bad", "bad:round", "bad:future"] {
        let always = SignCollectionInterestPlan.Identity(country: "DE", pack: "missing", classifier: "missing", label: label)
        try check(store.select(always, observation: observation).permits(at: now), "bad family works offline without a plan")
    }
    for label in ["badger", "Bad", "465bad98-c093-404b-9a47-8f19c833f988"] {
        try check(!SignCollectionInterestPlan.isAlways(label), "anchored class, never UUID substrings")
    }
    try store.install(bytes)
    try check(store.etag == "\"crop-interest-1\"", "revision ETag without digest")
    let chosen = store.select(identity, observation: observation)
    try check(chosen.decision == "selected" && chosen.permits(at: now), "matching exact selector collects")
    try check(store.select(.init(country: identity.country, pack: identity.pack, classifier: "wrong", label: identity.label), observation: observation).decision == "not_interested", "classifier identity must match")
    var replacement = plan.document; replacement["revision"] = 2
    try store.install(Data(SignCollectionJSON.canonical(replacement, maximumCollectionCount: 10_000).utf8))
    rejects { try store.install(bytes) }
    replacement["registry_revision"] = "conflict"
    rejects { try store.install(Data(SignCollectionJSON.canonical(replacement, maximumCollectionCount: 10_000).utf8)) }
    replacement["signature"] = "obsolete"
    rejects { _ = try SignCollectionInterestPlan(data: Data(SignCollectionJSON.canonical(replacement, maximumCollectionCount: 10_000).utf8), schema: schema) }
    let restarted = SignCollectionInterestStore(path: path, schema: schema, now: { now }, uptime: { uptime })
    try check(restarted.select(identity, observation: observation).revision == 2, "HTTPS cache survives restart")
    now = plan.expires; uptime += 172_740
    try check(restarted.etag == nil && !chosen.permits(at: now), "expiry disables ordinary crops and conditional requests")
    let vectors = try SignCollectionJSON.parse(String(contentsOf: contractRoot.appendingPathComponent("fixtures/crop-interest-sampling-v1.json"), encoding: .utf8)) as! [String: Any]
    for row in vectors["vectors"] as! [[String: Any]] {
        try check(SignCollectionInterestPlan.sample(revision: SignCollectionJSON.integer(row["revision"])!, key: row["collection_key"] as! String, observation: row["observation_id"] as! String, numerator: UInt64(SignCollectionJSON.integer(row["numerator"])!), denominator: UInt64(SignCollectionJSON.integer(row["denominator"])!)) == row["selected"] as! Bool, "shared noncryptographic selection vectors")
    }
    var activation = SignCollectionInterestActivation()
    try check(!activation.update(false) && !activation.update(false), "disabled startup makes no request")
    try check(activation.update(true) && !activation.update(true), "activation fetches once; foreground does not refetch")
    try check(!activation.update(false) && activation.update(true), "reactivation fetches once")
    var enabledStartup = SignCollectionInterestActivation()
    try check(enabledStartup.update(true) && !enabledStartup.update(true), "enabled startup fetches once")
    for decision in ["no_valid_plan", "not_interested", "sampled_out", "always", "selected"] {
        let observer = SignCollectionObserver()
        let selection = SignCollectionInterestSelection(revision: decision == "no_valid_plan" ? nil : 1, key: decision == "selected" || decision == "sampled_out" ? "DE:DE:278-10" : nil, decision: decision, fraction: ["numerator": 1, "denominator": 1], expires: plan.expires)
        var sightings = 0, crops = 0, decisions = 0
        for ms in [0, 100, 600, 1100] {
            try observer.observe(at: plan.generated.addingTimeInterval(Double(ms) / 1000), detections: [.init(key: "sign", box: [0.1, 0.1, 0.2, 0.2], payload: fixture, presentationTrack: nil)], captureCrop: { _ in crops += 1; return .stored }, selectCrop: { _, _ in decisions += 1; return selection }) { event in
                sightings += 1
                try check((event["collection_selection"] as! [String: Any])["decision"] as! String == decision, "sighting includes decision")
            }
        }
        try check(sightings == 1 && decisions == 1 && crops == (selection.collects ? 3 : 0), "all sightings survive image selection; decision freezes per encounter")
    }
    print("Swift crop interest: HTTPS schema/cache, exact selectors, expiry, noncrypto vectors, TSR activation and independent sightings passed")
}
