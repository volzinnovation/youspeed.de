#pragma once
// Experimental data layer only. This does not implement the app reference policy.
#include <cstdint>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace ysp::corrections {

enum class Entity : uint8_t { Way, Node, InventorySign };
enum class Direction : int8_t { Backward = -1, Both = 0, Forward = 1, Unknown = 2 };
enum class LimitKind : uint8_t { Numeric, Unlimited, WalkingPace, Unknown };
struct Limit {
    LimitKind kind = LimitKind::Unknown;
    uint16_t kmh = 0;
    std::string raw; // "signals", "variable", "DE:urban", etc. remain lossless.
    static Limit numeric(uint16_t value);
    static Limit unlimited();
    static Limit unknown(std::string raw);
    bool operator==(const Limit& other) const;
};

enum class ConditionKind : uint8_t {
    Always, Fact, Not, All, Any, Schedule, Vehicle, Lane, WeightAtLeastKg, Unsupported
};
struct Schedule {
    // ISO weekdays 1..7, local clock minutes [start,end), overnight anchors start day.
    std::vector<uint8_t> weekdays;
    std::vector<std::pair<uint16_t, uint16_t>> windows;
    uint16_t annualStart = 0, annualEnd = 0; // MMDD, both zero means unrestricted.
};
struct Condition {
    ConditionKind kind = ConditionKind::Always;
    std::string identity, raw;
    int64_t number = 0;
    Schedule schedule;
    std::vector<Condition> children;
    static Condition fact(std::string key, std::string raw = {});
    static Condition all(std::vector<Condition> items);
    static Condition negate(Condition item);
};
struct Clause { Limit limit; Condition condition; };
struct RuleSet {
    std::string grammar = "ysp-overlay-ast-1";
    // Complete original restriction tags, not only the latest numeric edit.
    std::map<std::string, std::string> rawTags;
    std::vector<Clause> clauses; // Last matching clause wins, as iPhone conditional data.
};

struct Anchor {
    std::string sourceNamespace = "osm"; // osm, mobidata, local, etc.
    Entity entity = Entity::Way;
    int64_t sourceID = 0; // Exact 64-bit source ID, never a packed file row number.
    std::string localID; // Stable UUID/key when newly adding a sign without source ID.
    Direction direction = Direction::Both;
    int64_t startMillimeters = 0, endMillimeters = INT64_MAX;
    std::string fingerprint; // Caller-supplied content/geometry digest of source target.
    // Node events require an explicitly proven directed association and passage.
    int64_t boundWayID = 0;
    bool bindingVerified = false;
    std::string key() const;
};
enum class SignKind : uint8_t { None, GenericMaxspeed, NumericMaxspeed, EndMaxspeed, ZoneStart, ZoneEnd, UnlimitedMaxspeed, VariableMaxspeed, UnknownMaxspeed };
struct NodeMembership {
    int64_t wayID = 0;
    uint32_t ordinal = 0;
    int64_t sourceChainageMillimeters = 0;
    Direction direction = Direction::Unknown;
    double sourceChainageMeters = 0; // Original source double, persisted bit-exact.
};
struct SignNode {
    SignKind kind = SignKind::None;
    int32_t latitudeE7 = 0, longitudeE7 = 0;
    std::string trafficSignRaw, supplementalRaw;
    // Topological source membership is evidence, not a proven applicability binding.
    std::vector<NodeMembership> memberships;
};
enum class Operation : uint8_t { Upsert, Tombstone };
enum class ReviewState : uint8_t { Confirmed, NeedsReview, RebaseRequired };
struct Provenance {
    std::string originalBundle, basisBundle, sourceRevision, author, evidenceID;
    std::string action = "amend";
    int64_t changedAtUTC = 0;
};
struct Record {
    std::string id; // Stable logical amendment/event ID across all pack generations.
    uint64_t revision = 0;
    Operation operation = Operation::Upsert;
    ReviewState review = ReviewState::Confirmed;
    Anchor anchor;
    SignNode sign;
    RuleSet rules;
    int64_t validFromUTC = 0, validUntilUTC = 0; // 0 = unbounded; end exclusive.
    Provenance provenance;
};
enum class WriteStatus { Written, Conflict, Invalid, Missing };
struct WriteResult { WriteStatus status; uint64_t revision; std::string reason; };
struct CivilDay { int year = 0; uint8_t month = 0, day = 0, weekday = 0; };
struct Context {
    bool epochTrusted = false;
    int64_t atUTC = 0;
    bool localClockTrusted = false;
    std::string timeZoneID; // Qualified local civil time supplied by platform adapter.
    CivilDay today, yesterday;
    uint16_t minuteOfDay = 0;
    std::map<std::string, bool> facts; // wet, PH:2026-10-26, vehicle:hgv, etc.
    std::string vehicle;
    int lane = 0;
    int64_t grossWeightKg = -1;
};
struct Target {
    std::string sourceNamespace = "osm";
    Entity entity = Entity::Way;
    int64_t sourceID = 0;
    std::string localID;
    Direction direction = Direction::Unknown;
    int64_t positionMillimeters = 0;
    std::string bundleGeneration, fingerprint;
    int64_t matchedWayID = 0;
    bool nodeCrossingConfirmed = false;
};
enum class LookupStatus { NoAmendment, Resolved, Unresolved, Conflict, RebaseRequired };
struct LookupResult {
    LookupStatus status = LookupStatus::NoAmendment;
    Limit limit;
    std::vector<std::string> recordIDs;
    std::string reason;
};
struct RebaseCandidate { Anchor anchor; };
struct RebaseReport { size_t unchanged = 0, reviewRequired = 0, failed = 0; };

class Overlay {
public:
    WriteResult put(Record record, uint64_t expectedRevision);
    // Common numeric edit preserves the entire restriction AST, source tags and node metadata.
    WriteResult amendLimit(const std::string& id, uint64_t expectedRevision, size_t clauseIndex,
        Limit replacement, Provenance provenance);
    WriteResult erase(const std::string& id, uint64_t expectedRevision, Provenance provenance);
    const Record* latest(const std::string& id) const;
    const std::vector<Record>& history() const { return history_; }
    // Returns amendment data only. Camera/voice/map priority and passage policy stay external.
    LookupResult lookup(const Target&, const Context&, Limit baseline) const;
    RebaseReport rebase(const std::string& newGeneration,
        const std::function<std::vector<RebaseCandidate>(const Anchor&)>& resolve);
    WriteResult confirmRebase(const std::string& id, uint64_t expectedRevision,
        const Anchor& reviewedAnchor, const std::string& generation, Provenance provenance);
    // Bounded versioned binary journal snapshot with integrity checksum, all revision history.
    std::vector<uint8_t> encode() const;
    static bool decode(const std::vector<uint8_t>&, Overlay& output, std::string& error);
    bool save(const std::string& path, std::string& error) const;
    static bool load(const std::string& path, Overlay& output, std::string& error);
private:
    std::vector<Record> history_;
    std::map<std::string, size_t> latest_;
    std::map<std::string, std::set<std::string>> byFeature_;
    size_t serializedBytes_ = 20;
};
} // namespace ysp::corrections

extern "C" {
// Thread-local storage; result remains valid until next same-thread call to that function.
const char* ysp_corrections_selftest_json();
// Creates/replaces only the explicitly supplied scratch journal (not a source bundle).
const char* ysp_corrections_persistence_selftest_json(const char* scratchJournalPath);
// Parses the actual full-source node JSON returned by storage_node_json(), validates
// the pinned source example, then probes restricted amendment composition on disk.
const char* ysp_corrections_source_node_probe_json(const char* sourceNodeJSON,
                                                   const char* scratchJournalPath);
// Hypothetical amendments on supplied full-dataset IDs; never writes to the source bundle.
const char* ysp_corrections_dataset_probe_json(int64_t wayID, int64_t nodeID,
                                             const char* generation, int iterations);
}
