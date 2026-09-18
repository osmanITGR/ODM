/// Tests for the segment maths and the rate limiter.
///
/// These mirror the Windows build's `tests/test_engine.py`. They are pure
/// logic tests with no sockets: the things worth catching here are off-by-one
/// errors in range planning, which silently corrupt a downloaded file.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:odm/engine/download_engine.dart';
import 'package:odm/engine/models.dart';
import 'package:odm/engine/rate_limiter.dart';

void main() {
  group('planSegments', () {
    test('covers every byte exactly once, with no gaps or overlaps', () {
      const size = 10 * 1024 * 1024;
      final segments = planSegments(size, 8);

      expect(segments.first.start, 0);
      expect(segments.last.end, size - 1);

      for (var i = 1; i < segments.length; i++) {
        expect(
          segments[i].start,
          segments[i - 1].end + 1,
          reason: 'segment $i must start where ${i - 1} ended',
        );
      }

      final covered = segments.fold(0, (sum, s) => sum + s.total);
      expect(covered, size);
    });

    test('does not create segments smaller than the minimum chunk', () {
      // 3 MB over 8 connections would be 384 KB each; the planner should
      // merge down to 3 segments of 1 MB instead.
      final segments = planSegments(3 * 1024 * 1024, 8);
      expect(segments.length, 3);
    });

    test('falls back to a single segment for a tiny file', () {
      final segments = planSegments(500, 8);
      expect(segments.length, 1);
      expect(segments.single.total, 500);
    });

    test('spreads the remainder so totals still add up', () {
      // 10 bytes over 3 parts cannot divide evenly.
      final segments = planSegments(10, 3, minChunk: 1);
      expect(segments.map((s) => s.total).toList(), [4, 3, 3]);
      expect(segments.last.end, 9);
    });
  });

  group('Segment', () {
    test('reports remaining and completion from done', () {
      final segment = Segment(0, 100, 199);
      expect(segment.total, 100);
      expect(segment.remaining, 100);
      expect(segment.complete, isFalse);

      segment.done = 100;
      expect(segment.remaining, 0);
      expect(segment.complete, isTrue);
    });

    test('survives a round trip through JSON', () {
      final original = Segment(3, 1000, 1999, 250);
      final restored = Segment.fromJson(original.toJson());

      expect(restored.index, original.index);
      expect(restored.start, original.start);
      expect(restored.end, original.end);
      expect(restored.done, original.done);
    });
  });

  group('RateLimiter', () {
    test('an unlimited bucket never waits', () async {
      final limiter = RateLimiter(0);
      final started = DateTime.now();
      for (var i = 0; i < 100; i++) {
        await limiter.take(1024 * 1024);
      }
      expect(DateTime.now().difference(started).inMilliseconds, lessThan(100));
    });

    test('a capped bucket delays once its tokens run out', () async {
      // 10 KB/s, spend 20 KB: the second half has to wait for a refill.
      final limiter = RateLimiter(10 * 1024);
      await limiter.take(10 * 1024);

      final started = DateTime.now();
      await limiter.take(5 * 1024);
      final waited = DateTime.now().difference(started).inMilliseconds;

      expect(waited, greaterThan(200));
    });

    test('lowering the rate does not leave a burst of stale tokens banked',
        () async {
      final limiter = RateLimiter(1024 * 1024);
      limiter.setRate(1024);
      expect(limiter.rate, 1024);

      // The old bucket held 1 MB; after the drop it must hold at most 1 KB, so
      // a 1 KB read empties it and the next one has to wait for a refill.
      await limiter.take(1024);
      final started = DateTime.now();
      await limiter.take(512);
      expect(
        DateTime.now().difference(started).inMilliseconds,
        greaterThan(200),
      );
    });

    test('a read larger than the rate completes instead of hanging', () async {
      // The bucket caps at one second's worth, so a 64 KB socket block at
      // 1 KB/s can never be covered outright. It must still go through.
      final limiter = RateLimiter(1024);
      await limiter
          .take(64 * 1024)
          .timeout(
            const Duration(seconds: 5),
            onTimeout: () => fail('take() hung on an oversized read'),
          );
    });

    test('an oversized read is paid back before the next one proceeds',
        () async {
      final limiter = RateLimiter(1024);
      await limiter.take(4096);

      // Four seconds of debt was just incurred; the next read cannot be free.
      final started = DateTime.now();
      await limiter
          .take(256)
          .timeout(const Duration(seconds: 10), onTimeout: () => fail('hung'));
      expect(
        DateTime.now().difference(started).inMilliseconds,
        greaterThan(200),
      );
    });
  });

  group('Progress', () {
    test('percent stays within bounds even past the stated total', () {
      final progress = Progress(downloaded: 150, total: 100);
      expect(progress.percent, 100.0);
    });

    test('percent is zero when the total is unknown', () {
      expect(Progress(downloaded: 500).percent, 0.0);
    });

    test('eta is null without a speed or a total', () {
      expect(Progress(downloaded: 10, total: 100).eta, isNull);
      expect(Progress(downloaded: 10, speed: 100).eta, isNull);
    });

    test('eta divides the remaining bytes by the speed', () {
      final progress = Progress(downloaded: 500, total: 1500, speed: 100);
      expect(progress.eta, const Duration(seconds: 10));
    });

    test('an absurd eta is suppressed rather than shown', () {
      // A stalled download must not claim "412 days left".
      final progress = Progress(downloaded: 0, total: 1000000000, speed: 0.001);
      expect(progress.eta, isNull);
    });
  });

  group('filenameFrom', () {
    test('falls back to the URL path when there is no header', () {
      expect(
        filenameFrom('https://example.com/files/report.pdf', null),
        'report.pdf',
      );
    });

    test('decodes a percent-encoded path', () {
      expect(
        filenameFrom('https://example.com/my%20file.zip', null),
        'my file.zip',
      );
    });

    test('supplies a default when the URL carries no name', () {
      expect(filenameFrom('https://example.com/', null), 'download');
    });
  });

  group('DownloadState', () {
    test('parses a name written by another build', () {
      expect(DownloadState.parse('running'), DownloadState.running);
      expect(DownloadState.parse('done'), DownloadState.done);
    });

    test('falls back to pending for an unknown name', () {
      // A record written by a newer build must not crash an older one.
      expect(DownloadState.parse('teleporting'), DownloadState.pending);
      expect(DownloadState.parse(null), DownloadState.pending);
    });
  });

  group('formatting', () {
    test('scales byte counts to a readable unit', () {
      expect(formatBytes(512), '512 B');
      expect(formatBytes(1536), '1.5 KB');
      expect(formatBytes(5 * 1024 * 1024), '5.0 MB');
      expect(formatBytes(null), '—');
    });

    test('renders durations at a sensible granularity', () {
      expect(formatDuration(const Duration(seconds: 45)), '45s');
      expect(formatDuration(const Duration(minutes: 3, seconds: 20)), '3m 20s');
      expect(formatDuration(const Duration(hours: 2, minutes: 5)), '2h 5m');
      expect(formatDuration(null), '—');
    });
  });
}
