/// Check GitHub for a newer release.
///
/// The app is installed from a GitHub release rather than a store, so nothing
/// tells anyone when the next one lands. This checks on launch and offers the
/// update; Android cannot install silently, so the APK is downloaded and
/// handed to the system installer, which asks the user to confirm.
library;

import 'dart:convert';
import 'dart:io';

import 'package:shared_preferences/shared_preferences.dart';

const String _latestReleaseApi =
    'https://api.github.com/repos/osmanITGR/ODM/releases/latest';
const String releasesPage =
    'https://github.com/osmanITGR/ODM/releases/latest';

/// The asset to fetch. Split-per-ABI builds mean the 64-bit one suits almost
/// every phone sold since 2017; the 32-bit build is offered on the page for
/// the rest.
const String _apkAsset = 'ODM-Android.apk';
const String _apk32Asset = 'ODM-Android-purono-phone.apk';

class Release {
  const Release({
    required this.version,
    required this.tag,
    required this.notes,
    this.downloadUrl,
    this.size,
  });

  final String version;
  final String tag;
  final String notes;
  final String? downloadUrl;
  final int? size;

  bool isNewerThan(String current) => compareVersions(version, current) > 0;
}

/// Turn "v1.3.1" into [1, 3, 1], ignoring anything non-numeric.
List<int> parseVersion(String raw) {
  final cleaned = raw.trim().replaceFirst(RegExp('^[vV]'), '').split(
    RegExp(r'[-+]'),
  ).first;
  final parts = <int>[];
  for (final piece in cleaned.split('.')) {
    final digits = piece.replaceAll(RegExp(r'\D'), '');
    parts.add(digits.isEmpty ? 0 : int.parse(digits));
  }
  return parts.isEmpty ? [0] : parts;
}

/// -1, 0 or 1, comparing two version strings by their numbers.
///
/// Compared piece by piece rather than as text, or "1.10" would sort below
/// "1.9".
int compareVersions(String left, String right) {
  final a = parseVersion(left);
  final b = parseVersion(right);
  final width = a.length > b.length ? a.length : b.length;

  for (var i = 0; i < width; i++) {
    // Missing components are zero, so 1.3 and 1.3.0 compare equal.
    final x = i < a.length ? a[i] : 0;
    final y = i < b.length ? b[i] : 0;
    if (x != y) return x > y ? 1 : -1;
  }
  return 0;
}

const String _lastCheckKey = 'last_update_check';

/// Whether enough time has passed since the last automatic check.
///
/// GitHub allows 60 unauthenticated calls an hour per address, shared by
/// everyone behind it. Checking at every launch would spend that on people
/// who reopen the app often, so the automatic check is daily. The Settings
/// button ignores this.
Future<bool> shouldCheckForUpdate({
  Duration interval = const Duration(hours: 24),
}) async {
  try {
    final prefs = await SharedPreferences.getInstance();
    final last = prefs.getInt(_lastCheckKey);
    if (last == null) return true;
    final elapsed = DateTime.now().millisecondsSinceEpoch - last;
    return elapsed >= interval.inMilliseconds;
  } on Exception {
    // Losing the stamp only means checking again sooner.
    return true;
  }
}

/// Record that an automatic check just happened.
Future<void> noteUpdateChecked() async {
  try {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_lastCheckKey, DateTime.now().millisecondsSinceEpoch);
  } on Exception {
    // Not worth surfacing; the next launch simply checks again.
  }
}

/// Ask GitHub for the newest release.
///
/// Returns null when the check fails for any reason — no internet, a rate
/// limit, a malformed response. An update notice is a convenience, and
/// someone offline should see nothing rather than an error they did not ask
/// for.
Future<Release?> checkForUpdate({
  Duration timeout = const Duration(seconds: 12),
  bool wantsArm32 = false,
}) async {
  final client = HttpClient()..connectionTimeout = timeout;
  try {
    final request = await client
        .getUrl(Uri.parse(_latestReleaseApi))
        .timeout(timeout);
    request.headers.set('user-agent', 'ODM-Android');
    request.headers.set('accept', 'application/vnd.github+json');

    final response = await request.close().timeout(timeout);
    if (response.statusCode != 200) return null;

    final body = await response.transform(utf8.decoder).join().timeout(timeout);
    final data = jsonDecode(body) as Map<String, dynamic>;

    final tag = data['tag_name'] as String?;
    if (tag == null || tag.isEmpty) return null;

    final wanted = wantsArm32 ? _apk32Asset : _apkAsset;
    String? downloadUrl;
    int? size;
    for (final raw in (data['assets'] as List? ?? const [])) {
      final asset = raw as Map<String, dynamic>;
      if (asset['name'] == wanted) {
        downloadUrl = asset['browser_download_url'] as String?;
        size = asset['size'] as int?;
        break;
      }
    }

    return Release(
      version: tag.replaceFirst(RegExp('^[vV]'), ''),
      tag: tag,
      notes: (data['body'] as String?) ?? '',
      downloadUrl: downloadUrl,
      size: size,
    );
  } on Exception {
    return null;
  } finally {
    client.close(force: true);
  }
}

/// Condense release notes into something that fits a dialog.
///
/// The notes are written for the download page, with tables and install
/// instructions; only the bullet points say what changed.
String summariseNotes(String notes, {int limit = 400}) {
  final lines = <String>[];
  for (final raw in notes.split('\n')) {
    final line = raw.trim();
    if (!line.startsWith('- ') &&
        !line.startsWith('* ') &&
        !line.startsWith('• ')) {
      continue;
    }
    // Strip the markdown that would otherwise show as literal characters.
    final text = line
        .substring(2)
        .replaceAll('**', '')
        .replaceAll('`', '')
        .trim();
    if (text.isNotEmpty) lines.add('• $text');
  }

  final summary = lines.join('\n');
  if (summary.length <= limit) return summary;
  // Cut between lines rather than mid-word.
  final cut = summary.substring(0, limit);
  final lastBreak = cut.lastIndexOf('\n');
  return lastBreak > 0 ? cut.substring(0, lastBreak) : cut;
}
