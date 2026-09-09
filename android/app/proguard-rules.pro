# JNA 5.18.1 has no consumer rules. Its native dispatch library resolves these
# bridge classes and members by name, including Pointer.peer and Native's
# fromNative/toNative callbacks, which Android's default native-method rule
# does not preserve. Keep the bridge package; internal helpers can still shrink.
-keep class com.sun.jna.* { *; }

# JNA's desktop window helpers reference AWT, which Android does not provide.
# Vosk never calls these helpers; JNA also marks HAS_AWT false on Android.
# Suppress only the four optional desktop types retained with the JNI bridge.
-dontwarn java.awt.Component
-dontwarn java.awt.GraphicsEnvironment
-dontwarn java.awt.HeadlessException
-dontwarn java.awt.Window

# Vosk passes Model through JNA's NativeMapped conversion, which reflectively
# calls its public no-argument constructor via Klass.newInstance().
-keepclassmembers class org.vosk.Model {
    public <init>();
}

# LiteRT supplies its own consumer rules for classes used through reflection.
