import XCTest
import CoreLocation
import UIKit
import ImageIO
import SQLite3
@testable import SpeedConsumer

final class TripJournalTests: XCTestCase {
    func testEndpointSeparationUsesStrictHundredMetreBoundary() {
        let origin = CLLocationCoordinate2D(latitude: 0, longitude: 0)
        for metres in [99.999, 100.001, 1000] {
            let end = CLLocationCoordinate2D(latitude: metres / 6_371_008.8 * 180 / .pi, longitude: 0)
            XCTAssertEqual(TripJournal.endpointSeparationMeters(origin, end), metres, accuracy: 0.000_001)
        }
    }
    func testShortLoopIsDiscardedOnStopWithoutResurrectionAndCountersSurvive() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            let at = Date().addingTimeInterval(-6)
            for (index, latitude) in [49, 49.0005, 49.001, 49.0005, 49].enumerated() {
                journal.location(fix(latitude, at: at.addingTimeInterval(Double(index))))
            }
            journal.bind("short-loop")
            let before = journal.snapshot()
            XCTAssertGreaterThan(before.trips.first?["distance"] as? Double ?? 0, 200)
            let exported = try journal.export(id)
            journal.location(CLLocation(coordinate: .init(latitude: 49, longitude: 8), altitude: 0,
                horizontalAccuracy: 3, verticalAccuracy: 3, course: 0, speed: 0, timestamp: Date()))
            _ = journal.snapshot()
            XCTAssertNil(journal.stoppedTripSnapshot(), "A short loop must never offer the stop button")
            XCTAssertThrowsError(try journal.endStoppedTrip(id), "A stale stop action must not save a short loop")
            journal.stop(); _ = journal.snapshot(); journal.completeFinalizerForTesting()
            XCTAssertTrue(journal.snapshot().trips.isEmpty)
            XCTAssertEqual(journal.snapshot().counters["distance"] as? Double, before.counters["distance"] as? Double)
            XCTAssertFalse(FileManager.default.fileExists(atPath: exported.path))
            journal.media(session: "short-loop", id: "late", path: "/missing.jpg", kind: "photo")
            journal.tsr("late callback"); XCTAssertTrue(journal.events(id).isEmpty)
            journal.newTrip();journal.location(fix(49.0001, at: Date().addingTimeInterval(0.1)))
            XCTAssertEqual(journal.snapshot().trips.count, 1)
            XCTAssertNotEqual(journal.snapshot().trips.first?["id"] as? String, id)
        }
    }
    func testStopAndVisibleHistoryRequireCurrentEndpointSeparationOfHundredMetres() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            let at = Date().addingTimeInterval(-1)
            var tick = 0
            func feed(_ metres: Double, accuracy: Double = 3) {
                journal.location(CLLocation(coordinate: .init(latitude: 49 + metres / 6_371_008.8 * 180 / .pi, longitude: 8),
                    altitude: 0, horizontalAccuracy: accuracy, verticalAccuracy: 3, course: 0, speed: 0,
                    timestamp: at.addingTimeInterval(Double(tick) * 0.05)))
                tick += 1; _ = journal.snapshot()
            }
            func assertVisibleHistoryCount(_ count: Int) {
                let published = expectation(description: "Published history has \(count) trips")
                DispatchQueue.main.async { XCTAssertEqual(journal.historyTrips.count, count); published.fulfill() }
                wait(for: [published], timeout: 5)
            }
            assertVisibleHistoryCount(0)
            feed(0); feed(50); feed(99.999)
            XCTAssertNil(journal.stoppedTripSnapshot()); assertVisibleHistoryCount(0)
            XCTAssertEqual(journal.snapshot().trips.count, 1, "Keep evidence buffered before the threshold")
            feed(100.001)
            XCTAssertNotNil(journal.stoppedTripSnapshot()); assertVisibleHistoryCount(1)
            feed(0, accuracy: 100)
            assertVisibleHistoryCount(1)
            feed(10)
            XCTAssertNil(journal.stoppedTripSnapshot()); assertVisibleHistoryCount(0)
            XCTAssertThrowsError(try journal.endStoppedTrip(id))
            XCTAssertEqual(journal.snapshot().trips.count, 1, "Returning near the start hides the active trip without deleting it")
            feed(150)
            XCTAssertNotNil(journal.stoppedTripSnapshot()); assertVisibleHistoryCount(1)
        }
    }
    func testFinalizerDropsShortTripAndRecoveryDropsEmptySession() throws {
        try withJournal { journal, root in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            let at = Date()
            journal.location(fix(49, at: at)); journal.location(fix(49.0001, at: at.addingTimeInterval(1)))
            journal.stop(); _ = journal.snapshot()
            XCTAssertEqual(journal.snapshot().trips.first?["state"] as? String, "finalizing")
            journal.completeFinalizerForTesting()
            XCTAssertTrue(journal.snapshot().trips.isEmpty); XCTAssertTrue(journal.events(id).isEmpty)
            journal.newTrip(); _ = journal.snapshot(); journal.close()
            let recovered = TripJournal(directory: root, heartbeat: false)
            defer { recovered.close() }
            XCTAssertTrue(recovered.snapshot().trips.isEmpty)
        }
    }
    func testUnsetPreferenceStaysOffUntilExplicitChoiceThenCurrentDrivingUseSavesNewLogs() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="trip-choice-\(UUID().uuidString)",prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        let journal=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        defer {journal.close();prefs.removePersistentDomain(forName:suite);try? FileManager.default.removeItem(at:root)}
        XCTAssertNil(prefs.object(forKey:"youspeed.journal.enabled"))
        XCTAssertFalse(journal.enabled);XCTAssertFalse(journal.configured)
        XCTAssertEqual(JournalHistoryPresentation.emptyMessage(recordingEnabled:journal.enabled),journalText("recording_off_history"))
        journal.start();let at=Date()
        journal.location(fix(49,at:at.addingTimeInterval(-4)));journal.location(fix(49.0001,at:at))
        let off=journal.snapshot()
        XCTAssertTrue(off.trips.isEmpty);XCTAssertGreaterThan(off.counters["distance"] as? Double ?? 0,10)
        XCTAssertNil(prefs.object(forKey:"youspeed.journal.enabled"),"Opening/using the app never makes a consent choice")
        journal.setEnabled(true)
        let id=try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String),newAt=Date().addingTimeInterval(0.01)
        journal.location(fix(49.1,at:newAt));journal.location(fix(49.1001,at:newAt.addingTimeInterval(4)))
        journal.tsrEvent(["event":"synthetic-unit-evidence"],at:newAt.addingTimeInterval(4))
        let recorded=journal.snapshot(),events=journal.events(id).map(JournalEvent.init)
        let gps=events.filter {$0.kind == "gps"}
        XCTAssertTrue(journal.enabled);XCTAssertTrue(journal.configured)
        XCTAssertEqual(recorded.trips.count,1);XCTAssertEqual(gps.count,2)
        XCTAssertEqual(gps.first?.payload["reason"] as? String,"segment_start")
        XCTAssertEqual(gps.first?.payload["latitude"] as? Double,49.1)
        XCTAssertEqual(events.filter {$0.kind == "tsr"}.count,1)
        XCTAssertGreaterThan(recorded.trips.first?["distance"] as? Double ?? 0,10)
        XCTAssertLessThan(recorded.trips.first?["distance"] as? Double ?? .infinity,20,"No backfill/bridge from earlier disabled GPS")
    }
    func testExplicitRecordingOptOutSurvivesReopenAndForegroundWithoutSavingTrips() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="trip-optout-\(UUID().uuidString)",prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        prefs.set(false,forKey:"youspeed.journal.enabled")
        let first=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        first.start();_ = first.snapshot();first.close()
        let reopened=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        defer {reopened.close();prefs.removePersistentDomain(forName:suite);try? FileManager.default.removeItem(at:root)}
        reopened.start();reopened.lifecycle(false);reopened.lifecycle(true)
        XCTAssertTrue(reopened.snapshot().trips.isEmpty)
        XCTAssertFalse(reopened.enabled);XCTAssertTrue(reopened.configured)
        XCTAssertEqual(prefs.object(forKey:"youspeed.journal.enabled") as? Bool,false)
        XCTAssertEqual(JournalHistoryPresentation.emptyMessage(recordingEnabled:false),journalText("recording_off_history"))
        XCTAssertEqual(JournalHistoryPresentation.emptyMessage(recordingEnabled:true),journalText("empty"))
    }
    func testSavedTripEndReadingIsWriteOnceAndBelongsToHistoricalTrip() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let first = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.odometer(first, start: 100, end: nil)
            seedRetainedEndpoints(journal)
            journal.stop(); _ = journal.snapshot(); journal.completeFinalizerForTesting()
            let before = journal.snapshot()
            journal.newTrip()
            let active = try XCTUnwrap(journal.snapshot().trips.first { $0["state"] as? String == "active" }?["id"] as? String)
            for bad in [-1.0, 99, .infinity, .nan] { XCTAssertThrowsError(try journal.enterEndOdometer(first, kilometres: bad)) }
            try journal.enterEndOdometer(first, kilometres: 101.2)
            XCTAssertThrowsError(try journal.enterEndOdometer(first, kilometres: 102))
            XCTAssertThrowsError(try journal.enterEndOdometer("missing", kilometres: 102))
            let after = try XCTUnwrap(journal.snapshot().trips.first { $0["id"] as? String == first })
            XCTAssertEqual(after["odo_end"] as? Double, 101.2)
            for key in ["start", "end", "distance", "duration"] { XCTAssertEqual(after[key] as? Double, before.trips.first?[key] as? Double, key) }
            XCTAssertEqual(after["state"] as? String, before.trips.first?["state"] as? String)
            XCTAssertEqual(journal.snapshot().counters["distance"] as? Double, before.counters["distance"] as? Double)
            let entries = journal.events(first).map(JournalEvent.init).filter { $0.kind == "odometer_entry" && $0.payload["field"] as? String == "end" }
            XCTAssertEqual(entries.count, 1); XCTAssertEqual(entries.first?.payload["entered_unit"] as? String, "km")
            XCTAssertFalse(journal.events(active).map(JournalEvent.init).contains { $0.kind == "odometer_entry" })
        }
    }
    func testEndpointNamesRequireNearbyMappedFixWithoutGapAndDistanceUsesOneLocalizedDecimal() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let at = Date().addingTimeInterval(4), id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.location(fix(49, at: at.addingTimeInterval(-4)))
            journal.matchedPlace(at: at.addingTimeInterval(-4), streetName: "Startstraße", cityName: "Karlsruhe", latitude: 49, longitude: 8, accuracy: 3)
            journal.location(fix(49.0001, at: at))
            journal.matchedPlace(at: at, streetName: "Zielstraße", cityName: "Karlsruhe", latitude: 49.0001, longitude: 8, accuracy: 3)
            let events = journal.events(id).map(JournalEvent.init)
            let names = JournalHistoryPresentation.endpointNames(trip: [:], events: events)
            XCTAssertEqual(names.start, "Startstraße, Karlsruhe"); XCTAssertEqual(names.end, "Zielstraße, Karlsruhe")
            let gps = events.filter { $0.kind == "gps" }
            let remote = JournalEvent(["seq": 500.0, "kind": "place", "time": at.timeIntervalSince1970, "payload": "{\"street_name\":\"Wrong\",\"latitude\":50,\"longitude\":8,\"accuracy\":3}"])
            let unknown = JournalHistoryPresentation.endpointNames(trip: [:], events: gps + [remote])
            XCTAssertEqual(unknown.start, journalText("location_unknown")); XCTAssertEqual(unknown.end, journalText("location_unknown"))
            let gap = JournalEvent(["seq": 501.0, "kind": "gap", "time": at.addingTimeInterval(-2).timeIntervalSince1970, "payload": "{}"])
            let onlyStart = events.filter { $0.kind != "place" || $0.payload["street_name"] as? String != "Zielstraße" }
            XCTAssertEqual(JournalHistoryPresentation.endpointNames(trip: [:], events: onlyStart + [gap]).end, journalText("location_unknown"))
            let boundaryGap = JournalEvent(["seq": 502.0, "kind": "gap", "time": at.timeIntervalSince1970, "payload": "{}"])
            XCTAssertEqual(JournalHistoryPresentation.endpointNames(trip: [:], events: events + [boundaryGap]).end, "Zielstraße, Karlsruhe")
            XCTAssertEqual(JournalHistoryPresentation.endpointNames(trip: [:], events: onlyStart + [boundaryGap]).end, journalText("location_unknown"))
            XCTAssertEqual(JournalHistoryPresentation.number(12.34, locale: Locale(identifier: "de_DE")), "12,3")
            XCTAssertEqual(JournalHistoryPresentation.number(12.36, locale: Locale(identifier: "en_US")), "12.4")
        }
    }
    func testDiagnosticShareIncludesGPSAndTSRButExcludesAllOdometerEvidence() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.odometer(id, start: 100, end: 101)
            journal.location(fix(49, at: Date())); journal.tsr("private TSR event")
            let exported = try journal.export(id, options: TripExportOptions(includeRawLogs: true))
            let canonical = try JSONSerialization.jsonObject(with: Data(contentsOf: exported.appendingPathComponent("journal.json"))) as! [String: Any]
            let trip = canonical["trip"] as! [String: Any], events = canonical["events"] as! [[String: Any]]
            XCTAssertNil(trip["odometer_start_km"]); XCTAssertNil(trip["odometer_end_km"]); XCTAssertNil(trip["odometer_entries"])
            XCTAssertFalse(events.contains { $0["kind"] as? String == "odometer_entry" })
            XCTAssertTrue(events.contains { $0["kind"] as? String == "gps" }); XCTAssertTrue(events.contains { $0["kind"] as? String == "tsr" })
            XCTAssertFalse(FileManager.default.fileExists(atPath: exported.appendingPathComponent("gps.ndjson").path))
            XCTAssertFalse(FileManager.default.fileExists(atPath: exported.appendingPathComponent("tsr.ndjson").path))
            let optedIn = try journal.export(id, options: TripExportOptions(includeRawLogs: true, includeOdometer: true))
            let withReadings = try JSONSerialization.jsonObject(with: Data(contentsOf: optedIn.appendingPathComponent("journal.json"))) as! [String: Any]
            XCTAssertEqual(((withReadings["events"] as? [[String: Any]]) ?? []).filter { $0["kind"] as? String == "odometer_entry" }.count, 2)
        }
    }
    func testMatchedPlacesRespectRecordingConsentAndForegroundEvenDuringFinalizer() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String), at = Date()
            journal.matchedPlace(at: at, streetName: "Visible", cityName: nil, latitude: 49, longitude: 8, accuracy: 3)
            XCTAssertEqual(journal.events(id).filter { $0["kind"] as? String == "place" }.count, 1)
            journal.stop(at: at.addingTimeInterval(0.01)); journal.setEnabled(false); _ = journal.snapshot()
            journal.matchedPlace(at: at, streetName: "Declined", cityName: nil, latitude: 49, longitude: 8, accuracy: 3)
            XCTAssertEqual(journal.events(id).filter { $0["kind"] as? String == "place" }.count, 1)
            journal.setEnabled(true); journal.lifecycle(false); _ = journal.snapshot()
            journal.matchedPlace(at: at, streetName: "Background", cityName: nil, latitude: 49, longitude: 8, accuracy: 3)
            XCTAssertEqual(journal.events(id).filter { $0["kind"] as? String == "place" }.count, 1)
        }
    }
    func testFreshDatabaseSettingsDoNotPublishSetupErrors() async throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="trip-startup-test-\(UUID().uuidString)"
        let prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        let journal=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        defer { journal.close(); prefs.removePersistentDomain(forName:suite); try? FileManager.default.removeItem(at:root) }
        let initial=journal.snapshot()
        XCTAssertTrue(initial.trips.isEmpty)
        XCTAssertEqual(initial.counters["distance"] as? Double,0)
        await MainActor.run { XCTAssertNil(journal.error) }
    }

    func testTripOwnsLogsAndDeletionPreservesCounterWithoutResurrection() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="trip-test-\(UUID().uuidString)"
        let prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        let journal=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        defer { journal.close(); prefs.removePersistentDomain(forName:suite); try? FileManager.default.removeItem(at:root) }
        journal.setEnabled(true); journal.start(); journal.start()
        let t=Date()
        journal.location(CLLocation(coordinate:.init(latitude:49,longitude:8),altitude:0,horizontalAccuracy:3,verticalAccuracy:3,course:0,speed:3,timestamp:t.addingTimeInterval(-4)))
        journal.location(CLLocation(coordinate:.init(latitude:49.0001,longitude:8),altitude:0,horizontalAccuracy:3,verticalAccuracy:3,course:0,speed:3,timestamp:t))
        journal.tsr("recognized class=DE:274-50 score=0.95")
        journal.bind("camera")
        let snapshot=journal.snapshot()
        XCTAssertEqual(snapshot.trips.count,1)
        let id=try XCTUnwrap(snapshot.trips.first?["id"] as? String)
        let distance=try XCTUnwrap(snapshot.counters["distance"] as? Double)
        XCTAssertGreaterThan(distance,10)
        XCTAssertEqual(journal.events(id).filter{$0["kind"] as? String == "gps"}.count,2)
        XCTAssertEqual(journal.events(id).filter{$0["kind"] as? String == "tsr"}.count,1)
        let archive=try journal.export(id)
        XCTAssertTrue(FileManager.default.fileExists(atPath:archive.appendingPathComponent("track.gpx").path))
        journal.delete(id)
        journal.media(session:"camera",id:"late",path:"/missing.jpg",kind:"photo")
        XCTAssertTrue(journal.snapshot().trips.isEmpty)
        XCTAssertTrue(journal.events(id).isEmpty)
        XCTAssertEqual(journal.snapshot().counters["distance"] as? Double,distance)
        XCTAssertFalse(FileManager.default.fileExists(atPath:archive.path))
        journal.lifecycle(false); journal.lifecycle(true); journal.start()
        journal.aliasBinding("camera",to:"late-capture")
        journal.media(session:"camera",id:"late",path:"/missing.jpg",kind:"photo",binding:"late-capture")
        let next=journal.snapshot()
        XCTAssertEqual(next.trips.count,1)
        let nextID=try XCTUnwrap(next.trips.first?["id"] as? String)
        XCTAssertTrue(journal.events(nextID).allSatisfy { $0["kind"] as? String == "coverage" })
    }
    func testDuplicateAndOutOfOrderFixesAreLoggedWithoutDistanceInflation() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4)))
            journal.location(fix(49.0001, at: at))
            let before = journal.snapshot()
            let id = try XCTUnwrap(before.trips.first?["id"] as? String)
            let distance = try XCTUnwrap(before.counters["distance"] as? Double)
            journal.location(fix(49.0001, at: at))
            journal.location(fix(49.0002, at: at.addingTimeInterval(-1)))
            XCTAssertEqual(journal.snapshot().counters["distance"] as? Double, distance)
            let gps = journal.events(id).map(JournalEvent.init).filter { $0.kind == "gps" }
            XCTAssertEqual(gps.count, 4)
            XCTAssertEqual(gps.filter { $0.payload["reason"] as? String == "duplicate_or_out_of_order" }.count, 2)
        }
    }
    func testRecordingOptOutKeepsOnlyAggregateCountersAndDoesNotBackfill() throws {
        try withJournal { journal, _ in
            journal.setEnabled(false); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4)))
            journal.location(fix(49.0001, at: at))
            let off = journal.snapshot()
            XCTAssertTrue(off.trips.isEmpty)
            XCTAssertGreaterThan(off.counters["distance"] as? Double ?? 0, 10)
            journal.setEnabled(true)
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            XCTAssertFalse(journal.events(id).contains { $0["kind"] as? String == "gps" })
        }
    }
    func testResumeWindowCreatesHonestGapAndLaterNewTrip() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let first = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            seedRetainedEndpoints(journal)
            let at = Date()
            journal.lifecycle(false, at: at); journal.lifecycle(true, at: at.addingTimeInterval(120))
            XCTAssertEqual(journal.snapshot().trips.count, 1)
            XCTAssertTrue(journal.events(first).contains { $0["kind"] as? String == "gap" })
            journal.lifecycle(false, at: at); journal.lifecycle(true, at: at.addingTimeInterval(301))
            let resumed = journal.snapshot()
            XCTAssertEqual(resumed.trips.count, 2)
            let old = try XCTUnwrap(resumed.trips.first { $0["id"] as? String == first })
            XCTAssertEqual(old["state"] as? String, "interrupted")
            XCTAssertEqual(old["end_reason"] as? String, "foreground_timeout")
            XCTAssertLessThan(old["end"] as? Double ?? .infinity, at.addingTimeInterval(3).timeIntervalSince1970)
        }
    }
    func testBoundedFinalizerAcceptsOnlyAlreadyCapturedEventsAndDeleteCancelsOwnership() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start(); let initial = journal.snapshot()
            let id = try XCTUnwrap(initial.trips.first?["id"] as? String)
            seedRetainedEndpoints(journal)
            let captured = Date(), end = captured.addingTimeInterval(0.001)
            journal.stop(at: end)
            journal.signEvent(["class_code": "DE:310"], at: captured)
            journal.signEvent(["class_code": "DE:311"], at: end.addingTimeInterval(1))
            XCTAssertEqual(journal.events(id).filter { $0["kind"] as? String == "sign" }.count, 1)
            journal.completeFinalizerForTesting()
            journal.signEvent(["class_code": "DE:310"], at: captured)
            XCTAssertEqual(journal.events(id).filter { $0["kind"] as? String == "sign" }.count, 1)
            journal.start(); XCTAssertEqual(journal.snapshot().trips.count, 1)
            journal.delete(id); journal.completeFinalizerForTesting()
            XCTAssertTrue(journal.snapshot().trips.isEmpty)
        }
    }
    func testEncryptedBackupRestorePreservesEpochSequencesAndDoesNotDoubleCount() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4))); journal.location(fix(49.0001, at: at))
            let before = journal.snapshot(), id = try XCTUnwrap(before.trips.first?["id"] as? String)
            let sequences = journal.events(id).compactMap { $0["seq"] as? Double }
            let backup = try journal.backup(password: "correct horse battery")
            defer { try? FileManager.default.removeItem(at: backup) }
            let bytes = try Data(contentsOf: backup)
            XCTAssertFalse(String(data: bytes, encoding: .utf8)!.contains(id))
            XCTAssertThrowsError(try journal.restore(from: backup, password: "incorrect password"))
            XCTAssertEqual(journal.snapshot().trips.count, 1)
            try journal.restore(from: backup, password: "correct horse battery")
            let first = journal.snapshot()
            try journal.restore(from: backup, password: "correct horse battery")
            let second = journal.snapshot()
            XCTAssertEqual(first.counters["origin"] as? Double, second.counters["origin"] as? Double)
            XCTAssertEqual(first.counters["distance"] as? Double, second.counters["distance"] as? Double)
            XCTAssertEqual(journal.events(id).compactMap { $0["seq"] as? Double }, sequences)
            XCTAssertEqual(second.trips.first?["state"] as? String, "interrupted")
            journal.clearAll()
            let empty = journal.snapshot()
            XCTAssertTrue(empty.trips.isEmpty); XCTAssertEqual(empty.counters["distance"] as? Double, 0)
        }
    }
    func testMaskedArchiveRemovesLocationsRawDiagnosticsAndUnlocatedPhotos() throws {
        try withJournal { journal, root in
            journal.setEnabled(true); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4))); journal.location(fix(49.0001, at: at))
            journal.signEvent(["class_code": "DE:310", "latitude": 49.0, "longitude": 8.0, "road_id": "private-road"], at: at)
            journal.tsr("private-road longitude=8.0 latitude=49.0")
            journal.bind("unknown-photo")
            let photo = root.appendingPathComponent("unknown.jpg"); try Data([1, 2, 3]).write(to: photo)
            journal.media(session: "unknown-photo", id: "unknown-photo", path: photo.path, kind: "photo", at: at.addingTimeInterval(60))
            let snapshot = journal.snapshot(), id = try XCTUnwrap(snapshot.trips.first?["id"] as? String)
            let exported = try journal.export(id, options: TripExportOptions(masked: true, selectedMedia: ["unknown-photo"]))
            XCTAssertFalse(FileManager.default.fileExists(atPath: exported.appendingPathComponent("gps.ndjson").path))
            XCTAssertFalse(FileManager.default.fileExists(atPath: exported.appendingPathComponent("tsr.ndjson").path))
            let gpx = try String(contentsOf: exported.appendingPathComponent("track.gpx"))
            XCTAssertFalse(gpx.contains("lat=\""))
            let media = try JSONSerialization.jsonObject(with: Data(contentsOf: exported.appendingPathComponent("media.json"))) as! [String: Any]
            XCTAssertTrue((media["media"] as! [[String: Any]]).isEmpty)
            XCTAssertEqual((media["omitted"] as! [[String: String]]).first?["reason"], "unproven_photo_location")
            let portable = try JSONSerialization.jsonObject(with: Data(contentsOf: exported.appendingPathComponent("journal.json"))) as! [String: Any]
            XCTAssertEqual(portable["schema_version"] as? Int, 1)
            XCTAssertEqual((portable["privacy"] as? [String: Any])?["raw_logs_included"] as? Bool, false)
            XCTAssertTrue((portable["trip"] as? [String: Any])?["distance_m"] is Double)
            let zip = try journal.archive(id)
            XCTAssertEqual(Array(try Data(contentsOf: zip).prefix(4)), [0x50, 0x4b, 0x03, 0x04])
            XCTAssertEqual(journal.snapshot().counters["distance"] as? Double, snapshot.counters["distance"] as? Double)
        }
    }
    func testGPXDoesNotSplitAtInterleavedTSREventsAndDiscoveriesKeepRawUpdates() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4)))
            journal.tsr("first event", at: at)
            journal.location(fix(49.0001, at: at))
            journal.signEvent(["class_code": "DE:274-30", "source": "camera", "track_id": "track-1"], at: Date())
            journal.signEvent(["class_code": "DE:274-30", "source": "camera", "track_id": "track-1", "confidence": 0.99], at: Date())
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            let events = journal.events(id).map(JournalEvent.init)
            XCTAssertEqual(events.filter { $0.kind == "sign" }.count, 2)
            XCTAssertEqual(JournalDiscoveries.project(events).count, 1)
            let exported = try journal.export(id)
            let gpx = try String(contentsOf: exported.appendingPathComponent("track.gpx"))
            XCTAssertEqual(gpx.components(separatedBy: "<trkseg>").count - 1, 1)
            XCTAssertEqual(gpx.components(separatedBy: "<trkpt ").count - 1, 2)
        }
    }
    func testEnablingJournalInsideLiveCameraAssociatesVideoAndSeeksOnlyWithinItsInterval() throws {
        try withJournal { journal, root in
            let file = root.appendingPathComponent("live.mov"); try Data([0]).write(to: file)
            let start = Date().addingTimeInterval(-5)
            journal.videoTiming(id: "live.mov", path: file.path, session: "camera", startedAt: start, duration: nil, finished: false)
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.videoTiming(id: "live.mov", path: file.path, session: "camera", startedAt: start, duration: 10, finished: true)
            let media = try XCTUnwrap(JournalMedia.project(journal.events(id).map(JournalEvent.init)).first)
            XCTAssertEqual(try XCTUnwrap(media.offset(at: start.addingTimeInterval(3))), 3, accuracy: 0.000_001)
            XCTAssertNil(media.offset(at: start.addingTimeInterval(-0.01)))
            XCTAssertNil(media.offset(at: start.addingTimeInterval(10.01)))
            XCTAssertEqual(media.payload["timing_quality"] as? String, "recorded_duration_anchor_estimated")
            journal.delete(id)
            journal.videoTiming(id: "live.mov", path: file.path, session: "camera", startedAt: start, duration: 10, finished: true)
            XCTAssertTrue(journal.snapshot().trips.isEmpty)
        }
    }
    func testOptionalOdometerIsWriteOnceAndDecliningPairIsRejected() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.odometer(id, start: 100, end: 90)
            journal.odometer(id, start: 200, end: 101)
            let trip = try XCTUnwrap(journal.snapshot().trips.first)
            XCTAssertEqual(trip["odo_start"] as? Double, 100)
            XCTAssertEqual(trip["odo_end"] as? Double, 101)
            seedRetainedEndpoints(journal)
            journal.stop(); journal.completeFinalizerForTesting()
            journal.odometer(id, start: nil, end: 102)
            XCTAssertEqual(journal.snapshot().trips.first?["odo_end"] as? Double, 101)
        }
    }
    func testMaskedSelectedPhotoOutsideEndpointAreasIsReencodedWithoutGPSMetadata() throws {
        try withJournal { journal, root in
            journal.setEnabled(true); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4))); journal.location(fix(49.0001, at: at))
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            let image = UIGraphicsImageRenderer(size: CGSize(width: 8, height: 8)).image { context in
                UIColor.blue.setFill(); context.fill(CGRect(x: 0, y: 0, width: 8, height: 8))
            }
            let location = PanoramaxLocationSample(latitude: 49.02, longitude: 8.02, capturedAt: at, accuracyMeters: 3, altitudeMeters: 10, headingDegrees: 0)
            let original = try XCTUnwrap(PanoramaxJPEGMetadata.adding(to: image.jpegData(compressionQuality: 0.9)!, location: location))
            let source = root.appendingPathComponent("private.jpg"); try original.write(to: source)
            journal.bind("photo"); journal.media(session: "photo", id: "photo", path: source.path, kind: "photo", at: at, location: location)
            _ = journal.snapshot()
            let exported = try journal.export(id, options: TripExportOptions(masked: true, selectedMedia: ["photo"]))
            let media = try JSONSerialization.jsonObject(with: Data(contentsOf: exported.appendingPathComponent("media.json"))) as! [String: Any]
            let rows = media["media"] as! [[String: Any]]
            let name = try XCTUnwrap(rows.first?["archive_path"] as? String)
            let copy = try XCTUnwrap(CGImageSourceCreateWithURL(exported.appendingPathComponent(name) as CFURL, nil))
            let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(copy, 0, nil) as? [String: Any])
            XCTAssertNil(properties[kCGImagePropertyGPSDictionary as String])
            XCTAssertNil(rows.first?["path"]); XCTAssertNil(rows.first?["remote_url"])
            XCTAssertEqual(try Data(contentsOf: source), original)
        }
    }
    func testMilesEntryRetainsOriginalUnitAndConvertsOnlyForComparableDistance() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.odometer(id, start: 100, end: 101, unit: "mi")
            let trip = try XCTUnwrap(journal.snapshot().trips.first)
            XCTAssertEqual(trip["odo_start"] as? Double ?? 0, 160.9344, accuracy: 0.000001)
            let entries = journal.events(id).map(JournalEvent.init).filter { $0.kind == "odometer_entry" }
            XCTAssertEqual(entries.count, 2)
            XCTAssertEqual(entries.first?.payload["entered_unit"] as? String, "mi")
            XCTAssertEqual(entries.first?.payload["entered_value"] as? Double, 100)
        }
    }
    func testRejectedNonfiniteAndOutOfRangeGPSFixesRemainLosslesslyExportable() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start(); _ = journal.snapshot()
            let at = Date()
            journal.location(fix(49, at: at.addingTimeInterval(-4)))
            journal.location(CLLocation(coordinate: .init(latitude: .nan, longitude: .infinity), altitude: .nan,
                horizontalAccuracy: .infinity, verticalAccuracy: 1, course: .infinity, speed: .infinity,
                timestamp: at.addingTimeInterval(-3)))
            journal.location(CLLocation(coordinate: .init(latitude: 95, longitude: 8), altitude: 0,
                horizontalAccuracy: 3, verticalAccuracy: 1, course: 0, speed: 3,
                timestamp: at.addingTimeInterval(-2)))
            journal.location(fix(49.0001, at: at))
            let snapshot = journal.snapshot(), id = try XCTUnwrap(snapshot.trips.first?["id"] as? String)
            let gps = journal.events(id).map(JournalEvent.init).filter { $0.kind == "gps" }
            XCTAssertEqual(gps.count, 4)
            for rejected in gps[1...2] {
                XCTAssertTrue(rejected.payload["latitude"] is NSNull)
                XCTAssertTrue(rejected.payload["longitude"] is NSNull)
                XCTAssertEqual(rejected.payload["valid"] as? Bool, false)
                XCTAssertEqual(rejected.payload["track_eligible"] as? Bool, false)
                XCTAssertEqual(rejected.payload["reason"] as? String, "invalid_coordinates")
            }
            XCTAssertTrue(gps[1].payload["accuracy"] is NSNull)
            XCTAssertTrue(gps[1].payload["speed"] is NSNull)
            XCTAssertTrue(gps[1].payload["altitude"] is NSNull)
            XCTAssertTrue(gps[1].payload["course"] is NSNull)
            XCTAssertTrue((gps[1].payload["quality_flags"] as? [String] ?? []).contains("coordinates_nonfinite"))
            XCTAssertTrue((gps[2].payload["quality_flags"] as? [String] ?? []).contains("coordinates_out_of_range"))
            XCTAssertEqual(gps.last?.payload["reason"] as? String, "segment_start")
            XCTAssertEqual(snapshot.counters["distance"] as? Double, 0)
            let exported = try journal.export(id)
            let canonicalBytes = try Data(contentsOf: exported.appendingPathComponent("journal.json"))
            let canonical = try JSONSerialization.jsonObject(with: canonicalBytes) as! [String: Any]
            let rows = (canonical["events"] as! [[String: Any]]).filter { $0["kind"] as? String == "gps" }
            XCTAssertEqual(rows.count, 4)
            XCTAssertTrue((rows[1]["payload"] as? [String: Any])?["latitude"] is NSNull)
        }
    }
    func testCustomHistoryDatesIncludeBothLocalDaysAndHonorDSTBoundaries() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "Europe/Berlin"))
        let formatter = ISO8601DateFormatter()
        func date(_ value: String) throws -> Date { try XCTUnwrap(formatter.date(from: value)) }
        let from = try date("2026-03-29T00:00:00+01:00")
        let last = try date("2026-03-29T23:59:59+02:00")
        let upper = try date("2026-03-30T00:00:00+02:00")
        XCTAssertEqual(upper.timeIntervalSince(from), 23 * 3600)
        XCTAssertTrue(JournalHistoryRange.includes(start: from.timeIntervalSince1970, periodDays: -1, customFrom: from, customTo: last, calendar: calendar))
        XCTAssertTrue(JournalHistoryRange.includes(start: last.timeIntervalSince1970, periodDays: -1, customFrom: from, customTo: last, calendar: calendar))
        XCTAssertFalse(JournalHistoryRange.includes(start: from.addingTimeInterval(-1).timeIntervalSince1970, periodDays: -1, customFrom: from, customTo: last, calendar: calendar))
        XCTAssertFalse(JournalHistoryRange.includes(start: upper.timeIntervalSince1970, periodDays: -1, customFrom: from, customTo: last, calendar: calendar))
        XCTAssertFalse(JournalHistoryRange.includes(start: from.timeIntervalSince1970, periodDays: -1, customFrom: upper, customTo: from, calendar: calendar))
    }
    func testHistoryPresetsIncludeTodayAndExactlyThePrecedingCalendarDates() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "Europe/Berlin"))
        let now = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-10-25T12:00:00+01:00"))
        let today = calendar.startOfDay(for: now)
        for count in [7, 30, 365] {
            let lower = try XCTUnwrap(calendar.date(byAdding: .day, value: 1 - count, to: today))
            let upper = try XCTUnwrap(calendar.date(byAdding: .day, value: 1, to: today))
            XCTAssertTrue(JournalHistoryRange.includes(start: lower.timeIntervalSince1970, periodDays: count, now: now, calendar: calendar))
            XCTAssertTrue(JournalHistoryRange.includes(start: upper.addingTimeInterval(-1).timeIntervalSince1970, periodDays: count, now: now, calendar: calendar))
            XCTAssertFalse(JournalHistoryRange.includes(start: lower.addingTimeInterval(-1).timeIntervalSince1970, periodDays: count, now: now, calendar: calendar))
            XCTAssertFalse(JournalHistoryRange.includes(start: upper.timeIntervalSince1970, periodDays: count, now: now, calendar: calendar))
        }
    }
    func testPeriodChartAggregatesSavedFactsByStartDayAndSeparatesObservedTimeFromSpan() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = try XCTUnwrap(TimeZone(identifier: "Europe/Berlin"))
        let formatter = ISO8601DateFormatter()
        let first = try XCTUnwrap(formatter.date(from: "2026-10-24T23:30:00+02:00"))
        let second = try XCTUnwrap(formatter.date(from: "2026-10-24T10:00:00+02:00"))
        let next = try XCTUnwrap(formatter.date(from: "2026-10-25T23:00:00+01:00"))
        let rows: [[String: Any]] = [
            ["start": first.timeIntervalSince1970, "distance": 1000.0, "duration": 7200.0, "observed": 3600.0],
            ["start": second.timeIntervalSince1970, "distance": 250.0, "duration": 600.0, "observed": 600.0],
            ["start": next.timeIntervalSince1970, "distance": 500.0, "duration": 300.0, "observed": 100.0]
        ]
        let days = JournalHistoryProjection.days(rows, calendar: calendar)
        XCTAssertEqual(days.count, 2)
        XCTAssertEqual(days[0].date, calendar.startOfDay(for: first))
        XCTAssertEqual(days[0].tripCount, 2)
        XCTAssertEqual(days[0].distanceMetres, 1250)
        XCTAssertEqual(days[0].durationSeconds, 7800)
        XCTAssertEqual(days[0].observedSeconds, 4200)
        XCTAssertEqual(days[1].date, calendar.startOfDay(for: next))
        XCTAssertEqual(days[1].observedSeconds, 100)
        XCTAssertEqual(days.reduce(0) { $0 + $1.distanceMetres }, 1750)
    }
    private func fix(_ latitude: Double, at timestamp: Date) -> CLLocation {
        CLLocation(coordinate: .init(latitude: latitude, longitude: 8), altitude: 10, horizontalAccuracy: 3, verticalAccuracy: 3, course: 0, speed: 3, timestamp: timestamp)
    }
    private func seedRetainedEndpoints(_ journal: TripJournal) {
        let at = Date()
        journal.location(fix(49, at: at)); journal.location(fix(49.001, at: at.addingTimeInterval(2)))
        _ = journal.snapshot()
    }
    private func withJournal(_ test: (TripJournal, URL) throws -> Void) throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite = "trip-feature-test-\(UUID().uuidString)", prefs = try XCTUnwrap(UserDefaults(suiteName: suite))
        let journal = TripJournal(directory: root, preferences: prefs, heartbeat: false)
        defer { journal.close(); prefs.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        _ = journal.snapshot()
        try test(journal, root)
    }

}

extension TripJournalTests {
    func testStandstillSaveRemembersOdometerAndResumesOnlyOnMovement() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="trip-stop-\(UUID().uuidString)",prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        var clock=0.0
        let journal=TripJournal(directory:root,preferences:prefs,heartbeat:false,promptClock:{clock})
        defer {journal.close();prefs.removePersistentDomain(forName:suite);try? FileManager.default.removeItem(at:root)}
        journal.setEnabled(true);journal.start();_ = journal.snapshot()
        let at=Date().addingTimeInterval(-0.5)
        func feed(_ speed:Double,_ tick:Int) {
            clock=Double(tick)
            journal.location(CLLocation(coordinate:.init(latitude:tick == 0 ? 49 : (tick <= 18 ? 49.001 : 49.002),longitude:8),altitude:0,horizontalAccuracy:3,verticalAccuracy:3,course:0,speed:speed,timestamp:at.addingTimeInterval((tick == 0 ? 0 : 2)+Double(tick)*0.01)))
            _ = journal.snapshot()
        }
        feed(10,0)
        for t in 1...16 {feed(0,t)}
        let prompt=try XCTUnwrap(journal.stoppedTripSnapshot())
        XCTAssertFalse(prompt.estimated)
        try journal.saveStoppedTrip(prompt.tripID,odometer:123456)
        XCTAssertNil(journal.stoppedTripSnapshot())
        let ended=try XCTUnwrap(journal.snapshot().trips.first)
        XCTAssertEqual(ended["state"] as? String,"ended");XCTAssertEqual(ended["odo_end"] as? Double,123456)
        feed(0,17);XCTAssertEqual(journal.snapshot().trips.count,1)
        journal.lifecycle(false);journal.lifecycle(true);XCTAssertEqual(journal.snapshot().trips.count,1)
        feed(10,18);XCTAssertEqual(journal.snapshot().trips.count,2)
        for t in 19...34 {feed(0,t)}
        let next=try XCTUnwrap(journal.stoppedTripSnapshot())
        XCTAssertEqual(next.reading,123456);XCTAssertTrue(next.estimated)
        journal.continueStoppedTrip(next.tripID);XCTAssertNil(journal.stoppedTripSnapshot())
        feed(1,35)
        XCTAssertThrowsError(try journal.saveStoppedTrip(next.tripID,odometer:123457))
    }
}

extension TripJournalTests {
    func testDelayedPlaceCallbacksAreIncludedBeforeHistoryIsFrozen() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String), at = Date()
            journal.location(fix(49, at: at))
            journal.location(fix(49.001, at: at.addingTimeInterval(2)))
            journal.stop(at: at.addingTimeInterval(2.25))
            let pending = try XCTUnwrap(journal.snapshot().trips.first)
            XCTAssertEqual(pending["history_version"] as? Double, 0)
            journal.matchedPlace(at: at, streetName: "Startstraße", cityName: "Karlsruhe", latitude: 49, longitude: 8, accuracy: 3)
            journal.matchedPlace(at: at.addingTimeInterval(2), streetName: "Zielstraße", cityName: "Karlsruhe", latitude: 49.001, longitude: 8, accuracy: 3)
            _ = journal.snapshot(); journal.completeFinalizerForTesting()
            let saved = try XCTUnwrap(journal.snapshot().trips.first)
            XCTAssertEqual(saved["start_place"] as? String, "Startstraße, Karlsruhe")
            XCTAssertEqual(saved["end_place"] as? String, "Zielstraße, Karlsruhe")
            XCTAssertEqual(saved["history_version"] as? Double, 2)
            for key in ["distance", "end", "duration"] { XCTAssertEqual(saved[key] as? Double, pending[key] as? Double, key) }
        }
    }

    func testMissingVersionOneNamesAreRepairedOnceWithoutReplacingSavedNames() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite = "history-repair-\(UUID().uuidString)", prefs = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { prefs.removePersistentDomain(forName: suite); try? FileManager.default.removeItem(at: root) }
        let journal = TripJournal(directory: root, preferences: prefs, heartbeat: false)
        journal.setEnabled(true); journal.start(); _ = journal.snapshot()
        let at = Date()
        journal.location(fix(49, at: at))
        journal.matchedPlace(at: at, streetName: "Captured", cityName: nil, latitude: 49, longitude: 8, accuracy: 3)
        journal.location(fix(49.001, at: at.addingTimeInterval(2)))
        journal.matchedPlace(at: at.addingTimeInterval(2), streetName: "Captured", cityName: nil, latitude: 49.001, longitude: 8, accuracy: 3)
        journal.stop(); _ = journal.snapshot(); journal.completeFinalizerForTesting()
        let before = try XCTUnwrap(journal.snapshot().trips.first)
        journal.close()
        var connection: OpaquePointer?
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("trips.sqlite").path, &connection), SQLITE_OK)
        XCTAssertEqual(sqlite3_exec(connection, "UPDATE trips SET start_place='Preserved',end_place=NULL,history_version=1", nil, nil, nil), SQLITE_OK)
        sqlite3_close(connection)
        let repaired = TripJournal(directory: root, preferences: prefs, heartbeat: false)
        let after = try XCTUnwrap(repaired.snapshot().trips.first)
        XCTAssertEqual(after["start_place"] as? String, "Preserved")
        XCTAssertEqual(after["end_place"] as? String, "Captured")
        XCTAssertEqual(after["history_version"] as? Double, 2)
        for key in ["distance", "end", "duration"] { XCTAssertEqual(after[key] as? Double, before[key] as? Double, key) }
        repaired.close()
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("trips.sqlite").path, &connection), SQLITE_OK)
        XCTAssertEqual(sqlite3_exec(connection, "DELETE FROM events; UPDATE trips SET end_place=NULL", nil, nil, nil), SQLITE_OK)
        sqlite3_close(connection)
        let reopened = TripJournal(directory: root, preferences: prefs, heartbeat: false)
        defer { reopened.close() }
        let stable = try XCTUnwrap(reopened.snapshot().trips.first)
        XCTAssertEqual(stable["start_place"] as? String, "Preserved")
        XCTAssertNil(stable["end_place"])
        XCTAssertEqual(stable["history_version"] as? Double, 2)
    }

    func testExplicitStopFreezesMetadataBeforeOdometerEntryAndSurvivesNewFixes() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let id=try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            let at=Date()
            journal.location(fix(49,at:at))
            journal.matchedPlace(at:at,streetName:"Startstraße",cityName:"Karlsruhe",latitude:49,longitude:8,accuracy:3)
            journal.location(fix(49.001,at:at.addingTimeInterval(2)))
            journal.matchedPlace(at:at.addingTimeInterval(2),streetName:"Zielstraße",cityName:"Karlsruhe",latitude:49.001,longitude:8,accuracy:3)
            journal.location(CLLocation(coordinate:.init(latitude:49.001,longitude:8),altitude:0,horizontalAccuracy:3,verticalAccuracy:3,course:0,speed:0,timestamp:at.addingTimeInterval(2.1)))
            let candidate=try XCTUnwrap(journal.stoppedTripSnapshot())
            XCTAssertEqual(candidate.tripID,id) // No fifteen-second wait.
            try journal.endStoppedTrip(id)
            let saved=try XCTUnwrap(journal.snapshot().trips.first)
            XCTAssertEqual(saved["state"] as? String,"ended")
            XCTAssertEqual(saved["start_place"] as? String,"Startstraße, Karlsruhe")
            XCTAssertEqual(saved["end_place"] as? String,"Zielstraße, Karlsruhe")
            XCTAssertEqual(saved["history_version"] as? Double,2)
            XCTAssertNil(saved["odo_end"])
            journal.location(CLLocation(coordinate:.init(latitude:49.01,longitude:8),altitude:0,horizontalAccuracy:3,verticalAccuracy:3,course:0,speed:0,timestamp:Date()))
            journal.lifecycle(false); journal.lifecycle(true)
            _ = journal.snapshot()
            try journal.saveEndedTripOdometer(id,odometer:123456)
            let after=try XCTUnwrap(journal.snapshot().trips.first { $0["id"] as? String == id })
            XCTAssertEqual(after["odo_end"] as? Double,123456)
            for key in ["start","end","distance","duration"] {XCTAssertEqual(saved[key] as? Double,after[key] as? Double,key)}
            for key in ["start_place","end_place"] {XCTAssertEqual(saved[key] as? String,after[key] as? String,key)}
            let exported=try journal.export(id)
            let canonical=try JSONSerialization.jsonObject(with:Data(contentsOf:exported.appendingPathComponent("journal.json"))) as! [String:Any]
            XCTAssertEqual((canonical["trip"] as? [String:Any])?["start_place"] as? String,"Startstraße, Karlsruhe")
            let masked=try journal.export(id,options:.init(masked:true))
            let maskedCanonical=try JSONSerialization.jsonObject(with:Data(contentsOf:masked.appendingPathComponent("journal.json"))) as! [String:Any]
            XCTAssertNil((maskedCanonical["trip"] as? [String:Any])?["start_place"])
            XCTAssertNil((maskedCanonical["trip"] as? [String:Any])?["end_place"])
            XCTAssertThrowsError(try journal.saveEndedTripOdometer(id,odometer:123457))
        }
    }
    func testSavedEndpointMetadataSurvivesReopenWithoutReprojection() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="history-reopen-\(UUID().uuidString)",prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        defer {prefs.removePersistentDomain(forName:suite);try? FileManager.default.removeItem(at:root)}
        let journal=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        journal.setEnabled(true);journal.start()
        let id=try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
        let at=Date()
        journal.location(fix(49,at:at));journal.matchedPlace(at:at,streetName:"Gespeichert",cityName:nil,latitude:49,longitude:8,accuracy:3)
        journal.location(fix(49.001, at: at.addingTimeInterval(2)))
        journal.matchedPlace(at: at.addingTimeInterval(2), streetName: "Gespeichert", cityName: nil, latitude: 49.001, longitude: 8, accuracy: 3)
        journal.stop();_ = journal.snapshot();journal.completeFinalizerForTesting()
        let before=try XCTUnwrap(journal.snapshot().trips.first)
        journal.close()
        // Saved metadata must survive even if old event evidence is unavailable.
        var connection:OpaquePointer?
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("trips.sqlite").path,&connection),SQLITE_OK)
        XCTAssertEqual(sqlite3_exec(connection,"DELETE FROM events",nil,nil,nil),SQLITE_OK)
        sqlite3_close(connection)
        let reopened=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        defer {reopened.close()}
        let after=try XCTUnwrap(reopened.snapshot().trips.first)
        XCTAssertEqual(after["id"] as? String,id)
        XCTAssertEqual(after["start_place"] as? String,"Gespeichert")
        XCTAssertEqual(after["end_place"] as? String,before["end_place"] as? String)
        XCTAssertEqual(after["distance"] as? Double,before["distance"] as? Double)
        XCTAssertTrue(reopened.events(id).isEmpty)
    }
    func testLegacyHistoryIsBackfilledOnceBeforeDisplay() throws {
        let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let suite="history-migrate-\(UUID().uuidString)",prefs=try XCTUnwrap(UserDefaults(suiteName:suite))
        defer {prefs.removePersistentDomain(forName:suite);try? FileManager.default.removeItem(at:root)}
        let journal=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        journal.setEnabled(true);journal.start()
        let id=try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String),at=Date()
        journal.location(fix(49,at:at));journal.matchedPlace(at:at,streetName:"Legacy",cityName:nil,latitude:49,longitude:8,accuracy:3)
        journal.location(fix(49.001, at: at.addingTimeInterval(2)))
        journal.matchedPlace(at: at.addingTimeInterval(2), streetName: "Legacy", cityName: nil, latitude: 49.001, longitude: 8, accuracy: 3)
        journal.stop();_ = journal.snapshot();journal.completeFinalizerForTesting();journal.close()
        var connection:OpaquePointer?
        XCTAssertEqual(sqlite3_open(root.appendingPathComponent("trips.sqlite").path,&connection),SQLITE_OK)
        XCTAssertEqual(sqlite3_exec(connection,"UPDATE trips SET start_place=NULL,end_place=NULL,history_version=0",nil,nil,nil),SQLITE_OK)
        sqlite3_close(connection)
        let reopened=TripJournal(directory:root,preferences:prefs,heartbeat:false)
        defer {reopened.close()}
        let saved=try XCTUnwrap(reopened.snapshot().trips.first)
        XCTAssertEqual(saved["start_place"] as? String,"Legacy")
        XCTAssertEqual(saved["end_place"] as? String,"Legacy")
        XCTAssertEqual(saved["history_version"] as? Double,2)
        XCTAssertEqual(saved["id"] as? String,id)
    }
}

final class TripStopPromptPolicyTests: XCTestCase {
    func testStopDelayContinueRearmFreshnessAndDigits() {
        var policy=TripStopPromptPolicy()
        for t in 0...30 {policy.observe(speed:0,at:Double(t),usable:true,recording:true)}
        XCTAssertFalse(policy.visible(at:30),"Initial parking is not a driven trip")
        policy.observe(speed:10,at:31,usable:true,recording:true)
        for t in 32...46 {policy.observe(speed:0,at:Double(t),usable:true,recording:true)}
        XCTAssertFalse(policy.visible(at:46))
        policy.observe(speed:0,at:47,usable:true,recording:true)
        XCTAssertTrue(policy.visible(at:47));XCTAssertFalse(policy.visible(at:51))
        policy.continueTrip()
        for t in 48...70 {policy.observe(speed:0,at:Double(t),usable:true,recording:true)}
        XCTAssertFalse(policy.visible(at:70))
        policy.observe(speed:4,at:71,usable:true,recording:true)
        for t in 72...87 {policy.observe(speed:0,at:Double(t),usable:true,recording:true)}
        XCTAssertTrue(policy.visible(at:87))
        policy.observe(speed:1,at:88,usable:true,recording:true)
        XCTAssertFalse(policy.visible(at:88))
        XCTAssertEqual(TripOdometer.estimate(last:123450,distance:4405),123454)
        XCTAssertEqual(TripOdometer.estimate(last:nil,distance:4405),0)
        XCTAssertEqual(TripOdometer.estimate(last:999999,distance:9000),999999)
        XCTAssertEqual(TripOdometer.replacingDigit(123456,index:2,digit:9),129456)
    }
}


extension TripJournalTests {
    func testCompactExportKeepsTypedOCRFrameEvidenceAndOnlyOmitsVerboseMessages() throws {
        try withJournal { journal, _ in
            journal.setEnabled(true); journal.start()
            let at = Date(), id = try XCTUnwrap(journal.snapshot().trips.first?["id"] as? String)
            journal.location(fix(49, at: at))
            journal.tsr(String(repeating: "diagnostic only ", count: 400), at: at)
            journal.tsrEvent(["event": "frame", "frame_id": "frame-1", "supplementary_ocr_only": true,
                              "candidate": ["assemblyId": "sign-1", "restrictions": ["22-6h"], "rawClassId": "DE:274-30"],
                              "message": "This message has structured evidence and must stay"], at: at)
            journal.signEvent(["class_code": "DE:274-30", "source": "camera", "frame_id": "frame-1", "ocr": "22-6h"], at: at)
            let original = journal.events(id).map(JournalEvent.init)
            let root = try journal.export(id)
            let output = try JSONSerialization.jsonObject(with: Data(contentsOf: root.appendingPathComponent("journal.json"))) as! [String: Any]
            let events = output["events"] as! [[String: Any]], expected = original.filter { !$0.isVerboseDiagnosticMessage }
            XCTAssertEqual(events.map { $0["seq"] as! Int }, expected.map(\.id))
            XCTAssertEqual(output["export_profile"] as? String, "compact")
            XCTAssertEqual(output["omitted_verbose_message_events"] as? Int, 1)
            XCTAssertEqual((output["privacy"] as? [String: Any])?["raw_logs_included"] as? Bool, false)
            let frame = try XCTUnwrap(events.first { ($0["payload"] as? [String: Any])?["frame_id"] as? String == "frame-1" })
            XCTAssertEqual((frame["payload"] as? [String: Any])?["supplementary_ocr_only"] as? Bool, true)
            let camera = try XCTUnwrap(events.first { $0["kind"] as? String == "sign" })
            XCTAssertEqual((camera["payload"] as? [String: Any])?["ocr"] as? String, "22-6h")
            for name in ["gps", "tsr", "gap", "sign"] {
                for ext in ["json", "ndjson", "csv"] { XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(name + "." + ext).path)) }
            }
            for name in ["sign_events.ndjson", "media.ndjson"] { XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent(name).path)) }
            let diagnosticRoot = try journal.export(id, options: .init(includeRawLogs: true))
            let diagnostic = try JSONSerialization.jsonObject(with: Data(contentsOf: diagnosticRoot.appendingPathComponent("journal.json"))) as! [String: Any]
            XCTAssertEqual((diagnostic["events"] as? [[String: Any]])?.map { $0["seq"] as! Int }, original.map(\.id))
            XCTAssertEqual(diagnostic["export_profile"] as? String, "diagnostic")
            XCTAssertEqual(diagnostic["omitted_verbose_message_events"] as? Int, 0)
            XCTAssertEqual(journal.events(id).map(JournalEvent.init).map(\.id), original.map(\.id))
        }
    }
}
