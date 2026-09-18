/// ODM — Osman Download Manager for Android.
///
/// The Android companion to the Windows build: the same segmented engine,
/// the same work-stealing speed boost, the same resume-across-restarts.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import 'services/app_controller.dart';
import 'services/incoming_links.dart';
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
  StreamSubscription<String>? _sharing;

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

  /// Links handed to ODM from anywhere on the phone — the share sheet, a
  /// tapped video link, or selected text. This is the mobile answer to the
  /// desktop build's browser extension.
  void _listenForSharedLinks() {
    final links = IncomingLinks.instance..start();

    // While the app is already open.
    _sharing = links.stream.listen(
      _handleLink,
      onError: (Object error) => debugPrint('link stream failed: $error'),
    );

    // The link that launched the app in the first place.
    links.initialLink().then((url) {
      if (url != null) _handleLink(url);
    });
  }

  void _handleLink(String url) {
    // The home screen may not be mounted yet on a cold share-launch.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _homeKey.currentState?.openWithUrl(url);
    });
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
