# R8 do release (spec §1, design §10).

# onnxruntime: JNI chama classes e métodos pelo nome.
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**

# kotlinx.serialization: serializers gerados e companions.
-keepattributes *Annotation*, InnerClasses, Signature, Exceptions
-dontnote kotlinx.serialization.**
-keepclassmembers @kotlinx.serialization.Serializable class ** {
    static ** Companion;
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclasseswithmembers class br.com.dekasis.condessa.** {
    kotlinx.serialization.KSerializer serializer(...);
}
-if @kotlinx.serialization.Serializable class **
-keepclassmembers class <1>$Companion {
    kotlinx.serialization.KSerializer serializer(...);
}

# Media3: MediaSessionService é achado pelo manifesto; extensões por reflexão.
-keep class androidx.media3.session.** { *; }
-dontwarn androidx.media3.**

# OkHttp 5
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
