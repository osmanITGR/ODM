# ODM for Android

`com.osmanit.odm` · [Osman IT — WhatsApp +8801625251930](https://wa.me/8801625251930)

The Android companion to the Windows build in [`../odm/`](../odm/). Same
segmented engine, same work-stealing speed boost, same resume-across-restarts —
ported from Python to Dart.

## What carried over, and what had to change

| Windows (`odm/`) | Android (`lib/`) | Why |
|---|---|---|
| `engine.py` | `engine/download_engine.dart` | Threads became async tasks: parallelism without extra threads, and the UI isolate never blocks |
| `manager.py` | `engine/manager.dart` | Plus persistence — Android kills processes freely, so the queue is written to disk |
| `video.py` (yt-dlp) | `engine/extractor.dart` | yt-dlp needs a Python runtime; extraction is done natively instead |
| `video.mux()` (ffmpeg) | `engine/muxer.dart` + `Muxer.kt` | Bundling ffmpeg would add ~30 MB; `MediaMuxer` does the same stream copy |
| `gui.py` (CustomTkinter) | `ui/` (Flutter) | Tkinter does not run on Android |
| `clipboard.py` | Share intent + clipboard read | Android has no global clipboard watching |
| `bridge.py` + extension | `services/incoming_links.dart` | Android browsers have no extensions |
| `setup.py`, `setup_ui.py` | — | Windows registry and Add/Remove Programs only |

## Running from source

```
flutter pub get
flutter run
```

## Building

```
flutter build apk --release --split-per-abi
```

Outputs land in `build/app/outputs/flutter-apk/`:

- `app-arm64-v8a-release.apk` (18 MB) — modern phones, the one to distribute
- `app-armeabi-v7a-release.apk` (16 MB) — older 32-bit devices
- `app-x86_64-release.apk` — emulators only

Release signing reads `android/key.properties`, which is not in the repo. See
`KEYSTORE-BACKUP-গুরুত্বপূর্ণ.txt` (also not in the repo) for the details and
for what to do on a new machine. Without that file the build falls back to debug
keys, which produces an APK that cannot be updated in place later.

## Launcher icon

The icon is the Windows app's artwork, redrawn as geometry rather than upscaled
(the 256px original stair-steps badly at 1024px):

```
python tool/make_icons.py          # writes assets/icon/
dart run flutter_launcher_icons    # writes the res/ densities
```

`odm_foreground.png` is drawn near full-bleed on purpose:
`flutter_launcher_icons` applies its own 16% inset when building the adaptive
icon, and insetting in both places leaves the arrow visibly undersized.

## Tests

```
flutter test
```

56 tests, no network needed. They cover the parts where a bug is expensive:
segment planning (a byte-range off-by-one silently corrupts a file), the rate
limiter, format selection, URL classification, and pulling a URL out of shared
text.

Two real bugs were caught here before the app ever ran — a rate-limiter
infinite loop that froze downloads whenever the speed cap fell below the
socket's block size, and a filename fallback that saved files literally named
`_`. Both have regression tests.

## How a download runs

1. **Probe** — a one-byte range request reveals the total size, whether the
   server supports ranges, and the filename.
2. **Plan** — the size is split into roughly equal segments, one per connection.
   Segments below 1 MB are merged, since per-request overhead would exceed the
   benefit.
3. **Fetch** — one async task per segment writes into its own region of a
   preallocated `.part` file, so no reassembly step is needed.
4. **Steal** — a task that finishes early halves the slowest remaining segment
   and takes the tail, instead of going idle. This is what makes the boost
   measurably faster rather than a label.
5. **Checkpoint** — segment offsets are written to a sidecar JSON file keyed by
   URL hash every two seconds, which is what makes resume work after the process
   is killed.
6. **Finish** — the `.part` file is renamed into place, the sidecar removed, and
   the file handed to `MediaScanner` so the gallery can see it.

## Video extraction

`extractor.dart` tries three things in order:

1. **Site-specific** — YouTube goes through the InnerTube player endpoint using
   the Android client, which returns unciphered stream URLs. The watch page's
   own URLs are signature-ciphered and would need a JavaScript interpreter.
2. **Generic markup** — Open Graph tags, JSON-LD `contentUrl`, bare
   `<video>`/`<source>` elements, and the escaped JSON blobs Facebook,
   Instagram and TikTok embed their playback URLs in.
3. **Direct file** — if the URL (or what it redirects to) is already a media
   file, it is probed and offered as a single format.

Fragmented streams (HLS `.m3u8`, DASH `.mpd`) are filtered out: they cannot be
fetched as one ranged file.

Known limits: YouTube changes its defences regularly, so that path will break
periodically. DRM-protected services (Netflix, Prime Video) are not possible by
any means and are not attempted.

## How links get in

Four intent filters in `AndroidManifest.xml`, all landing in
`services/incoming_links.dart`:

- `SEND` / `SEND_MULTIPLE` — the share sheet. Both `text/plain` and `text/*`
  are declared: several apps, Facebook included, do not always send
  `text/plain`, and a filter listing only that silently drops them.
- `VIEW` on a named host — "Open with ODM" on a video link. Hosts are listed
  explicitly rather than matching all of http(s), which would put ODM in the
  chooser for ordinary web pages.
- `VIEW` on a media mime type — a direct file link on any host.
- `PROCESS_TEXT` — text selected anywhere on the phone.

The native side hands over whatever text the intent carried; `firstUrlIn()`
extracts the URL. Apps rarely send a bare one — Facebook shares a sentence
("Check this out! https://fb.watch/…"), YouTube appends the title — and
treating the whole string as a URL is what made those shares fail.

## Background behaviour

Android suspends an app's threads within seconds of the user leaving it, which
on a phone is most of the time a large download is in flight. `DownloadService`
is a foreground service holding a partial wake lock, started exactly while work
is active and stopped when the queue drains — leaving it up drains the battery,
taking it down early suspends the transfer.

The wake lock carries a 6-hour timeout. A leaked indefinite one would flatten
the battery if the app ever failed to stop the service.

## Layout

```
lib/
  engine/
    models.dart           Segment, Progress, DownloadState
    rate_limiter.dart     app-wide token bucket, and byte/duration formatting
    download_engine.dart  probe, segment planning, work stealing, resume
    manager.dart          queue, concurrency, persistence, mux pairing
    task.dart             one queue entry, including muxed video+audio pairs
    extractor.dart        page URL -> media streams
    video_models.dart     MediaFormat, MediaInfo, format selection
    muxer.dart            method-channel wrapper around MediaMuxer
  services/
    app_controller.dart   owns the manager; foreground service, notifications,
                          Wi-Fi-only rule
    settings.dart         persisted preferences
    storage.dart          download directory and runtime permissions
    notifications.dart    completion and failure notifications
  ui/
    theme.dart            colours and component styling
    home_screen.dart      the download list
    download_tile.dart    one row
    add_download_sheet.dart  paste/share a link, pick a quality
    settings_screen.dart
android/app/src/main/kotlin/com/osmanit/odm/
  MainActivity.kt         method channel wiring
  Muxer.kt                MediaMuxer stream copy
  DownloadService.kt      foreground service and wake lock
test/
  engine_test.dart        segment maths, rate limiter, formatting
  extractor_test.dart     URL classification, format selection
```
