package de.youspeed.android.alpha

import android.database.CharArrayBuffer
import android.database.Cursor
import android.database.CursorIndexOutOfBoundsException
import android.database.MatrixCursor
import android.database.sqlite.SQLiteDatabase
import java.io.Closeable

/** Read-only SQL boundary shared by legacy framework SQLite and the packed VFS.
 * Queries, bindings, ordering, limits, and typed cursor values remain unchanged. */
interface RuntimeSqlDatabase : Closeable {
    fun rawQuery(sql:String,args:Array<out String?>?):Cursor
    val isOpen:Boolean
}

internal class FrameworkRuntimeSqlDatabase(private val database:SQLiteDatabase) : RuntimeSqlDatabase {
    override fun rawQuery(sql:String,args:Array<out String?>?)=database.rawQuery(sql,args)
    override val isOpen:Boolean get()=database.isOpen
    override fun close()=database.close()
}

/** One native SQLite connection, with statements finalized before its immutable
 * geometry/VFS handles. Cursors stream a row at a time rather than copying SQL
 * result sets into JVM memory. All native handle access uses this owner lock. */
internal class NativeRuntimeSqlDatabase(path:String,packed:Boolean) : RuntimeSqlDatabase {
    private var handle=RuntimePackedNative.sqlOpen(path.toByteArray(Charsets.UTF_8),packed)
    private val cursors=mutableSetOf<NativeCursor>()
    override val isOpen:Boolean @Synchronized get()=handle!=0L
    @Synchronized override fun rawQuery(sql:String,args:Array<out String?>?):Cursor {
        check(handle!=0L){"Packed SQL database is closed"}
        val statement=RuntimePackedNative.sqlPrepare(handle,sql.toByteArray(Charsets.UTF_8),
            args?.map { it?.toByteArray(Charsets.UTF_8) }?.toTypedArray())
        return try {NativeCursor(statement).also{cursors+=it}} catch(failure:Throwable) {
            RuntimePackedNative.sqlFinalize(statement);throw failure
        }
    }
    @Synchronized fun registerGeometry(path:String) {
        check(handle!=0L);RuntimePackedNative.sqlGeometry(handle,path.toByteArray(Charsets.UTF_8))
    }
    @Synchronized fun diagnostics(geometry:Boolean)=if(handle==0L)null else
        RuntimePackedNative.sqlStats(handle,geometry)?.toString(Charsets.UTF_8)
    @Synchronized override fun close() {
        if(handle==0L)return
        cursors.toList().forEach{it.close()}
        RuntimePackedNative.sqlClose(handle);handle=0
    }

    private inner class NativeCursor(private var statement:Long,
        private val metadata:MatrixCursor=MatrixCursor(emptyArray())) : Cursor by metadata {
        private val names=Array(RuntimePackedNative.sqlColumnCount(statement)) {
            RuntimePackedNative.sqlColumnName(statement,it).toString(Charsets.UTF_8)
        }
        private var row=-1
        private var total:Int?=null
        private var after=false
        private fun checkOpen() {check(statement!=0L&&handle!=0L){"Packed SQL cursor is closed"}}
        private fun checkColumn(column:Int) {
            checkOpen();if(row<0||after)throw CursorIndexOutOfBoundsException(row,total?:0)
            require(column in names.indices){"Column index out of bounds: $column"}
        }
        override fun getColumnNames()=names.clone()
        override fun getColumnCount()=names.size
        override fun getColumnName(column:Int)=names[column]
        override fun getColumnIndex(name:String?):Int {
            val selected=name?.substringAfterLast('.')?:return -1
            return names.indexOfFirst{it.equals(selected,true)}
        }
        override fun getColumnIndexOrThrow(name:String?):Int=getColumnIndex(name).also {
            require(it>=0){"Missing SQL column $name"}
        }
        override fun getPosition()=synchronized(this@NativeRuntimeSqlDatabase){row}
        override fun moveToPosition(position:Int):Boolean=synchronized(this@NativeRuntimeSqlDatabase) {
            checkOpen()
            if(position<0){RuntimePackedNative.sqlReset(statement);row=-1;after=false;return@synchronized false}
            total?.let { if(position>=it){row=it;after=true;return@synchronized false} }
            if(position<row||after){RuntimePackedNative.sqlReset(statement);row=-1;after=false}
            while(row<position) {
                if(!RuntimePackedNative.sqlStep(statement)){total=row+1;row=total!!;after=true;return@synchronized false}
                row++
            }
            true
        }
        override fun move(offset:Int)=moveToPosition(position+offset)
        override fun moveToNext()=moveToPosition(position+1)
        override fun moveToPrevious()=moveToPosition(position-1)
        override fun moveToFirst()=moveToPosition(0)
        override fun moveToLast()=moveToPosition(count-1)
        override fun getCount():Int=synchronized(this@NativeRuntimeSqlDatabase) {
            checkOpen();total?.let{return@synchronized it}
            val saved=row;val savedAfter=after
            while(!after)moveToNext()
            val result=total!!
            if(!savedAfter)moveToPosition(saved)
            result
        }
        override fun isBeforeFirst()=count!=0&&position<0
        override fun isAfterLast()=count!=0&&synchronized(this@NativeRuntimeSqlDatabase){after}
        override fun isFirst()=position==0&&!isAfterLast
        override fun isLast()=position>=0&&position==count-1
        override fun isClosed()=synchronized(this@NativeRuntimeSqlDatabase){statement==0L}
        override fun getType(column:Int)=synchronized(this@NativeRuntimeSqlDatabase) {
            checkColumn(column);RuntimePackedNative.sqlColumnType(statement,column)
        }
        override fun isNull(column:Int)=getType(column)==Cursor.FIELD_TYPE_NULL
        override fun getString(column:Int):String?=synchronized(this@NativeRuntimeSqlDatabase) {
            checkColumn(column);RuntimePackedNative.sqlColumnBytes(statement,column,false)?.toString(Charsets.UTF_8)
        }
        override fun getBlob(column:Int):ByteArray?=synchronized(this@NativeRuntimeSqlDatabase) {
            checkColumn(column);RuntimePackedNative.sqlColumnBytes(statement,column,true)
        }
        override fun getLong(column:Int)=synchronized(this@NativeRuntimeSqlDatabase) {
            checkColumn(column);RuntimePackedNative.sqlColumnLong(statement,column)
        }
        override fun getInt(column:Int)=getLong(column).toInt()
        override fun getShort(column:Int)=getLong(column).toShort()
        override fun getDouble(column:Int)=synchronized(this@NativeRuntimeSqlDatabase) {
            checkColumn(column);RuntimePackedNative.sqlColumnDouble(statement,column)
        }
        override fun getFloat(column:Int)=getDouble(column).toFloat()
        override fun copyStringToBuffer(column:Int,buffer:CharArrayBuffer) {
            val text=getString(column).orEmpty();if(buffer.data==null||buffer.data.size<text.length)buffer.data=CharArray(text.length)
            text.toCharArray(buffer.data,0,0,text.length);buffer.sizeCopied=text.length
        }
        override fun requery():Boolean {moveToPosition(-1);return true}
        override fun deactivate()=close()
        override fun close()=synchronized(this@NativeRuntimeSqlDatabase) {
            if(statement!=0L){RuntimePackedNative.sqlFinalize(statement);statement=0;cursors.remove(this)}
            metadata.close()
        }
    }
}
