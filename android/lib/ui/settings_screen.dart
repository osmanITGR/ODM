/// Settings.
library;

import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../engine/rate_limiter.dart';
import '../services/app_controller.dart';
import '../services/updater.dart';
import 'update_dialog.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.controller});

  final AppController controller;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _checkingUpdate = false;
  String? _updateStatus;

  Future<void> _checkForUpdate() async {
    setState(() {
      _checkingUpdate = true;
      _updateStatus = null;
    });

    final release = await checkForUpdate();
    final current = (await PackageInfo.fromPlatform()).version;
    if (!mounted) return;

    setState(() => _checkingUpdate = false);

    if (release == null) {
      setState(() => _updateStatus = 'Could not check — are you online?');
      return;
    }
    if (!release.isNewerThan(current) || release.downloadUrl == null) {
      setState(() => _updateStatus = 'You are on the latest version');
      return;
    }

    setState(() => _updateStatus = 'Version ${release.version} is available');
    if (mounted) await showUpdateDialog(context, release, current);
  }

  @override
  Widget build(BuildContext context) {
    final settings = widget.controller.settings;
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 32),
        children: [
          const _SectionHeader('Speed'),

          _SliderTile(
            title: 'Connections per file',
            // Past 8–16 rarely helps and some servers throttle or refuse many
            // parallel requests from one client.
            subtitle:
                '${settings.connections} parallel connections. '
                '8 suits most links; more can help on slow servers.',
            value: settings.connections.toDouble(),
            min: 1,
            max: 32,
            divisions: 31,
            onChanged: (v) => setState(() => settings.connections = v.round()),
          ),

          SwitchListTile(
            title: const Text('Speed boost'),
            subtitle: const Text(
              'When one connection finishes early it takes over the slowest '
              'remaining part instead of going idle.',
            ),
            value: settings.boost,
            onChanged: (v) => setState(() => settings.boost = v),
          ),

          _SliderTile(
            title: 'Downloads at once',
            subtitle: '${settings.concurrent} at a time, the rest queue up.',
            value: settings.concurrent.toDouble(),
            min: 1,
            max: 10,
            divisions: 9,
            onChanged: (v) => setState(() => settings.concurrent = v.round()),
          ),

          ListTile(
            title: const Text('Speed limit'),
            subtitle: Text(
              settings.speedLimitKb == 0
                  ? 'Unlimited'
                  : '${formatBytes(settings.speedLimitKb * 1024)}/s across all downloads',
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: _editSpeedLimit,
          ),

          const Divider(height: 32),
          const _SectionHeader('Data'),

          SwitchListTile(
            title: const Text('Wi-Fi only'),
            subtitle: const Text(
              'Pause downloads when the phone is on mobile data.',
            ),
            value: settings.wifiOnly,
            onChanged: (v) => setState(() => settings.wifiOnly = v),
          ),

          const Divider(height: 32),
          const _SectionHeader('Behaviour'),

          SwitchListTile(
            title: const Text('Read links from the clipboard'),
            subtitle: const Text(
              'Fill in a copied link automatically when you add a download.',
            ),
            value: settings.clipboardWatch,
            onChanged: (v) => setState(() => settings.clipboardWatch = v),
          ),

          SwitchListTile(
            title: const Text('Notify when finished'),
            value: settings.notifyOnDone,
            onChanged: (v) => setState(() => settings.notifyOnDone = v),
          ),

          ListTile(
            title: const Text('Theme'),
            subtitle: Text(
              switch (settings.themeMode) {
                1 => 'Light',
                2 => 'Dark',
                _ => 'Follow system',
              },
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: _pickTheme,
          ),

          const Divider(height: 32),
          const _SectionHeader('Storage'),

          ListTile(
            title: const Text('Save downloads to'),
            subtitle: Text(
              widget.controller.manager.destDir,
              style: TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant),
            ),
            isThreeLine: true,
          ),

          const Divider(height: 32),
          const _SectionHeader('About'),

          const ListTile(
            title: Text('ODM — Osman Download Manager'),
            subtitle: _AppVersion(),
          ),

          ListTile(
            leading: _checkingUpdate
                ? const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.system_update_outlined),
            title: const Text('Check for updates'),
            subtitle: _updateStatus == null ? null : Text(_updateStatus!),
            onTap: _checkingUpdate ? null : _checkForUpdate,
          ),

          ListTile(
            leading: const Icon(Icons.chat_outlined),
            title: const Text('Support on WhatsApp'),
            subtitle: const Text('+880 1625 251930'),
            onTap: () => launchUrl(
              Uri.parse('https://wa.me/8801625251930'),
              mode: LaunchMode.externalApplication,
            ),
          ),

          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Text(
              'Videos protected by DRM, such as Netflix or Prime Video, '
              'cannot be downloaded by any app.',
              style: TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _editSpeedLimit() async {
    final settings = widget.controller.settings;
    final field = TextEditingController(
      text: settings.speedLimitKb == 0 ? '' : '${settings.speedLimitKb}',
    );

    final result = await showDialog<int>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Speed limit'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: field,
              keyboardType: TextInputType.number,
              autofocus: true,
              decoration: const InputDecoration(
                suffixText: 'KB/s',
                hintText: 'Leave empty for unlimited',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, 0),
            child: const Text('Unlimited'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(
              dialogContext,
              int.tryParse(field.text.trim()) ?? 0,
            ),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    field.dispose();
    if (result != null && mounted) {
      setState(() => settings.speedLimitKb = result);
    }
  }

  Future<void> _pickTheme() async {
    final settings = widget.controller.settings;
    final choice = await showDialog<int>(
      context: context,
      builder: (dialogContext) => SimpleDialog(
        title: const Text('Theme'),
        children: [
          RadioGroup<int>(
            groupValue: settings.themeMode,
            onChanged: (v) => Navigator.pop(dialogContext, v),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final (value, label) in [
                  (0, 'Follow system'),
                  (1, 'Light'),
                  (2, 'Dark'),
                ])
                  RadioListTile<int>(value: value, title: Text(label)),
              ],
            ),
          ),
        ],
      ),
    );
    if (choice != null && mounted) {
      setState(() => settings.themeMode = choice);
    }
  }
}

/// The installed version, read from the package rather than hardcoded.
///
/// A number written into the UI falls out of step with pubspec.yaml the first
/// time someone forgets to change both.
class _AppVersion extends StatelessWidget {
  const _AppVersion();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<PackageInfo>(
      future: PackageInfo.fromPlatform(),
      builder: (context, snapshot) {
        final info = snapshot.data;
        // Until it resolves, show the identifier alone rather than a stale
        // number or a flash of empty space.
        final version = info == null ? '' : 'Version ${info.version} · ';
        return Text('$version${info?.packageName ?? 'com.osmanit.odm'}');
      },
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.title);

  final String title;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
    child: Text(
      title.toUpperCase(),
      style: TextStyle(
        fontSize: 11.5,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.8,
        color: Theme.of(context).colorScheme.primary,
      ),
    ),
  );
}

class _SliderTile extends StatelessWidget {
  const _SliderTile({
    required this.title,
    required this.subtitle,
    required this.value,
    required this.min,
    required this.max,
    required this.divisions,
    required this.onChanged,
  });

  final String title;
  final String subtitle;
  final double value;
  final double min;
  final double max;
  final int divisions;
  final ValueChanged<double> onChanged;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: const TextStyle(fontSize: 16)),
          const SizedBox(height: 2),
          Text(
            subtitle,
            style: TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant),
          ),
          Slider(
            value: value,
            min: min,
            max: max,
            divisions: divisions,
            label: value.round().toString(),
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}
