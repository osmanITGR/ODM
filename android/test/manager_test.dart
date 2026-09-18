/// Tests for the queue: persistence, naming, and ordering.
///
/// Android kills processes without warning, so the queue is written to disk
/// and rebuilt on launch. These cover that round trip and the cases where a
/// bad file must not take the app down with it.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:odm/engine/manager.dart';
import 'package:odm/engine/models.dart';
import 'package:path/path.dart' as p;

void main() {
  late Directory dir;
  late String stateFile;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('odm_test');
    stateFile = p.join(dir.path, 'queue.json');
  });

  tearDown(() async {
    if (await dir.exists()) await dir.delete(recursive: true);
  });

  DownloadManager manager() =>
      DownloadManager(destDir: dir.path, stateFile: stateFile);

  group('persistence', () {
    test('the queue survives a restart', () async {
      final first = manager();
      first.add('https://example.com/a.zip',
          autostart: false, filename: 'a.zip');
      first.add('https://example.com/b.mp4',
          autostart: false, filename: 'b.mp4');
      await first.persist();

      final second = manager();
      await second.restore();

      expect(second.tasks.length, 2);
      expect(
        second.tasks.map((t) => t.name).toList()..sort(),
        ['a.zip', 'b.mp4'],
      );
    });

    test('nothing resumes on its own after a restart', () async {
      // A killed process cannot know how far its sockets got, so everything
      // comes back paused rather than silently spending the user's data.
      final first = manager();
      first.add('https://example.com/a.zip',
          autostart: false, filename: 'a.zip');
      await first.persist();

      final second = manager();
      await second.restore();

      expect(second.tasks.single.state, DownloadState.paused);
    });

    test('a task the user paused stays held', () async {
      final first = manager();
      final task = first.add('https://example.com/a.zip',
          autostart: false, filename: 'a.zip');
      task.held = true;
      await first.persist();

      final second = manager();
      await second.restore();

      expect(second.tasks.single.held, isTrue);
    });

    test('a finished download comes back finished', () async {
      final first = manager();
      final task = first.add('https://example.com/a.zip',
          autostart: false, filename: 'a.zip');
      task.download.progress
        ..state = DownloadState.done
        ..total = 1000
        ..downloaded = 1000;
      await first.persist();

      final second = manager();
      await second.restore();

      expect(second.tasks.single.state, DownloadState.done);
      expect(second.tasks.single.held, isFalse);
    });

    test('a corrupt state file is ignored rather than fatal', () async {
      await File(stateFile).writeAsString('{ not json at all');

      final m = manager();
      await m.restore();

      expect(m.tasks, isEmpty);
    });

    test('a state file from a newer build does not crash', () async {
      // An unknown state name must not take the app down.
      await File(stateFile).writeAsString(
        '{"version":99,"tasks":[{"id":"abc","url":"https://x/a.zip",'
        '"state":"teleporting","added_at":"2026-01-01T00:00:00.000"}]}',
      );

      final m = manager();
      await m.restore();

      expect(m.tasks.single.state, DownloadState.paused);
    });

    test('a missing state file is simply an empty queue', () async {
      final m = manager();
      await m.restore();
      expect(m.tasks, isEmpty);
    });
  });

  group('naming', () {
    test('a second download of the same name does not overwrite the first',
        () async {
      await File(p.join(dir.path, 'clip.mp4')).writeAsString('already here');

      final m = manager();
      final task =
          m.add('https://example.com/clip.mp4', autostart: false, filename: 'clip.mp4');

      expect(task.name, 'clip (2).mp4');
    });

    test('queued names are counted too, not just files on disk', () {
      final m = manager();
      m.add('https://a.com/clip.mp4', autostart: false, filename: 'clip.mp4');
      final second =
          m.add('https://b.com/clip.mp4', autostart: false, filename: 'clip.mp4');

      expect(second.name, 'clip (2).mp4');
    });
  });

  group('ordering', () {
    test('the newest download is listed first', () async {
      final m = manager();
      m.add('https://example.com/first.zip',
          autostart: false, filename: 'first.zip');
      // The list sorts by timestamp, which needs to actually differ.
      await Future<void>.delayed(const Duration(milliseconds: 5));
      m.add('https://example.com/second.zip',
          autostart: false, filename: 'second.zip');

      expect(m.tasks.first.name, 'second.zip');
    });
  });
}
