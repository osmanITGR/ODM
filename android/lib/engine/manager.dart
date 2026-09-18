/// Download queue: runs several downloads at once, bounded by a worker pool.
///
/// A port of the Windows build's `odm/manager.py`, plus the persistence the
/// desktop app did not need: Android kills processes freely, so the queue is
/// written to disk on every change and rebuilt on launch.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:path/path.dart' as p;

import 'download_engine.dart';
import 'models.dart';
import 'muxer.dart';
import 'rate_limiter.dart';
import 'task.dart';
import 'video_models.dart';

class DownloadManager {
  DownloadManager({
    required this.destDir,
    required this.stateFile,
    this.connections = 8,
    this.concurrent = 3,
    double speedLimit = 0.0,
    this.boost = true,
  }) : limiter = RateLimiter(speedLimit);

  String destDir;
  final String stateFile;
  int connections;
  int concurrent;
  bool boost;

  /// One bucket shared by every download, so the cap is app-wide.
  final RateLimiter limiter;

  final Map<String, DownloadTask> _tasks = {};
  final Map<String, Future<void>> _running = {};

  /// Fires whenever the queue changes shape — the UI listens and rebuilds.
  final StreamController<void> _changes = StreamController<void>.broadcast();
  Stream<void> get changes => _changes.stream;

  Timer? _persistTimer;

  double get speedLimit => limiter.rate;
  set speedLimit(double bytesPerSecond) => limiter.setRate(bytesPerSecond);

  /// Visible queue entries, newest first, with muxing companions folded away.
  List<DownloadTask> get tasks {
    final visible = _tasks.values.where((t) => !t.isCompanionOf).toList();
    visible.sort((a, b) => b.addedAt.compareTo(a.addedAt));
    return visible;
  }

  DownloadTask? get(String id) => _tasks[id];

  int get activeCount => _running.length;

  (int, double) totals() {
    var active = 0;
    var speed = 0.0;
    for (final task in _tasks.values) {
      if (task.state == DownloadState.running) {
        active++;
        speed += task.progress.speed;
      }
    }
    return (active, speed);
  }

  void notify() {
    if (!_changes.isClosed) _changes.add(null);
    _schedulePersist();
  }

  // queue ------------------------------------------------------------

  DownloadTask add(
    String url, {
    String? filename,
    bool autostart = true,
    Map<String, String> headers = const {},
    String? title,
    String? thumbnail,
    String? sourcePage,
  }) {
    final task = DownloadTask(
      id: _newId(),
      addedAt: DateTime.now(),
      title: title,
      thumbnail: thumbnail,
      sourcePage: sourcePage,
      download: Download(
        url: url,
        destDir: destDir,
        connections: connections,
        filename: filename == null ? null : _uniqueName(filename),
        limiter: limiter,
        boost: boost,
        requestHeaders: headers,
      ),
    );
    _tasks[task.id] = task;
    if (autostart) pump();
    notify();
    return task;
  }

  /// Queue a video: one task, or a video+audio pair that is muxed on completion.
  DownloadTask addVideo(
    MediaInfo info,
    DownloadPlan plan, {
    String? sourcePage,
  }) {
    final primary = plan.video ?? plan.audio!;
    final finalName = _uniqueName(suggestedFilename(info, primary));

    if (!plan.needsMux) {
      return add(
        primary.url,
        filename: finalName,
        headers: primary.headers,
        title: info.title,
        thumbnail: info.thumbnail,
        sourcePage: sourcePage ?? info.webpageUrl,
      );
    }

    final stem = p.basenameWithoutExtension(finalName);
    final videoTask = add(
      plan.video!.url,
      filename: '$stem.video.${plan.video!.ext}',
      autostart: false,
      headers: plan.video!.headers,
      title: info.title,
      thumbnail: info.thumbnail,
      sourcePage: sourcePage ?? info.webpageUrl,
    );
    final audioTask = add(
      plan.audio!.url,
      filename: '$stem.audio.${plan.audio!.ext}',
      autostart: false,
      headers: plan.audio!.headers,
      title: info.title,
    );

    audioTask.isCompanionOf = true;
    videoTask.companion = audioTask;
    videoTask.muxTarget = p.join(destDir, finalName);

    pump();
    notify();
    return videoTask;
  }

  /// Avoid overwriting a file that is already there: "clip.mp4" -> "clip (2).mp4".
  String _uniqueName(String name) {
    final stem = p.basenameWithoutExtension(name);
    final ext = p.extension(name);
    var candidate = name;
    var counter = 2;
    while (_nameTaken(candidate)) {
      candidate = '$stem ($counter)$ext';
      counter++;
    }
    return candidate;
  }

  bool _nameTaken(String name) {
    final path = p.join(destDir, name);
    if (File(path).existsSync() || File('$path.part').existsSync()) return true;
    return _tasks.values.any(
      (t) => p.basename(t.download.targetPath) == name && !t.state.isTerminal,
    );
  }

  // scheduling -------------------------------------------------------

  /// Start queued downloads until the concurrency limit is reached.
  void pump() {
    _pumpMux();

    final waiting = _tasks.values
        .where(
          (t) =>
              !t.held &&
              !_running.containsKey(t.id) &&
              (t.state == DownloadState.pending ||
                  t.state == DownloadState.paused),
        )
        .toList();
    // Oldest first: a queue should drain in the order things were added.
    waiting.sort((a, b) => a.addedAt.compareTo(b.addedAt));

    final slots = max(0, concurrent - _running.length);
    for (final task in waiting.take(slots)) {
      _start(task);
    }
  }

  void _start(DownloadTask task) {
    final future = task.download.start().whenComplete(() {
      _running.remove(task.id);
      notify();
      // A finished slot may let the next queued item in, and a finished half
      // may complete a mux pair.
      pump();
    });
    _running[task.id] = future;
    notify();
  }

  /// Start muxing for any pair whose two halves have both finished.
  void _pumpMux() {
    for (final task in _tasks.values) {
      final mate = task.companion;
      if (mate == null || task.muxTarget == null || task.muxing) continue;
      if (task.download.progress.state != DownloadState.done) continue;
      if (mate.download.progress.state != DownloadState.done) continue;
      unawaited(_finishMux(task));
    }
  }

  Future<void> _finishMux(DownloadTask task) async {
    task.muxing = true;
    notify();
    try {
      await muxStreams(
        videoPath: task.download.targetPath,
        audioPath: task.companion!.download.targetPath,
        outputPath: task.muxTarget!,
      );
      await _deleteQuietly(task.download.targetPath);
      await _deleteQuietly(task.companion!.download.targetPath);
      _tasks.remove(task.companion!.id);
      task.finalPath = task.muxTarget;
      task.companion = null;
      task.muxTarget = null;
    } catch (error) {
      task.download.progress.state = DownloadState.error;
      task.download.progress.error = 'Could not join video and audio: $error';
    } finally {
      task.muxing = false;
      notify();
    }
  }

  Future<void> _deleteQuietly(String path) async {
    try {
      final file = File(path);
      if (await file.exists()) await file.delete();
    } on FileSystemException {
      // An undeleted temp file is untidy, not broken.
    }
  }

  // controls ---------------------------------------------------------

  Future<void> pause(String id) async {
    final task = _tasks[id];
    if (task == null) return;
    task.held = true;
    await task.download.pause();
    await task.companion?.download.pause();
    notify();
  }

  void resume(String id) {
    final task = _tasks[id];
    if (task == null || task.state == DownloadState.done) return;
    task.held = false;
    task.companion?.held = false;
    task.download.progress.error = null;
    pump();
    notify();
  }

  Future<void> remove(String id, {bool deleteFile = false}) async {
    final task = _tasks.remove(id);
    if (task == null) return;

    task.held = true;
    await task.download.pause();
    await task.download.discardPartial();

    final mate = task.companion;
    if (mate != null) {
      _tasks.remove(mate.id);
      await mate.download.pause();
      await mate.download.discardPartial();
    }

    if (deleteFile) await _deleteQuietly(task.resultPath);
    notify();
    pump();
  }

  Future<void> pauseAll() async {
    for (final task in _tasks.values) {
      if (task.state.isActive) {
        task.held = true;
        await task.download.pause();
      }
    }
    notify();
  }

  void resumeAll() {
    for (final task in _tasks.values) {
      if (!task.state.isTerminal) task.held = false;
    }
    pump();
    notify();
  }

  Future<void> clearCompleted() async {
    final done = _tasks.values
        .where((t) => t.state == DownloadState.done)
        .map((t) => t.id)
        .toList();
    for (final id in done) {
      _tasks.remove(id);
    }
    notify();
  }

  /// Retry a failed download from whatever it already has on disk.
  void retry(String id) {
    final task = _tasks[id];
    if (task == null) return;
    task.held = false;
    task.download.progress.state = DownloadState.pending;
    task.download.progress.error = null;
    pump();
    notify();
  }

  // persistence ------------------------------------------------------

  void _schedulePersist() {
    // Coalesce the flood of change events a running download produces into one
    // write every couple of seconds.
    _persistTimer?.cancel();
    _persistTimer = Timer(const Duration(seconds: 2), () {
      unawaited(persist());
    });
  }

  Future<void> persist() async {
    try {
      final payload = {
        'version': 1,
        'tasks': _tasks.values.map((t) => t.toJson()).toList(),
      };
      final tmp = File('$stateFile.tmp');
      await tmp.writeAsString(jsonEncode(payload), flush: true);
      await tmp.rename(stateFile);
    } catch (_) {
      // The queue is a convenience; the .part files and sidecars are the real
      // state, and those are written by the engine itself.
    }
  }

  /// Rebuild the queue from disk. Anything that was running is left paused,
  /// because a killed process cannot know how far its sockets got.
  Future<void> restore() async {
    final file = File(stateFile);
    if (!await file.exists()) return;

    Map<String, dynamic> payload;
    try {
      payload = jsonDecode(await file.readAsString()) as Map<String, dynamic>;
    } catch (_) {
      return;
    }

    final rawTasks = payload['tasks'];
    if (rawTasks is! List) return;

    final pendingCompanions = <String, String>{};

    for (final raw in rawTasks.cast<Map<String, dynamic>>()) {
      final state = DownloadState.parse(raw['state'] as String?);
      final task = DownloadTask(
        id: raw['id'] as String,
        addedAt:
            DateTime.tryParse(raw['added_at'] as String? ?? '') ??
            DateTime.now(),
        title: raw['title'] as String?,
        thumbnail: raw['thumbnail'] as String?,
        sourcePage: raw['source_page'] as String?,
        muxTarget: raw['mux_target'] as String?,
        download: Download(
          url: raw['url'] as String,
          destDir: raw['dest_dir'] as String? ?? destDir,
          connections: raw['connections'] as int? ?? connections,
          filename: raw['filename'] as String?,
          limiter: limiter,
          boost: raw['boost'] as bool? ?? boost,
          requestHeaders: Map<String, String>.from(
            (raw['headers'] as Map?) ?? const {},
          ),
        ),
      );

      task.finalPath = raw['final_path'] as String?;
      task.isCompanionOf = raw['is_companion'] as bool? ?? false;
      task.download.progress
        ..total = raw['total'] as int?
        ..downloaded = raw['downloaded'] as int? ?? 0
        ..error = raw['error'] as String?
        // Anything mid-flight when the process died comes back paused, so the
        // user chooses when to spend data resuming it.
        ..state = state.isTerminal ? state : DownloadState.paused;

      task.held = state != DownloadState.done && (raw['held'] as bool? ?? true);

      final companionId = raw['companion_id'] as String?;
      if (companionId != null) pendingCompanions[task.id] = companionId;

      _tasks[task.id] = task;
    }

    pendingCompanions.forEach((taskId, companionId) {
      _tasks[taskId]?.companion = _tasks[companionId];
    });

    // A pair whose halves both finished before the kill still needs joining.
    _pumpMux();
    notify();
  }

  Future<void> dispose() async {
    _persistTimer?.cancel();
    await persist();
    await _changes.close();
  }

  static final _random = Random();
  String _newId() =>
      List.generate(12, (_) => _random.nextInt(16).toRadixString(16)).join();
}
