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
