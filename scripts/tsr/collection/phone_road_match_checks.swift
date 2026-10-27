import Foundation

func runPhoneRoadMatchChecks(vectors: URL) throws {
    let input = try JSONSerialization.jsonObject(with: Data(contentsOf: vectors)) as! [String: Any]
    for scenario in input["cases"] as! [[String: Any]] {
        let v = scenario["input"] as! [String: Any], name = scenario["id"] as! String
        let fix = (v["matched_fix_ms"] as? NSNumber).map { Date(timeIntervalSince1970: $0.doubleValue / 1000) }
        let frame = Date(timeIntervalSince1970: (v["frame_ms"] as! NSNumber).doubleValue / 1000)
        let snapshot = SignCollectionPhoneRoadMatch(osmWayID: v["osm_way_id"] as? String,
            bundleVersion: v["bundle_version"] as? String, bundleDBSHA256: v["bundle_db_sha256"] as? String,
            matchedFixAt: fix, travelDirection: v["travel_direction"] as! String, matchedWayStable: v["matched_way_stable"] as! Bool)
        let value = snapshot?.metadata(at: frame)
        try check((value != nil) == scenario["accepted"] as! Bool, name + ": acceptance")
        if let value {
            try check(value["osm_way_id"] as? String == v["osm_way_id"] as? String, name + ": no integer precision loss")
            try check((value["frame_match_delta_ms"] as! Int64) == (v["frame_ms"] as! NSNumber).int64Value - (v["matched_fix_ms"] as! NSNumber).int64Value, name + ": signed original-fix delta")
        }
    }
    let invalid = SignCollectionPhoneRoadMatch(osmWayID: "1", bundleVersion: "b", bundleDBSHA256: String(repeating: "a", count: 64),
        matchedFixAt: Date(timeIntervalSince1970: .nan), travelDirection: "unknown", matchedWayStable: false)
    try check(invalid == nil, "invalid fix cannot enter provenance")
    print("Swift phone road match: shared diagnostic vectors passed")
}
