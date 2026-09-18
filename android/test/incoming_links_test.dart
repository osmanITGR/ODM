/// Tests for pulling a URL out of shared text.
///
/// These are the cases that made sharing from Facebook fail: the app sends a
/// sentence with the link inside it, not a bare URL.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:odm/services/incoming_links.dart';

void main() {
  group('firstUrlIn', () {
    test('returns a bare URL unchanged', () {
      expect(
        firstUrlIn('https://fb.watch/abc123/'),
        'https://fb.watch/abc123/',
      );
    });

    test('finds the URL inside a shared sentence', () {
      // This is what the Facebook app actually sends.
      expect(
        firstUrlIn('Check this out! https://fb.watch/abc123/'),
        'https://fb.watch/abc123/',
      );
    });

    test('finds a URL followed by trailing text', () {
      expect(
        firstUrlIn('https://www.youtube.com/watch?v=abc\n\nShared via YouTube'),
        'https://www.youtube.com/watch?v=abc',
      );
    });

    test('strips sentence punctuation from the end', () {
      expect(
        firstUrlIn('Watch https://fb.watch/abc123/.'),
        'https://fb.watch/abc123/',
      );
      expect(
        firstUrlIn('Is it https://vimeo.com/12345?'),
        'https://vimeo.com/12345',
      );
      expect(
        firstUrlIn('"https://x.com/user/status/1"'),
        'https://x.com/user/status/1',
      );
    });

    test('strips an unmatched closing bracket', () {
      expect(
        firstUrlIn('(see https://fb.watch/abc/)'),
        'https://fb.watch/abc/',
      );
    });

    test('keeps brackets that belong to the URL', () {
      // Some CDNs put brackets in query strings; those must survive.
      expect(
        firstUrlIn('https://cdn.example.com/v?ids=(1,2)'),
        'https://cdn.example.com/v?ids=(1,2)',
      );
    });

    test('keeps query strings and fragments intact', () {
      expect(
        firstUrlIn('https://www.facebook.com/watch/?v=123456&t=30'),
        'https://www.facebook.com/watch/?v=123456&t=30',
      );
    });

    test('takes the first URL when the text holds several', () {
      expect(
        firstUrlIn('https://fb.watch/one/ and https://fb.watch/two/'),
        'https://fb.watch/one/',
      );
    });

    test('handles the real shapes Facebook sends', () {
      // Reel, post and short link, as shared from the Android app.
      expect(
        firstUrlIn('https://www.facebook.com/reel/1234567890'),
        'https://www.facebook.com/reel/1234567890',
      );
      expect(
        firstUrlIn(
          'Amazing video! https://www.facebook.com/share/v/abc123/ '
          'via Facebook',
        ),
        'https://www.facebook.com/share/v/abc123/',
      );
      expect(firstUrlIn('https://fb.watch/xY9zAbC/'), 'https://fb.watch/xY9zAbC/');
    });

    test('returns null when there is no link', () {
      expect(firstUrlIn('just some text'), isNull);
      expect(firstUrlIn(''), isNull);
      expect(firstUrlIn('   '), isNull);
      expect(firstUrlIn(null), isNull);
    });

    test('ignores a scheme it cannot download', () {
      expect(firstUrlIn('ftp://example.com/file.zip'), isNull);
      expect(firstUrlIn('fb://profile/123'), isNull);
    });
  });
}
