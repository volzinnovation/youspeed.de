import XCTest
@testable import SpeedConsumer

final class DebugLogPersistenceTests: XCTestCase {
    func testDefaultOnAndSavedOffStateAcrossInstances() throws {
        let suite = "debug-logging-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let gate = DebugLogPersistence(defaults: defaults)
        XCTAssertTrue(gate.isEnabled)
        gate.setEnabled(false)
        XCTAssertFalse(DebugLogPersistence(defaults: defaults).isEnabled)
        gate.write { XCTFail("Persisted a log while disabled") }
        gate.setEnabled(true)
        XCTAssertTrue(DebugLogPersistence(defaults: defaults).isEnabled)
    }

    func testOffPreventsNewFilesAndPreservesExistingLogsThenResumes() throws {
        let suite = "debug-logging-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer {
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: root)
        }
        let gate = DebugLogPersistence(defaults: defaults)
        let log = root.appendingPathComponent("debug.log")
        try gate.write { try Data("enabled".utf8).write(to: log) }
        gate.setEnabled(false)
        try gate.write { try Data("disabled".utf8).write(to: log) }
        let newLog = root.appendingPathComponent("new.log")
        try gate.write { try Data().write(to: newLog) }
        XCTAssertEqual(try String(contentsOf: log), "enabled")
        XCTAssertFalse(FileManager.default.fileExists(atPath: newLog.path))
        gate.setEnabled(true)
        try gate.write { try Data("resumed".utf8).write(to: log) }
        XCTAssertEqual(try String(contentsOf: log), "resumed")
    }
}
