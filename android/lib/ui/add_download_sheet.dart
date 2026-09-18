/// The sheet that turns a pasted or shared link into a queued download.
///
/// A link can be three things: a plain file, a video page with several
/// qualities, or nothing downloadable. The sheet resolves which, then shows
/// the matching choice — the user never has to say which kind it was.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../engine/extractor.dart';
import '../engine/rate_limiter.dart';
import '../engine/video_models.dart';
import '../services/app_controller.dart';

Future<void> showAddDownloadSheet(
  BuildContext context,
  AppController controller, {
  String? initialUrl,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.of(context).viewInsets.bottom,
      ),
      child: _AddDownloadSheet(
        controller: controller,
        initialUrl: initialUrl,
      ),
    ),
  );
}

class _AddDownloadSheet extends StatefulWidget {
  const _AddDownloadSheet({required this.controller, this.initialUrl});

  final AppController controller;
  final String? initialUrl;

  @override
  State<_AddDownloadSheet> createState() => _AddDownloadSheetState();
}

class _AddDownloadSheetState extends State<_AddDownloadSheet> {
  late final TextEditingController _urlField = TextEditingController(
    text: widget.initialUrl ?? '',
  );

  bool _resolving = false;
  String? _error;
  MediaInfo? _media;
  int? _chosenHeight;

  @override
  void initState() {
    super.initState();
    if (widget.initialUrl != null) {
      // Shared links arrive ready to go; resolving straight away saves a tap.
      WidgetsBinding.instance.addPostFrameCallback((_) => _resolve());
    } else {
      unawaitedPasteCheck();
    }
  }

  /// Offer the clipboard when it holds a link, which is how most downloads
  /// start on a phone.
  Future<void> unawaitedPasteCheck() async {
    if (!widget.controller.settings.clipboardWatch) return;
    try {
      final data = await Clipboard.getData(Clipboard.kTextPlain);
      final text = data?.text?.trim() ?? '';
      if (!mounted || text.isEmpty) return;
      if (!text.startsWith('http://') && !text.startsWith('https://')) return;
      if (_urlField.text.isNotEmpty) return;
      setState(() => _urlField.text = text);
    } on PlatformException {
      // Clipboard access can be refused; typing still works.
    }
  }

  @override
  void dispose() {
    _urlField.dispose();
    super.dispose();
  }

  Future<void> _resolve() async {
    final url = _urlField.text.trim();
    if (url.isEmpty) return;

    setState(() {
      _resolving = true;
      _error = null;
      _media = null;
    });

    try {
      final info = await extract(url);
      if (!mounted) return;
      setState(() {
        _media = info;
        _chosenHeight = info.videoHeights().isEmpty
            ? null
            : info.videoHeights().first;
        _resolving = false;
      });
    } on ExtractorException catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error.message;
        _resolving = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not read that link. $error';
        _resolving = false;
      });
    }
  }

  void _queue() {
    final info = _media;
    final url = _urlField.text.trim();
    if (url.isEmpty) return;

    if (info == null) {
      // Nothing was resolved. Handing a video page's URL to the engine would
      // download the HTML itself — a few hundred KB of markup saved as a file,
      // which looks like a broken download and is what this guards against.
      if (isMediaPage(url)) {
        setState(
          () => _error =
              'This is a video page, but no video could be found on it. '
              'It may be private, or the site may have changed. '
              'Tap Check link to try again.',
        );
        return;
      }
      widget.controller.manager.add(url);
    } else {
      final plan = info.plan(maxHeight: _chosenHeight);
      widget.controller.manager.addVideo(info, plan);
    }

    Navigator.pop(context);
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Added to queue')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.55,
      minChildSize: 0.4,
      maxChildSize: 0.92,
      builder: (context, scrollController) => Column(
        children: [
          const _Grabber(),
          Expanded(
            child: ListView(
              controller: scrollController,
              padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
              children: [
                const Text(
                  'Add download',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _urlField,
                  autofocus: widget.initialUrl == null,
                  keyboardType: TextInputType.url,
                  textInputAction: TextInputAction.go,
                  onSubmitted: (_) => _resolve(),
                  decoration: InputDecoration(
                    hintText: 'Paste a link',
                    prefixIcon: const Icon(Icons.link),
                    suffixIcon: _urlField.text.isEmpty
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.clear),
                            onPressed: () => setState(() {
                              _urlField.clear();
                              _media = null;
                              _error = null;
                            }),
                          ),
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: 16),

                if (_resolving) const _Resolving(),
                if (_error != null) _ErrorNotice(message: _error!),
                if (_media != null)
                  _VideoChoice(
                    info: _media!,
                    chosenHeight: _chosenHeight,
                    onPick: (h) => setState(() => _chosenHeight = h),
                  ),

                const SizedBox(height: 20),
                Row(
                  children: [
                    if (_media == null && !_resolving)
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _urlField.text.trim().isEmpty
                              ? null
                              : _resolve,
                          icon: const Icon(Icons.search, size: 18),
                          label: const Text('Check link'),
                        ),
                      ),
                    if (_media == null && !_resolving)
                      const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: _urlField.text.trim().isEmpty || _resolving
                            ? null
                            : _queue,
                        icon: const Icon(Icons.download, size: 18),
                        label: Text(_media == null ? 'Download' : 'Download'),
                      ),
                    ),
                  ],
                ),
                if (_media == null && !_resolving && _error == null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      'For a video page, tap Check link first to choose a quality.',
                      style: TextStyle(
                        fontSize: 12.5,
                        color: scheme.onSurfaceVariant,
                      ),
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

class _Grabber extends StatelessWidget {
  const _Grabber();

  @override
  Widget build(BuildContext context) => Container(
    width: 36,
    height: 4,
    margin: const EdgeInsets.symmetric(vertical: 12),
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.outlineVariant,
      borderRadius: BorderRadius.circular(2),
    ),
  );
}

class _Resolving extends StatelessWidget {
  const _Resolving();

  @override
  Widget build(BuildContext context) => const Padding(
    padding: EdgeInsets.symmetric(vertical: 24),
    child: Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        SizedBox(
          width: 18,
          height: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
        SizedBox(width: 12),
        Text('Reading the link…'),
      ],
    ),
  );
}

class _ErrorNotice extends StatelessWidget {
  const _ErrorNotice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: scheme.errorContainer.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, size: 20, color: scheme.error),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(message, style: const TextStyle(fontSize: 13.5)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _VideoChoice extends StatelessWidget {
  const _VideoChoice({
    required this.info,
    required this.chosenHeight,
    required this.onPick,
  });

  final MediaInfo info;
  final int? chosenHeight;
  final ValueChanged<int?> onPick;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final heights = info.videoHeights();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest.withValues(alpha: 0.4),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (info.thumbnail != null)
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(
                    info.thumbnail!,
                    width: 84,
                    height: 56,
                    fit: BoxFit.cover,
                    errorBuilder: (_, _, _) => const SizedBox.shrink(),
                  ),
                ),
              if (info.thumbnail != null) const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      info.title,
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 14,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (info.uploader != null || info.duration != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          [
                            if (info.uploader != null) info.uploader!,
                            if (info.duration != null)
                              formatDuration(info.duration),
                          ].join(' · '),
                          style: TextStyle(
                            fontSize: 12.5,
                            color: scheme.onSurfaceVariant,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),

        if (heights.isNotEmpty) ...[
          const SizedBox(height: 18),
          const Text(
            'Quality',
            style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final height in heights)
                ChoiceChip(
                  label: Text(_qualityLabel(height)),
                  selected: chosenHeight == height,
                  onSelected: (_) => onPick(height),
                ),
            ],
          ),
          const SizedBox(height: 8),
          _SizeEstimate(info: info, height: chosenHeight),
        ],
      ],
    );
  }

  String _qualityLabel(int height) => switch (height) {
    >= 2160 => '4K',
    >= 1440 => '1440p',
    >= 1080 => '1080p HD',
    >= 720 => '720p HD',
    _ => '${height}p',
  };
}

class _SizeEstimate extends StatelessWidget {
  const _SizeEstimate({required this.info, required this.height});

  final MediaInfo info;
  final int? height;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final plan = info.plan(maxHeight: height);
    final size = plan.totalSize;

    return Row(
      children: [
        Icon(
          plan.needsMux ? Icons.merge_type : Icons.insert_drive_file_outlined,
          size: 15,
          color: scheme.onSurfaceVariant,
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            size == null
                ? (plan.needsMux
                      ? 'Video and audio will be joined after downloading'
                      : 'Size unknown until the download starts')
                : '${formatBytes(size)}'
                      '${plan.needsMux ? ' · video and audio will be joined' : ''}',
            style: TextStyle(fontSize: 12.5, color: scheme.onSurfaceVariant),
          ),
        ),
      ],
    );
  }
}
