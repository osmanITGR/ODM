/// Where downloads are saved, and how the app gets permission to write there.
library;

import 'dart:io';

import 'package:device_info_plus/device_info_plus.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';

class Storage {
  /// The public Downloads folder, so finished files show up in the phone's
  /// file manager and gallery rather than being locked inside the app.
  static Future<String> defaultDownloadDir() async {
    if (Platform.isAndroid) {
      const publicDownloads = '/storage/emulated/0/Download';
      final odm = Directory(p.join(publicDownloads, 'ODM'));
      try {
        if (!await odm.exists()) await odm.create(recursive: true);
        // Creating it can succeed while writing into it fails on some OEM
        // builds, so confirm with a real write before committing to the path.
        final probe = File(p.join(odm.path, '.odm-write-test'));
        await probe.writeAsString('ok');
        await probe.delete();
        return odm.path;
      } on FileSystemException {
        // Fall through to app-private storage below.
      }
    }

    // Always writable, but only visible to this app and wiped on uninstall.
    final fallback = await getExternalStorageDirectory() ??
        await getApplicationDocumentsDirectory();
    final dir = Directory(p.join(fallback.path, 'Downloads'));
    if (!await dir.exists()) await dir.create(recursive: true);
    return dir.path;
  }

  /// Where the queue's own state file lives — app-private, never user-visible.
  static Future<String> stateFilePath() async {
    final dir = await getApplicationSupportDirectory();
    if (!await dir.exists()) await dir.create(recursive: true);
    return p.join(dir.path, 'queue.json');
  }

  /// Ask for the permissions this Android version actually needs.
  ///
  /// The rules changed twice: up to Android 10 a storage permission was
  /// required to write anywhere public; from Android 11 the app's own folder
  /// under Downloads needs none. Asking regardless would show users a prompt
  /// the system then silently denies.
  static Future<bool> ensurePermissions() async {
    if (!Platform.isAndroid) return true;

    final info = await DeviceInfoPlugin().androidInfo;
    final sdk = info.version.sdkInt;

    if (sdk >= 33) {
      // Only the notification permission is new here, and it is not required
      // for downloading — just for showing progress.
      final status = await Permission.notification.status;
      if (status.isDenied) await Permission.notification.request();
      return true;
    }

    if (sdk <= 29) {
      final status = await Permission.storage.request();
      return status.isGranted;
    }

    return true;
  }

  /// True when the notification permission was granted, so the foreground
  /// service can show its progress bar.
  static Future<bool> hasNotificationPermission() async {
    if (!Platform.isAndroid) return true;
    return (await Permission.notification.status).isGranted;
  }

  /// Free space on the volume holding [path], or null if it cannot be read.
  static Future<int?> freeSpace(String path) async {
    try {
      final result = await Process.run('df', ['-k', path]);
      if (result.exitCode != 0) return null;
      final lines = (result.stdout as String).trim().split('\n');
      if (lines.length < 2) return null;
      final columns = lines[1].split(RegExp(r'\s+'));
      // df -k reports in 1 KB blocks; "Available" is the fourth column.
      if (columns.length < 4) return null;
      final kb = int.tryParse(columns[3]);
      return kb == null ? null : kb * 1024;
    } catch (_) {
      return null;
    }
  }
}
