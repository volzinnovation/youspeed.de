import Foundation

/// Serial, duplicate-free requests. Closing settings does not discard the queue.
struct BundleDownloadQueue<Entry: Identifiable> where Entry.ID == String {
    private(set) var entries: [Entry] = []
    var ids: [String] { entries.map(\.id) }

    mutating func enqueue(_ entry: Entry, activeID: String?) {
        guard entry.id != activeID, !ids.contains(entry.id) else { return }
        entries.append(entry)
    }

    mutating func remove(id: String) { entries.removeAll { $0.id == id } }

    mutating func next(isBusy: Bool) -> Entry? {
        guard !isBusy, !entries.isEmpty else { return nil }
        return entries.removeFirst()
    }
}
