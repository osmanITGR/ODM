/// Completion notifications.
///
/// The running-downloads notification belongs to the native foreground
/// service; this covers the one-off "finished" and "failed" messages.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:open_filex/open_filex.dart';

class Notifications {
  static final _plugin = FlutterLocalNotificationsPlugin();
  static bool _ready = false;

  static Future<void> init() async {
    if (_ready) return;
    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
    );
    await _plugin.initialize(
      settings,
      onDidReceiveNotificationResponse: (response) {
        // Tapping a completion notification opens the file itself, which is
        // what the user wanted when they started the download.
        final path = response.payload;
        if (path != null && path.isNotEmpty) OpenFilex.open(path);
      },
    );
    _ready = true;
  }

  static const _completed = AndroidNotificationDetails(
    'odm_completed',
    'Completed downloads',
    channelDescription: 'Shown when a download finishes',
    importance: Importance.defaultImportance,
    priority: Priority.defaultPriority,
  );

  static const _failed = AndroidNotificationDetails(
    'odm_failed',
    'Failed downloads',
    channelDescription: 'Shown when a download cannot be completed',
    importance: Importance.defaultImportance,
    priority: Priority.defaultPriority,
  );

  static Future<void> downloadComplete(String name, String path) async {
    if (!_ready) return;
    try {
      await _plugin.show(
        path.hashCode & 0x7fffffff,
        'Download finished',
        name,
        const NotificationDetails(android: _completed),
        payload: path,
      );
    } catch (error) {
      debugPrint('notification failed: $error');
    }
  }

  static Future<void> downloadFailed(String name, String reason) async {
    if (!_ready) return;
    try {
      await _plugin.show(
        name.hashCode & 0x7fffffff,
        'Download failed',
        '$name — $reason',
        const NotificationDetails(android: _failed),
      );
    } catch (error) {
      debugPrint('notification failed: $error');
    }
  }
}
