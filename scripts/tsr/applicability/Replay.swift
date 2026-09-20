import Foundation

@main struct Replay {
    struct Scenario: Decodable { let id: String; let batches: [TSRFrameCandidateBatch] }
    struct Vectors: Decodable { let scenarios: [Scenario] }
    struct Output: Encodable { let id: String; let frames: [TSRApplicabilityDiagnostic] }
    static func main() throws {
        let vectors = try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let outputs = vectors.scenarios.map { scenario in
            var session = TSRApplicabilitySession()
            return Output(id: scenario.id, frames: scenario.batches.map { session.evaluate($0) })
        }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        FileHandle.standardOutput.write(try encoder.encode(outputs))
    }
}
