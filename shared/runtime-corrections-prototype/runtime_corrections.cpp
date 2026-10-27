#include "runtime_corrections.hpp"
#include <algorithm>
#include <chrono>
#include <cctype>
#include <cmath>
#include <cstring>
#include <cstdio>
#include <fstream>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>

namespace ysp::corrections {
namespace {
constexpr size_t kMaxBytes = 16 * 1024 * 1024, kMaxRecords = 100000;
std::string json(const std::string& value) {
    std::ostringstream out; out << '"';
    for (unsigned char c : value) {
        if (c == '"' || c == '\\') out << '\\' << char(c);
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c) << std::dec;
        else out << char(c);
    }
    out << '"'; return out.str();
}
std::string limitKey(const Limit& limit) {
    return std::to_string(int(limit.kind)) + ":" + std::to_string(limit.kmh) + ":" +
        (limit.kind == LimitKind::Unknown ? limit.raw : "");
}
bool validLimit(const Limit& value) {
    return int(value.kind) <= int(LimitKind::Unknown) &&
        (value.kind != LimitKind::Numeric || (value.kmh > 0 && value.kmh <= 400)) && value.raw.size() <= 65536;
}
bool validDirection(Direction d) { return d == Direction::Backward || d == Direction::Both || d == Direction::Forward || d == Direction::Unknown; }
bool validDate(uint16_t date) { return date >= 101 && date <= 1231 && date % 100 >= 1 && date % 100 <= 31; }
bool validCondition(const Condition& c, int depth, size_t& count) {
    if (++count > 1024 || depth > 16 || int(c.kind) > int(ConditionKind::Unsupported) || c.raw.size() > 65536 || c.identity.size() > 4096) return false;
    if (c.kind == ConditionKind::Not && c.children.size() != 1) return false;
    if ((c.kind == ConditionKind::All || c.kind == ConditionKind::Any) && c.children.empty()) return false;
    if (c.kind != ConditionKind::Not && c.kind != ConditionKind::All && c.kind != ConditionKind::Any && !c.children.empty()) return false;
    if ((c.kind == ConditionKind::Fact || c.kind == ConditionKind::Unsupported || c.kind == ConditionKind::Vehicle) && c.identity.empty()) return false;
    if (c.kind == ConditionKind::Schedule && c.identity.empty()) return false;
    if ((c.kind == ConditionKind::Lane || c.kind == ConditionKind::WeightAtLeastKg) && c.number <= 0) return false;
    if (c.schedule.weekdays.size() > 7 || c.schedule.windows.size() > 32) return false;
    for (auto day : c.schedule.weekdays) if (day < 1 || day > 7) return false;
    for (auto window : c.schedule.windows) if (window.first >= 1440 || window.second > 1440 || window.first == window.second) return false;
    if ((c.schedule.annualStart || c.schedule.annualEnd) && (!validDate(c.schedule.annualStart) || !validDate(c.schedule.annualEnd))) return false;
    for (const auto& item : c.children) if (!validCondition(item, depth + 1, count)) return false;
    return true;
}
bool validAnchor(const Anchor& a) {
    return !a.sourceNamespace.empty() && a.sourceNamespace.size() <= 256 && int(a.entity) <= int(Entity::InventorySign) &&
        (a.sourceID > 0 || (a.sourceID == 0 && !a.localID.empty())) && a.localID.size() <= 4096 &&
        validDirection(a.direction) && a.startMillimeters >= 0 && a.endMillimeters >= a.startMillimeters &&
        a.fingerprint.size() <= 4096 && a.boundWayID >= 0 && (!a.bindingVerified || a.boundWayID > 0);
}
bool validRecord(const Record& r) {
    if (r.id.empty() || r.id.size() > 4096 || !validAnchor(r.anchor) ||
        int(r.review) > int(ReviewState::RebaseRequired) || int(r.operation) > int(Operation::Tombstone) ||
        int(r.sign.kind) > int(SignKind::UnknownMaxspeed) || r.sign.memberships.size() > 1024 ||
        r.sign.latitudeE7 < -900000000 || r.sign.latitudeE7 > 900000000 ||
        int64_t(r.sign.longitudeE7) < -1800000000LL || int64_t(r.sign.longitudeE7) > 1800000000LL ||
        r.validFromUTC < 0 || r.validUntilUTC < 0 || (r.validUntilUTC && r.validFromUTC >= r.validUntilUTC)) return false;
    if (r.anchor.entity == Entity::Way && r.sign.kind != SignKind::None) return false;
    for (auto& membership : r.sign.memberships) if (membership.wayID <= 0 || membership.sourceChainageMillimeters < 0 || !validDirection(membership.direction) || !std::isfinite(membership.sourceChainageMeters) || membership.sourceChainageMeters < 0) return false;
    if (r.rules.grammar != "ysp-overlay-ast-1" || r.rules.clauses.size() > 128 || r.rules.rawTags.size() > 128) return false;
    if (r.operation == Operation::Upsert && r.rules.clauses.empty()) return false;
    size_t count = 0, bytes = 0;
    for (auto& tag : r.rules.rawTags) bytes += tag.first.size() + tag.second.size();
    if (bytes > 128 * 1024) return false;
    for (const auto& clause : r.rules.clauses) if (!validLimit(clause.limit) || !validCondition(clause.condition, 0, count)) return false;
    const auto& p = r.provenance;
    if (p.basisBundle.empty() || p.originalBundle.empty() || p.author.empty()) return false;
    for (auto value : {p.originalBundle, p.basisBundle, p.sourceRevision, p.author, p.evidenceID, p.action, r.sign.trafficSignRaw, r.sign.supplementalRaw}) if (value.size() > 65536) return false;
    return true;
}
bool sameFeature(const Anchor& a, const Target& t) {
    return a.sourceNamespace == t.sourceNamespace && a.entity == t.entity && a.sourceID == t.sourceID && a.localID == t.localID;
}
struct Evaluation {
    const Context& context;
    std::set<std::string> unknown;
    const std::map<std::string, bool>* assignment = nullptr;
    bool fact(const std::string& key) {
        auto known = context.facts.find(key);
        if (known != context.facts.end()) return known->second;
        if (assignment) { auto found = assignment->find(key); if (found != assignment->end()) return found->second; }
        unknown.insert(key); return false;
    }
    bool dayMatches(const Schedule& s, const CivilDay& d) {
        bool weekday = s.weekdays.empty() || std::find(s.weekdays.begin(), s.weekdays.end(), d.weekday) != s.weekdays.end();
        uint16_t date = uint16_t(d.month) * 100 + d.day;
        bool annual = !s.annualStart || (s.annualStart <= s.annualEnd ? date >= s.annualStart && date <= s.annualEnd : date >= s.annualStart || date <= s.annualEnd);
        return weekday && annual;
    }
    bool condition(const Condition& c) {
        switch (c.kind) {
        case ConditionKind::Always: return true;
        case ConditionKind::Fact: return fact(c.identity);
        case ConditionKind::Unsupported: return fact("unsupported:" + c.identity + ":" + c.raw);
        case ConditionKind::Vehicle: return context.vehicle.empty() ? fact("vehicle:" + c.identity) : context.vehicle == c.identity;
        case ConditionKind::Lane: return context.lane <= 0 ? fact("lane:" + std::to_string(c.number)) : context.lane == c.number;
        case ConditionKind::WeightAtLeastKg: return context.grossWeightKg < 0 ? fact("weight_at_least_kg:" + std::to_string(c.number)) : context.grossWeightKg >= c.number;
        case ConditionKind::Not: return !condition(c.children[0]);
        case ConditionKind::All: { bool result = true; for (const auto& x : c.children) result = condition(x) && result; return result; }
        case ConditionKind::Any: { bool result = false; for (const auto& x : c.children) result = condition(x) || result; return result; }
        case ConditionKind::Schedule: {
            if (!context.localClockTrusted || context.timeZoneID.empty() || context.minuteOfDay >= 1440 || !context.today.weekday || !context.yesterday.weekday)
                return fact("schedule:" + c.identity);
            if (c.schedule.windows.empty()) return dayMatches(c.schedule, context.today);
            bool result = false;
            for (auto window : c.schedule.windows) {
                if (window.first < window.second) result = (context.minuteOfDay >= window.first && context.minuteOfDay < window.second && dayMatches(c.schedule, context.today)) || result;
                else if (context.minuteOfDay >= window.first) result = dayMatches(c.schedule, context.today) || result;
                else if (context.minuteOfDay < window.second) result = dayMatches(c.schedule, context.yesterday) || result;
            }
            return result;
        }
        }
        return fact("invalid_condition");
    }
};
bool applies(const Record& r, const Target& t, Evaluation& eval) {
    bool result = true;
    if (r.validFromUTC || r.validUntilUTC) {
        if (!eval.context.epochTrusted) result = eval.fact("validity:" + r.id);
        else result = eval.context.atUTC >= r.validFromUTC && (!r.validUntilUTC || eval.context.atUTC < r.validUntilUTC);
    }
    auto d = r.anchor.direction;
    if (d == Direction::Unknown) result = eval.fact("anchor_direction:" + r.id) && result;
    else if (d != Direction::Both) {
        if (t.direction == Direction::Unknown || t.direction == Direction::Both) result = (eval.fact("direction_forward") == (d == Direction::Forward)) && result;
        else result = d == t.direction && result;
    }
    if (r.anchor.entity != Entity::Way && (!r.anchor.bindingVerified || !t.nodeCrossingConfirmed || r.anchor.boundWayID != t.matchedWayID))
        result = eval.fact("node_binding_or_passage:" + r.id) && result;
    return result;
}
// Fixed little endian serialization: no C++ object-layout or ABI dependence.
struct Writer {
    std::vector<uint8_t> bytes;
    void number(uint64_t value, int width) { for (int i = 0; i < width; ++i) bytes.push_back(uint8_t(value >> (8 * i))); }
    void str(const std::string& value) { number(value.size(), 4); bytes.insert(bytes.end(), value.begin(), value.end()); }
};
struct Reader {
    const std::vector<uint8_t>& bytes; size_t offset = 0, end;
    explicit Reader(const std::vector<uint8_t>& b) : bytes(b), end(b.size()) {}
    uint64_t number(int width) {
        if (size_t(width) > end - offset) throw std::runtime_error("truncated_number");
        uint64_t n = 0; for (int i = 0; i < width; ++i) n |= uint64_t(bytes[offset++]) << (8 * i); return n;
    }
    size_t count(size_t max) { auto n = number(4); if (n > max) throw std::runtime_error("count_bound"); return size_t(n); }
    std::string str() { size_t n = count(128 * 1024); if (n > end - offset) throw std::runtime_error("truncated_string"); std::string s(bytes.begin() + offset, bytes.begin() + offset + n); offset += n; return s; }
};
uint64_t checksum(const uint8_t* bytes, size_t size) {
    // Accidental corruption detection, not authentication or a signature.
    uint64_t n = 14695981039346656037ULL;
    for (size_t i = 0; i < size; ++i) { n ^= bytes[i]; n *= 1099511628211ULL; } return n;
}
void writeCondition(Writer& w, const Condition& c) {
    w.number(int(c.kind), 1); w.str(c.identity); w.str(c.raw); w.number(uint64_t(c.number), 8);
    w.number(c.schedule.weekdays.size(), 4); for (auto x : c.schedule.weekdays) w.number(x, 1);
    w.number(c.schedule.windows.size(), 4); for (auto x : c.schedule.windows) { w.number(x.first, 2); w.number(x.second, 2); }
    w.number(c.schedule.annualStart, 2); w.number(c.schedule.annualEnd, 2);
    w.number(c.children.size(), 4); for (const auto& x : c.children) writeCondition(w, x);
}
Condition readCondition(Reader& r, int depth, size_t& count) {
    if (depth > 16 || ++count > 1024) throw std::runtime_error("ast_bound");
    Condition c; c.kind = ConditionKind(r.number(1)); c.identity = r.str(); c.raw = r.str(); c.number = int64_t(r.number(8));
    auto n = r.count(7); for (size_t i = 0; i < n; ++i) c.schedule.weekdays.push_back(uint8_t(r.number(1)));
    n = r.count(32); for (size_t i = 0; i < n; ++i) { auto a = uint16_t(r.number(2)); auto b = uint16_t(r.number(2)); c.schedule.windows.emplace_back(a, b); }
    c.schedule.annualStart = uint16_t(r.number(2)); c.schedule.annualEnd = uint16_t(r.number(2));
    n = r.count(1024); for (size_t i = 0; i < n; ++i) c.children.push_back(readCondition(r, depth + 1, count)); return c;
}
void writeRecord(Writer& w, const Record& r) {
    w.str(r.id); w.number(r.revision, 8); w.number(int(r.operation), 1); w.number(int(r.review), 1);
    const auto& a = r.anchor; w.str(a.sourceNamespace); w.number(int(a.entity), 1); w.number(uint64_t(a.sourceID), 8); w.str(a.localID);
    w.number(uint8_t(a.direction), 1); w.number(uint64_t(a.startMillimeters), 8); w.number(uint64_t(a.endMillimeters), 8); w.str(a.fingerprint); w.number(uint64_t(a.boundWayID), 8); w.number(a.bindingVerified, 1);
    w.number(int(r.sign.kind), 1); w.number(uint32_t(r.sign.latitudeE7), 4); w.number(uint32_t(r.sign.longitudeE7), 4); w.str(r.sign.trafficSignRaw); w.str(r.sign.supplementalRaw);
    w.number(r.sign.memberships.size(), 4); for (auto& m : r.sign.memberships) { w.number(uint64_t(m.wayID), 8); w.number(m.ordinal, 4); w.number(uint64_t(m.sourceChainageMillimeters), 8); w.number(uint8_t(m.direction), 1); uint64_t bits; static_assert(sizeof(bits) == sizeof(m.sourceChainageMeters)); std::memcpy(&bits, &m.sourceChainageMeters, sizeof(bits)); w.number(bits, 8); }
    w.str(r.rules.grammar); w.number(r.rules.rawTags.size(), 4); for (auto& tag : r.rules.rawTags) { w.str(tag.first); w.str(tag.second); }
    w.number(r.rules.clauses.size(), 4); for (auto& clause : r.rules.clauses) { w.number(int(clause.limit.kind), 1); w.number(clause.limit.kmh, 2); w.str(clause.limit.raw); writeCondition(w, clause.condition); }
    w.number(uint64_t(r.validFromUTC), 8); w.number(uint64_t(r.validUntilUTC), 8);
    auto& p = r.provenance; for (auto* s : {&p.originalBundle, &p.basisBundle, &p.sourceRevision, &p.author, &p.evidenceID, &p.action}) w.str(*s); w.number(uint64_t(p.changedAtUTC), 8);
}
Record readRecord(Reader& r) {
    Record v; v.id = r.str(); v.revision = r.number(8); v.operation = Operation(r.number(1)); v.review = ReviewState(r.number(1));
    auto& a = v.anchor; a.sourceNamespace = r.str(); a.entity = Entity(r.number(1)); a.sourceID = int64_t(r.number(8)); a.localID = r.str();
    a.direction = Direction(int8_t(r.number(1))); a.startMillimeters = int64_t(r.number(8)); a.endMillimeters = int64_t(r.number(8)); a.fingerprint = r.str(); a.boundWayID = int64_t(r.number(8));
    auto verified = r.number(1); if (verified > 1) throw std::runtime_error("invalid_bool"); a.bindingVerified = verified;
    v.sign.kind = SignKind(r.number(1)); v.sign.latitudeE7 = int32_t(r.number(4)); v.sign.longitudeE7 = int32_t(r.number(4)); v.sign.trafficSignRaw = r.str(); v.sign.supplementalRaw = r.str();
    auto memberships = r.count(1024); for (size_t i = 0; i < memberships; ++i) { NodeMembership m; m.wayID = int64_t(r.number(8)); m.ordinal = uint32_t(r.number(4)); m.sourceChainageMillimeters = int64_t(r.number(8)); m.direction = Direction(int8_t(r.number(1))); auto bits = r.number(8); std::memcpy(&m.sourceChainageMeters, &bits, sizeof(bits)); v.sign.memberships.push_back(m); }
    v.rules.grammar = r.str(); auto n = r.count(128); for (size_t i = 0; i < n; ++i) { auto key = r.str(); auto value = r.str(); if (!v.rules.rawTags.emplace(key, value).second) throw std::runtime_error("duplicate_raw_tag"); }
    n = r.count(128); size_t count = 0; for (size_t i = 0; i < n; ++i) { Clause c; c.limit.kind = LimitKind(r.number(1)); c.limit.kmh = uint16_t(r.number(2)); c.limit.raw = r.str(); c.condition = readCondition(r, 0, count); v.rules.clauses.push_back(c); }
    v.validFromUTC = int64_t(r.number(8)); v.validUntilUTC = int64_t(r.number(8));
    auto& p = v.provenance; for (auto* s : {&p.originalBundle, &p.basisBundle, &p.sourceRevision, &p.author, &p.evidenceID, &p.action}) *s = r.str(); p.changedAtUTC = int64_t(r.number(8)); return v;
}
}

Limit Limit::numeric(uint16_t value) { return {LimitKind::Numeric, value, std::to_string(value)}; }
Limit Limit::unlimited() { return {LimitKind::Unlimited, 0, "none"}; }
Limit Limit::unknown(std::string raw) { return {LimitKind::Unknown, 0, std::move(raw)}; }
bool Limit::operator==(const Limit& other) const { return limitKey(*this) == limitKey(other); }
Condition Condition::fact(std::string key, std::string raw) { Condition c; c.kind = ConditionKind::Fact; c.identity = std::move(key); c.raw = std::move(raw); return c; }
Condition Condition::all(std::vector<Condition> items) { Condition c; c.kind = ConditionKind::All; c.children = std::move(items); return c; }
Condition Condition::negate(Condition item) { Condition c; c.kind = ConditionKind::Not; c.children.push_back(std::move(item)); return c; }
std::string Anchor::key() const {
    return sourceNamespace + ":" + std::to_string(int(entity)) + ":" + std::to_string(sourceID) + ":" + localID;
}
const Record* Overlay::latest(const std::string& id) const { auto found = latest_.find(id); return found == latest_.end() ? nullptr : &history_[found->second]; }
WriteResult Overlay::put(Record record, uint64_t expectedRevision) {
    const auto* old = latest(record.id); uint64_t revision = old ? old->revision : 0;
    if (revision != expectedRevision) return {WriteStatus::Conflict, revision, "expected_revision_mismatch"};
    if (!validRecord(record) || history_.size() >= kMaxRecords || revision == UINT64_MAX) return {WriteStatus::Invalid, revision, "invalid_or_capacity"};
    if (old && old->provenance.originalBundle != record.provenance.originalBundle) return {WriteStatus::Invalid, revision, "original_provenance_immutable"};
    if (old && (old->anchor.key() != record.anchor.key() || old->anchor.fingerprint != record.anchor.fingerprint || old->provenance.basisBundle != record.provenance.basisBundle) &&
        record.provenance.action != "rebase_explicit_review" && record.provenance.action != "rebase_unchanged") return {WriteStatus::Invalid, revision, "target_change_requires_explicit_rebase"};
    record.revision = revision + 1;
    Writer w; writeRecord(w, record); if (serializedBytes_ + w.bytes.size() > kMaxBytes) return {WriteStatus::Invalid, revision, "journal_capacity"};
    if (old && old->anchor.key() != record.anchor.key()) { auto found = byFeature_.find(old->anchor.key()); if (found != byFeature_.end()) found->second.erase(record.id); }
    byFeature_[record.anchor.key()].insert(record.id); serializedBytes_ += w.bytes.size();
    latest_[record.id] = history_.size(); history_.push_back(std::move(record));
    return {WriteStatus::Written, revision + 1, "written"};
}
WriteResult Overlay::amendLimit(const std::string& id, uint64_t expected, size_t index, Limit replacement, Provenance p) {
    auto* old = latest(id); if (!old) return {WriteStatus::Missing, 0, "missing_record"};
    if (old->operation == Operation::Tombstone || index >= old->rules.clauses.size()) return {WriteStatus::Invalid, old->revision, "invalid_amendment_target"};
    Record r = *old; r.rules.clauses[index].limit = std::move(replacement);
    p.originalBundle = old->provenance.originalBundle; p.basisBundle = old->provenance.basisBundle; p.action = "amend_limit"; r.provenance = std::move(p);
    return put(std::move(r), expected);
}
WriteResult Overlay::erase(const std::string& id, uint64_t expected, Provenance provenance) {
    auto* old = latest(id); if (!old) return {WriteStatus::Missing, 0, "missing_record"};
    Record record = *old; record.operation = Operation::Tombstone; provenance.originalBundle = old->provenance.originalBundle; provenance.action = "tombstone"; record.provenance = std::move(provenance); return put(std::move(record), expected);
}
LookupResult Overlay::lookup(const Target& t, const Context& context, Limit baseline) const {
    LookupResult out; out.limit = baseline;
    if (!validLimit(baseline)) { out.status = LookupStatus::Unresolved; out.reason = "invalid_baseline"; return out; }
    std::vector<const Record*> rows;
    Anchor search; search.sourceNamespace = t.sourceNamespace; search.entity = t.entity; search.sourceID = t.sourceID; search.localID = t.localID;
    auto matches = byFeature_.find(search.key());
    if (matches == byFeature_.end()) { out.reason = "no_active_amendment"; return out; }
    for (auto& id : matches->second) {
        const auto& r = history_[latest_.at(id)];
        if (r.operation == Operation::Tombstone || !sameFeature(r.anchor, t) || t.positionMillimeters < r.anchor.startMillimeters || t.positionMillimeters > r.anchor.endMillimeters) continue;
        out.recordIDs.push_back(r.id);
        if (r.review == ReviewState::RebaseRequired || r.provenance.basisBundle != t.bundleGeneration || r.anchor.fingerprint != t.fingerprint) {
            out.status = LookupStatus::RebaseRequired; out.reason = "bundle_or_source_target_changed"; return out;
        }
        if (r.review != ReviewState::Confirmed) { out.status = LookupStatus::Unresolved; out.reason = "amendment_needs_review"; return out; }
        if (r.anchor.entity != Entity::Way && (!r.anchor.bindingVerified || !t.nodeCrossingConfirmed || r.anchor.boundWayID != t.matchedWayID)) {
            out.status = LookupStatus::Unresolved; out.reason = "node_association_or_crossing_unproven"; return out;
        }
        rows.push_back(&r);
    }
    if (rows.empty()) { out.reason = "no_active_amendment"; return out; }
    Evaluation eval{context, {}, nullptr};
    // Collect every fact (including short-circuited branches) before bounded correlated enumeration.
    for (auto* r : rows) { (void)applies(*r, t, eval); for (auto& c : r->rules.clauses) (void)eval.condition(c.condition); }
    if (eval.unknown.size() > 12) { out.status = LookupStatus::Unresolved; out.reason = "too_many_unknown_contexts"; return out; }
    std::vector<std::string> keys(eval.unknown.begin(), eval.unknown.end());
    std::map<std::string, Limit> outcomes; bool conflict = false;
    for (size_t mask = 0; mask < (size_t(1) << keys.size()); ++mask) {
        std::map<std::string, bool> assignment; for (size_t i = 0; i < keys.size(); ++i) assignment[keys[i]] = (mask & (size_t(1) << i)) != 0;
        eval.assignment = &assignment;
        bool any = false; Limit selected = baseline;
        for (auto* r : rows) {
            if (!applies(*r, t, eval)) continue;
            Limit value = baseline; bool matched = false;
            for (const auto& c : r->rules.clauses) if (eval.condition(c.condition)) { value = c.limit; matched = true; }
            if (!matched) continue;
            if (any && !(selected == value)) conflict = true;
            selected = value; any = true;
        }
        outcomes.emplace(limitKey(selected), selected);
    }
    if (conflict) { out.status = LookupStatus::Conflict; out.reason = "overlapping_amendments_disagree"; }
    else if (outcomes.size() != 1 || outcomes.begin()->second.kind == LimitKind::Unknown) { out.status = LookupStatus::Unresolved; out.reason = "restriction_or_sign_value_unresolved"; }
    else { out.status = LookupStatus::Resolved; out.limit = outcomes.begin()->second; out.reason = "all_admitted_outcomes_agree"; }
    return out;
}
RebaseReport Overlay::rebase(const std::string& generation, const std::function<std::vector<RebaseCandidate>(const Anchor&)>& resolve) {
    RebaseReport report; std::vector<Record> rows;
    for (auto& entry : latest_) rows.push_back(history_[entry.second]);
    for (auto& r : rows) {
        if (r.operation == Operation::Tombstone || r.provenance.basisBundle == generation) continue;
        auto candidates = resolve(r.anchor);
        bool exact = candidates.size() == 1 && candidates[0].anchor.key() == r.anchor.key() && candidates[0].anchor.fingerprint == r.anchor.fingerprint &&
            candidates[0].anchor.direction == r.anchor.direction && candidates[0].anchor.boundWayID == r.anchor.boundWayID && candidates[0].anchor.bindingVerified == r.anchor.bindingVerified &&
            candidates[0].anchor.startMillimeters == r.anchor.startMillimeters && candidates[0].anchor.endMillimeters == r.anchor.endMillimeters;
        r.provenance.action = exact ? "rebase_unchanged" : "rebase_review_required";
        if (exact) r.provenance.basisBundle = generation;
        else r.review = ReviewState::RebaseRequired;
        auto revision = r.revision; auto written = put(std::move(r), revision);
        if (written.status != WriteStatus::Written) ++report.failed;
        else if (exact) ++report.unchanged;
        else ++report.reviewRequired;
    }
    return report;
}
WriteResult Overlay::confirmRebase(const std::string& id, uint64_t expected, const Anchor& anchor, const std::string& generation, Provenance p) {
    auto* old = latest(id); if (!old) return {WriteStatus::Missing, 0, "missing_record"};
    if (old->operation == Operation::Tombstone) return {WriteStatus::Invalid, old->revision, "cannot_rebase_tombstone"};
    Record r = *old; r.anchor = anchor; r.review = ReviewState::Confirmed; p.originalBundle = old->provenance.originalBundle; p.basisBundle = generation; p.action = "rebase_explicit_review"; r.provenance = std::move(p); return put(std::move(r), expected);
}
std::vector<uint8_t> Overlay::encode() const {
    Writer w; for (auto c : std::string("YSPOVR01")) w.number(uint8_t(c), 1); w.number(history_.size(), 4);
    for (const auto& r : history_) writeRecord(w, r);
    if (w.bytes.size() + 8 > kMaxBytes) throw std::runtime_error("journal_capacity");
    w.number(checksum(w.bytes.data(), w.bytes.size()), 8); return w.bytes;
}
bool Overlay::decode(const std::vector<uint8_t>& bytes, Overlay& output, std::string& error) {
    try {
        if (bytes.size() < 20 || bytes.size() > kMaxBytes) throw std::runtime_error("journal_size");
        Reader r(bytes); r.offset = bytes.size() - 8; auto stored = r.number(8);
        if (stored != checksum(bytes.data(), bytes.size() - 8)) throw std::runtime_error("checksum_mismatch");
        r.offset = 0; r.end = bytes.size() - 8;
        for (auto c : std::string("YSPOVR01")) if (r.number(1) != uint8_t(c)) throw std::runtime_error("journal_version");
        Overlay candidate; auto n = r.count(kMaxRecords);
        for (size_t i = 0; i < n; ++i) {
            auto record = readRecord(r); auto revision = record.revision;
            auto* old = candidate.latest(record.id); auto expected = old ? old->revision : 0;
            if (revision != expected + 1 || candidate.put(std::move(record), expected).status != WriteStatus::Written) throw std::runtime_error("invalid_revision_or_record");
        }
        if (r.offset != r.end) throw std::runtime_error("trailing_bytes");
        output = std::move(candidate); error.clear(); return true;
    } catch (const std::exception& e) { error = e.what(); return false; }
}
bool Overlay::save(const std::string& path, std::string& error) const {
    try {
        auto bytes = encode(); std::string temp = path + ".tmp";
        { std::ofstream stream(temp, std::ios::binary | std::ios::trunc); if (!stream || !stream.write(reinterpret_cast<const char*>(bytes.data()), bytes.size()) || !stream.flush()) throw std::runtime_error("write_failed"); }
        if (std::rename(temp.c_str(), path.c_str()) != 0) { std::remove(temp.c_str()); throw std::runtime_error("rename_failed"); }
        error.clear(); return true;
    } catch (const std::exception& e) { error = e.what(); return false; }
}
bool Overlay::load(const std::string& path, Overlay& output, std::string& error) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) { error = "open_failed"; return false; }
    auto size = stream.tellg(); if (size < 0 || uint64_t(size) > kMaxBytes) { error = "journal_size"; return false; }
    std::vector<uint8_t> bytes(static_cast<size_t>(size)); stream.seekg(0);
    if (!stream.read(reinterpret_cast<char*>(bytes.data()), size)) { error = "read_failed"; return false; }
    return decode(bytes, output, error);
}
} // namespace ysp::corrections

namespace {
using namespace ysp::corrections;
Record sampleRecord(std::string id = "amendment:fixture", int64_t sourceID = 9223372036854775000LL, std::string generation = "bw:fixture:one") {
    Record r; r.id = std::move(id); r.anchor.sourceID = sourceID; r.anchor.fingerprint = "sha256:fixture-source-target";
    r.provenance.originalBundle = generation; r.provenance.basisBundle = std::move(generation); r.provenance.sourceRevision = "osm:way-version:7";
    r.provenance.author = "local:test-user"; r.provenance.evidenceID = "passage:fixture"; r.provenance.changedAtUTC = 1793000000;
    r.rules.rawTags = {{"maxspeed", "50"}, {"maxspeed:conditional", "30 @ (Mo-Fr 22:00-06:00 AND wet)"}};
    r.rules.clauses = {{Limit::numeric(30), Condition::fact("wet", "wet")}};
    return r;
}
Target targetOf(const Record& r) {
    Target t; t.sourceNamespace = r.anchor.sourceNamespace; t.entity = r.anchor.entity; t.sourceID = r.anchor.sourceID; t.localID = r.anchor.localID;
    t.direction = Direction::Forward; t.bundleGeneration = r.provenance.basisBundle; t.fingerprint = r.anchor.fingerprint;
    t.matchedWayID = r.anchor.boundWayID; t.nodeCrossingConfirmed = true; return t;
}
bool numericIs(const LookupResult& r, int speed) { return r.status == LookupStatus::Resolved && r.limit.kind == LimitKind::Numeric && r.limit.kmh == speed; }
std::string runSelftest() {
    std::vector<std::string> failures; size_t tests = 0;
    auto check = [&](bool good, const std::string& name) { ++tests; if (!good) failures.push_back(name); };
    Overlay overlay; auto r = sampleRecord(); auto target = targetOf(r); Context context; context.facts["wet"] = true;
    check(overlay.put(r, 0).status == WriteStatus::Written, "create_way_correction");
    check(numericIs(overlay.lookup(target, context, Limit::numeric(50)), 30), "wet_restriction_applies");
    context.facts["wet"] = false;
    check(numericIs(overlay.lookup(target, context, Limit::numeric(50)), 50), "dry_preserves_baseline");
    context.facts.clear();
    check(overlay.lookup(target, context, Limit::numeric(50)).status == LookupStatus::Unresolved, "unknown_wet_not_applied");
    check(numericIs(overlay.lookup(target, context, Limit::numeric(30)), 30), "correlated_unknown_agreement");
    auto amendment = *overlay.latest(r.id); amendment.rules.clauses[0].limit = Limit::numeric(40);
    check(overlay.put(amendment, 0).status == WriteStatus::Conflict, "optimistic_conflict");
    check(overlay.latest(r.id)->revision == 1, "conflict_does_not_mutate");
    check(overlay.amendLimit(r.id, 1, 0, Limit::numeric(40), r.provenance).status == WriteStatus::Written && overlay.latest(r.id)->rules.rawTags == r.rules.rawTags && overlay.latest(r.id)->rules.clauses[0].condition.identity == "wet", "edit_keeps_complete_restrictions");
    context.facts["wet"] = true;
    check(numericIs(overlay.lookup(target, context, Limit::numeric(50)), 40), "revision_replaces_value");
    auto bytes = overlay.encode(); Overlay restored; std::string error;
    check(Overlay::decode(bytes, restored, error) && restored.encode() == bytes, "journal_byte_exact_roundtrip");
    check(numericIs(restored.lookup(target, context, Limit::numeric(50)), 40), "restored_lookup_identical");
    check(restored.latest(r.id)->anchor.sourceID == 9223372036854775000LL, "source_id_64bit_exact");
    auto corrupt = bytes; corrupt[corrupt.size() / 2] ^= 1;
    check(!Overlay::decode(corrupt, restored, error) && restored.encode() == bytes, "corruption_fails_atomically");
    auto invalid = r; invalid.id = "invalid-numeric"; invalid.rules.clauses[0].limit.kmh = 0;
    check(overlay.put(invalid, 0).status == WriteStatus::Invalid, "invalid_numeric_rejected");
    auto p = r.provenance;
    check(overlay.erase(r.id, 1, p).status == WriteStatus::Conflict, "tombstone_revision_conflict");
    check(overlay.erase(r.id, 2, p).status == WriteStatus::Written && overlay.history().size() == 3, "tombstone_retains_history");
    check(overlay.lookup(target, context, Limit::numeric(50)).status == LookupStatus::NoAmendment, "tombstone_masks_latest_only");
    Overlay deleted; check(Overlay::decode(overlay.encode(), deleted, error) && deleted.latest(r.id)->operation == Operation::Tombstone, "tombstone_persists");

    Overlay directed; auto d = sampleRecord("directed"); d.anchor.direction = Direction::Forward; d.anchor.startMillimeters = 100; d.anchor.endMillimeters = 200; d.rules.clauses = {{Limit::numeric(60), {}}};
    (void)directed.put(d, 0); auto dt = targetOf(d); dt.positionMillimeters = 150;
    check(numericIs(directed.lookup(dt, context, Limit::numeric(80)), 60), "directed_range_applies");
    dt.direction = Direction::Backward; check(numericIs(directed.lookup(dt, context, Limit::numeric(80)), 80), "opposite_direction_preserved");
    dt.direction = Direction::Unknown; check(directed.lookup(dt, context, Limit::numeric(80)).status == LookupStatus::Unresolved, "unknown_direction_unresolved");
    dt.direction = Direction::Forward; dt.positionMillimeters = 250; check(directed.lookup(dt, context, Limit::numeric(80)).status == LookupStatus::NoAmendment, "out_of_range_not_selected");

    Overlay timed; auto timedRecord = sampleRecord("restricted"); Condition schedule; schedule.kind = ConditionKind::Schedule; schedule.identity = "Mo-Fr-22-06"; schedule.raw = "Mo-Fr 22:00-06:00";
    schedule.schedule.weekdays = {1, 2, 3, 4, 5}; schedule.schedule.windows = {{1320, 360}};
    Condition vehicle; vehicle.kind = ConditionKind::Vehicle; vehicle.identity = "hgv";
    Condition weight; weight.kind = ConditionKind::WeightAtLeastKg; weight.number = 7500;
    Condition lane; lane.kind = ConditionKind::Lane; lane.number = 2;
    auto restriction = Condition::all({schedule, vehicle, weight, lane});
    timedRecord.rules.clauses = {{Limit::numeric(30), restriction}}; timedRecord.validFromUTC = 100; timedRecord.validUntilUTC = 200;
    (void)timed.put(timedRecord, 0); auto tt = targetOf(timedRecord); Context tc;
    tc.epochTrusted = true; tc.atUTC = 150; tc.localClockTrusted = true; tc.timeZoneID = "Europe/Berlin";
    tc.today = {2026, 10, 24, 6}; tc.yesterday = {2026, 10, 23, 5}; tc.minuteOfDay = 120; tc.vehicle = "hgv"; tc.grossWeightKg = 9000; tc.lane = 2;
    check(numericIs(timed.lookup(tt, tc, Limit::numeric(80)), 30), "overnight_friday_anchors_on_saturday");
    tc.today = {2026, 10, 26, 1}; tc.yesterday = {2026, 10, 25, 7};
    check(numericIs(timed.lookup(tt, tc, Limit::numeric(80)), 80), "monday_morning_not_sunday_window");
    tc.today = {2026, 10, 24, 6}; tc.yesterday = {2026, 10, 23, 5}; tc.vehicle = "car";
    check(numericIs(timed.lookup(tt, tc, Limit::numeric(80)), 80), "vehicle_scope_preserved");
    tc.vehicle = "hgv"; tc.grossWeightKg = 6000; check(numericIs(timed.lookup(tt, tc, Limit::numeric(80)), 80), "weight_scope_preserved");
    tc.grossWeightKg = 9000; tc.lane = 1; check(numericIs(timed.lookup(tt, tc, Limit::numeric(80)), 80), "lane_scope_preserved");
    tc.lane = 2; tc.atUTC = 200; check(numericIs(timed.lookup(tt, tc, Limit::numeric(80)), 80), "validity_end_exclusive");
    tc.atUTC = 150; tc.epochTrusted = false; check(timed.lookup(tt, tc, Limit::numeric(80)).status == LookupStatus::Unresolved, "untrusted_validity_unresolved");
    tc.epochTrusted = true; tc.localClockTrusted = false; check(timed.lookup(tt, tc, Limit::numeric(80)).status == LookupStatus::Unresolved, "untrusted_local_clock_unresolved");

    Overlay nodes; auto n = sampleRecord("osm:node:maxspeed", 1234567890123LL); n.anchor.entity = Entity::Node; n.sign.kind = SignKind::GenericMaxspeed; n.sign.latitudeE7 = 487750000; n.sign.longitudeE7 = 91820000;
    n.sign.trafficSignRaw = "maxspeed"; n.sign.memberships = {{12345, 3, 145000, Direction::Unknown, 145.000123456789}, {12346, 0, 0, Direction::Unknown, 0}};
    n.rules.rawTags = {{"traffic_sign", "maxspeed"}, {"maxspeed", "signals"}}; n.rules.clauses = {{Limit::unknown("signals"), {}}};
    check(nodes.put(n, 0).status == WriteStatus::Written, "persist_generic_node_without_numeric");
    auto nt = targetOf(n); check(nodes.lookup(nt, context, Limit::numeric(50)).status == LookupStatus::Unresolved, "nearest_road_not_assumed_binding");
    auto verified = *nodes.latest(n.id); verified.anchor.boundWayID = 12345; verified.anchor.bindingVerified = true; verified.anchor.direction = Direction::Forward; (void)nodes.put(verified, 1); nt = targetOf(verified);
    check(nodes.lookup(nt, context, Limit::numeric(50)).status == LookupStatus::Unresolved, "variable_node_value_not_fabricated");
    verified.sign.kind = SignKind::NumericMaxspeed; verified.sign.trafficSignRaw = "maxspeed"; verified.rules.rawTags["maxspeed"] = "30"; verified.rules.rawTags["maxspeed:conditional"] = "30 @ (wet)"; verified.rules.clauses = {{Limit::numeric(30), Condition::fact("wet")}}; (void)nodes.put(verified, 2);
    check(numericIs(nodes.lookup(nt, context, Limit::numeric(50)), 30), "generic_numeric_node_applies_with_binding");
    context.facts["wet"] = false; check(numericIs(nodes.lookup(nt, context, Limit::numeric(50)), 50), "node_restriction_preserves_baseline");
    context.facts.clear(); check(nodes.lookup(nt, context, Limit::numeric(50)).status == LookupStatus::Unresolved, "node_unknown_restriction_unresolved");
    context.facts["wet"] = true; nt.direction = Direction::Backward; check(numericIs(nodes.lookup(nt, context, Limit::numeric(50)), 50), "node_direction_preserved"); nt.direction = Direction::Forward;
    nt.nodeCrossingConfirmed = false; check(nodes.lookup(nt, context, Limit::numeric(50)).status == LookupStatus::Unresolved, "node_not_applied_before_crossing");
    nt.nodeCrossingConfirmed = true; nt.matchedWayID = 12346; check(nodes.lookup(nt, context, Limit::numeric(50)).status == LookupStatus::Unresolved, "node_wrong_way_unresolved");
    Overlay nodeRestored; check(Overlay::decode(nodes.encode(), nodeRestored, error) && nodeRestored.latest(n.id)->rules.rawTags.at("traffic_sign") == "maxspeed" && nodeRestored.latest(n.id)->sign.latitudeE7 == 487750000 && nodeRestored.latest(n.id)->sign.memberships.size() == 2 && nodeRestored.latest(n.id)->sign.memberships[0].ordinal == 3 && nodeRestored.latest(n.id)->sign.memberships[0].sourceChainageMillimeters == 145000 && nodeRestored.latest(n.id)->sign.memberships[0].direction == Direction::Unknown, "node_geometry_membership_and_source_tags_persist");
    check(nodeRestored.latest(n.id)->sign.memberships[0].sourceChainageMeters == n.sign.memberships[0].sourceChainageMeters, "original_source_chainage_double_exact");
    auto local = verified; local.id = "local:new-sign:uuid"; local.anchor.sourceNamespace = "local"; local.anchor.sourceID = 0; local.anchor.localID = "fixture-uuid"; local.provenance.action = "add";
    check(nodes.put(local, 0).status == WriteStatus::Written, "add_new_local_sign_node");
    auto government = verified; government.id = "inventory:sign:9"; government.anchor.sourceNamespace = "mobidata"; government.anchor.entity = Entity::InventorySign; government.anchor.sourceID = 9;
    check(nodes.put(government, 0).status == WriteStatus::Written, "government_inventory_amendment");
    auto variable = local; variable.id = "local:variable"; variable.anchor.localID = "variable-uuid"; variable.sign.kind = SignKind::VariableMaxspeed; variable.rules.clauses = {{Limit::unknown("variable"), {}}};
    check(nodes.put(variable, 0).status == WriteStatus::Written && nodes.lookup(targetOf(variable), context, Limit::numeric(50)).status == LookupStatus::Unresolved, "typed_variable_sign_stays_unknown");
    auto unlimited = local; unlimited.id = "local:unlimited"; unlimited.anchor.localID = "unlimited-uuid"; unlimited.sign.kind = SignKind::UnlimitedMaxspeed; unlimited.rules.clauses = {{Limit::unlimited(), {}}}; (void)nodes.put(unlimited, 0);
    check(nodes.lookup(targetOf(unlimited), context, Limit::numeric(50)).limit.kind == LimitKind::Unlimited, "unlimited_distinct_from_missing");

    Overlay rebasing; auto rb = sampleRecord("rebase"); rb.rules.clauses = {{Limit::numeric(30), {}}}; (void)rebasing.put(rb, 0); auto rbt = targetOf(rb); rbt.bundleGeneration = "bw:fixture:two";
    check(rebasing.lookup(rbt, context, Limit::numeric(50)).status == LookupStatus::RebaseRequired, "new_generation_requires_rebase");
    auto report = rebasing.rebase(rbt.bundleGeneration, [](const Anchor& a) { return std::vector<RebaseCandidate>{{a}}; });
    check(report.unchanged == 1 && numericIs(rebasing.lookup(rbt, context, Limit::numeric(50)), 30), "unchanged_source_rebase");
    rbt.bundleGeneration = "bw:fixture:three"; report = rebasing.rebase(rbt.bundleGeneration, [](const Anchor& a) { auto b = a; b.sourceID += 1; return std::vector<RebaseCandidate>{{a}, {b}}; });
    check(report.reviewRequired == 1 && rebasing.lookup(rbt, context, Limit::numeric(50)).status == LookupStatus::RebaseRequired, "split_way_rebase_unresolved");
    auto reviewedAnchor = rb.anchor; reviewedAnchor.sourceID = 987654321; reviewedAnchor.fingerprint = "sha256:reviewed-target";
    check(rebasing.confirmRebase(rb.id, 3, reviewedAnchor, rbt.bundleGeneration, rb.provenance).status == WriteStatus::Written, "explicit_review_can_retarget");
    rbt.sourceID = reviewedAnchor.sourceID; rbt.fingerprint = reviewedAnchor.fingerprint;
    check(numericIs(rebasing.lookup(rbt, context, Limit::numeric(50)), 30) && rebasing.latest(rb.id)->provenance.originalBundle == rb.provenance.originalBundle, "reviewed_rebase_keeps_provenance");
    auto moved = *rebasing.latest(rb.id); moved.anchor.sourceID += 1; moved.provenance.action = "amend";
    check(rebasing.put(moved, 4).status == WriteStatus::Invalid, "silent_target_reassignment_rejected");

    Overlay ambiguous; auto a = sampleRecord("one"); a.rules.clauses = {{Limit::numeric(30), {}}}; auto b = a; b.id = "two"; b.rules.clauses[0].limit = Limit::numeric(40); (void)ambiguous.put(a, 0); (void)ambiguous.put(b, 0);
    check(ambiguous.lookup(targetOf(a), context, Limit::numeric(50)).status == LookupStatus::Conflict, "overlap_disagreement_not_last_writer");
    Overlay unsupported; auto u = sampleRecord("unsupported"); Condition un; un.kind = ConditionKind::Unsupported; un.identity = "external_unknown"; un.raw = "emergency_access_only"; u.rules.rawTags["maxspeed:conditional"] = "30 @ (emergency_access_only)"; u.rules.clauses = {{Limit::numeric(30), un}}; (void)unsupported.put(u, 0);
    check(unsupported.lookup(targetOf(u), context, Limit::numeric(50)).status == LookupStatus::Unresolved, "unsupported_raw_condition_retained");
    Overlay rawRestored; check(Overlay::decode(unsupported.encode(), rawRestored, error) && rawRestored.latest(u.id)->rules.clauses[0].condition.raw == un.raw, "unsupported_ast_lossless");
    auto taut = u; taut.id = "tautology"; Condition any; any.kind = ConditionKind::Any; any.children = {Condition::fact("wet"), Condition::negate(Condition::fact("wet"))}; taut.rules.clauses = {{Limit::numeric(30), any}};
    Overlay correlated; (void)correlated.put(taut, 0); context.facts.clear(); check(numericIs(correlated.lookup(targetOf(taut), context, Limit::numeric(50)), 30), "boolean_unknowns_are_correlated");
    auto many = taut; many.id = "too-many"; std::vector<Condition> children; for (int i = 0; i < 13; ++i) children.push_back(Condition::fact("unknown" + std::to_string(i))); many.rules.clauses = {{Limit::numeric(30), Condition::all(children)}}; Overlay bounded; (void)bounded.put(many, 0);
    check(bounded.lookup(targetOf(many), context, Limit::numeric(50)).status == LookupStatus::Unresolved, "unknown_enumeration_bounded");
    std::ostringstream out; out << "{\"schema\":1,\"module\":\"runtime-corrections-prototype\",\"tests\":" << tests << ",\"passed\":" << tests - failures.size() << ",\"failed\":" << failures.size() << ",\"journal_bytes\":" << bytes.size() << ",\"failures\":[";
    for (size_t i = 0; i < failures.size(); ++i) { if (i) out << ','; out << json(failures[i]); }
    out << "]}"; return out.str();
}
std::string runProbe(int64_t wayID, int64_t nodeID, const char* generation, int iterations) {
    if (wayID <= 0 || !generation || !*generation || iterations < 1 || iterations > 1000000) return "{\"schema\":1,\"error\":\"invalid_probe_arguments\"}";
    Overlay overlay; auto r = sampleRecord("hypothetical:dataset-way", wayID, generation); r.anchor.fingerprint = "prototype-caller-anchor:" + std::to_string(wayID);
    r.rules.clauses = {{Limit::numeric(30), Condition::fact("wet")}};
    (void)overlay.put(r, 0); Context context; context.facts["wet"] = true; auto target = targetOf(r);
    auto bytes = overlay.encode(); Overlay restored; std::string error; bool persisted = Overlay::decode(bytes, restored, error);
    bool equal = persisted && numericIs(restored.lookup(target, context, Limit::numeric(50)), 30);
    bool nodeStored = false, nodeUnbound = false;
    if (nodeID > 0) {
        auto n = sampleRecord("hypothetical:dataset-node", nodeID, generation); n.anchor.entity = Entity::Node; n.sign.kind = SignKind::GenericMaxspeed; n.sign.trafficSignRaw = "maxspeed"; n.rules.rawTags = {{"traffic_sign", "maxspeed"}}; n.rules.clauses = {{Limit::unknown("maxspeed"), {}}};
        nodeStored = restored.put(n, 0).status == WriteStatus::Written;
        Overlay nodeRoundtrip; nodeStored = nodeStored && Overlay::decode(restored.encode(), nodeRoundtrip, error);
        nodeUnbound = nodeRoundtrip.lookup(targetOf(n), context, Limit::numeric(50)).status == LookupStatus::Unresolved;
    }
    std::vector<int64_t> nanos; nanos.reserve(iterations); uint64_t sum = 0;
    auto totalStart = std::chrono::steady_clock::now();
    for (int i = 0; i < iterations; ++i) {
        auto start = std::chrono::steady_clock::now(); auto result = restored.lookup(target, context, Limit::numeric(50)); auto finish = std::chrono::steady_clock::now();
        nanos.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(finish - start).count()); sum += result.limit.kmh;
    }
    auto total = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - totalStart).count();
    std::sort(nanos.begin(), nanos.end()); auto percentile = [&](double p) { return nanos[std::min(nanos.size() - 1, size_t((nanos.size() - 1) * p))]; };
    std::ostringstream out; out << "{\"schema\":1,\"way_id\":" << json(std::to_string(wayID)) << ",\"node_id\":" << json(std::to_string(nodeID)) << ",\"generation\":" << json(generation)
        << ",\"persisted_lookup_equal\":" << (equal ? "true" : "false") << ",\"generic_node_persisted\":" << (nodeStored ? "true" : "false") << ",\"unbound_node_unresolved\":" << (nodeUnbound ? "true" : "false")
        << ",\"hypothetical_amendments\":true,\"journal_bytes\":" << restored.encode().size() << ",\"iterations\":" << iterations << ",\"p50_ns\":" << percentile(.50) << ",\"p95_ns\":" << percentile(.95) << ",\"p99_ns\":" << percentile(.99) << ",\"total_ns\":" << total << ",\"checksum\":" << sum << '}';
    return out.str();
}
}
extern "C" const char* ysp_corrections_selftest_json() {
    static thread_local std::string result;
    try { result = runSelftest(); } catch (const std::exception& e) { result = "{\"schema\":1,\"failed\":1,\"exception\":" + ysp::corrections::json(e.what()) + "}"; }
    return result.c_str();
}
extern "C" const char* ysp_corrections_dataset_probe_json(int64_t wayID, int64_t nodeID, const char* generation, int iterations) {
    static thread_local std::string result;
    try { result = runProbe(wayID, nodeID, generation, iterations); } catch (const std::exception& e) { result = "{\"schema\":1,\"error\":" + ysp::corrections::json(e.what()) + "}"; }
    return result.c_str();
}
extern "C" const char* ysp_corrections_persistence_selftest_json(const char* path) {
    static thread_local std::string result;
    try {
        if (!path || !*path) { result = "{\"schema\":1,\"error\":\"scratch_path_required\"}"; return result.c_str(); }
        Overlay original, restored; auto r = sampleRecord("disk:node", 9876543210123LL); r.anchor.entity = Entity::Node; r.anchor.direction = Direction::Forward;
        r.anchor.boundWayID = 1234567890123LL; r.anchor.bindingVerified = true; r.sign.kind = SignKind::NumericMaxspeed;
        r.sign.trafficSignRaw = "maxspeed"; r.sign.memberships = {{1234567890123LL, 7, 123450, Direction::Unknown, 123.450123456789}};
        auto target = targetOf(r); Context context; context.facts["wet"] = true; std::string error;
        bool created = original.put(r, 0).status == WriteStatus::Written && original.save(path, error) && Overlay::load(path, restored, error) && numericIs(restored.lookup(target, context, Limit::numeric(50)), 30);
        bool amended = restored.amendLimit(r.id, 1, 0, Limit::numeric(40), r.provenance).status == WriteStatus::Written && restored.save(path, error) && Overlay::load(path, original, error) && numericIs(original.lookup(target, context, Limit::numeric(50)), 40) && original.latest(r.id)->rules.rawTags == r.rules.rawTags;
        bool deleted = original.erase(r.id, 2, r.provenance).status == WriteStatus::Written && original.save(path, error) && Overlay::load(path, restored, error) && restored.lookup(target, context, Limit::numeric(50)).status == LookupStatus::NoAmendment;
        bool history = restored.history().size() == 3 && restored.history()[0].rules.clauses[0].limit.kmh == 30 && restored.history()[1].rules.clauses[0].limit.kmh == 40 && restored.history()[2].operation == Operation::Tombstone;
        std::ostringstream out; out << "{\"schema\":1,\"module\":\"runtime-corrections-disk\",\"created_reopened\":" << (created ? "true" : "false") << ",\"amended_reopened\":" << (amended ? "true" : "false") << ",\"tombstoned_reopened\":" << (deleted ? "true" : "false") << ",\"history_preserved\":" << (history ? "true" : "false") << ",\"journal_bytes\":" << restored.encode().size() << ",\"error\":" << ysp::corrections::json(error) << '}'; result = out.str();
    } catch (const std::exception& e) { result = "{\"schema\":1,\"error\":" + ysp::corrections::json(e.what()) + "}"; }
    return result.c_str();
}

namespace {
// Small bounded JSON decoder for source-bound probe input. No production app
// import path is changed. Numbers retain their lexemes so 64-bit IDs never pass
// through double; source chainage is parsed once to its original binary double.
struct SourceJSON {
    enum Kind { Null, Boolean, Number, String, Array, Object } kind = Null;
    std::string value;
    std::vector<SourceJSON> array;
    std::map<std::string, SourceJSON> object;
    const SourceJSON& at(const std::string& key) const {
        if (kind != Object) throw std::runtime_error("source_object_required");
        auto it = object.find(key); if (it == object.end()) throw std::runtime_error("source_missing_field:" + key); return it->second;
    }
    std::string text() const { if (kind != String) throw std::runtime_error("source_string_required"); return value; }
    int64_t integer() const {
        if (kind != Number || value.find_first_of(".eE") != std::string::npos) throw std::runtime_error("source_integer_required");
        size_t end = 0; auto out = std::stoll(value, &end); if (end != value.size()) throw std::runtime_error("source_invalid_integer"); return out;
    }
    double real() const {
        if (kind != Number) throw std::runtime_error("source_number_required");
        size_t end = 0; auto out = std::stod(value, &end); if (end != value.size() || !std::isfinite(out)) throw std::runtime_error("source_invalid_number"); return out;
    }
};
class SourceJSONParser {
    std::string input; size_t pos = 0, nodes = 0;
    [[noreturn]] void fail() const { throw std::runtime_error("malformed_or_oversized_source_json"); }
    void whitespace() { while (pos < input.size() && (input[pos] == ' ' || input[pos] == '\t' || input[pos] == '\r' || input[pos] == '\n')) ++pos; }
    bool consume(char c) { whitespace(); if (pos < input.size() && input[pos] == c) { ++pos; return true; } return false; }
    uint32_t hex4() {
        if (input.size() - pos < 4) fail(); uint32_t out = 0;
        for (int i = 0; i < 4; ++i) { char c = input[pos++]; out <<= 4; if (c >= '0' && c <= '9') out += c-'0'; else if (c >= 'a' && c <= 'f') out += c-'a'+10; else if (c >= 'A' && c <= 'F') out += c-'A'+10; else fail(); } return out;
    }
    static void utf8(std::string& out, uint32_t code) {
        if (code <= 0x7f) out += char(code);
        else if (code <= 0x7ff) { out += char(0xc0 | (code >> 6)); out += char(0x80 | (code & 63)); }
        else if (code <= 0xffff) { out += char(0xe0 | (code >> 12)); out += char(0x80 | ((code >> 6) & 63)); out += char(0x80 | (code & 63)); }
        else { out += char(0xf0 | (code >> 18)); out += char(0x80 | ((code >> 12) & 63)); out += char(0x80 | ((code >> 6) & 63)); out += char(0x80 | (code & 63)); }
    }
    std::string string() {
        if (!consume('"')) fail(); std::string out;
        while (pos < input.size()) {
            unsigned char c = input[pos++]; if (c == '"') return out; if (c < 32) fail();
            if (c != '\\') out += char(c);
            else {
                if (pos >= input.size()) fail(); c = input[pos++];
                if (c == '"' || c == '\\' || c == '/') out += char(c);
                else if (c == 'b') out += '\b'; else if (c == 'f') out += '\f'; else if (c == 'n') out += '\n'; else if (c == 'r') out += '\r'; else if (c == 't') out += '\t';
                else if (c == 'u') {
                    uint32_t code = hex4();
                    if (code >= 0xd800 && code <= 0xdbff) { if (input.size()-pos < 2 || input[pos++] != '\\' || input[pos++] != 'u') fail(); auto low = hex4(); if (low < 0xdc00 || low > 0xdfff) fail(); code = 0x10000 + ((code-0xd800) << 10) + low-0xdc00; }
                    else if (code >= 0xdc00 && code <= 0xdfff) fail(); utf8(out, code);
                } else fail();
            }
            if (out.size() > 65536) fail();
        }
        fail();
    }
    SourceJSON parse(size_t depth) {
        whitespace(); if (depth > 16 || ++nodes > 4096 || pos >= input.size()) fail(); SourceJSON out;
        char c = input[pos];
        if (c == '{') {
            ++pos; out.kind = SourceJSON::Object; if (consume('}')) return out;
            do { auto key = string(); if (!consume(':')) fail(); auto child = parse(depth+1); if (!out.object.emplace(key, std::move(child)).second) fail(); } while (consume(','));
            if (!consume('}')) fail(); return out;
        }
        if (c == '[') {
            ++pos; out.kind = SourceJSON::Array; if (consume(']')) return out;
            do { if (out.array.size() >= 1024) fail(); out.array.push_back(parse(depth+1)); } while (consume(',')); if (!consume(']')) fail(); return out;
        }
        if (c == '"') { out.kind = SourceJSON::String; out.value = string(); return out; }
        for (auto literal : {"null", "true", "false"}) {
            size_t length = std::strlen(literal); if (input.compare(pos, length, literal) == 0) { pos += length; out.kind = literal[0] == 'n' ? SourceJSON::Null : SourceJSON::Boolean; out.value = literal; return out; }
        }
        size_t start = pos; if (c == '-') ++pos; if (pos >= input.size()) fail();
        if (input[pos] == '0') ++pos;
        else { if (input[pos] < '1' || input[pos] > '9') fail(); while (pos < input.size() && std::isdigit(static_cast<unsigned char>(input[pos]))) ++pos; }
        if (pos < input.size() && input[pos] == '.') { ++pos; size_t digits = pos; while (pos < input.size() && std::isdigit(static_cast<unsigned char>(input[pos]))) ++pos; if (digits == pos) fail(); }
        if (pos < input.size() && (input[pos] == 'e' || input[pos] == 'E')) { ++pos; if (pos < input.size() && (input[pos] == '+' || input[pos] == '-')) ++pos; size_t digits = pos; while (pos < input.size() && std::isdigit(static_cast<unsigned char>(input[pos]))) ++pos; if (digits == pos) fail(); }
        out.kind = SourceJSON::Number; out.value = input.substr(start, pos-start); return out;
    }
public:
    explicit SourceJSONParser(const char* value) {
        if (!value) fail(); size_t length = 0; while (length <= 1024*1024 && value[length]) ++length; if (!length || length > 1024*1024) fail(); input.assign(value, length);
    }
    SourceJSON decode() { auto out = parse(0); whitespace(); if (pos != input.size()) fail(); return out; }
};
std::string sourceNodeProbe(const char* sourceJSON, const char* path) {
    if (!path || !*path) throw std::runtime_error("scratch_path_required");
    auto source = SourceJSONParser(sourceJSON).decode();
    auto requireSource = [](bool condition, const char* reason) { if (!condition) throw std::runtime_error(reason); };
    requireSource(source.at("osm_node_id").integer() == 2532969814LL && source.at("source_id").text() == "osm-node:2532969814", "unexpected_source_node_identity");
    requireSource(source.at("binding_status").text() == "unresolved_direction", "unexpected_source_binding_status");
    auto& tags = source.at("tags"); requireSource(tags.kind == SourceJSON::Object, "source_tags_required");
    requireSource(tags.at("maxspeed").text() == "50" && tags.at("maxspeed:hgv:conditional").text() == "30 @ (weight>7.5)", "source_restriction_does_not_match_pinned_case");
    Record r = sampleRecord("source-bound:osm-node:2532969814", 2532969814LL, "bw:pbf:2026-10-26:source-node-probe");
    r.anchor.entity = Entity::Node; r.anchor.direction = Direction::Unknown; r.anchor.boundWayID = 0; r.anchor.bindingVerified = false;
    r.anchor.fingerprint = "fnv1a64:"; uint64_t sourceDigest = 14695981039346656037ULL; for (const unsigned char* p = reinterpret_cast<const unsigned char*>(sourceJSON); *p; ++p) sourceDigest = (sourceDigest ^ *p) * 1099511628211ULL;
    { std::ostringstream digest; digest << std::hex << std::setw(16) << std::setfill('0') << sourceDigest; r.anchor.fingerprint += digest.str(); }
    r.sign.kind = SignKind::NumericMaxspeed; double lat = source.at("latitude").real(), lon = source.at("longitude").real();
    requireSource(std::abs(lat) <= 90 && std::abs(lon) <= 180 && std::round(lat*1e7)/1e7 == lat && std::round(lon*1e7)/1e7 == lon, "source_coordinate_not_exact_e7");
    r.sign.latitudeE7 = int32_t(std::llround(lat*1e7)); r.sign.longitudeE7 = int32_t(std::llround(lon*1e7)); r.sign.trafficSignRaw = tags.object.count("traffic_sign") ? tags.at("traffic_sign").text() : "";
    r.rules.rawTags.clear(); for (auto& entry : tags.object) r.rules.rawTags.emplace(entry.first, entry.second.text());
    auto& memberships = source.at("memberships"); requireSource(memberships.kind == SourceJSON::Array, "source_memberships_required"); bool sourceWayFound = false;
    for (auto& item : memberships.array) {
        requireSource(item.at("direction").text() == "unknown" && item.at("proof").text() == "explicit_source_way_node_membership", "unexpected_source_membership_proof");
        NodeMembership m; m.wayID = item.at("way_id").integer(); auto ordinal = item.at("source_vertex_ordinal").integer(); m.sourceChainageMeters = item.at("chainage_m").real();
        requireSource(m.wayID > 0 && ordinal >= 0 && uint64_t(ordinal) <= UINT32_MAX && m.sourceChainageMeters >= 0 && m.sourceChainageMeters < 1e9, "invalid_source_membership");
        m.ordinal = uint32_t(ordinal); m.sourceChainageMillimeters = std::llround(m.sourceChainageMeters*1000); m.direction = Direction::Unknown; r.sign.memberships.push_back(m);
        if (m.wayID == 159830790LL && m.ordinal == 8 && m.sourceChainageMeters == 261.9489296929296) sourceWayFound = true;
    }
    requireSource(sourceWayFound, "pinned_explicit_way_membership_missing");
    r.provenance.sourceRevision = r.anchor.fingerprint; r.provenance.author = "isolated-source-bound-probe"; r.provenance.evidenceID = source.at("source_id").text(); r.provenance.action = "source_import_probe";
    // The raw condition is strictly weight>7.5t. Gross weight in this AST is
    // integral kilograms, so >=7501kg implements >7500kg without changing scope.
    Condition hgv; hgv.kind = ConditionKind::Vehicle; hgv.identity = "hgv"; hgv.raw = "hgv";
    Condition weight; weight.kind = ConditionKind::WeightAtLeastKg; weight.number = 7501; weight.raw = "weight>7.5";
    r.rules.clauses = {{Limit::numeric(50), {}}, {Limit::numeric(30), Condition::all({hgv, weight})}};
    Overlay imported; std::string error; std::vector<std::string> failures; size_t tests = 0;
    auto check = [&](bool good, const char* name) { ++tests; if (!good) failures.push_back(name); };
    check(imported.put(r, 0).status == WriteStatus::Written, "actual_source_record_imported");
    auto sourceTarget = targetOf(r); Context heavy; heavy.vehicle = "hgv"; heavy.grossWeightKg = 9000;
    check(imported.lookup(sourceTarget, heavy, Limit::numeric(50)).status == LookupStatus::Unresolved, "source_membership_does_not_authorize_application");
    // Composition-only test context explicitly supplies a hypothetical forward
    // binding and passage. This never asserts that source direction=240 or way
    // membership proves legal authority in the driving apps.
    auto association = *imported.latest(r.id); association.anchor.direction = Direction::Forward; association.anchor.boundWayID = 159830790LL; association.anchor.bindingVerified = true; association.provenance.action = "probe_only_explicit_association";
    check(imported.put(association, 1).status == WriteStatus::Written, "probe_association_context_added");
    auto target = targetOf(association);
    check(numericIs(imported.lookup(target, heavy, Limit::numeric(50)), 30), "original_heavy_hgv_30");
    check(imported.amendLimit(r.id, 2, 1, Limit::numeric(25), association.provenance).status == WriteStatus::Written, "restricted_clause_amended_30_to_25");
    check(imported.latest(r.id)->rules.rawTags == r.rules.rawTags && imported.latest(r.id)->rules.clauses[1].condition.children[0].identity == "hgv" && imported.latest(r.id)->rules.clauses[1].condition.children[1].number == 7501, "full_source_tags_and_condition_retained");
    check(imported.save(path, error), "amendment_written_to_disk"); Overlay reopened; check(Overlay::load(path, reopened, error), "amendment_reopened");
    check(reopened.encode() == imported.encode(), "reopened_journal_byte_exact");
    Context car; car.vehicle = "car"; car.grossWeightKg = 2000; Context light; light.vehicle = "hgv"; light.grossWeightKg = 7500;
    Context boundary = light; boundary.grossWeightKg = 7501; Context unknown; unknown.vehicle = "hgv";
    auto carResult = reopened.lookup(target, car, Limit::numeric(50)), lightResult = reopened.lookup(target, light, Limit::numeric(50)), heavyResult = reopened.lookup(target, heavy, Limit::numeric(50)), unknownResult = reopened.lookup(target, unknown, Limit::numeric(50));
    check(numericIs(carResult, 50), "car_remains_50"); check(numericIs(lightResult, 50), "light_hgv_including_7500kg_remains_50"); check(numericIs(heavyResult, 25), "heavy_hgv_25");
    check(numericIs(reopened.lookup(target, boundary, Limit::numeric(50)), 25), "strict_weight_threshold_7501kg_25"); check(unknownResult.status == LookupStatus::Unresolved, "unknown_weight_unresolved");
    auto retained = reopened.latest(r.id); check(retained && retained->sign.memberships.size() == r.sign.memberships.size() && retained->sign.memberships[0].sourceChainageMeters == r.sign.memberships[0].sourceChainageMeters, "source_membership_chainage_double_preserved");
    check(reopened.erase(r.id, 3, association.provenance).status == WriteStatus::Written && reopened.save(path, error), "tombstone_written");
    Overlay deleted; check(Overlay::load(path, deleted, error), "tombstone_reopened"); auto after = deleted.lookup(target, heavy, Limit::numeric(50)); check(after.status == LookupStatus::NoAmendment && after.limit.kind == LimitKind::Numeric && after.limit.kmh == 50, "tombstone_restores_baseline_50");
    std::ostringstream out; out << "{\"schema\":1,\"module\":\"source-bound-restricted-node-amendment\",\"source_node_id\":\"2532969814\",\"source_way_id\":\"159830790\",\"source_record_fnv1a64\":" << ysp::corrections::json(r.anchor.fingerprint.substr(8)) << ",\"tests\":" << tests << ",\"passed\":" << tests-failures.size() << ",\"failed\":" << failures.size() << ",\"source_import_binding_verified\":false,\"composition_context_association\":\"hypothetical_forward_binding_and_confirmed_passage\",\"car_kmh\":50,\"light_hgv_kmh\":50,\"heavy_hgv_kmh\":25,\"unknown_weight_unresolved\":" << (unknownResult.status == LookupStatus::Unresolved ? "true" : "false") << ",\"tombstone_baseline_kmh\":50,\"journal_bytes\":" << deleted.encode().size() << ",\"failures\":[";
    for (size_t i=0;i<failures.size();++i) { if(i) out << ','; out << ysp::corrections::json(failures[i]); } out << "],\"error\":" << ysp::corrections::json(error) << '}'; return out.str();
}
}
extern "C" const char* ysp_corrections_source_node_probe_json(const char* sourceJSON, const char* path) {
    static thread_local std::string result;
    try { result = sourceNodeProbe(sourceJSON, path); }
    catch (const std::exception& e) { result = "{\"schema\":1,\"module\":\"source-bound-restricted-node-amendment\",\"failed\":1,\"error\":" + ysp::corrections::json(e.what()) + "}"; }
    return result.c_str();
}
