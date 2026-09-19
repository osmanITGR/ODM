/// The download list — the app's only real screen.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../engine/models.dart';
import '../engine/rate_limiter.dart';
import '../engine/task.dart';
import '../services/app_controller.dart';
import '../services/updater.dart';
import 'add_download_sheet.dart';
import 'download_tile.dart';
import 'settings_screen.dart';
import 'update_dialog.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<HomeScreen> createState() => HomeScreenState();
}

class HomeScreenState extends State<HomeScreen> {
  Timer? _ticker;
  _Filter _filter = _Filter.all;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_onChanged);
    // The app is not in a store, so nothing else tells anyone a new release
    // exists. Delayed so it does not compete with the first frame.
    Future<void>.delayed(const Duration(seconds: 4), _checkForUpdate);
    // Speed and byte counts move continuously; the manager only notifies on
    // structural changes, so the numbers need their own repaint.
    _ticker = Timer.periodic(const Duration(milliseconds: 600), (_) {
      if (mounted && widget.controller.tasks.any((t) => t.state.isActive)) {
        setState(() {});
      }
    });
  }

  void _onChanged() {
    if (mounted) setState(() {});
  }

  /// Offer a newer release, if there is one.
  ///
  /// Silent when the check fails or the app is current: someone offline
  /// should see nothing rather than an error they did not ask for.
  Future<void> _checkForUpdate() async {
    if (!await shouldCheckForUpdate()) return;
    await noteUpdateChecked();

    final release = await checkForUpdate();
    if (!mounted || release == null || release.downloadUrl == null) return;

    final current = (await PackageInfo.fromPlatform()).version;
    if (!mounted || !release.isNewerThan(current)) return;

    await showUpdateDialog(context, release, current);
  }

  @override
  void dispose() {
    _ticker?.cancel();
    widget.controller.removeListener(_onChanged);
    super.dispose();
  }

  /// Entry point for links shared into the app from elsewhere.
  void openWithUrl(String url) {
    showAddDownloadSheet(context, widget.controller, initialUrl: url);
  }

  List<DownloadTask> get _visible {
    final all = widget.controller.tasks;
    return switch (_filter) {
      _Filter.all => all,
      _Filter.active => all.where((t) => !t.state.isTerminal).toList(),
      _Filter.done =>
        all.where((t) => t.state == DownloadState.done).toList(),
    };
  }

  @override
  Widget build(BuildContext context) {
    final tasks = _visible;
    final (active, speed) = widget.controller.totals;

    return Scaffold(
      appBar: AppBar(
        title: const Text('ODM'),
        actions: [
          if (widget.controller.tasks.any(
            (t) => t.state == DownloadState.done,
          ))
            IconButton(
              tooltip: 'Clear finished',
              icon: const Icon(Icons.cleaning_services_outlined),
              onPressed: () => widget.controller.manager.clearCompleted(),
            ),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => SettingsScreen(controller: widget.controller),
              ),
            ),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(50),
          child: _Header(
            active: active,
            speed: speed,
            filter: _filter,
            blockedByWifi: widget.controller.blockedByWifiRule,
            onFilter: (f) => setState(() => _filter = f),
          ),
        ),
      ),
      body: tasks.isEmpty
          ? _EmptyState(filter: _filter)
          : ListView.separated(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
              itemCount: tasks.length,
              separatorBuilder: (_, _) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final task = tasks[index];
                return DownloadTile(
                  key: ValueKey(task.id),
                  task: task,
                  onPause: () => widget.controller.manager.pause(task.id),
                  onResume: () => widget.controller.manager.resume(task.id),
                  onRetry: () => widget.controller.manager.retry(task.id),
                  onRemove: () => _confirmRemove(task),
                );
              },
            ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => showAddDownloadSheet(context, widget.controller),
        icon: const Icon(Icons.add),
        label: const Text('Add'),
      ),
    );
  }

  Future<void> _confirmRemove(DownloadTask task) async {
    final finished = task.state == DownloadState.done;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(finished ? 'Remove from list?' : 'Cancel download?'),
        content: Text(
          finished
              ? 'The downloaded file stays on your phone.'
              : 'The part already downloaded will be deleted.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Keep'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: Text(finished ? 'Remove' : 'Cancel download'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      await widget.controller.manager.remove(task.id);
    }
  }
}

enum _Filter { all, active, done }

class _Header extends StatelessWidget {
  const _Header({
    required this.active,
    required this.speed,
    required this.filter,
    required this.blockedByWifi,
    required this.onFilter,
  });

  final int active;
  final double speed;
  final _Filter filter;
  final bool blockedByWifi;
  final ValueChanged<_Filter> onFilter;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    if (blockedByWifi) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        color: scheme.tertiaryContainer,
        child: Row(
          children: [
            Icon(Icons.wifi_off, size: 18, color: scheme.onTertiaryContainer),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                'Paused — waiting for Wi-Fi',
                style: TextStyle(
                  fontSize: 13,
                  color: scheme.onTertiaryContainer,
                  fontWeight: FontWeight.w500,
                ),
              ),
            ),
          ],
        ),
      );
    }

    return SizedBox(
      height: 50,
      child: Row(
        children: [
          const SizedBox(width: 12),
          for (final option in _Filter.values) ...[
            _FilterChip(
              label: switch (option) {
                _Filter.all => 'All',
                _Filter.active => 'Active',
                _Filter.done => 'Finished',
              },
              selected: filter == option,
              onTap: () => onFilter(option),
            ),
            const SizedBox(width: 8),
          ],
          const Spacer(),
          if (active > 0)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Row(
                children: [
                  Icon(Icons.speed, size: 15, color: scheme.primary),
                  const SizedBox(width: 5),
                  Text(
                    formatSpeed(speed),
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: scheme.primary,
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
        decoration: BoxDecoration(
          color: selected ? scheme.primary : scheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: selected ? scheme.onPrimary : scheme.onSurfaceVariant,
          ),
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.filter});

  final _Filter filter;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    final (icon, title, body) = switch (filter) {
      _Filter.active => (
        Icons.download_done,
        'Nothing downloading',
        'Downloads you start will appear here.',
      ),
      _Filter.done => (
        Icons.inbox_outlined,
        'No finished downloads yet',
        'Completed files will be listed here.',
      ),
      _Filter.all => (
        Icons.download_outlined,
        'No downloads yet',
        'Tap Add to paste a link, or share a link to ODM from any app.',
      ),
    };

    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 48),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 56, color: scheme.outlineVariant),
            const SizedBox(height: 18),
            Text(
              title,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            Text(
              body,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 14, color: scheme.onSurfaceVariant),
            ),
          ],
        ),
      ),
    );
  }
}
