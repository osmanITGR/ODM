/// Links handed to ODM from elsewhere on the phone.
///
/// This is the mobile answer to the desktop build's browser extension. Apps
/// are inconsistent about how they share — some send the bare URL, some wrap
/// it in a sentence, some pass it as the intent's data rather than an extra —
/// so the native side normalises all of that and this just receives URLs.
library;

import 'dart:async';

import 'package:flutter/services.dart';

const MethodChannel _channel = MethodChannel('com.osmanit.odm/links');

/// Pull the first URL out of shared text.
///
/// Apps rarely send a bare URL. Facebook sends a sentence for reels and posts
/// ("Check this out! https://fb.watch/xyz/"), YouTube appends the title, and
/// several append tracking text after the link. Taking the whole string as a
/// URL is what made shares from those apps fail.
String? firstUrlIn(String? text) {
  if (text == null || text.trim().isEmpty) return null;

  final match = RegExp(r'https?://\S+').firstMatch(text);
  if (match == null) return null;

  var url = match.group(0)!;

  // Trailing punctuation is common when the URL ends a sentence. A closing
  // bracket is only stripped when it has no opener inside the URL, since some
  // CDNs put brackets in query strings.
  const trailing = ['.', ',', ';', ':', '!', '?', '"', "'", '>', '»'];
  while (url.isNotEmpty && trailing.contains(url[url.length - 1])) {
    url = url.substring(0, url.length - 1);
  }
  for (final (open, close) in [('(', ')'), ('[', ']'), ('{', '}')]) {
    while (url.endsWith(close) &&
        !url.substring(0, url.length - 1).contains(open)) {
      url = url.substring(0, url.length - 1);
    }
  }

  return url.isEmpty ? null : url;
}

class IncomingLinks {
  IncomingLinks._();

  static final IncomingLinks instance = IncomingLinks._();

  final StreamController<String> _controller =
      StreamController<String>.broadcast();

  /// Links arriving while the app is already open.
  Stream<String> get stream => _controller.stream;

  bool _listening = false;

  void start() {
    if (_listening) return;
    _listening = true;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'onLink') {
        final url = firstUrlIn(call.arguments as String?);
        if (url != null) _controller.add(url);
      }
    });
  }

  /// The link that launched the app, if it was started by a share or a tap.
  ///
  /// Returns null on an ordinary launch. Safe to call before [start].
  Future<String?> initialLink() async {
    try {
      return firstUrlIn(await _channel.invokeMethod<String>('getInitialLink'));
    } on PlatformException {
      return null;
    } on MissingPluginException {
      return null;
    }
  }

  Future<void> dispose() async {
    _listening = false;
    await _controller.close();
  }
}
