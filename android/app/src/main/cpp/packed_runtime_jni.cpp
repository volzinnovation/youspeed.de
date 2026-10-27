#include <jni.h>
#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <vector>
#include "packed_runtime.h"
#include "packed_nodes.h"

namespace {
void fail(JNIEnv* env, const char* message) {
    if (env->ExceptionCheck()) return;
    auto type = env->FindClass("java/io/IOException");
    if (type) env->ThrowNew(type, message && *message ? message : "Packed runtime I/O failed");
}
class Utf8 {
    JNIEnv* env_; jstring source_;
public:
    const char* value;
    Utf8(JNIEnv* env, jstring source): env_(env), source_(source),
        value(source ? env->GetStringUTFChars(source, nullptr) : nullptr) {}
    ~Utf8() { if (value) env_->ReleaseStringUTFChars(source_, value); }
};
void* handle(jlong value) { return reinterpret_cast<void*>(static_cast<uintptr_t>(value)); }
jlong number(void* value) { return static_cast<jlong>(reinterpret_cast<uintptr_t>(value)); }
jbyteArray bytes(JNIEnv* env, char* value, void (*release)(void*) = ysp_packed_free) {
    std::unique_ptr<char,decltype(release)> owned(value, release);
    if (!value) return nullptr;
    size_t length = std::char_traits<char>::length(value);
    if (length > static_cast<size_t>(std::numeric_limits<jsize>::max())) {
        fail(env, "Packed JSON exceeds JNI array bounds"); return nullptr;
    }
    auto out = env->NewByteArray(static_cast<jsize>(length));
    if (out) env->SetByteArrayRegion(out, 0, static_cast<jsize>(length),
        reinterpret_cast<const jbyte*>(value));
    return out;
}
}

extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_contextOpen(JNIEnv* env, jobject, jstring path) {
    Utf8 p(env,path); if (!p.value) return 0;
    char error[1024]{}; auto out=ysp_context_open(p.value,0,error,sizeof error);
    if (!out) fail(env,error); return number(out);
}
extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_contextSize(JNIEnv* env, jobject, jlong value) {
    if (!value) {fail(env,"Closed packed context");return 0;}
    auto size=ysp_context_size(handle(value));
    if (size>static_cast<uint64_t>(std::numeric_limits<jlong>::max())) {
        fail(env,"Packed context exceeds signed file bounds");return 0;
    }
    return static_cast<jlong>(size);
}
extern "C" JNIEXPORT jint JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_contextRead(JNIEnv* env, jobject, jlong value,
    jlong offset, jint requested, jbyteArray destination) {
    if (!value||offset<0||requested<0||!destination||requested>env->GetArrayLength(destination)||requested>1024*1024) {
        fail(env,"Invalid packed context read");return -1;
    }
    try {
        std::vector<uint8_t> data(static_cast<size_t>(requested)); char error[1024]{};
        auto count=ysp_context_read(handle(value),static_cast<uint64_t>(offset),data.data(),data.size(),error,sizeof error);
        if (count<0) {fail(env,error);return -1;}
        if (count>requested) {fail(env,"Packed reader exceeded requested bounds");return -1;}
        if (count) env->SetByteArrayRegion(destination,0,static_cast<jsize>(count),reinterpret_cast<const jbyte*>(data.data()));
        return static_cast<jint>(count);
    } catch (const std::exception& e) {fail(env,e.what());return -1;}
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_contextClose(JNIEnv*, jobject, jlong value) {ysp_context_close(handle(value));}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_contextStats(JNIEnv* env, jobject, jlong value) {
    return value ? bytes(env,ysp_context_stats_json(handle(value))) : nullptr;
}
extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_geometryOpen(JNIEnv* env, jobject, jstring path) {
    Utf8 p(env,path);if (!p.value) return 0;
    char error[1024]{};auto out=ysp_geometry_open(p.value,0,error,sizeof error);
    if (!out) fail(env,error);return number(out);
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_geometryJson(JNIEnv* env, jobject, jlong value, jstring way) {
    if (!value) {fail(env,"Closed packed geometry");return nullptr;}
    Utf8 key(env,way);if (!key.value) return nullptr;
    char error[1024]{};auto out=ysp_geometry_json(handle(value),key.value,error,sizeof error);
    if (!out && *error) fail(env,error);
    return bytes(env,out);
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_geometryClose(JNIEnv*, jobject, jlong value) {ysp_geometry_close(handle(value));}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_geometryStats(JNIEnv* env, jobject, jlong value) {
    return value ? bytes(env,ysp_geometry_stats_json(handle(value))) : nullptr;
}
extern "C" JNIEXPORT jlong JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_nodesOpen(JNIEnv* env, jobject, jstring path) {
    Utf8 p(env,path);if (!p.value) return 0;
    char error[1024]{};auto out=ysp_nodes_open(p.value,512*1024,error,sizeof error);
    if (!out) fail(env,error);return number(out);
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_nodeJson(JNIEnv* env, jobject, jlong value, jstring node) {
    if (!value) {fail(env,"Closed packed nodes");return nullptr;}
    Utf8 key(env,node);if (!key.value) return nullptr;
    char error[1024]{};auto out=ysp_nodes_json(handle(value),key.value,error,sizeof error);
    if (!out && *error) fail(env,error);return bytes(env,out,ysp_nodes_free);
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_nodesQueryJson(JNIEnv* env, jobject, jlong value,
    jdouble latitude, jdouble longitude, jdouble radius) {
    if (!value) {fail(env,"Closed packed nodes");return nullptr;}
    char error[1024]{};auto out=ysp_nodes_query_json(handle(value),latitude,longitude,radius,error,sizeof error);
    if (!out && *error) fail(env,error);return bytes(env,out,ysp_nodes_free);
}
extern "C" JNIEXPORT jbyteArray JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_nodesStats(JNIEnv* env, jobject, jlong value) {
    return value ? bytes(env,ysp_nodes_stats_json(handle(value)),ysp_nodes_free) : nullptr;
}
extern "C" JNIEXPORT void JNICALL
Java_de_youspeed_android_alpha_RuntimePackedNative_nodesClose(JNIEnv*, jobject, jlong value) {ysp_nodes_close(handle(value));}
