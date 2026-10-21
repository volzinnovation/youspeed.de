import Foundation

/// Formatting only: retains every clause and never evaluates a restriction.
enum TrafficSignOCRTextFormatting {
    static func display(_ raw: String) -> String {
        let superscripts = Array("⁰¹²³⁴⁵⁶⁷⁸⁹")
        var text = raw.map { character in superscripts.firstIndex(of: character).map(String.init) ?? String(character) }.joined()
        let pattern = #"(?<!\d)(\d{3,4})\s*[-–—_−]\s*(\d{3,4})\s*h(?!\p{L})"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) else { return text }
        for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            let source = text as NSString
            func time(_ group: Int) -> String? {
                let value = source.substring(with: match.range(at: group))
                guard let hour = Int(value.dropLast(2)), let minute = Int(value.suffix(2)), hour < 24, minute < 60 else { return nil }
                return String(format: "%d:%02d", hour, minute)
            }
            guard let start = time(1), let end = time(2), let range = Range(match.range, in: text) else { continue }
            text.replaceSubrange(range, with: "\(start)–\(end) h")
        }
        return text
    }

    static func speech(_ raw: String, language: String) -> String {
        var text = display(raw)
        let pattern = #"(?<!\d)\d{1,2}(?::[0-5]\d)?\s*[-–—_−]\s*\d{1,2}(?::[0-5]\d)?\s*h(?!\p{L})"#
        if let regex = try? NSRegularExpression(pattern: pattern, options: .caseInsensitive) {
            for match in regex.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
                guard let range = Range(match.range, in: text),
                      let window = TrafficSignSupplementaryTimeWindow.parse(String(text[range]).replacingOccurrences(of: "_", with: "–")) else { continue }
                text.replaceSubrange(range, with: TrafficSignSupplementaryPresentation.spokenPhrase(for: window, languageIdentifier: language))
            }
        }
        let weekday: (String, String)?
        switch language.prefix(2) {
        case "de": weekday = (#"\bMo\s*[-–]\s*Fr\b"#, "Montag bis Freitag")
        case "fr": weekday = (#"\bLu\s*[-–]\s*Ve\b"#, "lundi à vendredi")
        case "nl": weekday = (#"\bMa\s*[-–]\s*Vr\b"#, "maandag tot vrijdag")
        case "it": weekday = (#"\bLu\s*[-–]\s*Ve\b"#, "lunedì a venerdì")
        default: weekday = nil
        }
        if let weekday { text = text.replacingOccurrences(of: weekday.0, with: weekday.1, options: [.regularExpression, .caseInsensitive]) }
        return text.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}
