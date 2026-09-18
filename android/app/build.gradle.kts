plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val releaseStoreFile = providers.environmentVariable("YOUSPEED_ANDROID_RELEASE_STORE_FILE").orNull
val releaseStorePassword = providers.environmentVariable("YOUSPEED_ANDROID_RELEASE_STORE_PASSWORD").orNull
val releaseKeyAlias = providers.environmentVariable("YOUSPEED_ANDROID_RELEASE_KEY_ALIAS").orNull
val releaseKeyPassword = providers.environmentVariable("YOUSPEED_ANDROID_RELEASE_KEY_PASSWORD").orNull

val releaseBaseVersionCode = providers.gradleProperty("youspeedBuildNumber").orElse("10007").get().toInt()
val releaseVersionName = providers.gradleProperty("youspeedVersionName").orElse("1.1").get()
val releaseAbiCodes = linkedMapOf(
    "armeabi-v7a" to 1,
    "arm64-v8a" to 2,
    "x86" to 3,
    "x86_64" to 4,
)
val releaseAbi = providers.gradleProperty("youspeedAbi").orNull
require(releaseAbi == null || releaseAbi in releaseAbiCodes) {
    "Unsupported youspeedAbi '$releaseAbi'. Expected one of: ${releaseAbiCodes.keys.joinToString()}"
}

android {
    namespace = "de.youspeed.android.alpha"
    compileSdk = 36

    dependenciesInfo {
        // F-Droid rejects AGP's Google-encrypted dependency metadata block.
        includeInApk = false
        includeInBundle = false
    }

    defaultConfig {
        applicationId = "de.youspeed.android"
        minSdk = 34
        targetSdk = 36
        versionCode = releaseAbi?.let { releaseBaseVersionCode * 10 + releaseAbiCodes.getValue(it) }
            ?: releaseBaseVersionCode
        versionName = releaseVersionName
        buildConfigField("String", "MAP_COMPATIBILITY_APP_VERSION", "\"$releaseVersionName\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            // Vosk only supplies these four ABIs. Exclude obsolete JNA-only ABIs so
            // every APK advertised as supported contains the speech recognizer.
            abiFilters += releaseAbi?.let(::setOf) ?: releaseAbiCodes.keys
        }
    }

    signingConfigs {
        if (!releaseStoreFile.isNullOrBlank() &&
            !releaseStorePassword.isNullOrBlank() &&
            !releaseKeyAlias.isNullOrBlank() &&
            !releaseKeyPassword.isNullOrBlank()
        ) {
            create("releaseUpload") {
                storeFile = file(releaseStoreFile)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            signingConfigs.findByName("releaseUpload")?.let {
                signingConfig = it
            }
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    androidResources {
        noCompress += "tflite"
    }

    sourceSets {
        getByName("main") {
            assets.srcDirs("src/main/assets", "../../shared")
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")
    // CameraX 1.5+ requires AGP 8.6; 1.4.2 remains compatible with this app's
    // AGP 8.5 / Kotlin 1.9 toolchain.
    val cameraXVersion = "1.4.2"

    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.activity:activity-compose:1.9.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.4")
    implementation("androidx.exifinterface:exifinterface:1.3.7")
    implementation("androidx.camera:camera-core:$cameraXVersion")
    implementation("androidx.camera:camera-camera2:$cameraXVersion")
    implementation("androidx.camera:camera-lifecycle:$cameraXVersion")
    implementation("androidx.camera:camera-video:$cameraXVersion")
    implementation("androidx.camera:camera-view:$cameraXVersion")
    implementation(composeBom)
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("com.alphacephei:vosk-android:0.3.75")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    // 1.4.2 is the newest LiteRT line compatible with this module's Kotlin 1.9 ABI.
    implementation("com.google.ai.edge.litert:litert:1.4.2")
    implementation("com.google.ai.edge.litert:litert-gpu:1.4.2")
    implementation("com.google.ai.edge.litert:litert-gpu-api:1.4.2")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test:rules:1.6.1")
    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")
    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")

    debugImplementation(composeBom)
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
