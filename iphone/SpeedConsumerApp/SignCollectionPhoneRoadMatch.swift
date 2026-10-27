import Foundation

/// Diagnostic provenance from the original committed matcher lookup, never sign-road truth.
/// Kept separate from recognition context so capture metadata cannot change runtime gates.
struct SignCollectionPhoneRoadMatch: Equatable, Sendable {
    let osmWayID: String
    let bundleVersion: String
    let bundleDBSHA256: String
    let matchedFixMilliseconds: Int64
    let travelDirection: String
    let matchedWayStable: Bool

    init?(osmWayID: String?, bundleVersion: String?, bundleDBSHA256: String?, matchedFixAt: Date?,
          travelDirection: String, matchedWayStable: Bool) {
        guard let osmWayID, let id = Int64(osmWayID), id > 0, String(id) == osmWayID,
              let bundleVersion, (1...160).contains(bundleVersion.unicodeScalars.count),
              let bundleDBSHA256, bundleDBSHA256.utf8.count == 64,
              bundleDBSHA256.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
              let matchedFixAt, let milliseconds = Self.milliseconds(matchedFixAt),
              ["forward", "reverse", "unknown"].contains(travelDirection) else { return nil }
        self.osmWayID = osmWayID; self.bundleVersion = bundleVersion; self.bundleDBSHA256 = bundleDBSHA256
        matchedFixMilliseconds = milliseconds; self.travelDirection = travelDirection; self.matchedWayStable = matchedWayStable
    }

    private static func milliseconds(_ date: Date) -> Int64? {
        let value = date.timeIntervalSince1970 * 1000
        guard value.isFinite, value >= 0, value <= 253_402_300_799_999 else { return nil }
        return Int64(value.rounded(.down))
    }

    /// Signed age is evidence, not a freshness assertion. Unknown/invalid metadata never blocks a crop.
    func metadata(at frameAt: Date) -> [String: Any]? {
        guard let frame = Self.milliseconds(frameAt) else { return nil }
        let delta = frame - matchedFixMilliseconds
        guard (-86_400_000...86_400_000).contains(delta) else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return ["schema_version": 1, "source": "on_device_bundle_matcher", "osm_way_id": osmWayID,
                "bundle_version": bundleVersion, "bundle_db_sha256": bundleDBSHA256,
                "matched_fix_at": formatter.string(from: Date(timeIntervalSince1970: Double(matchedFixMilliseconds) / 1000)),
                "frame_match_delta_ms": delta, "travel_direction": travelDirection, "matched_way_stable": matchedWayStable]
    }
}
