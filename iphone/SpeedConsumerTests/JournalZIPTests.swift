import XCTest
import Foundation
import zlib
@testable import SpeedConsumer

final class JournalZIPTests: XCTestCase {
    private struct Decoded { let data: Data; let method: Int; let compressedSize: Int }
    private enum ParseFailure: Error { case invalidArchive, inflate(Int32) }

    func testTextIsDeflatedWhileSelectedImageAndVideoBytesRemainStoredAndLossless() throws {
        try fixture { root, input, output in
            let journal = Data("{\"schema_version\":1,\"trip\":{\"id\":\"synthetic\"}}".utf8)
            let lines = Data(String(repeating: "{\"kind\":\"gps\",\"latitude\":48.8,\"longitude\":8.5,\"speed\":12.4}\n", count: 30_000).utf8)
            let gpx = Data(("<gpx><trk><trkseg>" + String(repeating: "<trkpt lat=\"48.8\" lon=\"8.5\"/>", count: 10_000) + "</trkseg></trk></gpx>").utf8)
            let image = Data((0..<(1024 * 1024)).map { UInt8(truncatingIfNeeded: $0 * 31) })
            let video = Data((0..<(1024 * 1024 + 13)).map { UInt8(truncatingIfNeeded: $0 * 17) })
            let expected = ["journal.json": journal, "gps.ndjson": lines, "track.gpx": gpx, "media/ä-photo.jpg": image, "media/recording.mp4": video]
            for (name, bytes) in expected { try save(bytes, as: name, in: input) }
            try JournalZIP.write(directory: input, to: output)
            let decoded = try decode(Data(contentsOf: output))
            XCTAssertEqual(Set(decoded.keys), Set(expected.keys))
            for (name, bytes) in expected { XCTAssertEqual(decoded[name]?.data, bytes, name) }
            XCTAssertEqual(decoded["journal.json"]?.method, 8)
            XCTAssertEqual(decoded["gps.ndjson"]?.method, 8)
            XCTAssertEqual(decoded["track.gpx"]?.method, 8)
            XCTAssertLessThan(try XCTUnwrap(decoded["gps.ndjson"]).compressedSize, lines.count / 10)
            XCTAssertEqual(decoded["media/ä-photo.jpg"]?.method, 0)
            XCTAssertEqual(decoded["media/ä-photo.jpg"]?.compressedSize, image.count)
            XCTAssertEqual(decoded["media/recording.mp4"]?.method, 0)
            XCTAssertEqual(decoded["media/recording.mp4"]?.compressedSize, video.count)
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: root.path).filter { $0.hasSuffix(".partial") }, [])
        }
    }

    func testEmptyTextAndMediaFilesHaveValidSizesAndCRC() throws {
        try fixture { _, input, output in
            try save(Data(), as: "empty.json", in: input); try save(Data(), as: "media/empty.png", in: input)
            try JournalZIP.write(directory: input, to: output)
            let decoded = try decode(Data(contentsOf: output))
            XCTAssertEqual(decoded["empty.json"]?.data, Data()); XCTAssertEqual(decoded["empty.json"]?.method, 8)
            XCTAssertEqual(decoded["media/empty.png"]?.data, Data()); XCTAssertEqual(decoded["media/empty.png"]?.method, 0)
        }
    }

    func testPartialFailureDoesNotReplaceAnExistingArchiveOrLeaveScratchFiles() throws {
        try fixture { root, input, output in
            let old = Data("previous successful export".utf8); try old.write(to: output)
            try save(Data(String(repeating: "some trip metadata\n", count: 10_000).utf8), as: "journal.json", in: input)
            XCTAssertThrowsError(try JournalZIP.write(directory: input, to: output, maximumArchiveSize: 64)) { error in
                guard case JournalZIP.Failure.zip32Limit = error else { return XCTFail("Unexpected error: \(error)") }
            }
            XCTAssertEqual(try Data(contentsOf: output), old)
            XCTAssertFalse(try FileManager.default.contentsOfDirectory(atPath: root.path).contains { $0.hasSuffix(".partial") })
        }
    }

    func testSuccessfulExportReplacesAnExistingArchive() throws {
        try fixture { _, input, output in
            try Data("old".utf8).write(to: output)
            let content = Data("{\"trip\":\"new\"}".utf8); try save(content, as: "journal.json", in: input)
            try JournalZIP.write(directory: input, to: output)
            XCTAssertEqual(try decode(Data(contentsOf: output))["journal.json"]?.data, content)
        }
    }

    func testSymlinksAndDestinationInsideSourceAreRejected() throws {
        try fixture { root, input, output in
            let elsewhere = root.appendingPathComponent("outside.json"); try Data("outside".utf8).write(to: elsewhere)
            try FileManager.default.createSymbolicLink(at: input.appendingPathComponent("journal.json"), withDestinationURL: elsewhere)
            XCTAssertThrowsError(try JournalZIP.write(directory: input, to: output))
            XCTAssertFalse(FileManager.default.fileExists(atPath: output.path))
            try FileManager.default.removeItem(at: input.appendingPathComponent("journal.json"))
            try save(Data("{}".utf8), as: "journal.json", in: input)
            let destination = input.appendingPathComponent("self.zip")
            let oldRoot = input.standardizedFileURL.resolvingSymlinksInPath()
            let oldTarget = destination.standardizedFileURL.resolvingSymlinksInPath()
            print("ZIP_DESTINATION_REGRESSION source=\(oldRoot.path) target=\(oldTarget.path) source_components=\(oldRoot.pathComponents) target_components=\(oldTarget.pathComponents)")
            assertInvalidDestination(input, destination)
            XCTAssertFalse(FileManager.default.fileExists(atPath: destination.path))
        }
    }

    func testSourceAndNestedDestinationsAreRejectedWithoutChangingExistingFiles() throws {
        try fixture { _, input, _ in
            let original = Data("original source bytes".utf8)
            let existing = input.appendingPathComponent("journal.json")
            try original.write(to: existing)
            let nested = input.appendingPathComponent("nested", isDirectory: true)
            try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
            assertInvalidDestination(input, input)
            assertInvalidDestination(input, existing)
            assertInvalidDestination(input, nested.appendingPathComponent("export.zip"))
            assertInvalidDestination(input.resolvingSymlinksInPath(), input.appendingPathComponent("fresh.zip"))
            assertInvalidDestination(input, input.resolvingSymlinksInPath().appendingPathComponent("fresh.zip"))
            XCTAssertEqual(try Data(contentsOf: existing), original)
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: input.path).sorted(), ["journal.json", "nested"])
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: nested.path), [])
        }
    }

    func testDestinationsThroughSymlinksIntoSourceAreRejected() throws {
        try fixture { root, input, _ in
            let original = Data("source must survive rejection".utf8)
            let existing = input.appendingPathComponent("journal.json")
            try original.write(to: existing)
            let directoryAlias = root.appendingPathComponent("source-alias", isDirectory: true)
            try FileManager.default.createSymbolicLink(at: directoryAlias, withDestinationURL: input)
            let fileAlias = root.appendingPathComponent("existing.zip")
            try FileManager.default.createSymbolicLink(at: fileAlias, withDestinationURL: existing)
            assertInvalidDestination(input, directoryAlias.appendingPathComponent("fresh.zip"))
            assertInvalidDestination(directoryAlias, input.appendingPathComponent("fresh.zip"))
            assertInvalidDestination(input, fileAlias)
            XCTAssertEqual(try Data(contentsOf: existing), original)
            XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: input.path), ["journal.json"])
        }
    }

    func testSimilarlyNamedSiblingAndItsDirectoryAliasRemainValidDestinations() throws {
        try fixture { root, input, _ in
            let original = Data("{\"trip\":\"sibling export\"}".utf8)
            try save(original, as: "journal.json", in: input)
            let sibling = root.appendingPathComponent("source-other", isDirectory: true)
            try FileManager.default.createDirectory(at: sibling, withIntermediateDirectories: true)
            let alias = root.appendingPathComponent("sibling-alias", isDirectory: true)
            try FileManager.default.createSymbolicLink(at: alias, withDestinationURL: sibling)
            for (index, directory) in [sibling, alias].enumerated() {
                let destination = directory.appendingPathComponent("trip-\(index).zip")
                try JournalZIP.write(directory: input, to: destination)
                XCTAssertEqual(try decode(Data(contentsOf: destination))["journal.json"]?.data, original)
            }
            XCTAssertEqual(try Data(contentsOf: input.appendingPathComponent("journal.json")), original)
        }
    }

    private func assertInvalidDestination(_ input: URL, _ destination: URL, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertThrowsError(try JournalZIP.write(directory: input, to: destination), file: file, line: line) { error in
            guard case JournalZIP.Failure.invalidDestination = error else {
                return XCTFail("Expected invalidDestination, received \(error)", file: file, line: line)
            }
        }
    }

    private func fixture(_ run: (URL, URL, URL) throws -> Void) throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("journal-zip-tests-\(UUID().uuidString)", isDirectory: true)
        let input = root.appendingPathComponent("source", isDirectory: true)
        try FileManager.default.createDirectory(at: input, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try run(root, input, root.appendingPathComponent("trip.zip"))
    }

    private func save(_ data: Data, as name: String, in root: URL) throws {
        let url = root.appendingPathComponent(name)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: url)
    }

    /// Decode the public ZIP structure independently and verify raw zlib output + CRC.
    private func decode(_ zip: Data) throws -> [String: Decoded] {
        func word(_ at: Int) throws -> Int {
            guard at >= 0, at + 2 <= zip.count else { throw ParseFailure.invalidArchive }
            return Int(zip[at]) | Int(zip[at + 1]) << 8
        }
        func dword(_ at: Int) throws -> Int {
            guard at >= 0, at + 4 <= zip.count else { throw ParseFailure.invalidArchive }
            return Int(zip[at]) | Int(zip[at + 1]) << 8 | Int(zip[at + 2]) << 16 | Int(zip[at + 3]) << 24
        }
        let end = zip.count - 22
        guard try dword(end) == 0x06054b50 else { throw ParseFailure.invalidArchive }
        let count = try word(end + 10), start = try dword(end + 16), size = try dword(end + 12)
        guard start + size == end else { throw ParseFailure.invalidArchive }
        var at = start, result = [String: Decoded]()
        for _ in 0..<count {
            guard try dword(at) == 0x02014b50 else { throw ParseFailure.invalidArchive }
            let flags = try word(at + 8), method = try word(at + 10), crc = try dword(at + 16), compressed = try dword(at + 20), uncompressed = try dword(at + 24)
            let nameLength = try word(at + 28), extra = try word(at + 30), comment = try word(at + 32), local = try dword(at + 42)
            guard at + 46 + nameLength + extra + comment <= end,
                  let name = String(data: zip.subdata(in: at + 46..<at + 46 + nameLength), encoding: .utf8), result[name] == nil else { throw ParseFailure.invalidArchive }
            guard flags == 0x0800, try dword(local) == 0x04034b50, try word(local + 6) == flags, try word(local + 8) == method,
                  try dword(local + 14) == crc, try dword(local + 18) == compressed, try dword(local + 22) == uncompressed else { throw ParseFailure.invalidArchive }
            let localNameLength = try word(local + 26), localExtra = try word(local + 28), body = local + 30 + localNameLength + localExtra
            guard localNameLength == nameLength, zip.subdata(in: local + 30..<local + 30 + localNameLength) == Data(name.utf8), body + compressed <= start else { throw ParseFailure.invalidArchive }
            let encoded = zip.subdata(in: body..<body + compressed)
            let decoded: Data
            if method == 0 { decoded = encoded }
            else if method == 8 { decoded = try inflateRaw(encoded, expectedSize: uncompressed) }
            else { throw ParseFailure.invalidArchive }
            XCTAssertEqual(decoded.count, uncompressed, name)
            let actualCRC = decoded.withUnsafeBytes { zlib.crc32(0, $0.bindMemory(to: UInt8.self).baseAddress, uInt($0.count)) }
            XCTAssertEqual(UInt32(truncatingIfNeeded: actualCRC), UInt32(crc), name)
            result[name] = Decoded(data: decoded, method: method, compressedSize: compressed)
            at += 46 + nameLength + extra + comment
        }
        XCTAssertEqual(at, end)
        return result
    }

    private func inflateRaw(_ encoded: Data, expectedSize: Int) throws -> Data {
        var state = z_stream()
        let initialized = inflateInit2_(&state, -MAX_WBITS, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size))
        guard initialized == Z_OK else { throw ParseFailure.inflate(initialized) }
        defer { inflateEnd(&state) }
        var result = Data(), buffer = [UInt8](repeating: 0, count: 64 * 1024)
        try encoded.withUnsafeBytes { bytes in
            state.next_in = UnsafeMutablePointer(mutating: bytes.bindMemory(to: UInt8.self).baseAddress); state.avail_in = uInt(bytes.count)
            var status = Z_OK
            repeat {
                let capacity = buffer.count
                status = buffer.withUnsafeMutableBytes { destination in
                    state.next_out = destination.bindMemory(to: UInt8.self).baseAddress; state.avail_out = uInt(capacity)
                    return inflate(&state, Z_NO_FLUSH)
                }
                guard status == Z_OK || status == Z_STREAM_END else { throw ParseFailure.inflate(status) }
                result.append(contentsOf: buffer.prefix(capacity - Int(state.avail_out)))
                guard result.count <= expectedSize else { throw ParseFailure.invalidArchive }
            } while status != Z_STREAM_END
            XCTAssertEqual(state.avail_in, 0)
        }
        return result
    }
}
