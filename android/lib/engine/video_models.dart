/// Media types shared by every extractor.
///
/// Mirrors the Windows build's `odm/video.py`: an extractor resolves a page
/// into these, and ODM's own engine does the transfer — so videos get the
/// same segmented speed and resume behaviour as any other file.
library;

class ExtractorException implements Exception {
  ExtractorException(this.message, {this.isUnsupported = false});

  final String message;

  /// True when no extractor recognised the URL, as opposed to one that
  /// recognised it and failed. The UI wording differs.
  final bool isUnsupported;

  @override
  String toString() => message;
}

class MediaFormat {
  const MediaFormat({
    required this.formatId,
    required this.url,
    required this.ext,
    required this.label,
    this.filesize,
    this.height,
    this.vcodec = 'none',
    this.acodec = 'none',
    this.headers = const {},
  });

  final String formatId;
  final String url;
  final String ext;
  final String label;
  final int? filesize;
  final int? height;
  final String vcodec;
  final String acodec;

  /// Referer/Cookie the CDN requires; without these many hosts return 403.
  final Map<String, String> headers;

  bool get hasVideo => vcodec != 'none' && vcodec.isNotEmpty;
  bool get hasAudio => acodec != 'none' && acodec.isNotEmpty;

  /// True when this stream needs no muxing with a second one.
  bool get isComplete => hasVideo && hasAudio;
}

class DownloadPlan {
  const DownloadPlan({this.video, this.audio, this.needsMux = false});

  final MediaFormat? video;
  final MediaFormat? audio;
  final bool needsMux;

  List<MediaFormat> get streams =>
      [video, audio].whereType<MediaFormat>().toList();

  int? get totalSize {
    final sizes = streams.map((f) => f.filesize).toList();
    if (sizes.isEmpty || sizes.any((s) => s == null)) return null;
    return sizes.fold(0, (sum, s) => sum! + s!);
  }
}

class MediaInfo {
  const MediaInfo({
    required this.title,
    required this.webpageUrl,
    required this.formats,
    this.duration,
    this.thumbnail,
    this.uploader,
  });

  final String title;
  final String webpageUrl;
  final List<MediaFormat> formats;
  final Duration? duration;
  final String? thumbnail;
  final String? uploader;

  MediaFormat? bestComplete() {
    final candidates = formats.where((f) => f.isComplete).toList();
    if (candidates.isEmpty) return null;
    candidates.sort((a, b) {
      final byHeight = (b.height ?? 0).compareTo(a.height ?? 0);
      if (byHeight != 0) return byHeight;
      return (b.filesize ?? 0).compareTo(a.filesize ?? 0);
    });
    return candidates.first;
  }

  MediaFormat? bestAudio() {
    final candidates = formats.where((f) => f.hasAudio && !f.hasVideo).toList();
    if (candidates.isEmpty) return null;
    candidates.sort((a, b) => (b.filesize ?? 0).compareTo(a.filesize ?? 0));
    return candidates.first;
  }

  MediaFormat? bestVideo({int? maxHeight}) {
    var candidates = formats.where((f) => f.hasVideo && !f.hasAudio).toList();
    if (maxHeight != null) {
      final capped = candidates
          .where((f) => (f.height ?? 0) <= maxHeight)
          .toList();
      if (capped.isNotEmpty) candidates = capped;
    }
    if (candidates.isEmpty) return null;
    candidates.sort((a, b) {
      final byHeight = (b.height ?? 0).compareTo(a.height ?? 0);
      if (byHeight != 0) return byHeight;
      // Prefer mp4 at equal height: it muxes without re-encoding and plays
      // on every Android version.
      final byExt = (b.ext == 'mp4' ? 1 : 0).compareTo(a.ext == 'mp4' ? 1 : 0);
      if (byExt != 0) return byExt;
      return (a.filesize ?? 0).compareTo(b.filesize ?? 0);
    });
    return candidates.first;
  }

  /// Distinct heights offered, highest first — what the quality picker shows.
  List<int> videoHeights() {
    final heights = <int>{
      for (final f in formats)
        if (f.hasVideo && f.height != null) f.height!,
    };
    final sorted = heights.toList()..sort((a, b) => b.compareTo(a));
    return sorted;
  }

  /// Pick the streams needed for one playable file.
  DownloadPlan plan({int? maxHeight}) {
    final complete = bestComplete();
    if (complete != null &&
        (maxHeight == null || (complete.height ?? 0) <= maxHeight)) {
      return DownloadPlan(video: complete, needsMux: false);
    }

    final video = bestVideo(maxHeight: maxHeight);
    if (video == null) {
      final audio = bestAudio();
      if (audio == null) {
        throw ExtractorException('no downloadable streams found');
      }
      return DownloadPlan(audio: audio, needsMux: false);
    }

    if (video.hasAudio) return DownloadPlan(video: video, needsMux: false);

    final audio = bestAudio();
    return DownloadPlan(video: video, audio: audio, needsMux: audio != null);
  }
}

/// Strip characters Android will not accept in a filename.
String safeTitle(String raw) {
  var cleaned = raw
      .replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1f]'), '')
      .replaceAll(RegExp(r'\s+'), ' ')
      .trim();
  if (cleaned.isEmpty) cleaned = 'video';
  return cleaned.length > 100 ? cleaned.substring(0, 100).trim() : cleaned;
}

String suggestedFilename(MediaInfo info, MediaFormat format) {
  final quality = format.height != null ? '.${format.height}p' : '';
  return '${safeTitle(info.title)}$quality.${format.ext}';
}
