import Foundation
import SQLite3

enum AssetStore {
    static func applicationSupportDirectory() throws -> URL {
        let fm = FileManager.default
        let base = try fm.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appendingPathComponent("SpeedDBBench", isDirectory: true)
    }

    static func prepareBundledDatabase(
        resourceName: String,
        extension ext: String = "sqlite",
        targetFileName: String
    ) throws -> URL {
        let fm = FileManager.default
        let dir = try applicationSupportDirectory()
        if !fm.fileExists(atPath: dir.path) {
            try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }

        let dst = dir.appendingPathComponent(targetFileName)
        if !fm.fileExists(atPath: dst.path) {
            if let src = Bundle.main.url(forResource: resourceName, withExtension: ext) {
                try fm.copyItem(at: src, to: dst)
            } else {
                try createSyntheticBenchmarkDB(at: dst)
            }
        }
        return dst
    }

    static func downloadDatabase(from remoteURL: URL, targetFileName: String) async throws -> URL {
        let (tempURL, response) = try await URLSession.shared.download(from: remoteURL)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            throw BenchmarkError.ioError("Download failed with unexpected status code")
        }

        let fm = FileManager.default
        let dir = try applicationSupportDirectory()
        if !fm.fileExists(atPath: dir.path) {
            try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }

        let dst = dir.appendingPathComponent(targetFileName)
        let bak = dir.appendingPathComponent(targetFileName + ".bak")
        if fm.fileExists(atPath: bak.path) {
            try fm.removeItem(at: bak)
        }
        if fm.fileExists(atPath: dst.path) {
            try fm.moveItem(at: dst, to: bak)
        }

        do {
            try fm.moveItem(at: tempURL, to: dst)
            if fm.fileExists(atPath: bak.path) {
                try fm.removeItem(at: bak)
            }
            return dst
        } catch {
            if fm.fileExists(atPath: bak.path) {
                try? fm.moveItem(at: bak, to: dst)
            }
            throw error
        }
    }

    private static func createSyntheticBenchmarkDB(at url: URL) throws {
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK, let db else {
            throw BenchmarkError.sqliteError("sqlite open failed for synthetic DB")
        }
        defer { sqlite3_close(db) }

        let sql = """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata(key, value) VALUES('tile_size_m', '4096');
        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        CREATE TABLE way_tile (
          row_id INTEGER NOT NULL,
          tile_x INTEGER NOT NULL,
          tile_y INTEGER NOT NULL
        );
        """
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            let msg = String(cString: sqlite3_errmsg(db))
            throw BenchmarkError.sqliteError("sqlite schema init failed: \(msg)")
        }

        let berlinLat = 52.5200
        let berlinLon = 13.4050
        let (tileX, tileY) = tileForLonLat(lon: berlinLon, lat: berlinLat, tileSizeM: 4096.0)
        let minLon = berlinLon - 0.01
        let maxLon = berlinLon + 0.01
        let minLat = berlinLat - 0.01
        let maxLat = berlinLat + 0.01

        let wayInsert = """
        INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
        VALUES(1, \(minLon), \(maxLon), \(minLat), \(maxLat));
        """
        guard sqlite3_exec(db, wayInsert, nil, nil, nil) == SQLITE_OK else {
            let msg = String(cString: sqlite3_errmsg(db))
            throw BenchmarkError.sqliteError("sqlite ways_rtree insert failed: \(msg)")
        }

        let tileInsert = """
        INSERT INTO way_tile(row_id, tile_x, tile_y)
        VALUES(1, \(tileX), \(tileY));
        """
        guard sqlite3_exec(db, tileInsert, nil, nil, nil) == SQLITE_OK else {
            let msg = String(cString: sqlite3_errmsg(db))
            throw BenchmarkError.sqliteError("sqlite way_tile insert failed: \(msg)")
        }
    }

    private static func tileForLonLat(lon: Double, lat: Double, tileSizeM: Double) -> (Int, Int) {
        let clampedLat = min(max(lat, -85.05112878), 85.05112878)
        let x = 6_378_137.0 * lon * .pi / 180.0
        let y = 6_378_137.0 * log(tan(.pi / 4.0 + clampedLat * .pi / 360.0))
        return (Int(floor(x / tileSizeM)), Int(floor(y / tileSizeM)))
    }
}
