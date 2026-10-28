package de.youspeed.android.alpha

/** Numeric geometry is ASCII; metadata/diagnostics use a byte array so JNI never
 * mistakes ordinary UTF-8 for Java's modified UTF-8 string representation. */
internal object RuntimePackedNative {
    init { System.loadLibrary("youspeed_packed_runtime") }
    external fun applyBundleDelta(path: ByteArray, sql: ByteArray)
    external fun sqlOpen(path:ByteArray,packed:Boolean):Long
    external fun sqlGeometry(handle:Long,path:ByteArray)
    external fun sqlPrepare(handle:Long,sql:ByteArray,args:Array<ByteArray?>?):Long
    external fun sqlStep(statement:Long):Boolean
    external fun sqlReset(statement:Long)
    external fun sqlColumnCount(statement:Long):Int
    external fun sqlColumnName(statement:Long,column:Int):ByteArray
    external fun sqlColumnType(statement:Long,column:Int):Int
    external fun sqlColumnLong(statement:Long,column:Int):Long
    external fun sqlColumnDouble(statement:Long,column:Int):Double
    external fun sqlColumnBytes(statement:Long,column:Int,blob:Boolean):ByteArray?
    external fun sqlFinalize(statement:Long)
    external fun sqlStats(handle:Long,geometry:Boolean):ByteArray?
    external fun sqlClose(handle:Long)
    external fun contextOpen(path: String): Long
    external fun contextSize(handle: Long): Long
    external fun contextRead(handle: Long, offset: Long, requested: Int, destination: ByteArray): Int
    external fun contextClose(handle: Long)
    external fun contextStats(handle: Long): ByteArray?
    external fun geometryOpen(path: String): Long
    external fun geometryJson(handle: Long, decimalWayId: String): ByteArray?
    external fun geometryClose(handle: Long)
    external fun geometryStats(handle: Long): ByteArray?
    external fun nodesOpen(path: String): Long
    external fun nodeJson(handle: Long, decimalNodeId: String): ByteArray?
    external fun nodesQueryJson(handle: Long, latitude: Double, longitude: Double, radiusM: Double): ByteArray?
    external fun nodesStats(handle: Long): ByteArray?
    external fun nodesClose(handle: Long)
}
