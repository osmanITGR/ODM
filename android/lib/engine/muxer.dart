/// Join a separate video track and audio track into one playable file.
///
/// The Windows build shells out to ffmpeg. Android has no such binary, and
/// bundling one would add ~30 MB to the APK, so this hands the job to the
/// platform's own MediaMuxer through a method channel. It is a stream copy,
/// exactly like `ffmpeg -c copy`: no re-encoding, so it is fast and lossless.
library;

import 'dart:io';

import 'package:flutter/services.dart';

const MethodChannel _channel = MethodChannel('com.osmanit.odm/muxer');

class MuxException implements Exception {
  MuxException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Combine [videoPath] and [audioPath] into [outputPath] without re-encoding.
Future<void> muxStreams({
  required String videoPath,
  required String audioPath,
  required String outputPath,
}) async {
  for (final path in [videoPath, audioPath]) {
    if (!await File(path).exists()) {
      throw MuxException('A downloaded track is missing: $path');
    }
  }

  try {
    await _channel.invokeMethod<void>('mux', {
      'video': videoPath,
      'audio': audioPath,
      'output': outputPath,
    });
  } on PlatformException catch (error) {
    throw MuxException(error.message ?? 'MediaMuxer failed');
  } on MissingPluginException {
    throw MuxException('The muxer is unavailable on this device.');
  }

  final result = File(outputPath);
  if (!await result.exists() || await result.length() == 0) {
    throw MuxException('The joined file came out empty.');
  }
}

/// Ask the platform to index a finished file so it shows up in the gallery
/// and in other apps' file pickers.
Future<void> scanMedia(String path) async {
  try {
    await _channel.invokeMethod<void>('scanFile', {'path': path});
  } on PlatformException {
    // The file is saved either way; indexing is a nicety.
  } on MissingPluginException {
    // Older build without the channel — nothing to do.
  }
}
