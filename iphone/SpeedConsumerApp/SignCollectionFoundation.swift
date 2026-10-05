import Foundation

/// Initialized at first app launch even before camera/contribution consent.
/// Contract failure blocks collection but does not rotate an existing identity.
final class SignCollectionFoundation {
    let store: Result<SignCollectionStore, Error>
    let contractFailure: Error?
    init(bundle: Bundle = .main) {
        var failure: Error?
        let gate: SignCollectionContractGate
        do {
            gate = try SignCollectionContractGate { path in
                guard let root = bundle.url(forResource: "collection-contract-v1", withExtension: nil) else { throw SignCollectionError.invalidContract }
                return try Data(contentsOf: root.appendingPathComponent(path))
            }
        } catch { failure = error; gate = .blocked }
        contractFailure = failure
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("YouSpeed/SignCollection", isDirectory: true)
        store = Result { try SignCollectionStore(root: root, gate: gate) }
    }
}
