import Foundation

struct TrafficSignOCRPass: Equatable, Sendable {
    let text: String
    let confidence: Double
    let scale: Int
    var uncoveredInk: Bool = false
}

/// Admission for presentation only; raw rejected reads remain collection evidence.
enum TrafficSignOCRQuality {
    static func comparison(_ text: String) -> String {
        text.precomposedStringWithCompatibilityMapping.lowercased().unicodeScalars.filter {
            CharacterSet.alphanumerics.contains($0)
        }.map(String.init).joined()
    }
    static func selected(_ passes: [TrafficSignOCRPass]) -> TrafficSignOCRPass? {
        guard let last = passes.last else { return nil }
        // Preserve a native diacritic actually read by the engine when the
        // interpolation pass only loses that mark. Never insert a guessed glyph.
        let plain = comparison(last.text).folding(options: .diacriticInsensitive, locale: Locale(identifier: "en_US_POSIX"))
        return passes.dropLast().first { candidate in
            let value = comparison(candidate.text)
            return !candidate.uncoveredInk && candidate.confidence >= 0.25 && value != comparison(last.text)
                && value.folding(options: .diacriticInsensitive, locale: Locale(identifier: "en_US_POSIX")) == plain
                && comparison(last.text) == plain
        } ?? last
    }
    static func decision(passes: [TrafficSignOCRPass], nativeWidth: Int) -> String {
        guard let chosen = selected(passes) else { return "empty" }
        let others = passes.filter { $0 != chosen }
        guard !chosen.uncoveredInk else { return "incomplete_plate" }
        let text = comparison(chosen.text)
        guard text.count >= 2, chosen.confidence >= 0.25 else { return "symbol_or_uncertain" }
        guard !["zone", "lone", "lune"].contains(text), (!text.allSatisfy(\.isNumber) || TrafficSignSupplementaryTimeWindow.parse(chosen.text) != nil) else { return "primary_or_symbol" }
        guard !others.contains(where: { $0.text.filter(\.isNumber).count > chosen.text.filter(\.isNumber).count }) else { return "lost_numeric_clause" }
        let digits = text.filter(\.isNumber)
        if !digits.isEmpty {
            guard passes.count >= 2, others.contains(where: {
                $0.text.filter(\.isNumber) == chosen.text.filter(\.isNumber) && !$0.text.isEmpty
            }) else { return "numeric_disagreement" }
            guard digits.count < 6 || Double(nativeWidth)/Double(text.count) >= 8 else { return "insufficient_native_detail" }
        }
        // Arrow glyphs often become T/I/1. Preserve the raw evidence without
        // presenting a made-up distance or dropping part of the annotation.
        if chosen.text.range(of: #"(?i)(?:^[TIil|↑↕]+\s*\d|[TIil1]\s*$)"#, options: .regularExpression) != nil,
           chosen.text.range(of: #"(?i)\d\s*(?:m|km)"#, options: .regularExpression) != nil { return "ambiguous_arrow" }
        return "accepted"
    }
}
