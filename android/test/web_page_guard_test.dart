/// Tests for refusing to download a web page as if it were a file.
///
/// Pointing ODM at a video page used to save the HTML itself: a few hundred KB
/// of markup carrying a video's filename, which looks exactly like a corrupt
/// download. These cover the guard that stops it.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:odm/engine/download_engine.dart';

/// Serves whatever content type a test asks for, so the guard can be exercised
/// without reaching the network.
Future<HttpServer> _serve({
  required String contentType,
  String? disposition,
  int status = 200,
  String body = 'x',
}) async {
  final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
  server.listen((request) async {
    request.response.statusCode = status;
    request.response.headers.set('content-type', contentType);
    if (disposition != null) {
      request.response.headers.set('content-disposition', disposition);
    }
    request.response.write(body);
    await request.response.close();
  });
  return server;
}

void main() {
  group('probe rejects web pages', () {
    test('refuses text/html', () async {
      final server = await _serve(contentType: 'text/html; charset=utf-8');
      addTearDown(() => server.close(force: true));

      await expectLater(
        probe('http://127.0.0.1:${server.port}/video-page'),
        throwsA(isA<NotAFileException>()),
      );
    });

    test('refuses application/xhtml+xml', () async {
      final server = await _serve(contentType: 'application/xhtml+xml');
      addTearDown(() => server.close(force: true));

      await expectLater(
        probe('http://127.0.0.1:${server.port}/page'),
        throwsA(isA<NotAFileException>()),
      );
    });

    test('allows html the server marks as an attachment', () async {
      // Someone genuinely saving an .html file should not be blocked.
      final server = await _serve(
        contentType: 'text/html',
        disposition: 'attachment; filename="saved.html"',
      );
      addTearDown(() => server.close(force: true));

      final info = await probe('http://127.0.0.1:${server.port}/f');
      expect(info.filename, 'saved.html');
    });

    test('allows a real media type', () async {
      final server = await _serve(contentType: 'video/mp4');
      addTearDown(() => server.close(force: true));

      final info = await probe('http://127.0.0.1:${server.port}/clip.mp4');
      expect(info.filename, 'clip.mp4');
    });

    test('allows an unknown type', () async {
      // Plenty of file servers send octet-stream; that must still work.
      final server = await _serve(contentType: 'application/octet-stream');
      addTearDown(() => server.close(force: true));

      final info = await probe('http://127.0.0.1:${server.port}/file.bin');
      expect(info.filename, 'file.bin');
    });

    test('the message tells the user what to do instead', () {
      final message = NotAFileException('https://example.com/watch').toString();
      expect(message, contains('web page'));
      expect(message, contains('Check link'));
    });
  });
}
