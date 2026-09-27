import Foundation

/// Settings may close before the asynchronous bundle work it started finishes.
struct MapLookupPauseState {
    var settingsPresented = false
    private(set) var pendingBundleRemovals = 0
    var isPaused: Bool { settingsPresented || pendingBundleRemovals > 0 }

    mutating func beginBundleRemoval() { pendingBundleRemovals += 1 }
    mutating func finishBundleRemoval() {
        precondition(pendingBundleRemovals > 0)
        pendingBundleRemovals -= 1
    }
}

/// GPS map fixes are replaceable. Finish one operation, then run only the most
/// recent pending fix; location recording and recognition events stay upstream.
@MainActor
final class LatestPendingLookupWorker {
    struct Token: Sendable {
        fileprivate weak var owner: LatestPendingLookupWorker?
        fileprivate let revision: UInt64
        @MainActor var isCurrent: Bool { owner?.revision == revision }
    }

    private struct Pending {
        let token: Token
        let operation: @MainActor (Token) async -> Void
    }

    private var revision: UInt64 = 0
    private var pending: Pending?
    private var task: Task<Void, Never>?
    private(set) var isPaused = false

    func submit(_ operation: @escaping @MainActor (Token) async -> Void) {
        guard !isPaused else { return }
        revision &+= 1
        pending = Pending(token: Token(owner: self, revision: revision), operation: operation)
        guard task == nil else { return }
        task = Task { [weak self] in
            guard let self else { return }
            await self.drain()
        }
    }

    func cancel() {
        revision &+= 1
        pending = nil
        // A synchronous SQLite query cannot be cancelled cooperatively. Keep
        // its slot until it returns, while invalidating its publication token.
    }

    func setPaused(_ paused: Bool) {
        guard isPaused != paused else { return }
        isPaused = paused
        if paused { cancel() }
        // Resuming waits for a fresh fix; work captured in Settings is not queued.
    }

    func waitUntilIdle() async { await task?.value }

    private func drain() async {
        while let next = pending {
            pending = nil
            await next.operation(next.token)
        }
        task = nil
    }
}
