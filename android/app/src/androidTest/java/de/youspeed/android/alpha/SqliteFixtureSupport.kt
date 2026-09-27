package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.util.Log

/** Fixture loading only. Ordinary bounds tables do not claim native R-tree coverage. */
internal object SqliteFixtureSupport {
    private val rtreeDeclaration = Regex(
        "CREATE\\s+VIRTUAL\\s+TABLE\\s+([A-Za-z_][A-Za-z0-9_]*)\\s+USING\\s+rtree\\s*\\(([^)]+)\\)",
        RegexOption.IGNORE_CASE,
    )

    fun execSql(db: SQLiteDatabase, sql: String) {
        sql.lineSequence().filterNot { it.trimStart().startsWith("--") }.joinToString("\n")
            .split(';').map(String::trim).filter(String::isNotEmpty).forEach { statement ->
                try { db.execSQL(statement) } catch (error: SQLiteException) {
                    val declaration = rtreeDeclaration.matchEntire(statement)
                    if (declaration == null || !isRtreeUnavailable(error)) throw error
                    val table = declaration.groupValues[1]
                    val columns = declaration.groupValues[2].split(',').map(String::trim)
                    require(columns.size == 5 && columns.all { it.matches(Regex("[A-Za-z_][A-Za-z0-9_]*")) })
                    val typedColumns = columns.mapIndexed { index, column ->
                        "$column ${if (index == 0) "INTEGER PRIMARY KEY" else "REAL NOT NULL"}"
                    }
                    db.execSQL("CREATE TABLE $table (${typedColumns.joinToString(",")})")
                    Log.i("SqliteFixtureSupport", "$table: native R-tree unavailable; fixture uses ordinary bounds table")
                }
            }
    }

    fun createRtree(db: SQLiteDatabase, table: String) {
        require(table.matches(Regex("[A-Za-z_][A-Za-z0-9_]*")))
        execSql(db, "CREATE VIRTUAL TABLE $table USING rtree(way_id,min_lon,max_lon,min_lat,max_lat)")
    }

    fun isRtreeUnavailable(error: SQLiteException): Boolean =
        error.message?.contains("no such module: rtree", ignoreCase = true) == true
}
