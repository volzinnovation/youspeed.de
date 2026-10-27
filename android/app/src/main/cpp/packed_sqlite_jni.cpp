#include <jni.h>
#include <sqlite3.h>
#include <cstdint>
#include <cstring>
#include <string>
#include "packed_runtime.h"

namespace {
struct Session { sqlite3* db=nullptr; void* geometry=nullptr; };
template<class T> T* pointer(jlong value) { return reinterpret_cast<T*>(static_cast<uintptr_t>(value)); }
jlong number(void* value) { return static_cast<jlong>(reinterpret_cast<uintptr_t>(value)); }
void fail(JNIEnv* env,const char* reason) {
    if(env->ExceptionCheck())return;
    auto type=env->FindClass("android/database/sqlite/SQLiteException");
    if(type)env->ThrowNew(type,reason&&*reason?reason:"Packed SQLite failed");
}
std::string input(JNIEnv* env,jbyteArray bytes) {
    if(!bytes)return {};
    const auto size=env->GetArrayLength(bytes);std::string out(static_cast<size_t>(size),'\0');
    if(size)env->GetByteArrayRegion(bytes,0,size,reinterpret_cast<jbyte*>(&out[0]));
    return out;
}
jbyteArray output(JNIEnv* env,const void* data,int size) {
    if(!data)return nullptr;
    auto result=env->NewByteArray(size);
    if(result&&size)env->SetByteArrayRegion(result,0,size,static_cast<const jbyte*>(data));
    return result;
}
void geometryFunction(sqlite3_context* context,int argc,sqlite3_value** argv) {
    auto session=static_cast<Session*>(sqlite3_user_data(context));
    if(argc!=1||sqlite3_value_type(argv[0])==SQLITE_NULL){sqlite3_result_null(context);return;}
    const auto key=reinterpret_cast<const char*>(sqlite3_value_text(argv[0]));char error[1024]{};
    char* json=ysp_geometry_json(session->geometry,key,error,sizeof error);
    if(json)sqlite3_result_text(context,json,-1,ysp_packed_free);
    else if(*error)sqlite3_result_error(context,error,-1);
    else sqlite3_result_null(context);
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlOpen(JNIEnv* env,jobject,jbyteArray path,jboolean packed) {
    auto name=input(env,path);if(env->ExceptionCheck())return 0;
    auto session=new Session;
    if(packed&&ysp_register_context_vfs()!=SQLITE_OK){delete session;fail(env,"Cannot register packed SQLite VFS");return 0;}
    const int code=sqlite3_open_v2(name.c_str(),&session->db,SQLITE_OPEN_READONLY|SQLITE_OPEN_FULLMUTEX,
        packed?"ysp-packed-v1":nullptr);
    if(code!=SQLITE_OK){std::string reason=session->db?sqlite3_errmsg(session->db):"Cannot allocate SQLite connection";
        if(session->db)sqlite3_close(session->db);delete session;fail(env,reason.c_str());return 0;}
    sqlite3_extended_result_codes(session->db,1);
    char* error=nullptr;
    const std::string configuration="PRAGMA mmap_size=0;PRAGMA cache_size=-"+std::to_string(ysp_sqlite_cache_kib())+
        ";PRAGMA temp_store=FILE;PRAGMA query_only=ON";
    const int configured=sqlite3_exec(session->db,configuration.c_str(),nullptr,nullptr,&error);
    if(configured!=SQLITE_OK){std::string reason=error?error:sqlite3_errmsg(session->db);sqlite3_free(error);sqlite3_close(session->db);delete session;fail(env,reason.c_str());return 0;}
    return number(session);
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlGeometry(JNIEnv* env,jobject,jlong value,jbyteArray path) {
    auto session=pointer<Session>(value);auto name=input(env,path);char error[1024]{};
    if(!session||session->geometry){fail(env,"Packed SQLite geometry lifetime violation");return;}
    session->geometry=ysp_geometry_open(name.c_str(),0,error,sizeof error);
    if(!session->geometry){fail(env,error);return;}
    if(sqlite3_create_function_v2(session->db,"ysp_way_points_json",1,SQLITE_UTF8|SQLITE_DETERMINISTIC,
        session,geometryFunction,nullptr,nullptr,nullptr)!=SQLITE_OK)fail(env,sqlite3_errmsg(session->db));
}
extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlPrepare(JNIEnv* env,jobject,jlong value,jbyteArray sql,jobjectArray args) {
    auto session=pointer<Session>(value);if(!session){fail(env,"Packed SQLite is closed");return 0;}
    auto source=input(env,sql);sqlite3_stmt* statement=nullptr;const char* tail=nullptr;
    int code=sqlite3_prepare_v2(session->db,source.c_str(),static_cast<int>(source.size()),&statement,&tail);
    if(code!=SQLITE_OK||!statement){fail(env,sqlite3_errmsg(session->db));return 0;}
    while(tail&&*tail&&(*tail==' '||*tail=='\t'||*tail=='\r'||*tail=='\n'||*tail==';'))++tail;
    if((tail&&*tail)||!sqlite3_stmt_readonly(statement)) {sqlite3_finalize(statement);fail(env,"Packed map queries must be one read-only statement");return 0;}
    const int count=args?env->GetArrayLength(args):0;
    if(sqlite3_bind_parameter_count(statement)!=count){sqlite3_finalize(statement);fail(env,"Packed query argument count mismatch");return 0;}
    for(int i=0;i<count;++i){auto bytes=static_cast<jbyteArray>(env->GetObjectArrayElement(args,i));
        auto text=input(env,bytes);code=bytes?sqlite3_bind_text(statement,i+1,text.data(),static_cast<int>(text.size()),SQLITE_TRANSIENT):sqlite3_bind_null(statement,i+1);
        if(bytes)env->DeleteLocalRef(bytes);
        if(env->ExceptionCheck()||code!=SQLITE_OK){sqlite3_finalize(statement);if(!env->ExceptionCheck())fail(env,sqlite3_errmsg(session->db));return 0;}}
    return number(statement);
}
extern "C" JNIEXPORT jboolean JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlStep(JNIEnv* env,jobject,jlong value) {
    auto statement=pointer<sqlite3_stmt>(value);const int code=sqlite3_step(statement);
    if(code==SQLITE_ROW)return JNI_TRUE;if(code==SQLITE_DONE)return JNI_FALSE;
    fail(env,sqlite3_errmsg(sqlite3_db_handle(statement)));return JNI_FALSE;
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlReset(JNIEnv* env,jobject,jlong value) {
    auto statement=pointer<sqlite3_stmt>(value);if(sqlite3_reset(statement)!=SQLITE_OK)fail(env,sqlite3_errmsg(sqlite3_db_handle(statement)));
}
extern "C" JNIEXPORT jint JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlColumnCount(JNIEnv*,jobject,jlong value) {return sqlite3_column_count(pointer<sqlite3_stmt>(value));}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlColumnName(JNIEnv* env,jobject,jlong value,jint column) {
    const char* name=sqlite3_column_name(pointer<sqlite3_stmt>(value),column);return name?output(env,name,static_cast<int>(std::strlen(name))):nullptr;
}
extern "C" JNIEXPORT jint JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlColumnType(JNIEnv*,jobject,jlong value,jint column) {
    // Android Cursor constants differ from SQLite's NULL/TEXT/BLOB constants.
    switch(sqlite3_column_type(pointer<sqlite3_stmt>(value),column)) {case SQLITE_INTEGER:return 1;case SQLITE_FLOAT:return 2;case SQLITE_TEXT:return 3;case SQLITE_BLOB:return 4;default:return 0;}
}
extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlColumnLong(JNIEnv*,jobject,jlong value,jint column) {return sqlite3_column_int64(pointer<sqlite3_stmt>(value),column);}
extern "C" JNIEXPORT jdouble JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlColumnDouble(JNIEnv*,jobject,jlong value,jint column) {return sqlite3_column_double(pointer<sqlite3_stmt>(value),column);}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlColumnBytes(JNIEnv* env,jobject,jlong value,jint column,jboolean blob) {
    auto statement=pointer<sqlite3_stmt>(value);
    const void* bytes=blob?sqlite3_column_blob(statement,column):sqlite3_column_text(statement,column);
    if(!bytes&&sqlite3_column_type(statement,column)!=SQLITE_NULL)return env->NewByteArray(0);
    return output(env,bytes,sqlite3_column_bytes(statement,column));
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlFinalize(JNIEnv*,jobject,jlong value) {if(value)sqlite3_finalize(pointer<sqlite3_stmt>(value));}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlStats(JNIEnv* env,jobject,jlong value,jboolean geometry) {
    auto session=pointer<Session>(value);if(!session)return nullptr;
    char* raw=geometry?ysp_geometry_stats_json(session->geometry):ysp_context_vfs_stats_json(session->db);
    if(!raw)return nullptr;auto result=output(env,raw,static_cast<int>(std::strlen(raw)));ysp_packed_free(raw);return result;
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_sqlClose(JNIEnv* env,jobject,jlong value) {
    auto session=pointer<Session>(value);if(!session)return;
    // SQLite owns internal virtual-table statements (notably RTREE). Only the
    // Kotlin owner's tracked user cursors may finalize statements; enumerating
    // sqlite3_next_stmt here would destroy RTREE caches and double-free on close.
    if(sqlite3_close(session->db)!=SQLITE_OK){fail(env,"Packed SQLite still has active cursors");return;}
    ysp_geometry_close(session->geometry);delete session;
}
