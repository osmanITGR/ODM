/// App-wide bandwidth cap, shared by every worker of every download.
library;

/// Token bucket. A rate of 0 means unlimited and costs nothing to call.
///
/// Dart's single-threaded isolates make this simpler than the Python original:
/// no mutex is needed, only an await where the worker must wait for tokens.
class RateLimiter {
  RateLimiter([double bytesPerSecond = 0.0])
    : _rate = bytesPerSecond < 0 ? 0.0 : bytesPerSecond {
    _tokens = _rate;
    _updated = DateTime.now();
  }

  double _rate;
  late double _tokens;
  late DateTime _updated;

  double get rate => _rate;

  void setRate(double bytesPerSecond) {
    _rate = bytesPerSecond < 0 ? 0.0 : bytesPerSecond;
    // Dropping to a lower cap must not leave a burst of stale tokens banked.
    _tokens = _rate > 0 ? (_tokens < _rate ? _tokens : _rate) : 0.0;
    _updated = DateTime.now();
  }

  /// Wait until [amount] bytes may be read, then spend them.
  ///
  /// The bucket holds at most one second's worth of tokens, so a read larger
  /// than the current rate could never be satisfied outright. Such a read is
  /// allowed through on a full bucket and the balance carried as a debt, which
  /// the next calls pay off — otherwise lowering the limit below the socket's
  /// block size would wedge the download forever.
  Future<void> take(int amount) async {
    if (_rate <= 0) return;
    while (true) {
      final now = DateTime.now();
      final elapsed = now.difference(_updated).inMicroseconds / 1e6;
      final refilled = _tokens + elapsed * _rate;
      _tokens = refilled < _rate ? refilled : _rate;
      _updated = now;

      if (_tokens >= amount) {
        _tokens -= amount;
        return;
      }

      // Oversized read: spend everything and go into debt rather than spin.
      if (amount > _rate && _tokens >= _rate) {
        _tokens -= amount;
        return;
      }

      final deficit = amount - _tokens;
      var waitMs = (deficit / _rate * 1000).ceil();
      // Cap the sleep so a rate change mid-wait takes effect promptly.
      if (waitMs > 250) waitMs = 250;
      if (waitMs < 1) waitMs = 1;
      await Future<void>.delayed(Duration(milliseconds: waitMs));
    }
  }
}

String formatBytes(int? bytes) {
  if (bytes == null || bytes < 0) return '—';
  if (bytes < 1024) return '$bytes B';
  const units = ['KB', 'MB', 'GB', 'TB'];
  var value = bytes / 1024;
  var unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return '${value.toStringAsFixed(value >= 100 ? 0 : 1)} ${units[unit]}';
}

String formatSpeed(double bytesPerSecond) {
  if (bytesPerSecond <= 0) return '—';
  return '${formatBytes(bytesPerSecond.round())}/s';
}

String formatDuration(Duration? d) {
  if (d == null) return '—';
  final h = d.inHours;
  final m = d.inMinutes.remainder(60);
  final s = d.inSeconds.remainder(60);
  if (h > 0) return '${h}h ${m}m';
  if (m > 0) return '${m}m ${s}s';
  return '${s}s';
}
