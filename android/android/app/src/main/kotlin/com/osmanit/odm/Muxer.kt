package com.osmanit.odm

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import java.io.File
import java.nio.ByteBuffer

/**
 * Joins a video-only file and an audio-only file into one MP4.
 *
 * This is a stream copy — the encoded samples are moved across untouched, the
 * same thing `ffmpeg -c copy` does — so it costs a file copy rather than a
 * re-encode, and loses no quality.
 */
object Muxer {

    /** Samples are read one at a time; this bounds the buffer for 4K bitrates. */
    private const val BUFFER_SIZE = 1 shl 20

    fun mux(videoPath: String, audioPath: String, outputPath: String) {
        val output = File(outputPath)
        output.parentFile?.mkdirs()
        // A leftover from a failed attempt would otherwise be appended to.
        if (output.exists()) output.delete()

        var muxer: MediaMuxer? = null
        val extractors = mutableListOf<MediaExtractor>()

        try {
            muxer = MediaMuxer(outputPath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)

            val video = openTrack(videoPath, "video/")
                ?: throw MuxError("No video track found in the downloaded file.")
            val audio = openTrack(audioPath, "audio/")
                ?: throw MuxError("No audio track found in the downloaded file.")
            extractors += video.extractor
            extractors += audio.extractor

            val videoOut = muxer.addTrack(video.format)
            val audioOut = muxer.addTrack(audio.format)

            // Rotation lives on the container, not the samples, so it has to be
            // carried over explicitly or portrait clips come out sideways.
            video.format.getIntegerOrNull(MediaFormat.KEY_ROTATION)?.let {
                muxer.setOrientationHint(it)
            }

            muxer.start()
            copySamples(video, videoOut, muxer)
            copySamples(audio, audioOut, muxer)
            muxer.stop()
        } catch (error: MuxError) {
            output.delete()
            throw error
        } catch (error: Exception) {
            output.delete()
            throw MuxError(error.message ?: error.javaClass.simpleName)
        } finally {
            try {
                muxer?.release()
            } catch (_: Exception) {
                // stop() already failed; releasing is best effort.
            }
            extractors.forEach {
                try {
                    it.release()
                } catch (_: Exception) {
                }
            }
        }
    }

    private class Track(
        val extractor: MediaExtractor,
        val format: MediaFormat,
        val index: Int,
    )

    private fun openTrack(path: String, mimePrefix: String): Track? {
        val extractor = MediaExtractor()
        extractor.setDataSource(path)
        for (i in 0 until extractor.trackCount) {
            val format = extractor.getTrackFormat(i)
            val mime = format.getString(MediaFormat.KEY_MIME) ?: continue
            if (mime.startsWith(mimePrefix)) {
                extractor.selectTrack(i)
                return Track(extractor, format, i)
            }
        }
        extractor.release()
        return null
    }

    private fun copySamples(track: Track, outputIndex: Int, muxer: MediaMuxer) {
        val buffer = ByteBuffer.allocate(BUFFER_SIZE)
        val info = MediaCodec.BufferInfo()
        val extractor = track.extractor

        while (true) {
            buffer.clear()
            val size = extractor.readSampleData(buffer, 0)
            if (size < 0) break

            info.offset = 0
            info.size = size
            info.presentationTimeUs = extractor.sampleTime
            info.flags = extractor.sampleFlags

            muxer.writeSampleData(outputIndex, buffer, info)
            if (!extractor.advance()) break
        }
    }

    private fun MediaFormat.getIntegerOrNull(key: String): Int? =
        if (containsKey(key)) getInteger(key) else null

    class MuxError(message: String) : Exception(message)
}
