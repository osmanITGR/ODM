/// Persisted user preferences.
library;

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class Settings extends ChangeNotifier {
  Settings._(this._prefs);

  final SharedPreferences _prefs;

  static Future<Settings> load() async {
    return Settings._(await SharedPreferences.getInstance());
  }

  // Keys are spelled out rather than generated, so a rename cannot silently
  // orphan a user's saved value.
  static const _kConnections = 'connections';
  static const _kConcurrent = 'concurrent';
  static const _kBoost = 'boost';
  static const _kSpeedLimit = 'speed_limit_kb';
  static const _kWifiOnly = 'wifi_only';
  static const _kDestDir = 'dest_dir';
  static const _kClipboardWatch = 'clipboard_watch';
  static const _kNotifyDone = 'notify_done';
  static const _kThemeMode = 'theme_mode';

  int get connections => _prefs.getInt(_kConnections) ?? 8;
  set connections(int value) {
    _prefs.setInt(_kConnections, value.clamp(1, 32));
    notifyListeners();
  }

  int get concurrent => _prefs.getInt(_kConcurrent) ?? 3;
  set concurrent(int value) {
    _prefs.setInt(_kConcurrent, value.clamp(1, 10));
    notifyListeners();
  }

  bool get boost => _prefs.getBool(_kBoost) ?? true;
  set boost(bool value) {
    _prefs.setBool(_kBoost, value);
    notifyListeners();
  }

  /// Cap in KB/s. 0 means unlimited.
  int get speedLimitKb => _prefs.getInt(_kSpeedLimit) ?? 0;
  set speedLimitKb(int value) {
    _prefs.setInt(_kSpeedLimit, value < 0 ? 0 : value);
    notifyListeners();
  }

  double get speedLimitBytes => speedLimitKb * 1024.0;

  /// On a phone this matters more than any other setting: mobile data is
  /// metered and a large download can cost real money.
  bool get wifiOnly => _prefs.getBool(_kWifiOnly) ?? false;
  set wifiOnly(bool value) {
    _prefs.setBool(_kWifiOnly, value);
    notifyListeners();
  }

  String? get destDir => _prefs.getString(_kDestDir);
  set destDir(String? value) {
    if (value == null) {
      _prefs.remove(_kDestDir);
    } else {
      _prefs.setString(_kDestDir, value);
    }
    notifyListeners();
  }

  bool get clipboardWatch => _prefs.getBool(_kClipboardWatch) ?? true;
  set clipboardWatch(bool value) {
    _prefs.setBool(_kClipboardWatch, value);
    notifyListeners();
  }

  bool get notifyOnDone => _prefs.getBool(_kNotifyDone) ?? true;
  set notifyOnDone(bool value) {
    _prefs.setBool(_kNotifyDone, value);
    notifyListeners();
  }

  /// 0 = system, 1 = light, 2 = dark.
  int get themeMode => _prefs.getInt(_kThemeMode) ?? 0;
  set themeMode(int value) {
    _prefs.setInt(_kThemeMode, value);
    notifyListeners();
  }
}
