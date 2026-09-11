package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** SQLite execution is injectable so transfer/activation failure paths can be tested without a device. */
interface BundleDeltaDatabase {
    fun applyPatch(database: File, sql: String)
    fun validate(database: File)
}

internal class AndroidBundleDeltaDatabase : BundleDeltaDatabase {
    override fun applyPatch(database: File, sql: String) {
        SQLiteDatabase.openDatabase(database.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            for (statement in DeltaUpdatePolicy.sqlStatements(sql)) db.execSQL(statement)
            db.rawQuery("PRAGMA wal_checkpoint(TRUNCATE)", null).use { cursor ->
                check(cursor.moveToFirst() && cursor.getInt(0) == 0) { "Delta checkpoint failed" }
            }
        }
    }

    override fun validate(database: File) {
        SQLiteDatabase.openDatabase(database.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            for (table in listOf("ways", "ways_rtree", "way_geom")) {
                db.rawQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", arrayOf(table)).use {
                    check(it.moveToFirst()) { "Missing table in v3 database: $table" }
                }
            }
            db.rawQuery("PRAGMA quick_check", null).use { cursor ->
                check(cursor.moveToFirst() && cursor.getString(0) == "ok" && !cursor.moveToNext()) { "Delta database quick_check failed" }
            }
        }
    }
}

internal object DeltaUpdatePolicy {
    fun forceFullReload(current: String?, target: String): Boolean {
        if (current == null || current == "seed" || current == target) return false
        val from = runCatching { LocalDate.parse(current) }.getOrNull() ?: return true
        val to = runCatching { LocalDate.parse(target) }.getOrNull() ?: return true
        return ChronoUnit.DAYS.between(from, to) > 30
    }

    fun path(entries: List<V3DeltaEntry>, from: String, to: String, region: String): List<V3DeltaEntry>? {
        if (from == to) return emptyList()
        val edges = entries.filter { it.fromBundleVersion != it.toBundleVersion && (it.region == null || it.region == region) }
            .groupBy { it.fromBundleVersion }.mapValues { (_, values) -> values.sortedWith(compareBy<V3DeltaEntry> { it.toBundleVersion }.thenBy { it.deltaManifestFile }) }
        val queue = ArrayDeque<String>(); queue += from
        val visited = mutableSetOf(from)
        val parent = mutableMapOf<String, V3DeltaEntry>()
        while (queue.isNotEmpty() && to !in visited) {
            for (edge in edges[queue.removeFirst()].orEmpty()) if (visited.add(edge.toBundleVersion)) {
                parent[edge.toBundleVersion] = edge
                if (edge.toBundleVersion == to) break
                queue += edge.toBundleVersion
            }
        }
        if (to !in visited) return null
        val path = mutableListOf<V3DeltaEntry>()
        var cursor = to
        while (cursor != from) { val edge = parent[cursor] ?: return null; path += edge; cursor = edge.fromBundleVersion }
        return path.asReversed()
    }

    /** Generated v3 patches contain ordinary DML and explicit BEGIN/COMMIT; quoted semicolons stay in a statement. */
    fun sqlStatements(sql: String): List<String> {
        val statements = mutableListOf<String>()
        val statement = StringBuilder()
        var quote: Char? = null
        var lineComment = false
        var blockComment = false
        var index = 0
        while (index < sql.length) {
            val c = sql[index]; val next = sql.getOrNull(index + 1)
            when {
                lineComment -> { if (c == '\n') { lineComment = false; statement.append('\n') } }
                blockComment -> { if (c == '*' && next == '/') { blockComment = false; statement.append(' '); index++ } }
                quote != null -> {
                    statement.append(c)
                    if (c == quote) {
                        if (next == quote && quote != ']') { statement.append(next); index++ } else quote = null
                    }
                }
                c == '-' && next == '-' -> { lineComment = true; index++ }
                c == '/' && next == '*' -> { blockComment = true; index++ }
                c == '\'' || c == '"' || c == '`' || c == '[' -> { quote = if (c == '[') ']' else c; statement.append(c) }
                c == ';' -> { statement.toString().trim().takeIf { it.isNotEmpty() }?.let(statements::add); statement.clear() }
                else -> statement.append(c)
            }
            index++
        }
        require(quote == null && !blockComment) { "Unterminated SQL literal or comment in delta patch" }
        statement.toString().trim().takeIf { it.isNotEmpty() }?.let(statements::add)
        return statements
    }
}
