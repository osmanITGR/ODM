# Flutter's embedding is reached reflectively from generated code, so R8 sees
# no references to it and would otherwise strip it out.
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }
-dontwarn io.flutter.embedding.**

# The method channel resolves these by name at runtime.
-keep class com.osmanit.odm.Muxer { *; }
-keep class com.osmanit.odm.DownloadService { *; }
-keep class com.osmanit.odm.MainActivity { *; }

# flutter_local_notifications deserialises its callbacks through Gson.
-keep class com.dexterous.** { *; }
-keepattributes *Annotation*
-keepattributes Signature
-dontwarn com.dexterous.**

# Play Core is referenced by the deferred-components code path, which this app
# does not use; without this R8 fails on the missing classes.
-dontwarn com.google.android.play.core.**
