package com.osmanit.odm

import android.content.Intent
import android.media.MediaScannerConnection
import android.os.Build
import androidx.annotation.NonNull
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {

    private val channelName = "com.osmanit.odm/muxer"
    private val linkChannelName = "com.osmanit.odm/links"

    /** Set once the Dart side is listening; before that, links are queued. */
    private var linkChannel: MethodChannel? = null

    /**
     * A link that arrived before Flutter was ready.
     *
     * A cold start from a share lands here: the intent is delivered to the
     * activity well before the Dart side has registered its handler, so
     * without this the very first share would be dropped.
     */
    private var pendingLink: String? = null

    /**
     * Muxing a long video takes seconds, so it must not run on the platform
     * thread — that would freeze the UI and trip Android's ANR watchdog.
     */
    private val worker = Executors.newSingleThreadExecutor()

    override fun configureFlutterEngine(@NonNull flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "mux" -> handleMux(call.argument("video"), call.argument("audio"), call.argument("output"), result)
                    "scanFile" -> handleScan(call.argument("path"), result)
                    "keepAwake" -> {
                        DownloadService.setActive(this, call.argument("active") ?: false)
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            }

        linkChannel = MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            linkChannelName,
        ).also { channel ->
            channel.setMethodCallHandler { call, result ->
                when (call.method) {
                    // Dart asks for the link that launched the app, if any.
                    "getInitialLink" -> {
                        result.success(pendingLink)
                        pendingLink = null
                    }
                    else -> result.notImplemented()
                }
            }
        }

        // The intent that started this activity may already carry a link.
        extractLink(intent)?.let { pendingLink = it }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        // Already running: hand the link straight over.
        extractLink(intent)?.let { link ->
            val channel = linkChannel
            if (channel != null) {
                channel.invokeMethod("onLink", link)
            } else {
                pendingLink = link
            }
        }
    }

    /**
     * Find the text an intent carries, wherever the sending app put it.
     *
     * Apps are inconsistent: some use EXTRA_TEXT, some pass the URL as the
     * intent's data, selected text arrives as EXTRA_PROCESS_TEXT, and
     * SEND_MULTIPLE uses a list. The text is handed over as-is — pulling the
     * URL out of it is done once on the Dart side, where it is under test,
     * rather than reimplemented here.
     */
    private fun extractLink(intent: Intent?): String? {
        if (intent == null) return null

        val candidates = listOfNotNull(
            intent.getStringExtra(Intent.EXTRA_TEXT),
            intent.getStringExtra(Intent.EXTRA_PROCESS_TEXT),
            intent.dataString,
            intent.getStringExtra(Intent.EXTRA_SUBJECT),
        )

        candidates.firstOrNull { it.contains("http", ignoreCase = true) }
            ?.let { return it }

        // SEND_MULTIPLE: take the first entry that mentions a link.
        intent.getStringArrayListExtra(Intent.EXTRA_TEXT)
            ?.firstOrNull { it.contains("http", ignoreCase = true) }
            ?.let { return it }

        return candidates.firstOrNull()
    }

    private fun handleMux(
        video: String?,
        audio: String?,
        output: String?,
        result: MethodChannel.Result,
    ) {
        if (video == null || audio == null || output == null) {
            result.error("ARGS", "video, audio and output paths are required", null)
            return
        }

        worker.execute {
            try {
                Muxer.mux(video, audio, output)
                runOnUiThread { result.success(null) }
            } catch (error: Exception) {
                runOnUiThread {
                    result.error("MUX_FAILED", error.message ?: "Muxing failed", null)
                }
            }
        }
    }

    private fun handleScan(path: String?, result: MethodChannel.Result) {
        if (path == null || !File(path).exists()) {
            result.success(null)
            return
        }
        MediaScannerConnection.scanFile(this, arrayOf(path), null) { _, _ -> }
        result.success(null)
    }

    override fun onDestroy() {
        worker.shutdown()
        super.onDestroy()
    }
}
