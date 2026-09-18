/// Tests for URL classification and the media models.
///
/// No network: these cover the decisions made before any request goes out,
/// plus the format-picking logic that decides what actually gets downloaded.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:odm/engine/extractor.dart';
import 'package:odm/engine/video_models.dart';

MediaFormat _format({
  required String id,
  String ext = 'mp4',
  int? height,
  int? filesize,
  String vcodec = 'none',
  String acodec = 'none',
}) => MediaFormat(
  formatId: id,
  url: 'https://cdn.example.com/$id.$ext',
  ext: ext,
  label: id,
  height: height,
  filesize: filesize,
  vcodec: vcodec,
  acodec: acodec,
);

void main() {
  group('isDirectMedia', () {
    test('recognises a file extension in the path', () {
      expect(isDirectMedia('https://example.com/clip.mp4'), isTrue);
      expect(isDirectMedia('https://example.com/song.mp3'), isTrue);
      expect(isDirectMedia('https://example.com/video.MKV'), isTrue);
    });

    test('ignores a query string after the extension', () {
      expect(
        isDirectMedia('https://cdn.example.com/a/b/clip.mp4?token=abc&x=1'),
        isTrue,
      );
    });

    test('rejects a page URL', () {
      expect(isDirectMedia('https://youtube.com/watch?v=abc'), isFalse);
      expect(isDirectMedia('https://example.com/article'), isFalse);
    });
  });

  group('isMediaPage', () {
    test('recognises the hosts people share from', () {
      for (final url in [
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'https://youtu.be/dQw4w9WgXcQ',
        'https://www.facebook.com/watch?v=123',
        'https://www.instagram.com/reel/abc/',
        'https://www.tiktok.com/@user/video/123',
        'https://x.com/user/status/123',
      ]) {
        expect(isMediaPage(url), isTrue, reason: url);
      }
    });

    test('rejects a non-http scheme', () {
      expect(isMediaPage('ftp://example.com/file'), isFalse);
      expect(isMediaPage('not a url'), isFalse);
    });

    test('a direct file is not a page to extract', () {
      expect(isMediaPage('https://example.com/clip.mp4'), isFalse);
    });

    test('does not match a lookalike host', () {
      // "youtube.com.evil.net" must not pass as YouTube.
      expect(isMediaPage('https://youtube.com.evil.net/watch?v=1'), isFalse);
    });
  });

  group('MediaInfo.plan', () {
    test('prefers a single complete stream when one exists', () {
      final info = MediaInfo(
        title: 'clip',
        webpageUrl: 'https://example.com',
        formats: [
          _format(id: 'both', height: 720, vcodec: 'avc1', acodec: 'mp4a'),
          _format(id: 'video', height: 1080, vcodec: 'avc1'),
          _format(id: 'audio', acodec: 'mp4a'),
        ],
      );

      final plan = info.plan();
      expect(plan.needsMux, isFalse);
      expect(plan.video?.formatId, 'both');
    });

    test('pairs video with audio when no complete stream fits', () {
      final info = MediaInfo(
        title: 'clip',
        webpageUrl: 'https://example.com',
        formats: [
          _format(id: 'v1080', height: 1080, vcodec: 'avc1'),
          _format(id: 'a128', acodec: 'mp4a', filesize: 1000),
        ],
      );

      final plan = info.plan();
      expect(plan.needsMux, isTrue);
      expect(plan.video?.formatId, 'v1080');
      expect(plan.audio?.formatId, 'a128');
    });

    test('honours a height cap', () {
      final info = MediaInfo(
        title: 'clip',
        webpageUrl: 'https://example.com',
        formats: [
          _format(id: 'v2160', height: 2160, vcodec: 'avc1'),
          _format(id: 'v720', height: 720, vcodec: 'avc1'),
          _format(id: 'audio', acodec: 'mp4a'),
        ],
      );

      expect(info.plan(maxHeight: 720).video?.formatId, 'v720');
    });

    test('prefers mp4 over webm at the same height', () {
      final info = MediaInfo(
        title: 'clip',
        webpageUrl: 'https://example.com',
        formats: [
          _format(id: 'webm', ext: 'webm', height: 1080, vcodec: 'vp9'),
          _format(id: 'mp4', ext: 'mp4', height: 1080, vcodec: 'avc1'),
          _format(id: 'audio', acodec: 'mp4a'),
        ],
      );

      expect(info.plan().video?.formatId, 'mp4');
    });

    test('falls back to audio-only when there is no video track', () {
      final info = MediaInfo(
        title: 'song',
        webpageUrl: 'https://example.com',
        formats: [_format(id: 'a256', ext: 'm4a', acodec: 'mp4a')],
      );

      final plan = info.plan();
      expect(plan.needsMux, isFalse);
      expect(plan.audio?.formatId, 'a256');
      expect(plan.video, isNull);
    });

    test('throws when nothing is downloadable', () {
      final info = MediaInfo(
        title: 'empty',
        webpageUrl: 'https://example.com',
        formats: const [],
      );

      expect(() => info.plan(), throwsA(isA<ExtractorException>()));
    });
  });

  group('DownloadPlan.totalSize', () {
    test('adds both halves when each size is known', () {
      final plan = DownloadPlan(
        video: _format(id: 'v', filesize: 1000, vcodec: 'avc1'),
        audio: _format(id: 'a', filesize: 200, acodec: 'mp4a'),
        needsMux: true,
      );
      expect(plan.totalSize, 1200);
    });

    test('is null when any half has an unknown size', () {
      final plan = DownloadPlan(
        video: _format(id: 'v', filesize: 1000, vcodec: 'avc1'),
        audio: _format(id: 'a', acodec: 'mp4a'),
        needsMux: true,
      );
      expect(plan.totalSize, isNull);
    });
  });

  group('videoHeights', () {
    test('lists distinct heights, highest first', () {
      final info = MediaInfo(
        title: 'clip',
        webpageUrl: 'https://example.com',
        formats: [
          _format(id: 'a', height: 720, vcodec: 'avc1'),
          _format(id: 'b', height: 1080, vcodec: 'avc1'),
          _format(id: 'c', height: 720, vcodec: 'vp9'),
          _format(id: 'd', acodec: 'mp4a'),
        ],
      );

      expect(info.videoHeights(), [1080, 720]);
    });
  });

  group('safeTitle', () {
    test('strips characters Android will not accept in a filename', () {
      expect(safeTitle('a/b\\c:d*e?f"g<h>i|j'), 'abcdefghij');
    });

    test('collapses runs of whitespace', () {
      expect(safeTitle('My    Great   Video'), 'My Great Video');
    });

    test('supplies a default when nothing usable is left', () {
      expect(safeTitle('///'), 'video');
      expect(safeTitle('   '), 'video');
    });

    test('caps the length so the path stays valid', () {
      expect(safeTitle('x' * 300).length, lessThanOrEqualTo(100));
    });
  });

  group('suggestedFilename', () {
    test('includes the quality when a height is known', () {
      final info = MediaInfo(
        title: 'My Video',
        webpageUrl: 'https://example.com',
        formats: const [],
      );
      final format = _format(id: 'v', height: 1080, vcodec: 'avc1');
      expect(suggestedFilename(info, format), 'My Video.1080p.mp4');
    });

    test('omits the quality for an audio track', () {
      final info = MediaInfo(
        title: 'My Song',
        webpageUrl: 'https://example.com',
        formats: const [],
      );
      final format = _format(id: 'a', ext: 'm4a', acodec: 'mp4a');
      expect(suggestedFilename(info, format), 'My Song.m4a');
    });
  });
}
