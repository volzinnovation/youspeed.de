package de.youspeed.android.alpha

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import java.io.Closeable
import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.security.MessageDigest

/** Owns the SQL connection and the immutable packed-file handles behind it.
 * Existing matchers continue to execute their original SQL and rule semantics. */
internal class RuntimeMapDatabase private constructor(
    val database: RuntimeSqlDatabase,
    private val native: NativeRuntimeSqlDatabase?,
) : Closeable {
    private var closed = false
    @Synchronized override fun close() {
        if (closed) return
        closed = true
        database.close()
    }

    internal fun contextDiagnostics(): String? = native?.diagnostics(false)
    internal fun geometryDiagnostics(): String? = native?.diagnostics(true)

    companion object {
        @Volatile private var applicationContext: Context? = null
        private val verifiedGeometry = LinkedHashMap<String, Unit>(32, .75f, true)
        fun initialize(context: Context) { applicationContext = context.applicationContext }

        fun open(path: String, flags: Int = SQLiteDatabase.OPEN_READONLY): RuntimeMapDatabase {
            val source = File(path)
            val isPacked = isPackedFile(source)
            if (!isPacked) return RuntimeMapDatabase(FrameworkRuntimeSqlDatabase(
                SQLiteDatabase.openDatabase(path,null,flags or SQLiteDatabase.OPEN_READONLY)),null)
            val db=NativeRuntimeSqlDatabase(path,true)
            try {
                if(metadata(db,"packed_geometry_version")!="1") throw IOException("Unsupported packed geometry capability")
                val name=metadata(db,"packed_geometry_file")?:throw IOException("Packed geometry file is not declared")
                val expected=metadata(db,"packed_geometry_sha256")?:throw IOException("Packed geometry checksum is not declared")
                val file=companionFile(source.parentFile?:throw IOException("Map has no parent directory"),name)
                verifyGeometry(file,expected)
                db.registerGeometry(file.path)
                return RuntimeMapDatabase(db,db)
            } catch(failure:Throwable) {db.close();throw failure}
        }

        internal fun isPackedFile(source: File): Boolean = FileInputStream(source).use { input ->
            val bytes = ByteArray(8)
            input.read(bytes) == bytes.size && bytes.contentEquals(byteArrayOf(89, 83, 80, 67, 84, 88, 49, 0))
        }

        private fun metadata(db: RuntimeSqlDatabase, key: String): String? {
            val present = db.rawQuery("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'", null)
                .use { it.moveToFirst() }
            if (!present) return null
            return db.rawQuery("SELECT value FROM metadata WHERE key=? LIMIT 1", arrayOf(key))
                .use { if (it.moveToFirst()) it.getString(0) else null }
        }

        internal fun companionFile(directory: File, name: String): File {
            if (name.isBlank() || name == "." || name == ".." || '/' in name || '\\' in name)
                throw IOException("Packed artifact must use a local file name")
            val root = directory.canonicalFile
            val file = File(root, name).canonicalFile
            if (file.parentFile != root || !file.isFile) throw IOException("Packed companion is unavailable")
            return file
        }

        internal fun verifyGeometry(file: File, expected: String) {
            if (!expected.matches(Regex("[0-9a-fA-F]{64}"))) throw IOException("Invalid packed geometry checksum")
            val key = "${file.path}|${file.length()}|${file.lastModified()}|${expected.lowercase()}"
            synchronized(verifiedGeometry) { if (verifiedGeometry.containsKey(key)) return }
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) { val count = input.read(buffer); if (count < 0) break; if (count > 0) digest.update(buffer, 0, count) }
            }
            val actual = digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
            if (!actual.equals(expected, true)) throw IOException("Packed geometry checksum mismatch")
            synchronized(verifiedGeometry) {
                verifiedGeometry[key] = Unit
                while (verifiedGeometry.size > 32) verifiedGeometry.remove(verifiedGeometry.keys.first())
            }
        }
    }
}
