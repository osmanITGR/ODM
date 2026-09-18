/// Core data types for the download engine.
///
/// These mirror the Windows build's `odm/engine.py` so behaviour stays
/// identical across the two apps: same segment maths, same resume format.
library;

enum DownloadState {
  pending,
  probing,
  running,
  paused,
  muxing,
  done,
  error;

  /// The state persists to disk, so parse defensively: a record written by a
  /// newer build must not crash an older one.
  static DownloadState parse(String? raw) => DownloadState.values.firstWhere(
    (s) => s.name == raw,
    orElse: () => DownloadState.pending,
  );

  bool get isTerminal => this == done || this == error;
  bool get isActive => this == probing || this == running || this == muxing;
}

/// One byte range of a file, fetched down its own connection.
class Segment {
  Segment(this.index, this.start, this.end, [this.done = 0]);

  final int index;
  final int start;

  /// Inclusive, and mutable: a stealing worker moves it back to hand the tail
  /// of this range to itself.
  int end;
  int done;

  int get total => end - start + 1;
  int get remaining => total - done;
  bool get complete => done >= total;

  List<int> toJson() => [index, start, end, done];

  static Segment fromJson(List<dynamic> raw) =>
      Segment(raw[0] as int, raw[1] as int, raw[2] as int, raw[3] as int);
}

/// What a probe request revealed about the remote file.
class SourceInfo {
  const SourceInfo({
    required this.url,
    required this.size,
    required this.resumable,
    required this.filename,
  });

  /// The URL after redirects — ranged requests must go to the final host.
  final String url;
  final int? size;
  final bool resumable;
  final String filename;
}

/// A live snapshot of one download, rebuilt on every UI tick.
class Progress {
  Progress({
    this.downloaded = 0,
    this.total,
    this.speed = 0.0,
    this.state = DownloadState.pending,
    this.error,
    this.segments = const [],
  });

  int downloaded;
  int? total;
  double speed;
  DownloadState state;
  String? error;

  /// (done, total) per segment, for the progress bar's striped fill.
  List<(int, int)> segments;

  double get percent {
    final t = total;
    if (t == null || t <= 0) return 0.0;
    return (downloaded / t * 100).clamp(0.0, 100.0);
  }

  /// Seconds remaining, or null when the size or speed is not yet known.
  Duration? get eta {
    final t = total;
    if (t == null || t <= 0 || speed <= 0) return null;
    final seconds = (t - downloaded) / speed;
    if (seconds.isInfinite || seconds.isNaN || seconds < 0) return null;
    // Past a day the number stops being useful and starts overflowing.
    if (seconds > 86400 * 7) return null;
    return Duration(seconds: seconds.round());
  }
}
