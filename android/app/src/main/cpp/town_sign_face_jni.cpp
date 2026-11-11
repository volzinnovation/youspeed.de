#include <jni.h>
#include <array>
#include "german_town_sign_face.h"

extern "C" JNIEXPORT jboolean JNICALL
Java_de_youspeed_android_alpha_GermanTownSignFace_accepts(
    JNIEnv *env, jobject, jintArray input, jdouble width, jdouble height, jboolean townExit) {
    constexpr int count = YSP_TOWN_FACE_WIDTH * YSP_TOWN_FACE_HEIGHT;
    if (!input || env->GetArrayLength(input) != count) return JNI_FALSE;
    std::array<jint, count> argb;
    env->GetIntArrayRegion(input, 0, count, argb.data());
    if (env->ExceptionCheck()) return JNI_FALSE;
    std::array<uint8_t, 4 * count> rgba;
    for (int i = 0; i < count; ++i) {
        const auto pixel = static_cast<uint32_t>(argb[i]);
        rgba[4*i] = pixel >> 16;
        rgba[4*i + 1] = pixel >> 8;
        rgba[4*i + 2] = pixel;
        rgba[4*i + 3] = 255;
    }
    return ysp_german_town_sign_face(rgba.data(), width, height, townExit) ? JNI_TRUE : JNI_FALSE;
}
