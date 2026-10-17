import Foundation
import NaturalLanguage

/// Sign text follows the road's languages, independently of the app's UI language.
/// Country coverage is not a language-area map: CH/BE remain unresolved unless
/// the actual text supplies sufficiently clear language evidence.
enum TrafficSignOCRLanguageContext {
    private static let lock = NSLock()
    private static var country: String?
    private static var prepared: [String: String] = [:]

    static func configure(countryCode: String?) {
        lock.lock(); defer { lock.unlock() }
        country = countryCode?.uppercased()
    }

    static func languages(for countryCode: String?) -> [String] {
        switch countryCode?.uppercased() {
        case "DE", "DEU", "LI", "LIE": return ["de-DE"]
        case "FR", "FRA", "MC", "MCO": return ["fr-FR"]
        case "NL", "NLD": return ["nl-NL"]
        case "BE", "BEL": return ["nl-BE", "fr-BE", "de-BE"]
        case "CH", "CHE": return ["de-CH", "fr-CH", "it-CH", "rm-CH"]
        case "LU", "LUX": return ["fr-LU", "de-LU", "lb-LU"]
        case "RO", "ROU": return ["ro-RO"]
        case "SE", "SWE": return ["sv-SE"]
        case "IS", "ISL": return ["is-IS"]
        default: return ["de-DE", "fr-FR", "nl-NL", "it-IT", "en-GB"]
        }
    }

    static var recognitionLanguages: [String] {
        lock.lock(); defer { lock.unlock() }
        return languages(for: country)
    }

    /// Resolve using the unconditioned hypotheses, not a forced choice among
    /// country candidates. A foreign or ambiguous result must not become local.
    static func resolve(text: String, candidates: [String], hypotheses: [String: Double] = [:]) -> String? {
        guard candidates.count != 1 else { return candidates.first }
        let words = Set(text.lowercased().components(separatedBy: CharacterSet.letters.inverted).filter { !$0.isEmpty })
        let cues: [String: Set<String>] = [
            "de": ["werktags", "nässe", "schulweg", "ausgenommen", "anlieger", "frei", "uhr"],
            "fr": ["sauf", "école", "pluie", "riverains", "heures"],
            "nl": ["uitgezonderd", "school", "nat", "wegdek", "uur"],
            "it": ["lunedi", "lunedì", "martedì", "venerdì", "eccetto", "escluso", "scuola", "pioggia", "ore"],
            "rm": ["scola", "exceptà", "lavurdis"], "lb": ["ausser", "schoul"]
        ]
        var evidenced = cues.filter { !words.isDisjoint(with: $0.value) }.map(\.key)
        if words.contains("mo") && words.contains("fr") { evidenced.append("de") }
        if words.contains("ma") && words.contains("vr") { evidenced.append("nl") }
        evidenced = Array(Set(evidenced))
        // Multilingual blocks stay displayed; never choose one of their languages
        // and mispronounce the remainder of the same sign.
        if evidenced.count > 1 { return nil }
        let allowed = Set(candidates.map { String($0.prefix(2)) })
        if let language = evidenced.first, allowed.contains(language) {
            return candidates.first { $0.hasPrefix(language + "-") }
        }
        guard words.joined().count >= 12 else { return nil }
        let ranked = hypotheses.sorted { $0.value > $1.value }
        guard let best = ranked.first, allowed.contains(best.key), best.value >= 0.75,
              best.value - (ranked.dropFirst().first?.value ?? 0) >= 0.20 else { return nil }
        return candidates.first { $0.hasPrefix(best.key + "-") }
    }

    /// Called on the serial OCR worker, never the presentation lane.
    static func prepare(text: String, candidates: [String]) {
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(text)
        let hypotheses = Dictionary(uniqueKeysWithValues: recognizer.languageHypotheses(withMaximum: 5).map { ($0.key.rawValue, $0.value) })
        var resolved = resolve(text: text, candidates: candidates, hypotheses: hypotheses)
        if candidates.count > 1 {
            var lineLanguages = Set<String>()
            for line in text.components(separatedBy: .newlines).prefix(6) {
                guard line.filter(\.isLetter).count >= 12 else { continue }
                recognizer.reset(); recognizer.processString(line)
                let scores = Dictionary(uniqueKeysWithValues: recognizer.languageHypotheses(withMaximum: 5).map { ($0.key.rawValue, $0.value) })
                if let tag = resolve(text: line, candidates: candidates, hypotheses: scores) { lineLanguages.insert(tag) }
            }
            if lineLanguages.count > 1 { resolved = nil }
        }
        lock.lock(); defer { lock.unlock() }
        if prepared.count >= 128 { prepared.removeAll(keepingCapacity: true) }
        prepared[candidates.joined(separator: ",") + "|" + text] = resolved ?? ""
    }

    static func speechLanguage(for text: String) -> String? {
        lock.lock(); defer { lock.unlock() }
        let candidates = languages(for: country)
        if let cached = prepared[candidates.joined(separator: ",") + "|" + text] { return cached.isEmpty ? nil : cached }
        return resolve(text: text, candidates: candidates)
    }
}
