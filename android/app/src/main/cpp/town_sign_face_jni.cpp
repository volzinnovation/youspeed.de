#include <jni.h>
#include <array>
#include "german_cargo_plate.h"
#include "german_town_sign_face.h"
#include "german_town_exit_rescue.h"

template <std::size_t count>
static bool readRGBA(JNIEnv *env, jintArray input, std::array<uint8_t, 4 * count> &rgba) {
    if (!input || env->GetArrayLength(input) != static_cast<jsize>(count)) return false;
    std::array<jint, count> argb;
    env->GetIntArrayRegion(input, 0, count, argb.data());
    if (env->ExceptionCheck()) return false;
    for (std::size_t i = 0; i < count; ++i) {
        const auto pixel = static_cast<uint32_t>(argb[i]);
        rgba[4*i] = pixel >> 16;
        rgba[4*i + 1] = pixel >> 8;
        rgba[4*i + 2] = pixel;
        rgba[4*i + 3] = 255;
    }
    return true;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_de_youspeed_android_alpha_GermanTownSignFace_accepts(
    JNIEnv *env, jobject, jintArray input, jdouble width, jdouble height, jboolean townExit) {
    constexpr std::size_t count = YSP_TOWN_FACE_WIDTH * YSP_TOWN_FACE_HEIGHT;
    std::array<uint8_t, 4 * count> rgba;
    if (!readRGBA<count>(env, input, rgba)) return JNI_FALSE;
    return ysp_german_town_sign_face(rgba.data(), width, height, townExit) ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_de_youspeed_android_alpha_GermanTownSignFace_recoverExit(JNIEnv *env, jobject, jintArray input) {
    constexpr std::size_t count = 96 * 72;
    std::array<uint8_t, 4 * count> rgba;
    return readRGBA<count>(env, input, rgba) && ysp_german_town_exit_rescue(rgba.data()) ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT jint JNICALL
Java_de_youspeed_android_alpha_GermanCargoPlate_match(
    JNIEnv *env, jobject, jintArray input, jdouble width, jintArray output) {
    constexpr std::size_t count = YSP_CARGO_PLATE_SIZE * YSP_CARGO_PLATE_SIZE;
    std::array<uint8_t, 4 * count> rgba;
    if (!output || env->GetArrayLength(output) != 4 || !readRGBA<count>(env, input, rgba)) return 0;
    std::array<jint, 4> bounds;
    const int code = ysp_german_cargo_plate(rgba.data(), width, bounds.data());
    if (code) env->SetIntArrayRegion(output, 0, bounds.size(), bounds.data());
    return code;
}
