/// Owns the download manager and connects it to the platform.
///
/// Everything with a side effect outside the queue lives here: starting and
/// stopping the foreground service, firing completion notifications, honouring
/// the Wi-Fi-only setting, and indexing finished files so other apps see them.
library;

import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../engine/manager.dart';
import '../engine/models.dart';
import '../engine/muxer.dart';
import '../engine/task.dart';
import 'notifications.dart';
import 'settings.dart';
import 'storage.dart';

const MethodChannel _platform = MethodChannel('com.osmanit.odm/muxer');

class AppController extends ChangeNotifier {
  AppController({required this.manager, required this.settings}) {
    _subscription = manager.changes.listen((_) => _onQueueChanged());
    settings.addListener(_applySettings);
    _watchConnectivity();
  }

  final DownloadManager manager;
  final Settings settings;

  late final StreamSubscription<void> _subscription;
  StreamSubscription<List<ConnectivityResult>>? _connectivity;

  /// Tracks which tasks have already had their completion notification, so a
  /// rebuild does not fire it again.
  final Set<String> _announced = {};

  bool _serviceActive = false;
  bool _onMeteredConnection = false;

  /// True when downloads are held back because the user asked for Wi-Fi only.
  bool get blockedByWifiRule => settings.wifiOnly && _onMeteredConnection;

  static Future<AppController> create() async {
    final settings = await Settings.load();
    final destDir = settings.destDir ?? await Storage.defaultDownloadDir();
    final stateFile = await Storage.stateFilePath();

    final manager = DownloadManager(
      destDir: destDir,
      stateFile: stateFile,
      connections: settings.connections,
      concurrent: settings.concurrent,
      speedLimit: settings.speedLimitBytes,
      boost: settings.boost,
    );
    await manager.restore();

    await Notifications.init();
    return AppController(manager: manager, settings: settings);
  }

  void _applySettings() {
    manager
      ..connections = settings.connections
      ..concurrent = settings.concurrent
      ..boost = settings.boost
      ..speedLimit = settings.speedLimitBytes;
    final dir = settings.destDir;
    if (dir != null) manager.destDir = dir;
    manager.pump();
    notifyListeners();
  }

  // platform wiring ---------------------------------------------------

  void _onQueueChanged() {
    _syncForegroundService();
    _announceFinished();
    notifyListeners();
  }

  /// The service must run exactly while work is in flight: leaving it up drains
  /// the battery, taking it down early gets the process suspended mid-transfer.
  void _syncForegroundService() {
    final busy = manager.tasks.any((t) => t.state.isActive) ||
        manager.activeCount > 0;
    if (busy == _serviceActive) return;
    _serviceActive = busy;
    _platform
        .invokeMethod<void>('keepAwake', {'active': busy})
        .catchError((Object error) {
      debugPrint('foreground service toggle failed: $error');
    });
  }

  void _announceFinished() {
    for (final task in manager.tasks) {
      if (task.state == DownloadState.done) {
        if (!_announced.add(task.id)) continue;
        // Index it so the gallery and other apps' pickers can see it.
        unawaited(scanMedia(task.resultPath));
        if (settings.notifyOnDone) {
          unawaited(Notifications.downloadComplete(task.name, task.resultPath));
        }
      } else if (task.state == DownloadState.error) {
        if (!_announced.add(task.id)) continue;
        if (settings.notifyOnDone) {
          unawaited(
            Notifications.downloadFailed(
              task.name,
              task.progress.error ?? 'unknown error',
            ),
          );
        }
      } else {
        // A retried task should be able to announce itself again.
        _announced.remove(task.id);
      }
    }
  }

  void _watchConnectivity() {
    _connectivity = Connectivity().onConnectivityChanged.listen((results) {
      final wasMetered = _onMeteredConnection;
      _onMeteredConnection = results.isNotEmpty &&
          !results.contains(ConnectivityResult.wifi) &&
          !results.contains(ConnectivityResult.ethernet) &&
          !results.contains(ConnectivityResult.none);

      if (wasMetered == _onMeteredConnection) return;

      if (blockedByWifiRule) {
        // Dropping onto mobile data must not quietly spend the user's balance.
        unawaited(manager.pauseAll());
      } else if (settings.wifiOnly && wasMetered) {
        manager.resumeAll();
      }
      notifyListeners();
    });
  }

  // queue passthrough -------------------------------------------------

  List<DownloadTask> get tasks => manager.tasks;

  (int, double) get totals => manager.totals();

  @override
  void dispose() {
    _subscription.cancel();
    _connectivity?.cancel();
    settings.removeListener(_applySettings);
    unawaited(manager.dispose());
    super.dispose();
  }
}
