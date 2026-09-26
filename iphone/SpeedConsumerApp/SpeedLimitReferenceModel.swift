import CryptoKit
import Foundation

/// The packaged, owner-controlled runtime policy. Bundle downloads cannot override it.
struct SpeedLimitReferenceModel {
    static let approvalLockSHA256 = "d501f8fdcc6b4a0bddd7d6827f2c58753c7c15efb8d341d8b47d6e9992023b3a"
    static let directory = "speed-limit-reference"
    let policy: [String: Any]
    let sha256: String
    var version: String { policy["version"] as! String }
    enum LoadError: Error { case invalidArtifact }

    static func load(read: (String) throws -> Data) throws -> Self {
        let data = try read("approval-lock.json")
        guard hash(data) == approvalLockSHA256,
              let lock = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              lock["schema_version"] as? Int == 1, lock["runtime_active"] as? Bool == true,
              let entries = lock["artifacts"] as? [[String: String]] else { throw LoadError.invalidArtifact }
        var target: Self?
        for entry in entries {
            guard let file = entry["file"], (file as NSString).lastPathComponent == file,
                  let digest = entry["sha256"] else { throw LoadError.invalidArtifact }
            let bytes = try read(file)
            guard hash(bytes) == digest else { throw LoadError.invalidArtifact }
            if entry["role"] == "target" {
                guard let policy = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
                      policy["schema_version"] as? Int == 1,
                      policy["version"] as? String == lock["target_version"] as? String else { throw LoadError.invalidArtifact }
                target = Self(policy: policy, sha256: digest)
            }
        }
        guard let target else { throw LoadError.invalidArtifact }
        return target
    }
    static func bundled(bundle: Bundle = .main) throws -> Self {
        try load { name in
            guard let url = bundle.url(forResource: name, withExtension: nil, subdirectory: directory) else { throw LoadError.invalidArtifact }
            return try Data(contentsOf: url)
        }
    }
    private static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
}
