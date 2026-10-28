import Foundation
import zlib

/// Streaming ZIP32 export. Text is raw DEFLATE; already-compressed media keeps its bytes.
/// Local headers are patched after each stream so STORE entries work with streaming ZIP readers too.
enum JournalZIP {
    enum Failure: Error, LocalizedError {
        case invalidDirectory, invalidDestination, unsafeEntry, tooManyEntries, zip32Limit
        case sourceChanged, compression(Int32), cannotCreateArchive
        var errorDescription: String? {
            switch self {
            case .invalidDirectory: return "The trip export directory is unavailable."
            case .invalidDestination: return "The ZIP destination must be outside the export directory."
            case .unsafeEntry: return "The export contains an unsupported file or path."
            case .tooManyEntries: return "The export has too many files for a ZIP32 archive."
            case .zip32Limit: return "The export exceeds the ZIP32 size limit."
            case .sourceChanged: return "An export file changed while the ZIP was being written."
            case .compression(let code): return "ZIP compression failed (\(code))."
            case .cannotCreateArchive: return "The ZIP archive could not be created."
            }
        }
    }

    private static let chunkSize = 64 * 1024
    private static let compressibleExtensions: Set<String> = ["json", "ndjson", "jsonl", "gpx", "geojson", "csv", "txt", "log", "xml"]
    private struct Source { let url: URL; let name: Data; let size: UInt64; let method: UInt16 }
    private struct Entry { let source: Source; let offset: UInt32; let crc: UInt32; let compressedSize: UInt32; let uncompressedSize: UInt32 }
    private struct Header {
        var data = Data()
        mutating func u16(_ value: UInt16) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
        mutating func u32(_ value: UInt32) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
    }
    private final class Output {
        let handle: FileHandle
        let maximum: UInt64
        var offset: UInt64 = 0
        init(_ handle: FileHandle, maximum: UInt64) { self.handle = handle; self.maximum = maximum }
        func write(_ data: Data) throws {
            let count = UInt64(data.count)
            guard count <= maximum, offset <= maximum - count else { throw Failure.zip32Limit }
            try handle.write(contentsOf: data); offset += count
        }
        func patch(at offset: UInt64, data: Data) throws {
            try handle.seek(toOffset: offset); try handle.write(contentsOf: data)
            try handle.seek(toOffset: self.offset)
        }
    }

    static func write(directory: URL, to destination: URL, maximumArchiveSize: UInt64 = UInt64(UInt32.max)) throws {
        let manager = FileManager.default
        let root = directory.standardizedFileURL.resolvingSymlinksInPath()
        var isDirectory: ObjCBool = false
        guard manager.fileExists(atPath: root.path, isDirectory: &isDirectory), isDirectory.boolValue else { throw Failure.invalidDirectory }
        let requestedTarget = destination.standardizedFileURL
        // On iPhone, a missing leaf and an existing directory can resolve /var and
        // /private/var differently. Resolve the parent before adding a new filename.
        let target = manager.fileExists(atPath: requestedTarget.path)
            ? requestedTarget.resolvingSymlinksInPath()
            : requestedTarget.deletingLastPathComponent().resolvingSymlinksInPath()
                .appendingPathComponent(requestedTarget.lastPathComponent)
        guard !target.pathComponents.starts(with: root.pathComponents) else { throw Failure.invalidDestination }
        let sources = try list(root)
        guard sources.count < Int(UInt16.max) else { throw Failure.tooManyEntries }
        let temporary = target.deletingLastPathComponent().appendingPathComponent(".\(target.lastPathComponent).\(UUID().uuidString).partial")
        guard manager.createFile(atPath: temporary.path, contents: nil, attributes: [.posixPermissions: 0o600]) else { throw Failure.cannotCreateArchive }
        var completed = false
        defer { if !completed { try? manager.removeItem(at: temporary) } }
        let handle = try FileHandle(forWritingTo: temporary)
        var closed = false
        defer { if !closed { try? handle.close() } }
        let output = Output(handle, maximum: min(maximumArchiveSize, UInt64(UInt32.max)))
        var entries = [Entry]()
        for source in sources {
            guard output.offset <= UInt64(UInt32.max) else { throw Failure.zip32Limit }
            let start = UInt32(output.offset)
            var header = Header()
            header.u32(0x04034b50); header.u16(20); header.u16(0x0800); header.u16(source.method)
            header.u16(0); header.u16(33) // Valid DOS timestamp: 1980-01-01.
            header.u32(0); header.u32(0); header.u32(0); header.u16(UInt16(source.name.count)); header.u16(0)
            try output.write(header.data); try output.write(source.name)
            let bodyStart = output.offset
            let result = try stream(source, into: output)
            let compressed = output.offset - bodyStart
            guard result.bytes == source.size, compressed <= UInt64(UInt32.max) else { throw Failure.sourceChanged }
            let entry = Entry(source: source, offset: start, crc: result.crc, compressedSize: UInt32(compressed), uncompressedSize: UInt32(result.bytes))
            var patch = Header(); patch.u32(entry.crc); patch.u32(entry.compressedSize); patch.u32(entry.uncompressedSize)
            try output.patch(at: UInt64(start) + 14, data: patch.data)
            entries.append(entry)
        }
        guard output.offset <= UInt64(UInt32.max) else { throw Failure.zip32Limit }
        let centralStart = UInt32(output.offset)
        for entry in entries {
            var header = Header()
            header.u32(0x02014b50); header.u16(20); header.u16(20); header.u16(0x0800); header.u16(entry.source.method)
            header.u16(0); header.u16(33); header.u32(entry.crc); header.u32(entry.compressedSize); header.u32(entry.uncompressedSize)
            header.u16(UInt16(entry.source.name.count)); header.u16(0); header.u16(0); header.u16(0); header.u16(0); header.u32(0); header.u32(entry.offset)
            try output.write(header.data); try output.write(entry.source.name)
        }
        let centralSize = output.offset - UInt64(centralStart)
        guard centralSize <= UInt64(UInt32.max) else { throw Failure.zip32Limit }
        var end = Header(); end.u32(0x06054b50); end.u16(0); end.u16(0); end.u16(UInt16(entries.count)); end.u16(UInt16(entries.count))
        end.u32(UInt32(centralSize)); end.u32(centralStart); end.u16(0)
        try output.write(end.data)
        try handle.synchronize(); try handle.close(); closed = true
        if manager.fileExists(atPath: target.path) { _ = try manager.replaceItemAt(target, withItemAt: temporary) }
        else { try manager.moveItem(at: temporary, to: target) }
        completed = true
    }

    private static func list(_ root: URL) throws -> [Source] {
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .isDirectoryKey, .isSymbolicLinkKey, .fileSizeKey]
        var enumerationError: Error?
        guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: Array(keys), errorHandler: { _, error in enumerationError = error; return false }) else { throw Failure.invalidDirectory }
        var sources = [Source]()
        for case let url as URL in enumerator {
            let values = try url.resourceValues(forKeys: keys)
            guard values.isSymbolicLink != true else { throw Failure.unsafeEntry }
            if values.isDirectory == true { continue }
            guard values.isRegularFile == true, let size = values.fileSize, size >= 0 else { throw Failure.unsafeEntry }
            guard UInt64(size) <= UInt64(UInt32.max) else { throw Failure.zip32Limit }
            let entryPath = url.standardizedFileURL.resolvingSymlinksInPath().path
            guard entryPath.hasPrefix(root.path + "/") else { throw Failure.unsafeEntry }
            let name = String(entryPath.dropFirst(root.path.count + 1))
            guard !name.isEmpty, !name.contains("\\"), !name.split(separator: "/", omittingEmptySubsequences: false).contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }), let encoded = name.data(using: .utf8), encoded.count <= Int(UInt16.max) else { throw Failure.unsafeEntry }
            sources.append(Source(url: url, name: encoded, size: UInt64(size), method: compressibleExtensions.contains(url.pathExtension.lowercased()) ? 8 : 0))
            if sources.count >= Int(UInt16.max) { throw Failure.tooManyEntries }
        }
        if let error = enumerationError { throw error }
        return sources.sorted { $0.name.lexicographicallyPrecedes($1.name) }
    }

    private static func stream(_ source: Source, into output: Output) throws -> (crc: UInt32, bytes: UInt64) {
        let input = try FileHandle(forReadingFrom: source.url)
        defer { try? input.close() }
        var crc = zlib.crc32(0, nil, 0), count: UInt64 = 0
        var compressor = z_stream()
        if source.method == 8 {
            let status = deflateInit2_(&compressor, Z_DEFAULT_COMPRESSION, Z_DEFLATED, -MAX_WBITS, MAX_MEM_LEVEL, Z_DEFAULT_STRATEGY, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size))
            guard status == Z_OK else { throw Failure.compression(status) }
        }
        defer { if source.method == 8 { deflateEnd(&compressor) } }
        var buffer = [UInt8](repeating: 0, count: chunkSize)
        func drain(_ flush: Int32) throws -> Int32 {
            let capacity = buffer.count
            let status = buffer.withUnsafeMutableBytes { bytes -> Int32 in
                compressor.next_out = bytes.bindMemory(to: UInt8.self).baseAddress
                compressor.avail_out = uInt(capacity)
                return deflate(&compressor, flush)
            }
            guard status == Z_OK || status == Z_STREAM_END else { throw Failure.compression(status) }
            let produced = capacity - Int(compressor.avail_out)
            if produced > 0 { try output.write(Data(buffer.prefix(produced))) }
            return status
        }
        while let chunk = try input.read(upToCount: chunkSize), !chunk.isEmpty {
            count += UInt64(chunk.count)
            guard count <= source.size else { throw Failure.sourceChanged }
            try chunk.withUnsafeBytes { bytes in
                let pointer = bytes.bindMemory(to: UInt8.self).baseAddress
                crc = zlib.crc32(crc, pointer, uInt(bytes.count))
                if source.method == 0 { try output.write(chunk) }
                else {
                    compressor.next_in = UnsafeMutablePointer(mutating: pointer); compressor.avail_in = uInt(bytes.count)
                    while compressor.avail_in > 0 { _ = try drain(Z_NO_FLUSH) }
                }
            }
        }
        guard count == source.size else { throw Failure.sourceChanged }
        if source.method == 8 {
            compressor.next_in = nil; compressor.avail_in = 0
            while try drain(Z_FINISH) != Z_STREAM_END { }
        }
        return (UInt32(truncatingIfNeeded: crc), count)
    }
}
