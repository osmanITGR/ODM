/// Resolve a page URL into downloadable media streams.
///
/// The Windows build hands this job to yt-dlp. Android cannot run it without
/// embedding a Python runtime, so extraction happens here: site-specific
/// readers for the hosts people actually share from, then a generic reader
/// that scrapes embedded players and meta tags, then a last check for whether
/// the URL is simply a direct media file.
library;

import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'download_engine.dart' show probe;
import 'video_models.dart';

/// A desktop UA gets the full-quality player markup; the mobile site often
/// serves a stripped-down one with only low bitrates.
const String _browserUa =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36';

const Set<String> _mediaExtensions = {
  'mp4', 'mkv', 'webm', 'avi', 'mov', 'flv', 'm4v', '3gp', 'ts', 'mpg', 'mpeg',
  'mp3', 'm4a', 'aac', 'ogg', 'opus', 'wav', 'flac', 'wma',
};

/// True when the URL points straight at a media file rather than a page.
bool isDirectMedia(String url) {
  try {
    final ext = p.extension(Uri.parse(url).path).replaceFirst('.', '').toLowerCase();
    return _mediaExtensions.contains(ext);
  } catch (_) {
    return false;
  }
}

/// Cheap check for whether a URL is worth handing to the extractor.
bool isMediaPage(String url) {
  final lower = url.toLowerCase();
  if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
    return false;
  }
  if (isDirectMedia(url)) return false;

  const hosts = [
    'youtube.com', 'youtu.be', 'facebook.com', 'fb.watch', 'fb.com',
    'instagram.com', 'instagr.am', 'tiktok.com', 'twitter.com', 'x.com',
    'vimeo.com', 'dailymotion.com', 'dai.ly', 'reddit.com', 'redd.it',
    'twitch.tv', 'pinterest.com', 'pin.it', 'linkedin.com', 'snapchat.com',
    'tumblr.com', 'soundcloud.com', 'bilibili.com', 'ok.ru', 'vk.com',
    'rumble.com', 'odysee.com', 'streamable.com', 'imgur.com', 'likee.video',
    'threads.net', 'kuaishou.com', 'weibo.com', 'douyin.com',
  ];
  try {
    final host = Uri.parse(url).host.toLowerCase().replaceFirst('www.', '');
    return hosts.any((h) => host == h || host.endsWith('.$h'));
  } catch (_) {
    return false;
  }
}

/// Resolve [url] into its media formats without downloading any of them.
Future<MediaInfo> extract(
  String url, {
  Duration timeout = const Duration(seconds: 30),
}) async {
  final normalised = _normaliseUrl(url);

  // A direct file link needs no extractor at all — probe it and present the
  // one stream it is.
  if (isDirectMedia(normalised)) {
    return _directMediaInfo(normalised, timeout: timeout);
  }

  final host = _hostOf(normalised);

  if (host.contains('youtube.com') || host.contains('youtu.be')) {
    return _extractYouTube(normalised, timeout: timeout);
  }

  final page = await _fetchPage(normalised, timeout: timeout);
  final generic = _extractFromMarkup(normalised, page, host);
  if (generic != null) return generic;

  // The page may itself be a redirect to a media file (many short links are).
  try {
    final info = await probe(normalised, timeout: timeout);
    if (isDirectMedia(info.url) || _looksLikeMedia(info.filename)) {
      return _directMediaInfo(info.url, timeout: timeout);
    }
  } on Exception {
    // Fall through to the unsupported message below.
  }

  throw ExtractorException(
    'Could not find a downloadable video on this page.',
    isUnsupported: true,
  );
}

String _normaliseUrl(String url) {
  var cleaned = url.trim();
  if (!cleaned.startsWith('http://') && !cleaned.startsWith('https://')) {
    cleaned = 'https://$cleaned';
  }
  return cleaned;
}

String _hostOf(String url) {
  try {
    return Uri.parse(url).host.toLowerCase().replaceFirst('www.', '');
  } catch (_) {
    return '';
  }
}

bool _looksLikeMedia(String filename) {
  final ext = p.extension(filename).replaceFirst('.', '').toLowerCase();
  return _mediaExtensions.contains(ext);
}

/// Build a one-format MediaInfo for a URL that is already a media file.
Future<MediaInfo> _directMediaInfo(
  String url, {
  required Duration timeout,
}) async {
  int? size;
  var filename = p.basename(Uri.parse(url).path);
  try {
    final info = await probe(url, timeout: timeout);
    size = info.size;
    if (info.filename.isNotEmpty) filename = info.filename;
  } on Exception {
    // A probe failure is not fatal here: the engine will probe again when the
    // download starts, and the user still gets a usable entry now.
  }

  final ext = p.extension(filename).replaceFirst('.', '').toLowerCase();
  final isAudio = {
    'mp3', 'm4a', 'aac', 'ogg', 'opus', 'wav', 'flac', 'wma',
  }.contains(ext);

  return MediaInfo(
    title: safeTitle(p.basenameWithoutExtension(filename)),
    webpageUrl: url,
    formats: [
      MediaFormat(
        formatId: 'direct',
        url: url,
        ext: ext.isEmpty ? 'mp4' : ext,
        label: isAudio ? 'Audio ($ext)' : 'Original ($ext)',
        filesize: size,
        vcodec: isAudio ? 'none' : 'unknown',
        acodec: 'unknown',
      ),
    ],
  );
}

Future<String> _fetchPage(
  String url, {
  required Duration timeout,
  Map<String, String> extraHeaders = const {},
}) async {
  final client = HttpClient()
    ..connectionTimeout = timeout
    ..userAgent = _browserUa;
  try {
    final request = await client.getUrl(Uri.parse(url)).timeout(timeout);
    request.headers.set('user-agent', _browserUa);
    request.headers.set(
      'accept',
      'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    );
    request.headers.set('accept-language', 'en-US,en;q=0.9');
    extraHeaders.forEach(request.headers.set);

    final response = await request.close().timeout(timeout);
    if (response.statusCode >= 400) {
      throw ExtractorException(
        'The page could not be opened (HTTP ${response.statusCode}). '
        'It may be private or region-locked.',
      );
    }
    return await response.transform(utf8.decoder).join().timeout(timeout);
  } on SocketException {
    throw ExtractorException('No internet connection.');
  } finally {
    client.close(force: true);
  }
}

// -------------------------------------------------------------------------
// Generic markup reader
// -------------------------------------------------------------------------

/// Pull media URLs out of a page's markup.
///
/// Covers Open Graph video tags, JSON-LD, bare <video>/<source> elements, and
/// the JSON blobs Facebook/Instagram/TikTok embed their playback URLs in.
MediaInfo? _extractFromMarkup(String pageUrl, String html, String host) {
  final title = _readTitle(html);
  final thumbnail = _readMeta(html, 'og:image');
  final formats = <MediaFormat>[];
  final seen = <String>{};

  void add(
    String rawUrl, {
    required String label,
    int? height,
    String vcodec = 'unknown',
    String acodec = 'unknown',
  }) {
    final url = _cleanUrl(rawUrl);
    if (url == null || !seen.add(url)) return;
    final ext = _extensionOf(url);
    formats.add(
      MediaFormat(
        formatId: 'gen${formats.length}',
        url: url,
        ext: ext,
        label: label,
        height: height,
        vcodec: vcodec,
        acodec: acodec,
        // The CDN checks Referer on most of these hosts.
        headers: {'Referer': pageUrl, 'User-Agent': _browserUa},
      ),
    );
  }

  // Facebook and Instagram ship their playback URLs in escaped JSON. Quality
  // is named in the key, which is the only reliable height hint available.
  for (final match in RegExp(
    r'"(playable_url_quality_hd|browser_native_hd_url|hd_src|playable_url|'
    r'browser_native_sd_url|sd_src|video_url|progressive_url)"\s*:\s*"([^"]+)"',
  ).allMatches(html)) {
    final key = match.group(1)!;
    final isHd = key.contains('hd') || key.contains('quality_hd');
    add(
      match.group(2)!,
      label: isHd ? 'HD (mp4)' : 'SD (mp4)',
      height: isHd ? 720 : 360,
    );
  }

  // TikTok's SIGI_STATE / universal data blob.
  for (final match in RegExp(
    r'"(playAddr|downloadAddr)"\s*:\s*"([^"]+)"',
  ).allMatches(html)) {
    add(
      match.group(2)!,
      label: match.group(1) == 'downloadAddr'
          ? 'Original (mp4)'
          : 'Playback (mp4)',
    );
  }

  // Open Graph — the most widely implemented signal of "this page is a video".
  for (final property in ['og:video:secure_url', 'og:video:url', 'og:video']) {
    final value = _readMeta(html, property);
    if (value != null) add(value, label: 'Video (${_extensionOf(value)})');
  }
  final twitterStream = _readMeta(html, 'twitter:player:stream');
  if (twitterStream != null) add(twitterStream, label: 'Stream (mp4)');

  // Bare HTML5 players. The attribute may be single- or double-quoted, so the
  // closing quote is matched by class rather than by backreference.
  for (final match in RegExp(
    '<(?:video|source|audio)[^>]+src\\s*=\\s*["\']([^"\']+)["\']',
    caseSensitive: false,
  ).allMatches(html)) {
    final url = match.group(1)!;
    if (url.startsWith('blob:') || url.startsWith('data:')) continue;
    add(_absolute(pageUrl, url), label: 'Embedded (${_extensionOf(url)})');
  }

  // JSON-LD contentUrl, used by news sites and most CMS video plugins.
  for (final match in RegExp(
    r'"contentUrl"\s*:\s*"([^"]+)"',
  ).allMatches(html)) {
    add(match.group(1)!, label: 'Content (${_extensionOf(match.group(1)!)})');
  }

  if (formats.isEmpty) return null;

  // Highest quality first, so the default pick is the best one.
  formats.sort((a, b) => (b.height ?? 0).compareTo(a.height ?? 0));

  return MediaInfo(
    title: safeTitle(title ?? host),
    webpageUrl: pageUrl,
    formats: formats,
    thumbnail: thumbnail,
  );
}

String? _readMeta(String html, String property) {
  final patterns = [
    RegExp(
      '<meta[^>]+(?:property|name)=["\']${RegExp.escape(property)}["\'][^>]+content=["\']([^"\']+)["\']',
      caseSensitive: false,
    ),
    RegExp(
      '<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']${RegExp.escape(property)}["\']',
      caseSensitive: false,
    ),
  ];
  for (final pattern in patterns) {
    final match = pattern.firstMatch(html);
    if (match != null) return _unescapeHtml(match.group(1)!);
  }
  return null;
}

String? _readTitle(String html) {
  final og = _readMeta(html, 'og:title');
  if (og != null && og.trim().isNotEmpty) return og;
  final match = RegExp(
    r'<title[^>]*>([^<]+)</title>',
    caseSensitive: false,
  ).firstMatch(html);
  return match == null ? null : _unescapeHtml(match.group(1)!).trim();
}

/// Undo the escaping that survives in embedded JSON and HTML attributes, and
/// reject anything that is not a plain ranged-fetchable URL.
String? _cleanUrl(String raw) {
  var url = raw
      .replaceAll(r'\/', '/')
      .replaceAll(r'%', '%')
      .replaceAll(r'\\', r'\')
      .trim();
  url = _unescapeHtml(url);

  // Unicode escapes appear inside the JSON blobs Facebook and TikTok embed.
  url = url.replaceAllMapped(
    RegExp(r'\\u([0-9a-fA-F]{4})'),
    (m) => String.fromCharCode(int.parse(m.group(1)!, radix: 16)),
  );

  if (!url.startsWith('http://') && !url.startsWith('https://')) return null;
  // Fragmented playlists cannot be fetched as one ranged file.
  if (url.contains('.m3u8') || url.contains('.mpd')) return null;
  return url;
}

String _unescapeHtml(String value) => value
    .replaceAll('&amp;', '&')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
    .replaceAll('&#039;', "'")
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>');

String _absolute(String base, String maybeRelative) {
  if (maybeRelative.startsWith('http')) return maybeRelative;
  try {
    return Uri.parse(base).resolve(maybeRelative).toString();
  } catch (_) {
    return maybeRelative;
  }
}

String _extensionOf(String url) {
  try {
    final ext = p
        .extension(Uri.parse(url).path)
        .replaceFirst('.', '')
        .toLowerCase();
    return _mediaExtensions.contains(ext) ? ext : 'mp4';
  } catch (_) {
    return 'mp4';
  }
}

// -------------------------------------------------------------------------
// YouTube
// -------------------------------------------------------------------------

/// Resolve a YouTube watch URL through the InnerTube player endpoint.
///
/// The watch page itself no longer carries usable stream URLs, and the ones it
/// does carry are signature-ciphered. The Android client's player response
/// returns unciphered URLs, which is the only route that works without a
/// JavaScript interpreter on board.
Future<MediaInfo> _extractYouTube(
  String url, {
  required Duration timeout,
}) async {
  final videoId = _youTubeId(url);
  if (videoId == null) {
    throw ExtractorException('That does not look like a YouTube video link.');
  }

  final client = HttpClient()..connectionTimeout = timeout;
  try {
    final request = await client
        .postUrl(Uri.parse('https://www.youtube.com/youtubei/v1/player'))
        .timeout(timeout);
    request.headers.set('content-type', 'application/json');
    request.headers.set(
      'user-agent',
      'com.google.android.youtube/19.09.37 (Linux; U; Android 14) gzip',
    );
    request.headers.set('x-youtube-client-name', '3');
    request.headers.set('x-youtube-client-version', '19.09.37');

    request.write(
      jsonEncode({
        'videoId': videoId,
        'context': {
          'client': {
            'clientName': 'ANDROID',
            'clientVersion': '19.09.37',
            'androidSdkVersion': 34,
            'hl': 'en',
            'gl': 'US',
          },
        },
        'contentCheckOk': true,
        'racyCheckOk': true,
      }),
    );

    final response = await request.close().timeout(timeout);
    final body = await response.transform(utf8.decoder).join().timeout(timeout);
    final data = jsonDecode(body) as Map<String, dynamic>;

    final status = data['playabilityStatus'] as Map<String, dynamic>?;
    final playable = status?['status'] as String?;
    if (playable != null && playable != 'OK') {
      throw ExtractorException(
        _youTubeStatusMessage(playable, status?['reason'] as String?),
      );
    }

    final details = data['videoDetails'] as Map<String, dynamic>? ?? {};
    final streaming =
        data['streamingData'] as Map<String, dynamic>? ?? const {};

    final raw = <Map<String, dynamic>>[
      ...(streaming['formats'] as List? ?? const []).cast(),
      ...(streaming['adaptiveFormats'] as List? ?? const []).cast(),
    ];

    final formats = <MediaFormat>[];
    for (final entry in raw) {
      final streamUrl = entry['url'] as String?;
      // A ciphered stream needs the player's JS to unscramble; skip it rather
      // than queue a download that would 403.
      if (streamUrl == null || streamUrl.isEmpty) continue;

      final mime = (entry['mimeType'] as String?) ?? '';
      final height = entry['height'] as int?;
      final ext = _mimeToExtension(mime);
      final hasVideo = mime.startsWith('video/');
      final hasAudio =
          mime.startsWith('audio/') || (entry['audioQuality'] != null && hasVideo);

      String label;
      if (hasVideo && height != null) {
        label = '${height}p ($ext)';
        final fps = entry['fps'] as int?;
        if (fps != null && fps > 30) label = '${height}p$fps ($ext)';
      } else if (mime.startsWith('audio/')) {
        final bitrate = entry['bitrate'] as int?;
        label = bitrate != null
            ? 'Audio ${(bitrate / 1000).round()}k ($ext)'
            : 'Audio ($ext)';
      } else {
        label = entry['qualityLabel'] as String? ?? 'Stream ($ext)';
      }

      formats.add(
        MediaFormat(
          formatId: '${entry['itag'] ?? formats.length}',
          url: streamUrl,
          ext: ext,
          label: label,
          filesize: int.tryParse('${entry['contentLength'] ?? ''}'),
          height: height,
          vcodec: hasVideo ? _codecOf(mime, 0) : 'none',
          acodec: mime.startsWith('audio/')
              ? _codecOf(mime, 0)
              : (hasAudio ? 'aac' : 'none'),
        ),
      );
    }

    if (formats.isEmpty) {
      throw ExtractorException(
        'YouTube did not return any downloadable streams for this video. '
        'It may be protected or streamed live.',
      );
    }

    final seconds = int.tryParse('${details['lengthSeconds'] ?? ''}');
    return MediaInfo(
      title: safeTitle(details['title'] as String? ?? 'video'),
      webpageUrl: 'https://www.youtube.com/watch?v=$videoId',
      duration: seconds == null ? null : Duration(seconds: seconds),
      thumbnail: _youTubeThumbnail(details),
      uploader: details['author'] as String?,
      formats: formats,
    );
  } on FormatException {
    throw ExtractorException('YouTube returned an unreadable response.');
  } on SocketException {
    throw ExtractorException('No internet connection.');
  } finally {
    client.close(force: true);
  }
}

String _youTubeStatusMessage(String status, String? reason) {
  switch (status) {
    case 'LOGIN_REQUIRED':
      return 'This video is private or age-restricted, so it cannot be '
          'downloaded without signing in.';
    case 'UNPLAYABLE':
      return reason ?? 'YouTube will not play this video here.';
    case 'LIVE_STREAM_OFFLINE':
      return 'This is a live stream and cannot be downloaded.';
    case 'ERROR':
      return reason ?? 'This video is unavailable.';
    default:
      return reason ?? 'YouTube refused this video ($status).';
  }
}

String? _youTubeThumbnail(Map<String, dynamic> details) {
  final thumbnails =
      (details['thumbnail'] as Map<String, dynamic>?)?['thumbnails'] as List?;
  if (thumbnails == null || thumbnails.isEmpty) return null;
  return (thumbnails.last as Map<String, dynamic>)['url'] as String?;
}

String? _youTubeId(String url) {
  try {
    final uri = Uri.parse(url);
    final host = uri.host.toLowerCase();
    if (host.contains('youtu.be')) {
      final segments = uri.pathSegments;
      return segments.isEmpty ? null : segments.first;
    }
    final v = uri.queryParameters['v'];
    if (v != null && v.isNotEmpty) return v;
    // /shorts/<id>, /embed/<id>, /live/<id>
    final segments = uri.pathSegments;
    for (final prefix in ['shorts', 'embed', 'live', 'v']) {
      final index = segments.indexOf(prefix);
      if (index != -1 && index + 1 < segments.length) {
        return segments[index + 1];
      }
    }
  } catch (_) {
    return null;
  }
  return null;
}

String _mimeToExtension(String mime) {
  if (mime.contains('mp4')) return 'mp4';
  if (mime.contains('webm')) return 'webm';
  if (mime.contains('3gpp')) return '3gp';
  if (mime.startsWith('audio/mp4')) return 'm4a';
  return 'mp4';
}

String _codecOf(String mime, int index) {
  final match = RegExp(r'codecs="([^"]+)"').firstMatch(mime);
  if (match == null) return 'unknown';
  final parts = match.group(1)!.split(',');
  return index < parts.length ? parts[index].trim() : 'unknown';
}
