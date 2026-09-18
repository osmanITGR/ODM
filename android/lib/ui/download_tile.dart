/// One row in the download list.
library;

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';

import '../engine/models.dart';
import '../engine/rate_limiter.dart';
import '../engine/task.dart';
import 'theme.dart';

class DownloadTile extends StatelessWidget {
  const DownloadTile({
    super.key,
    required this.task,
    required this.onPause,
    required this.onResume,
    required this.onRetry,
    required this.onRemove,
  });

  final DownloadTask task;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onRetry;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final state = task.state;

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: state == DownloadState.done
            ? () => OpenFilex.open(task.resultPath)
            : null,
        onLongPress: () => _showMenu(context),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 14, 8, 14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Icon(state: state, scheme: scheme),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      task.title ?? task.name,
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 15,
                        height: 1.25,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 8),
                    _ProgressBar(task: task, scheme: scheme),
                    const SizedBox(height: 6),
                    _StatusLine(task: task, scheme: scheme),
                  ],
                ),
              ),
              _ActionButton(
                state: state,
                onPause: onPause,
                onResume: onResume,
                onRetry: onRetry,
                onOpen: () => OpenFilex.open(task.resultPath),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showMenu(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
              child: Text(
                task.name,
                style: const TextStyle(fontWeight: FontWeight.w600),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const Divider(),
            if (task.state == DownloadState.done)
              ListTile(
                leading: const Icon(Icons.open_in_new),
                title: const Text('Open file'),
                onTap: () {
                  Navigator.pop(sheetContext);
                  OpenFilex.open(task.resultPath);
                },
              ),
            ListTile(
              leading: const Icon(Icons.delete_outline),
              title: Text(
                task.state == DownloadState.done
                    ? 'Remove from list'
                    : 'Cancel download',
              ),
              onTap: () {
                Navigator.pop(sheetContext);
                onRemove();
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _Icon extends StatelessWidget {
  const _Icon({required this.state, required this.scheme});

  final DownloadState state;
  final ColorScheme scheme;

  @override
  Widget build(BuildContext context) {
    final (icon, color) = switch (state) {
      DownloadState.done => (Icons.check_circle, StatusColors.done(scheme)),
      DownloadState.error => (Icons.error_outline, StatusColors.error(scheme)),
      DownloadState.paused => (
        Icons.pause_circle_outline,
        StatusColors.paused(scheme),
      ),
      DownloadState.muxing => (Icons.merge_type, scheme.primary),
      DownloadState.probing => (Icons.search, scheme.primary),
      DownloadState.running => (Icons.downloading, scheme.primary),
      DownloadState.pending => (
        Icons.schedule,
        StatusColors.paused(scheme),
      ),
    };

    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Icon(icon, color: color, size: 22),
    );
  }
}

class _ProgressBar extends StatelessWidget {
  const _ProgressBar({required this.task, required this.scheme});

  final DownloadTask task;
  final ColorScheme scheme;

  @override
  Widget build(BuildContext context) {
    final state = task.state;
    if (state == DownloadState.done) return const SizedBox.shrink();

    // An unknown total means no meaningful fraction to show, so the bar
    // animates instead of lying about a position.
    final indeterminate =
        state == DownloadState.probing ||
        state == DownloadState.muxing ||
        (state == DownloadState.running && task.totalBytes == null);

    final color = switch (state) {
      DownloadState.error => StatusColors.error(scheme),
      DownloadState.paused => StatusColors.paused(scheme),
      _ => scheme.primary,
    };

    return ClipRRect(
      borderRadius: BorderRadius.circular(3),
      child: LinearProgressIndicator(
        value: indeterminate ? null : task.percent / 100,
        minHeight: 5,
        backgroundColor: scheme.surfaceContainerHighest,
        valueColor: AlwaysStoppedAnimation(color),
      ),
    );
  }
}

class _StatusLine extends StatelessWidget {
  const _StatusLine({required this.task, required this.scheme});

  final DownloadTask task;
  final ColorScheme scheme;

  @override
  Widget build(BuildContext context) {
    final style = TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant);

    final text = switch (task.state) {
      DownloadState.done => formatBytes(task.totalBytes ?? task.downloaded),
      DownloadState.error =>
        task.progress.error ?? 'Failed',
      DownloadState.probing => 'Checking link…',
      DownloadState.muxing => 'Joining video and audio…',
      DownloadState.pending => 'Waiting in queue',
      DownloadState.paused =>
        '${formatBytes(task.downloaded)} of ${formatBytes(task.totalBytes)} · Paused',
      DownloadState.running => _runningText(),
    };

    return Text(
      text,
      style: task.state == DownloadState.error
          ? style.copyWith(color: StatusColors.error(scheme))
          : style,
      maxLines: 2,
      overflow: TextOverflow.ellipsis,
    );
  }

  String _runningText() {
    final done = formatBytes(task.downloaded);
    final total = task.totalBytes == null ? '' : ' of ${formatBytes(task.totalBytes)}';
    final speed = task.speed > 0 ? ' · ${formatSpeed(task.speed)}' : '';
    final eta = task.progress.eta;
    final left = eta == null ? '' : ' · ${formatDuration(eta)} left';
    return '$done$total$speed$left';
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.state,
    required this.onPause,
    required this.onResume,
    required this.onRetry,
    required this.onOpen,
  });

  final DownloadState state;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onRetry;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final (icon, action, tooltip) = switch (state) {
      DownloadState.running || DownloadState.probing => (
        Icons.pause,
        onPause,
        'Pause',
      ),
      DownloadState.paused || DownloadState.pending => (
        Icons.play_arrow,
        onResume,
        'Resume',
      ),
      DownloadState.error => (Icons.refresh, onRetry, 'Try again'),
      DownloadState.done => (Icons.open_in_new, onOpen, 'Open'),
      // Muxing cannot be interrupted safely — it would leave a broken file.
      DownloadState.muxing => (null, null, ''),
    };

    if (icon == null) {
      return const SizedBox(
        width: 48,
        height: 48,
        child: Center(
          child: SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
    }

    return IconButton(
      onPressed: action,
      icon: Icon(icon),
      tooltip: tooltip,
      visualDensity: VisualDensity.compact,
    );
  }
}
