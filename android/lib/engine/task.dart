/// One entry in the download queue.
library;

import 'package:path/path.dart' as p;

import 'download_engine.dart';
import 'models.dart';

class DownloadTask {
  DownloadTask({
    required this.id,
    required this.download,
    required this.addedAt,
    this.companion,
    this.muxTarget,
    this.title,
    this.thumbnail,
    this.sourcePage,
  });

  final String id;
  final Download download;
  final DateTime addedAt;

  /// Set for the video half of a muxed pair: the audio task it waits for.
  DownloadTask? companion;

  /// Where the two halves are joined, once both have finished.
  String? muxTarget;

  /// Set when the user pauses, so the queue does not restart it on its own.
  bool held = false;
  bool muxing = false;
  String? finalPath;

  /// Video metadata, kept for the list tile.
  String? title;
  String? thumbnail;
  String? sourcePage;

  /// True for the audio half of a pair, which the UI hides behind its video.
  bool isCompanionOf = false;

  String get resultPath => finalPath ?? muxTarget ?? download.targetPath;

  String get name => p.basename(resultPath);

  DownloadState get state =>
      muxing ? DownloadState.muxing : download.progress.state;

  Progress get progress => download.progress;

  /// Combined progress across both halves of a muxed pair.
  double get percent {
    final mate = companion;
    if (mate == null) return progress.percent;
    final mine = progress.total ?? 0;
    final theirs = mate.progress.total ?? 0;
    if (mine + theirs == 0) return progress.percent;
    final done = progress.downloaded + mate.progress.downloaded;
    return (done / (mine + theirs) * 100).clamp(0.0, 100.0);
  }

  int get downloaded =>
      progress.downloaded + (companion?.progress.downloaded ?? 0);

  int? get totalBytes {
    final mine = progress.total;
    final mate = companion?.progress.total;
    if (mine == null) return null;
    if (companion == null) return mine;
    if (mate == null) return null;
    return mine + mate;
  }

  double get speed => progress.speed + (companion?.progress.speed ?? 0);

  Map<String, dynamic> toJson() => {
    'id': id,
    'url': download.url,
    'dest_dir': download.destDir,
    'filename': download.filename,
    'connections': download.connections,
    'boost': download.boost,
    'headers': download.requestHeaders,
    'state': state.name,
    'held': held,
    'added_at': addedAt.toIso8601String(),
    'total': progress.total,
    'downloaded': progress.downloaded,
    'title': title,
    'thumbnail': thumbnail,
    'source_page': sourcePage,
    'mux_target': muxTarget,
    'final_path': finalPath,
    'companion_id': companion?.id,
    'is_companion': isCompanionOf,
    'error': progress.error,
  };
}
