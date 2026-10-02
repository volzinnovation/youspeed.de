import XCTest
@testable import SpeedConsumer

@MainActor
final class LookupSchedulingTests: XCTestCase {
    func testBlockedLookupRunsOnlyNewestPendingFixAndNeverPublishesSupersededResult() async {
        let worker = LatestPendingLookupWorker()
        let blocked = Gate()
        let startedFirst = expectation(description: "First lookup is running")
        var started: [Int] = []
        var published: [Int] = []
        worker.submit { token in
            started.append(0)
            startedFirst.fulfill()
            await blocked.wait()
            if token.isCurrent { published.append(0) }
        }
        await fulfillment(of: [startedFirst], timeout: 2)
        for fix in 1...100 {
            worker.submit { token in
                started.append(fix)
                if token.isCurrent { published.append(fix) }
            }
        }
        XCTAssertEqual(started, [0])
        blocked.open()
        await worker.waitUntilIdle()
        XCTAssertEqual(started, [0, 100])
        XCTAssertEqual(published, [100])
    }

    func testLifecycleCancellationDropsPendingAndCannotPublishRunningPreviousSession() async {
        let worker = LatestPendingLookupWorker()
        let blocked = Gate()
        let startedFirst = expectation(description: "Previous session lookup is running")
        var started: [Int] = []
        var published: [Int] = []
        worker.submit { token in
            started.append(0)
            startedFirst.fulfill()
            await blocked.wait()
            if token.isCurrent { published.append(0) }
        }
        await fulfillment(of: [startedFirst], timeout: 2)
        worker.submit { _ in XCTFail("Cancelled pending fix ran") }
        worker.cancel()
        worker.submit { token in
            started.append(2)
            if token.isCurrent { published.append(2) }
        }
        XCTAssertEqual(started, [0], "A new session must wait for the prior SQLite operation to finish")
        blocked.open()
        await worker.waitUntilIdle()
        XCTAssertEqual(started, [0, 2])
        XCTAssertEqual(published, [2])
        worker.submit { token in
            if token.isCurrent { published.append(3) }
        }
        await worker.waitUntilIdle()
        XCTAssertEqual(published, [2, 3])
    }

    func testSettingsPauseDropsPendingAndResumesOnlyOnFreshFix() async {
        let worker = LatestPendingLookupWorker()
        let blocked = Gate()
        let startedFirst = expectation(description: "Lookup is running when Settings opens")
        var started: [Int] = []
        var published: [Int] = []
        worker.submit { token in
            started.append(0)
            startedFirst.fulfill()
            await blocked.wait()
            if token.isCurrent { published.append(0) }
        }
        await fulfillment(of: [startedFirst], timeout: 2)
        worker.submit { _ in XCTFail("Pending pre-Settings fix ran") }
        worker.setPaused(true)
        worker.setPaused(true) // Duplicate presentation notifications are harmless.
        XCTAssertTrue(worker.isPaused)
        for _ in 1...100 {
            worker.submit { _ in XCTFail("A fix received in Settings was queued") }
        }
        XCTAssertEqual(started, [0])

        worker.setPaused(false)
        XCTAssertFalse(worker.isPaused)
        blocked.open()
        await worker.waitUntilIdle()
        XCTAssertEqual(started, [0], "Closing Settings does not replay a paused fix")
        XCTAssertEqual(published, [], "The pre-Settings result stays invalid after closing")

        worker.submit { token in
            started.append(101)
            if token.isCurrent { published.append(101) }
        }
        await worker.waitUntilIdle()
        XCTAssertEqual(started, [0, 101])
        XCTAssertEqual(published, [101])
    }

    func testClosingSettingsWaitsForAllBundleRemovalsIncludingFailure() async {
        enum RemovalError: Error { case bootstrapFailed }
        let worker = LatestPendingLookupWorker()
        var pause = MapLookupPauseState()
        let firstBlocked = Gate()
        let secondBlocked = Gate()
        let removalsStarted = expectation(description: "Both removals are waiting for completion")
        removalsStarted.expectedFulfillmentCount = 2
        pause.settingsPresented = true
        worker.setPaused(pause.isPaused)

        // Admission is paused before either asynchronous removal is launched.
        pause.beginBundleRemoval()
        let first = Task { @MainActor in
            defer {
                pause.finishBundleRemoval()
                worker.setPaused(pause.isPaused)
            }
            removalsStarted.fulfill()
            await firstBlocked.wait()
            throw RemovalError.bootstrapFailed
        }
        pause.beginBundleRemoval()
        let second = Task { @MainActor in
            defer {
                pause.finishBundleRemoval()
                worker.setPaused(pause.isPaused)
            }
            removalsStarted.fulfill()
            await secondBlocked.wait()
        }
        await fulfillment(of: [removalsStarted], timeout: 2)
        pause.settingsPresented = false
        worker.setPaused(pause.isPaused)
        worker.submit { _ in XCTFail("Closing Settings resumed during a blocked removal") }

        firstBlocked.open()
        do {
            try await first.value
            XCTFail("Expected bootstrap failure")
        } catch { }
        XCTAssertEqual(pause.pendingBundleRemovals, 1)
        XCTAssertTrue(worker.isPaused)
        worker.submit { _ in XCTFail("A failed removal resumed the other active removal") }

        secondBlocked.open()
        await second.value
        XCTAssertEqual(pause.pendingBundleRemovals, 0)
        XCTAssertFalse(worker.isPaused)
        var published = false
        worker.submit { token in published = token.isCurrent }
        await worker.waitUntilIdle()
        XCTAssertTrue(published, "The next fresh fix resumes once every removal settles")
    }

    @MainActor private final class Gate {
        private var continuation: CheckedContinuation<Void, Never>?
        func wait() async { await withCheckedContinuation { continuation = $0 } }
        func open() { continuation?.resume(); continuation = nil }
    }
}
