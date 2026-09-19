/// Tests for version comparison and release-note summarising.
///
/// The app is installed from a GitHub release rather than a store, so this
/// is the only thing that tells anyone a new one exists. The comparison is
/// where a mistake is expensive: too strict and nobody is told, too loose and
/// everyone is told at every launch.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:odm/services/updater.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('check interval', () {
    // GitHub allows 60 unauthenticated calls an hour per address, shared by
    // everyone behind it, so the automatic check is daily rather than at
    // every launch.
    setUp(() => SharedPreferences.setMockInitialValues({}));

    test('the first run checks', () async {
      expect(await shouldCheckForUpdate(), isTrue);
    });

    test('reopening the app soon after does not', () async {
      await noteUpdateChecked();
      expect(await shouldCheckForUpdate(), isFalse);
    });

    test('it checks again the next day', () async {
      final yesterday = DateTime.now()
          .subtract(const Duration(hours: 25))
          .millisecondsSinceEpoch;
      SharedPreferences.setMockInitialValues({
        'last_update_check': yesterday,
      });
      expect(await shouldCheckForUpdate(), isTrue);
    });

    test('a shorter interval can be asked for', () async {
      await noteUpdateChecked();
      expect(
        await shouldCheckForUpdate(interval: Duration.zero),
        isTrue,
      );
    });
  });

  group('parseVersion', () {
    test('splits a plain version', () {
      expect(parseVersion('1.3.1'), [1, 3, 1]);
    });

    test('drops a leading v', () {
      expect(parseVersion('v1.3.1'), [1, 3, 1]);
    });

    test('ignores a pre-release suffix', () {
      expect(parseVersion('1.0.0-beta.2'), [1, 0, 0]);
      expect(parseVersion('1.0.0+build7'), [1, 0, 0]);
    });

    test('a malformed tag does not throw', () {
      // A bad tag on the release must not crash the app at launch.
      expect(() => parseVersion('not-a-version'), returnsNormally);
    });
  });

  group('compareVersions', () {
    test('a higher patch is newer', () {
      expect(compareVersions('1.3.1', '1.3.0'), 1);
    });

    test('an older version is not newer', () {
      expect(compareVersions('1.3.0', '1.3.1'), -1);
    });

    test('equal versions compare equal', () {
      expect(compareVersions('1.3.1', '1.3.1'), 0);
    });

    test('missing components count as zero', () {
      // 1.3 and 1.3.0 are the same release written two ways.
      expect(compareVersions('1.3', '1.3.0'), 0);
    });

    test('numbers compare numerically, not as text', () {
      // The classic trap: "1.10" sorts before "1.9" alphabetically.
      expect(compareVersions('1.10.0', '1.9.0'), 1);
      expect(compareVersions('1.9.0', '1.10.0'), -1);
    });

    test('a major bump outranks a large minor', () {
      expect(compareVersions('2.0.0', '1.99.99'), 1);
    });

    test('a v prefix on either side is ignored', () {
      expect(compareVersions('v1.4', '1.3.1'), 1);
      expect(compareVersions('1.4', 'v1.3.1'), 1);
    });
  });

  group('Release.isNewerThan', () {
    Release at(String version) =>
        Release(version: version, tag: 'v$version', notes: '');

    test('offers a newer release', () {
      expect(at('1.4.0').isNewerThan('1.3.1'), isTrue);
    });

    test('does not offer the installed version', () {
      expect(at('1.3.1').isNewerThan('1.3.1'), isFalse);
    });

    test('does not offer an older release', () {
      // A rolled-back release must not push people backwards.
      expect(at('1.2.0').isNewerThan('1.3.1'), isFalse);
    });
  });

  group('summariseNotes', () {
    test('keeps only the bullet points', () {
      const notes = '''
## Download

Some prose about installing.

- Fixed the thing
- Fixed the other thing

More prose.
''';
      final summary = summariseNotes(notes);
      expect(summary, contains('Fixed the thing'));
      expect(summary, isNot(contains('prose')));
      expect(summary, isNot(contains('##')));
    });

    test('strips markdown that would show literally', () {
      expect(summariseNotes('- **Bold** item'), isNot(contains('**')));
      expect(summariseNotes('- A `code` item'), isNot(contains('`')));
    });

    test('accepts the bullet characters the notes actually use', () {
      expect(summariseNotes('* Star item'), contains('Star item'));
      expect(summariseNotes('• Dot item'), contains('Dot item'));
    });

    test('notes with no bullets summarise to nothing', () {
      expect(summariseNotes('Just a sentence.'), isEmpty);
      expect(summariseNotes(''), isEmpty);
    });

    test('long notes are cut at a line boundary', () {
      final notes = List.generate(
        40,
        (i) => '- item number $i with some text',
      ).join('\n');
      final summary = summariseNotes(notes, limit: 120);

      expect(summary.length, lessThanOrEqualTo(120));
      // Cut between lines, not mid-word.
      expect(summary.endsWith('item'), isFalse);
    });

    test('non-ascii notes survive', () {
      // The release notes are written in Bengali.
      final summary = summariseNotes('- ফেসবুক ভিডিও এখন নামে');
      expect(summary, contains('ফেসবুক'));
    });
  });
}
