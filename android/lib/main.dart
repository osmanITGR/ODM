/// ODM — Osman Download Manager for Android.
///
/// The Android companion to the Windows build: the same segmented engine,
/// the same work-stealing speed boost, the same resume-across-restarts.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';

import 'services/app_controller.dart';
import 'services/storage.dart';
import 'ui/home_screen.dart';
import 'ui/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Storage.ensurePermissions();
  final controller = await AppController.create();
  runApp(OdmApp(controller: controller));
}

class OdmApp extends StatefulWidget {
  const OdmApp({super.key, required this.controller});

  final AppController controller;

  @override
  State<OdmApp> createState() => _OdmAppState();
}

class _OdmAppState extends State<OdmApp> with WidgetsBindingObserver {
  final _homeKey = GlobalKey<HomeScreenState>();
  StreamSubscription<List<SharedMediaFile>>? _sharing;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.controller.settings.addListener(_onSettingsChanged);
    _listenForSharedLinks();
  }

  void _onSettingsChanged() {
    // The theme lives in settings, so a change there has to repaint the root.
    if (mounted) setState(() {});
  }

  /// Links shared into ODM from any app — the phone's answer to the desktop
  /// build's browser extension.
  void _listenForSharedLinks() {
    // While the app is already open.
    _sharing = ReceiveSharingIntent.instance.getMediaStream().listen(
      _handleShared,
      onError: (Object error) => debugPrint('share stream failed: $error'),
    );

    // The share that launched the app in the first place.
    ReceiveSharingIntent.instance.getInitialMedia().then((media) {
      _handleShared(media);
      ReceiveSharingIntent.instance.reset();
    });
  }

  void _handleShared(List<SharedMediaFile> media) {
    if (media.isEmpty) return;

    // A shared link arrives as text, which may be a sentence with the URL in
    // it — "Watch this: https://…" is what most apps send.
    final text = media
        .map((m) => m.path)
        .firstWhere((p) => p.isNotEmpty, orElse: () => '');
    final url = _firstUrl(text);
    if (url == null) return;

    // The home screen may not be mounted yet on a cold share-launch.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _homeKey.currentState?.openWithUrl(url);
    });
  }

  String? _firstUrl(String text) {
    final match = RegExp(r'https?://\S+').firstMatch(text);
    return match?.group(0);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Persist on the way out: Android may kill the process without warning
    // once the app is no longer visible.
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached) {
      unawaited(widget.controller.manager.persist());
    }
  }

  @override
  void dispose() {
    _sharing?.cancel();
    widget.controller.settings.removeListener(_onSettingsChanged);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mode = switch (widget.controller.settings.themeMode) {
      1 => ThemeMode.light,
      2 => ThemeMode.dark,
      _ => ThemeMode.system,
    };

    return MaterialApp(
      title: 'ODM',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: mode,
      home: HomeScreen(key: _homeKey, controller: widget.controller),
    );
  }
}
