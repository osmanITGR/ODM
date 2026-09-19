/// Offering, downloading and installing an update.
///
/// The app is not in a store, so nothing tells anyone when a new release
/// lands. Android cannot install silently either, so the APK is downloaded
/// and handed to the system installer, which asks the user to confirm.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../engine/download_engine.dart';
import '../engine/models.dart';
import '../engine/rate_limiter.dart';
import '../services/updater.dart';

Future<void> showUpdateDialog(
  BuildContext context,
  Release release,
  String currentVersion,
) {
  return showDialog<void>(
    context: context,
    builder: (_) => _UpdateDialog(
      release: release,
      currentVersion: currentVersion,
    ),
  );
}

class _UpdateDialog extends StatefulWidget {
  const _UpdateDialog({required this.release, required this.currentVersion});

  final Release release;
  final String currentVersion;

  @override
  State<_UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends State<_UpdateDialog> {
  Download? _download;
  String? _error;
  double _percent = 0;
  bool _downloading = false;

  @override
  void dispose() {
    // Leaving the dialog cancels the transfer rather than letting it run on
    // with nothing to report to.
    _download?.pause();
    super.dispose();
  }

  Future<void> _startDownload() async {
    final url = widget.release.downloadUrl;
    if (url == null) return;

    setState(() {
      _downloading = true;
      _error = null;
    });

    try {
      // App-private storage: the installer can read it, and it does not
      // leave an APK in the user's Downloads folder afterwards.
      final dir = await getTemporaryDirectory();
      final download = Download(
        url: url,
        destDir: dir.path,
        connections: 4,
        filename: 'ODM-${widget.release.version}.apk',
      );
      _download = download;

      // Poll rather than await: the engine reports progress on the object.
      final ticker = Stream<void>.periodic(
        const Duration(milliseconds: 400),
      ).listen((_) {
        if (!mounted) return;
        setState(() => _percent = download.progress.percent);
      });

      await download.start();
      await ticker.cancel();

      if (!mounted) return;

      if (download.progress.state != DownloadState.done) {
        setState(() {
          _downloading = false;
          _error = download.progress.error ?? 'Download failed';
        });
        return;
      }

      final result = await OpenFilex.open(download.targetPath);
      if (!mounted) return;

      if (result.type != ResultType.done) {
        setState(() {
          _downloading = false;
          _error =
              'Downloaded, but the installer could not be opened. '
              'The file is in ${p.basename(download.targetPath)}.';
        });
        return;
      }

      // The system installer has it from here.
      Navigator.of(context).pop();
    } on FileSystemException catch (error) {
      if (!mounted) return;
      setState(() {
        _downloading = false;
        _error = 'Could not save the update: ${error.message}';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final summary = summariseNotes(widget.release.notes);

    return AlertDialog(
      title: Text('ODM ${widget.release.version} is available'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'You have ${widget.currentVersion}.',
            style: TextStyle(fontSize: 13, color: scheme.onSurfaceVariant),
          ),
          if (summary.isNotEmpty) ...[
            const SizedBox(height: 14),
            Container(
              constraints: const BoxConstraints(maxHeight: 180),
              width: double.maxFinite,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
                borderRadius: BorderRadius.circular(10),
              ),
              child: SingleChildScrollView(
                child: Text(summary, style: const TextStyle(fontSize: 13)),
              ),
            ),
          ],
          if (widget.release.size != null) ...[
            const SizedBox(height: 10),
            Text(
              'Download size: ${formatBytes(widget.release.size)}',
              style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
            ),
          ],
          if (_downloading) ...[
            const SizedBox(height: 16),
            LinearProgressIndicator(
              value: _percent > 0 ? _percent / 100 : null,
            ),
            const SizedBox(height: 8),
            Text(
              _percent > 0
                  ? 'Downloading… ${_percent.toStringAsFixed(0)}%'
                  : 'Starting…',
              style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 14),
            Text(
              _error!,
              style: TextStyle(fontSize: 12.5, color: scheme.error),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => launchUrl(
            Uri.parse(releasesPage),
            mode: LaunchMode.externalApplication,
          ),
          child: const Text("What's new"),
        ),
        if (!_downloading)
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Later'),
          ),
        FilledButton(
          onPressed: _downloading || widget.release.downloadUrl == null
              ? null
              : _startDownload,
          child: Text(_error != null ? 'Try again' : 'Update now'),
        ),
      ],
    );
  }
}
