/// Segmented HTTP download engine.
///
/// A port of the Windows build's `odm/engine.py`. The transfer runs on Dart's
/// event loop rather than threads: each segment is an async task doing
/// non-blocking socket reads, so parallelism costs no extra threads and the
/// UI isolate never blocks.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;

import 'package:crypto/crypto.dart';
import 'package:path/path.dart' as p;

import 'models.dart';
import 'rate_limiter.dart';

const String userAgent = 'ODM/1.0 (+com.osmanit.odm)';
const int chunkSize = 256 * 1024;

/// Segments below this are not worth splitting further mid-flight.
const int minSplit = 2 * 1024 * 1024;

/// Without boost we stay conservative: a couple of streams is enough to cover
/// per-connection throttling without hammering the server.
const int plainConnections = 2;

/// Split [size] into roughly equal ranges, avoiding uselessly small parts.
List<Segment> planSegments(
  int size,
  int connections, {
  int minChunk = 1024 * 1024,
}) {
  final byChunk = size ~/ minChunk;
  final count = math.max(1, math.min(connections, byChunk == 0 ? 1 : byChunk));
  final base = size ~/ count;
  final extra = size % count;

  final segments = <Segment>[];
  var cursor = 0;
  for (var i = 0; i < count; i++) {
    final length = base + (i < extra ? 1 : 0);
    segments.add(Segment(i, cursor, cursor + length - 1));
    cursor += length;
  }
  return segments;
}

/// Read a filename from Content-Disposition, falling back to the URL path.
String filenameFrom(String url, HttpHeaders? headers) {
  final disposition = headers?.value('content-disposition') ?? '';

  // RFC 5987 form wins when present: it carries the real encoding.
  final extended = RegExp(
    r"""filename\*\s*=\s*([^']*)'([^']*)'([^;]+)""",
    caseSensitive: false,
  ).firstMatch(disposition);
  if (extended != null) {
    final decoded = _tryUnquote(extended.group(3)!.trim());
    final name = _sanitiseFilename(p.basename(decoded));
    if (name.isNotEmpty) return name;
  }

  final plain = RegExp(
    r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)',
    caseSensitive: false,
  ).firstMatch(disposition);
  if (plain != null) {
    final raw = (plain.group(1) ?? plain.group(2) ?? '').trim();
    final name = _sanitiseFilename(p.basename(_tryUnquote(raw)));
    if (name.isNotEmpty) return name;
  }

  try {
    final path = Uri.parse(url).path;
    final name = _sanitiseFilename(p.basename(Uri.decodeComponent(path)));
    if (name.isNotEmpty) return name;
  } catch (_) {
    // A malformed URL just means we fall through to the default name.
  }
  return 'download';
}

String _tryUnquote(String value) {
  try {
    return Uri.decodeComponent(value);
  } catch (_) {
    return value;
  }
}

/// Strip characters that are illegal in Android filenames.
String _sanitiseFilename(String name) {
  var cleaned = name.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1f]'), '_').trim();
  // A leading dot would hide the file from the gallery and most file managers.
  while (cleaned.startsWith('.')) {
    cleaned = cleaned.substring(1);
  }
  if (cleaned.length > 150) {
    final ext = p.extension(cleaned);
    cleaned = cleaned.substring(0, 150 - ext.length) + ext;
  }
  return cleaned;
}

/// Discover size, resumability and filename without fetching the body.
Future<SourceInfo> probe(
  String url, {
  Duration timeout = const Duration(seconds: 20),
  Map<String, String> headers = const {},
}) async {
  final client = HttpClient()..connectionTimeout = timeout;
  try {
    final request = await client.getUrl(Uri.parse(url)).timeout(timeout);
    request.headers.set('user-agent', userAgent);
    request.headers.set('accept-encoding', 'identity');
    // One byte is enough to learn the total from Content-Range.
    request.headers.set('range', 'bytes=0-0');
    headers.forEach(request.headers.set);

    final response = await request.close().timeout(timeout);
    final finalUrl = _resolveFinalUrl(url, response);
    final contentRange = response.headers.value('content-range') ?? '';

    // Drain the single byte so the connection can be reused or closed cleanly.
    await response.drain<void>().timeout(timeout, onTimeout: () {});

    if (response.statusCode == 206 && contentRange.contains('/')) {
      final tail = contentRange.split('/').last.trim();
      final size = int.tryParse(tail);
      return SourceInfo(
        url: finalUrl,
        size: size,
        resumable: size != null && size > 0,
        filename: filenameFrom(finalUrl, response.headers),
      );
    }

    if (response.statusCode >= 400) {
      throw HttpException(
        'server returned ${response.statusCode}',
        uri: Uri.parse(url),
      );
    }

    // 200 to a ranged request means ranges are ignored: single stream only.
    final length = response.headers.contentLength;
    return SourceInfo(
      url: finalUrl,
      size: length > 0 ? length : null,
      resumable: false,
      filename: filenameFrom(finalUrl, response.headers),
    );
  } finally {
    client.close(force: true);
  }
}

String _resolveFinalUrl(String original, HttpClientResponse response) {
  final redirects = response.redirects;
  if (redirects.isEmpty) return original;
  return redirects.last.location.toString();
}

/// A single download: segmented and resumable when the server allows it.
class Download {
  Download({
    required this.url,
    required this.destDir,
    this.connections = 8,
    String? filename,
    this.timeout = const Duration(seconds: 30),
    RateLimiter? limiter,
    this.boost = true,
    this.requestHeaders = const {},
  }) : _forcedName = filename,
       limiter = limiter ?? RateLimiter();

  final String url;
  final String destDir;
  final int connections;
  final Duration timeout;
  final RateLimiter limiter;
  final bool boost;

  /// Extra headers a video extractor needs (Referer, Cookie) to be accepted.
  final Map<String, String> requestHeaders;

  String? _forcedName;

  SourceInfo? info;
  List<Segment> segments = [];
  final Progress progress = Progress();

  bool _stop = false;
  bool _paused = false;
  String? _lastError;

  /// Rolling window of (timestamp, bytes) used to compute the live speed.
  final List<(DateTime, int)> _samples = [];
  DateTime _windowStart = DateTime.now();

  /// Held open so pause() can tear a stalled socket down immediately rather
  /// than waiting out its timeout.
  final List<HttpClient> _clients = [];

  /// How many streams to open. This is what the boost toggle buys you.
  int get activeConnections =>
      boost ? connections : math.min(connections, plainConnections);

  String get filename =>
      _forcedName ?? info?.filename ?? p.basename(Uri.parse(url).path);

  String get targetPath => p.join(destDir, filename.isEmpty ? 'download' : filename);

  String get partPath => '$targetPath.part';

  /// Keyed by URL, not by filename: resume has to find this before the remote
  /// filename is known.
  String get metaPath {
    final digest = sha256.convert(utf8.encode(url)).toString().substring(0, 16);
    return p.join(destDir, '.odm-$digest.json');
  }

  // state persistence -------------------------------------------------

  Future<void> _saveMeta() async {
    final source = info;
    if (source == null || segments.isEmpty) return;
    final payload = {
      'url': url,
      'final_url': source.url,
      'size': source.size,
      'filename': p.basename(targetPath),
      'segments': segments.map((s) => s.toJson()).toList(),
    };
    try {
      // Write-then-rename, so a kill mid-write cannot leave a truncated file
      // that would silently discard the whole download's progress.
      final tmp = File('$metaPath.tmp');
      await tmp.writeAsString(jsonEncode(payload), flush: true);
      await tmp.rename(metaPath);
    } on FileSystemException {
      // Losing one checkpoint only costs a little re-downloading on resume.
    }
  }

  Future<bool> _loadMeta() async {
    final meta = File(metaPath);
    if (!await meta.exists()) return false;

    Map<String, dynamic> payload;
    try {
      payload = jsonDecode(await meta.readAsString()) as Map<String, dynamic>;
    } catch (_) {
      return false;
    }

    if (payload['url'] != url) return false;
    final rawSegments = payload['segments'];
    if (rawSegments is! List || rawSegments.isEmpty) return false;

    final size = payload['size'] as int?;
    final restored = SourceInfo(
      url: (payload['final_url'] as String?) ?? url,
      size: size,
      resumable: true,
      filename: (payload['filename'] as String?) ?? 'download',
    );

    // partPath derives from info/_forcedName, so commit those before checking
    // that the partial data is actually still on disk.
    final savedInfo = info;
    final savedName = _forcedName;
    info = restored;
    _forcedName = _forcedName ?? payload['filename'] as String?;

    final part = File(partPath);
    if (!await part.exists() || await part.length() != (size ?? -1)) {
      info = savedInfo;
      _forcedName = savedName;
      return false;
    }

    segments = rawSegments
        .map((raw) => Segment.fromJson(raw as List<dynamic>))
        .toList();
    progress.downloaded = segments.fold(0, (sum, s) => sum + s.done);
    progress.total = size;
    return true;
  }

  // speed -------------------------------------------------------------

  void _noteBytes(int count) {
    final now = DateTime.now();
    progress.downloaded += count;
    _samples.add((now, count));

    final cutoff = now.subtract(const Duration(seconds: 3));
    while (_samples.isNotEmpty && _samples.first.$1.isBefore(cutoff)) {
      // The evicted sample's timestamp is where the retained window now begins.
      _windowStart = _samples.removeAt(0).$1;
    }
    if (_windowStart.isBefore(cutoff)) _windowStart = cutoff;

    if (_samples.length > 1) {
      // Measure from just before the first retained sample, so its bytes are
      // counted over the window that actually produced them.
      final span = now.difference(_windowStart).inMicroseconds / 1e6;
      final moved = _samples.fold(0, (sum, s) => sum + s.$2);
      progress.speed = span > 0 ? moved / span : 0.0;
    }
  }

  // work stealing -----------------------------------------------------

  bool get _workOutstanding => segments.any((s) => !s.complete);

  /// Halve the largest lagging segment and take the tail of it.
  ///
  /// Without this, one slow connection holds up the whole transfer while the
  /// workers that already finished sit idle.
  Segment? _stealWork() {
    if (!boost) return null;

    Segment? candidate;
    var bestRemaining = minSplit;
    for (final segment in segments) {
      if (segment.complete) continue;
      if (segment.remaining > bestRemaining) {
        candidate = segment;
        bestRemaining = segment.remaining;
      }
    }
    if (candidate == null) return null;

    // Cut the untouched tail in half; the original worker keeps writing into
    // the front half and stops at the new boundary.
    final splitAt = candidate.end - bestRemaining ~/ 2;
    if (splitAt <= candidate.start + candidate.done) return null;

    final tail = Segment(segments.length, splitAt + 1, candidate.end);
    candidate.end = splitAt;
    segments.add(tail);
    return tail;
  }

  // workers -----------------------------------------------------------

  /// Fetch a segment, then keep stealing work until nothing is left.
  ///
  /// A worker that runs dry does not exit while other segments are still
  /// lagging: it splits the tail off the slowest one and helps finish it.
  /// That is what makes boost measurably faster rather than a label.
  Future<void> _worker(Segment initial, RandomAccessFile handle) async {
    Segment? segment = initial;
    while (segment != null && !_stop) {
      await _fetchSegment(segment, handle);
      if (_stop || !segment.complete) return;

      segment = _stealWork();
      while (segment == null && boost && _workOutstanding && !_stop) {
        // Nothing splittable yet, but peers are still going. Wait for a laggard
        // to fall far enough behind to be worth halving.
        await Future<void>.delayed(const Duration(milliseconds: 250));
        if (_stop) return;
        segment = _stealWork();
      }
    }
  }

  Future<void> _fetchSegment(Segment segment, RandomAccessFile handle) async {
    var attempt = 0;
    while (!segment.complete && !_stop) {
      await _awaitResume();
      if (_stop) return;

      final start = segment.start + segment.done;
      final client = HttpClient()..connectionTimeout = timeout;
      _clients.add(client);

      try {
        final request = await client
            .getUrl(Uri.parse(info!.url))
            .timeout(timeout);
        request.headers.set('user-agent', userAgent);
        request.headers.set('accept-encoding', 'identity');
        request.headers.set('range', 'bytes=$start-${segment.end}');
        requestHeaders.forEach(request.headers.set);

        final response = await request.close().timeout(timeout);
        if (response.statusCode != 206 && response.statusCode != 200) {
          throw HttpException('HTTP ${response.statusCode}');
        }

        var writeAt = start;
        await for (final block in response.timeout(timeout)) {
          if (_stop) {
            await response.detachSocket().then((s) => s.destroy()).catchError(
              (_) {},
            );
            return;
          }
          await _awaitResume();
          if (_stop) return;

          await limiter.take(block.length);

          // A stealer may have moved segment.end since this response opened,
          // so never write past it.
          final wanted = segment.remaining;
          if (wanted <= 0) return;
          final data = block.length > wanted ? block.sublist(0, wanted) : block;

          await handle.setPosition(writeAt);
          await handle.writeFrom(data);
          writeAt += data.length;
          segment.done += data.length;
          _noteBytes(data.length);

          if (segment.complete) return;
        }

        // The stream ended without filling the range: treat as a dropped
        // connection and retry from where it stopped.
        if (!segment.complete && !_stop) {
          throw const HttpException('connection closed early');
        }
      } catch (error) {
        if (_stop) return;
        _lastError = _describeError(error);
        attempt++;
        // Back off a little on repeated failures, but keep retrying: a phone
        // switching cell towers should recover on its own.
        final backoff = math.min(attempt, 5);
        await Future<void>.delayed(Duration(seconds: backoff));
      } finally {
        _clients.remove(client);
        client.close(force: true);
      }
    }
  }

  /// Fallback for servers that ignore Range: one stream, no resume.
  Future<void> _singleStream() async {
    final client = HttpClient()..connectionTimeout = timeout;
    _clients.add(client);
    final part = File(partPath);
    final sink = part.openWrite();

    try {
      final request = await client.getUrl(Uri.parse(info!.url)).timeout(timeout);
      request.headers.set('user-agent', userAgent);
      request.headers.set('accept-encoding', 'identity');
      requestHeaders.forEach(request.headers.set);

      final response = await request.close().timeout(timeout);
      if (response.statusCode >= 400) {
        throw HttpException('HTTP ${response.statusCode}');
      }

      await for (final block in response.timeout(timeout)) {
        if (_stop) return;
        await _awaitResume();
        if (_stop) return;
        await limiter.take(block.length);
        sink.add(block);
        _noteBytes(block.length);
      }
    } finally {
      await sink.close();
      _clients.remove(client);
      client.close(force: true);
    }
  }

  Future<void> _awaitResume() async {
    while (_paused && !_stop) {
      await Future<void>.delayed(const Duration(milliseconds: 150));
    }
  }

  String _describeError(Object error) {
    if (error is SocketException) {
      return 'network unreachable — ${error.osError?.message ?? error.message}';
    }
    if (error is TimeoutException) return 'connection timed out';
    if (error is HttpException) return error.message;
    if (error is FileSystemException) {
      return 'storage error — ${error.osError?.message ?? error.message}';
    }
    return error.toString();
  }

  // public API --------------------------------------------------------

  Future<void> start() async {
    _stop = false;
    _paused = false;
    _lastError = null;
    // A resumed download must not average against its old idle gap.
    _samples.clear();
    _windowStart = DateTime.now();
    progress.error = null;

    RandomAccessFile? handle;
    Timer? checkpoint;

    try {
      await Directory(destDir).create(recursive: true);

      final resumed = await _loadMeta();
      if (!resumed) {
        progress.state = DownloadState.probing;
        info = await probe(url, timeout: timeout, headers: requestHeaders);
        progress.total = info!.size;

        if (info!.resumable && (info!.size ?? 0) > 0) {
          segments = planSegments(info!.size!, activeConnections);
          // Preallocate so each worker can write straight into its own region
          // with no reassembly step at the end.
          final part = await File(partPath).create(recursive: true);
          final raf = await part.open(mode: FileMode.write);
          await raf.truncate(info!.size!);
          await raf.close();
          await _saveMeta();
        } else {
          segments = [];
        }
      }

      progress.state = DownloadState.running;

      if (segments.isNotEmpty) {
        handle = await File(partPath).open(mode: FileMode.append);

        // Checkpoint on a timer rather than per block: resume only needs to be
        // roughly current, and writing the sidecar on every chunk would cost
        // more than the bytes it saves.
        checkpoint = Timer.periodic(const Duration(seconds: 2), (_) {
          progress.segments = [for (final s in segments) (s.done, s.total)];
          unawaited(_saveMeta());
        });

        final pending = segments.where((s) => !s.complete).toList();
        await Future.wait([for (final s in pending) _worker(s, handle)]);

        checkpoint.cancel();
        progress.segments = [for (final s in segments) (s.done, s.total)];
      } else {
        await _singleStream();
      }

      if (_stop) {
        progress.state = DownloadState.paused;
        await _saveMeta();
        return;
      }

      final incomplete = segments.where((s) => !s.complete).toList();
      if (incomplete.isNotEmpty) {
        progress.state = DownloadState.error;
        progress.error = _lastError ?? 'download incomplete';
        await _saveMeta();
        return;
      }

      await handle?.close();
      handle = null;

      await File(partPath).rename(targetPath);
      await File(metaPath).delete().catchError((_) => File(metaPath));

      progress.state = DownloadState.done;
      if (progress.total != null) progress.downloaded = progress.total!;
      progress.speed = 0.0;
    } catch (error) {
      progress.state = _stop ? DownloadState.paused : DownloadState.error;
      if (!_stop) progress.error = _describeError(error);
    } finally {
      checkpoint?.cancel();
      await handle?.close().catchError((_) {});
    }
  }

  Future<void> pause() async {
    _paused = true;
    _stop = true;
    progress.state = DownloadState.paused;
    progress.speed = 0.0;
    // Tear down in-flight sockets so a stalled read does not hold the pause up
    // for the full timeout.
    for (final client in List.of(_clients)) {
      client.close(force: true);
    }
    _clients.clear();
    await _saveMeta();
  }

  Future<void> resume() async {
    if (progress.state == DownloadState.running ||
        progress.state == DownloadState.done) {
      return;
    }
    await start();
  }

  /// Delete the partial file and its checkpoint.
  Future<void> discardPartial() async {
    for (final path in [partPath, metaPath]) {
      try {
        final file = File(path);
        if (await file.exists()) await file.delete();
      } on FileSystemException {
        // Nothing useful to do if the OS refuses; the file is already orphaned.
      }
    }
  }
}
