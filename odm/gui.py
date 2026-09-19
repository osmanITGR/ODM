"""ODM desktop interface."""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from .bridge import Bridge
from .clipboard import ClipboardMonitor
from .engine import State
from .manager import Manager
from .scheduler import Scheduler, parse_window

APP_ID = "com.osmanit.odm"
APP_NAME = "ODM"
VENDOR = "Osman IT"
WHATSAPP_NUMBER = "+8801625251930"
WHATSAPP_URL = "https://wa.me/8801625251930"
DEFAULT_DIR = Path.home() / "Downloads"

ACCENT = "#2f6fed"
SURFACE = "#1b1b1f"
SURFACE_2 = "#232329"
BORDER = "#34343c"
TEXT_DIM = "#8b8b96"

STATE_COLOR = {
    State.RUNNING: "#3fb950",
    State.DONE: "#58a6ff",
    State.PAUSED: "#d29922",
    State.ERROR: "#f85149",
    State.PENDING: TEXT_DIM,
    State.PROBING: TEXT_DIM,
}

STATE_LABEL = {
    State.PENDING: "Queued",
    State.PROBING: "Connecting",
    State.RUNNING: "Downloading",
    State.PAUSED: "Paused",
    State.DONE: "Completed",
    State.ERROR: "Failed",
}


def human_bytes(value: float) -> str:
    if value is None:
        return "--"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def human_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def resource_path(relative: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / relative if base else Path(__file__).parent / relative


class TaskRow(ctk.CTkFrame):
    """One download in the list."""

    def __init__(self, parent, task, on_pause, on_resume, on_remove, on_open):
        super().__init__(parent, fg_color=SURFACE_2, corner_radius=10, border_width=1, border_color=BORDER)
        self.task = task
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_remove = on_remove
        self.on_open = on_open

        self.columnconfigure(0, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        top.columnconfigure(0, weight=1)

        self.name_label = ctk.CTkLabel(
            top, text=task.name, font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        )
        self.name_label.grid(row=0, column=0, sticky="w")

        self.state_label = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=11), text_color=TEXT_DIM)
        self.state_label.grid(row=0, column=1, sticky="e", padx=(8, 0))

        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 6))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 10))
        bottom.columnconfigure(0, weight=1)

        self.stats_label = ctk.CTkLabel(bottom, text="", font=ctk.CTkFont(size=11), text_color=TEXT_DIM, anchor="w")
        self.stats_label.grid(row=0, column=0, sticky="w")

        self.action_btn = ctk.CTkButton(
            bottom, text="Pause", width=64, height=26, corner_radius=6,
            font=ctk.CTkFont(size=11), fg_color=SURFACE, hover_color=BORDER,
            border_width=1, border_color=BORDER, command=self._action,
        )
        self.action_btn.grid(row=0, column=1, padx=(6, 0))

        self.remove_btn = ctk.CTkButton(
            bottom, text="Remove", width=64, height=26, corner_radius=6,
            font=ctk.CTkFont(size=11), fg_color=SURFACE, hover_color="#5a2020",
            border_width=1, border_color=BORDER, command=lambda: self.on_remove(self.task),
        )
        self.remove_btn.grid(row=0, column=2, padx=(6, 0))

    def _action(self) -> None:
        state = self.task.state
        if state is State.RUNNING:
            self.on_pause(self.task)
        elif state is State.DONE:
            self.on_open(self.task)
        else:
            self.on_resume(self.task)

    def refresh(self) -> None:
        progress = self.task.download.progress
        state = progress.state

        self.name_label.configure(text=self.task.name)
        self.state_label.configure(
            text=STATE_LABEL.get(state, state.value), text_color=STATE_COLOR.get(state, TEXT_DIM)
        )

        if progress.total:
            self.bar.set(progress.percent / 100)
        elif state is State.DONE:
            self.bar.set(1.0)

        if state is State.RUNNING:
            self.bar.configure(progress_color=ACCENT)
            segs = len(self.task.download.segments) or 1
            self.stats_label.configure(
                text=f"{human_bytes(progress.downloaded)} / {human_bytes(progress.total)}   "
                     f"{human_bytes(progress.speed)}/s   ETA {human_time(progress.eta)}   {segs} conn"
            )
            self.action_btn.configure(text="Pause")
        elif state is State.DONE:
            self.bar.configure(progress_color=STATE_COLOR[State.DONE])
            if self.task.muxing:
                self.state_label.configure(text="Combining", text_color=STATE_COLOR[State.RUNNING])
                self.stats_label.configure(text="merging video and audio...")
                self.action_btn.configure(text="Open")
            elif self.task.mux_target and self.task.companion:
                self.state_label.configure(text="Waiting", text_color=TEXT_DIM)
                self.stats_label.configure(text="waiting for the other track")
                self.action_btn.configure(text="Open")
            else:
                self.stats_label.configure(
                    text=f"{human_bytes(progress.total or progress.downloaded)}   saved"
                )
                self.action_btn.configure(text="Open")
        elif state is State.PAUSED:
            self.bar.configure(progress_color=STATE_COLOR[State.PAUSED])
            self.stats_label.configure(
                text=f"{human_bytes(progress.downloaded)} / {human_bytes(progress.total)}   paused"
            )
            self.action_btn.configure(text="Resume")
        elif state is State.ERROR:
            self.bar.configure(progress_color=STATE_COLOR[State.ERROR])
            self.stats_label.configure(text=(progress.error or "failed")[:70])
            self.action_btn.configure(text="Retry")
        else:
            self.stats_label.configure(text=STATE_LABEL.get(state, ""))
            self.action_btn.configure(text="Pause" if state is State.RUNNING else "Resume")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        self.title(f"{APP_NAME} - Osman Download Manager")
        self.geometry("720x560")
        self.minsize(600, 420)
        self.configure(fg_color=SURFACE)

        icon = resource_path("icons/app.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self.dest_var = tk.StringVar(value=str(DEFAULT_DIR))
        self.conn_var = tk.StringVar(value="8")
        self.clip_var = tk.BooleanVar(value=False)
        self.limit_var = tk.StringVar(value="Unlimited")
        self.boost_var = tk.BooleanVar(value=True)

        self.manager = Manager(DEFAULT_DIR, connections=8, concurrent=3)
        self.rows: dict[str, TaskRow] = {}
        self.scheduler = Scheduler(self.manager)
        self.bridge = Bridge(self._bridge_download)

        self._build()

        self.monitor = ClipboardMonitor(self._clipboard_hit)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._tick)
        self._start_bridge_quietly()

        # The installer hands this over right after the extension step, so the
        # token is ready to paste when the popup asks for it.
        if "--copy-token" in sys.argv:
            self.after(600, self._copy_token_to_clipboard)

    def _copy_token_to_clipboard(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.bridge.token)
        self.summary_label.configure(
            text="Pairing token copied - paste it into the browser extension"
        )

    def _start_bridge_quietly(self) -> None:
        """Bring the bridge up on launch.

        The extension can only reach a running bridge, so leaving it off by
        default meant every session began with the extension reporting ODM as
        not running until someone found the Settings toggle. A failure here is
        not worth interrupting anyone over — Settings shows the real state and
        the error if they go looking.
        """
        try:
            self.bridge.start()
        except OSError:
            pass

    # layout -----------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text=APP_NAME, font=ctk.CTkFont(size=22, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        self.summary_label = ctk.CTkLabel(
            header, text="Idle", font=ctk.CTkFont(size=12), text_color=TEXT_DIM
        )
        self.summary_label.grid(row=0, column=1, sticky="e")

        entry_card = ctk.CTkFrame(self, fg_color=SURFACE_2, corner_radius=12, border_width=1, border_color=BORDER)
        entry_card.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        entry_card.columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            entry_card, placeholder_text="Paste a download link here",
            height=38, corner_radius=8, fg_color=SURFACE, border_color=BORDER,
        )
        self.url_entry.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=12)
        self.url_entry.bind("<Return>", lambda _e: self._add_from_entry())

        ctk.CTkButton(
            entry_card, text="Download", width=100, height=38, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"), fg_color=ACCENT,
            hover_color="#2558c0", command=self._add_from_entry,
        ).grid(row=0, column=1, padx=(0, 12), pady=12)

        options = ctk.CTkFrame(entry_card, fg_color="transparent")
        options.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        options.columnconfigure(1, weight=1)

        ctk.CTkLabel(options, text="Save to", font=ctk.CTkFont(size=11), text_color=TEXT_DIM).grid(
            row=0, column=0, sticky="w"
        )
        self.dest_entry = ctk.CTkEntry(
            options, textvariable=self.dest_var, height=30, corner_radius=6,
            fg_color=SURFACE, border_color=BORDER, font=ctk.CTkFont(size=11),
        )
        self.dest_entry.grid(row=0, column=1, sticky="ew", padx=8)

        ctk.CTkButton(
            options, text="...", width=34, height=30, corner_radius=6,
            fg_color=SURFACE, hover_color=BORDER, border_width=1, border_color=BORDER,
            command=self._browse,
        ).grid(row=0, column=2)

        ctk.CTkLabel(options, text="Connections", font=ctk.CTkFont(size=11), text_color=TEXT_DIM).grid(
            row=0, column=3, sticky="e", padx=(14, 6)
        )
        ctk.CTkOptionMenu(
            options, variable=self.conn_var, values=["1", "4", "8", "16", "32"],
            width=70, height=30, corner_radius=6, fg_color=SURFACE,
            button_color=BORDER, button_hover_color=ACCENT, font=ctk.CTkFont(size=11),
            command=self._set_connections,
        ).grid(row=0, column=4)

        ctk.CTkSwitch(
            options, text="Watch clipboard", variable=self.clip_var,
            font=ctk.CTkFont(size=11), progress_color=ACCENT,
            command=self._toggle_clipboard, height=24,
        ).grid(row=1, column=0, sticky="w", pady=(10, 0))

        ctk.CTkSwitch(
            options, text="Speed boost", variable=self.boost_var,
            font=ctk.CTkFont(size=11), progress_color=ACCENT,
            command=self._toggle_boost, height=24,
        ).grid(row=1, column=1, sticky="w", padx=(14, 0), pady=(10, 0))

        ctk.CTkLabel(options, text="Speed limit", font=ctk.CTkFont(size=11), text_color=TEXT_DIM).grid(
            row=1, column=3, sticky="e", padx=(14, 6), pady=(10, 0)
        )
        ctk.CTkOptionMenu(
            options, variable=self.limit_var,
            values=["Unlimited", "256 KB/s", "512 KB/s", "1 MB/s", "2 MB/s", "5 MB/s", "10 MB/s"],
            width=110, height=30, corner_radius=6, fg_color=SURFACE,
            button_color=BORDER, button_hover_color=ACCENT, font=ctk.CTkFont(size=11),
            command=self._set_speed_limit,
        ).grid(row=1, column=4, sticky="e", pady=(10, 0))

        self.list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", scrollbar_button_color=BORDER
        )
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.list_frame.columnconfigure(0, weight=1)

        self.empty_label = ctk.CTkLabel(
            self.list_frame, text="No downloads yet.\nPaste a link above to begin.",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM, justify="center",
        )
        self.empty_label.grid(row=0, column=0, pady=40)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 12))
        footer.columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(footer, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w")

        self.brand_link = ctk.CTkLabel(
            brand, text="Osman IT", font=ctk.CTkFont(size=11, weight="bold", underline=True),
            text_color=ACCENT, cursor="hand2",
        )
        self.brand_link.grid(row=0, column=0, sticky="w")
        self.brand_link.bind("<Button-1>", lambda _e: self._open_whatsapp())
        self.brand_link.bind("<Enter>", lambda _e: self._brand_hover(True))
        self.brand_link.bind("<Leave>", lambda _e: self._brand_hover(False))

        ctk.CTkLabel(
            brand, text=f"  {APP_ID}", font=ctk.CTkFont(size=10), text_color="#55555e"
        ).grid(row=0, column=1, sticky="w")

        ctk.CTkButton(
            footer, text="Settings", width=80, height=28, corner_radius=6,
            font=ctk.CTkFont(size=11), fg_color=SURFACE_2, hover_color=BORDER,
            border_width=1, border_color=BORDER, command=self._open_settings,
        ).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkButton(
            footer, text="Pause all", width=80, height=28, corner_radius=6,
            font=ctk.CTkFont(size=11), fg_color=SURFACE_2, hover_color=BORDER,
            border_width=1, border_color=BORDER, command=self.manager.pause_all,
        ).grid(row=0, column=2, padx=(6, 0))

        ctk.CTkButton(
            footer, text="Clear finished", width=110, height=28, corner_radius=6,
            font=ctk.CTkFont(size=11), fg_color=SURFACE_2, hover_color=BORDER,
            border_width=1, border_color=BORDER, command=self._clear_finished,
        ).grid(row=0, column=3, padx=(6, 0))

    # actions ----------------------------------------------------------

    def _toggle_boost(self) -> None:
        enabled = self.boost_var.get()
        self.manager.boost = enabled
        # Applies to running downloads too, not just newly queued ones. The
        # connection count is fixed when a download starts, so a running one
        # only picks up the change in work stealing until it is restarted.
        running = False
        for task in self.manager.tasks():
            task.download.boost = enabled
            if task.download.progress.state is State.RUNNING:
                running = True
        note = "Speed boost " + ("on" if enabled else "off")
        if running:
            note += " — full effect on next start"
        self.summary_label.configure(text=note)

    def _set_speed_limit(self, label: str) -> None:
        if label == "Unlimited":
            self.manager.speed_limit = 0.0
            return
        amount, _, unit = label.partition(" ")
        factor = 1024 if unit.startswith("KB") else 1024 * 1024
        self.manager.speed_limit = float(amount) * factor

    def _brand_hover(self, entering: bool) -> None:
        self.brand_link.configure(text_color="#5b8ff5" if entering else ACCENT)
        if entering:
            self._summary_before_hover = self.summary_label.cget("text")
            self.summary_label.configure(text=f"WhatsApp {WHATSAPP_NUMBER}")
        elif getattr(self, "_summary_before_hover", None) is not None:
            self.summary_label.configure(text=self._summary_before_hover)
            self._summary_before_hover = None

    def _open_whatsapp(self) -> None:
        import webbrowser

        webbrowser.open(WHATSAPP_URL)
        self.summary_label.configure(text=f"Opening WhatsApp {WHATSAPP_NUMBER}")

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.dest_var.get(), title="Choose download folder")
        if chosen:
            self.dest_var.set(chosen)
            self.manager.dest_dir = Path(chosen)

    def _set_connections(self, value: str) -> None:
        self.manager.connections = int(value)

    def _toggle_clipboard(self) -> None:
        if self.clip_var.get():
            self.monitor.start()
        else:
            self.monitor.stop()

    def _clipboard_hit(self, url: str) -> None:
        self.after(0, lambda: self._offer(url))

    def _offer(self, url: str) -> None:
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self.summary_label.configure(text="Link detected from clipboard")

    def _add_from_entry(self) -> None:
        url = self.url_entry.get().strip()
        if not url.lower().startswith(("http://", "https://")):
            self.summary_label.configure(text="Enter a http:// or https:// link")
            return
        self.manager.dest_dir = Path(self.dest_var.get())
        self.manager.connections = int(self.conn_var.get())
        self.url_entry.delete(0, "end")

        from . import video as video_mod

        if video_mod.available() and video_mod.is_media_page(url):
            self._resolve_video(url)
        else:
            self.manager.add(url)

    def _resolve_video(self, url: str) -> None:
        self.summary_label.configure(text="Reading video page...")

        def task():
            from . import video as video_mod

            try:
                info = video_mod.extract(url)
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._video_failed(url, e))
                return
            self.after(0, lambda: self._choose_quality(info))

        threading.Thread(target=task, daemon=True).start()

    def _video_failed(self, url: str, message: str) -> None:
        """Explain why a video page yielded nothing, in the user's terms.

        Queueing the page URL as a plain file used to be the fallback here,
        which downloaded the HTML itself under the video's name. That looks
        like a corrupt download, so a recognised video page now reports the
        failure instead. Anything unrecognised is still queued, since it may
        genuinely be a file whose type the extractor simply did not know.
        """
        from . import video as video_mod

        if video_mod.is_media_page(url):
            self.summary_label.configure(text=self._explain_video_error(url, message))
            return

        self.summary_label.configure(text="Not a video page - queued as file")
        self.manager.add(url)

    @staticmethod
    def _explain_video_error(url: str, message: str) -> str:
        """Turn an extractor error into something worth reading.

        yt-dlp's own text names flags and wiki pages, which is no help to
        someone who just pasted a link.
        """
        lowered = message.lower()
        if "logged-in" in lowered or "log in" in lowered or "private" in lowered:
            return "This video needs a login - it cannot be downloaded"
        if "not found" in lowered or "404" in lowered or "unavailable" in lowered:
            return "This video no longer exists or was removed"
        if "drm" in lowered or "protected" in lowered:
            return "This video is DRM protected - it cannot be downloaded"
        if "geo" in lowered or "region" in lowered or "country" in lowered:
            return "This video is blocked in your region"
        if "unsupported url" in lowered or "no video" in lowered:
            return "No video was found on that page"
        return "Could not read that video page - it may be private"

    def _choose_quality(self, info) -> None:
        heights = info.video_heights()
        if not heights:
            self._queue_video(info, None)
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Choose quality")
        dialog.geometry("380x260")
        dialog.resizable(False, False)
        dialog.configure(fg_color=SURFACE)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text=info.title[:60], font=ctk.CTkFont(size=13, weight="bold"),
            wraplength=340, justify="left",
        ).pack(padx=20, pady=(18, 4), anchor="w")

        if info.duration:
            ctk.CTkLabel(
                dialog, text=human_time(info.duration), font=ctk.CTkFont(size=11),
                text_color=TEXT_DIM,
            ).pack(padx=20, anchor="w")

        choice = tk.StringVar(value=f"{heights[0]}p")
        ctk.CTkLabel(
            dialog, text="Quality", font=ctk.CTkFont(size=11), text_color=TEXT_DIM
        ).pack(padx=20, pady=(14, 4), anchor="w")
        ctk.CTkOptionMenu(
            dialog, variable=choice, values=[f"{h}p" for h in heights] + ["Audio only"],
            width=200, height=32, corner_radius=6, fg_color=SURFACE_2,
            button_color=BORDER, button_hover_color=ACCENT,
        ).pack(padx=20, anchor="w")

        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=20, pady=18)

        def confirm():
            picked = choice.get()
            dialog.destroy()
            self._queue_video(info, None if picked == "Audio only" else int(picked[:-1]))

        ctk.CTkButton(
            row, text="Download", height=34, corner_radius=8, fg_color=ACCENT,
            hover_color="#2558c0", font=ctk.CTkFont(size=13, weight="bold"), command=confirm,
        ).pack(side="right")
        ctk.CTkButton(
            row, text="Cancel", width=80, height=34, corner_radius=8, fg_color=SURFACE_2,
            hover_color=BORDER, border_width=1, border_color=BORDER, command=dialog.destroy,
        ).pack(side="right", padx=(0, 8))

    def _queue_video(self, info, max_height: int | None) -> None:
        try:
            if max_height is None and not info.video_heights():
                plan = info.plan()
            elif max_height is None:
                audio = info.best_audio()
                if audio is None:
                    plan = info.plan()
                else:
                    from .video import DownloadPlan

                    plan = DownloadPlan(video=None, audio=audio, needs_mux=False)
            else:
                plan = info.plan(max_height=max_height)
        except ValueError as exc:
            self.summary_label.configure(text=str(exc))
            return

        from .video import ffmpeg_path

        if plan.needs_mux and not ffmpeg_path():
            self.summary_label.configure(text="ffmpeg needed for this quality - install it first")
            return

        self.manager.add_video(info, plan)
        self.summary_label.configure(text=f"Queued: {info.title[:40]}")

    def _pause(self, task) -> None:
        self.manager.pause(task.id)

    def _resume(self, task) -> None:
        self.manager.resume(task.id)

    def _remove(self, task) -> None:
        self.manager.remove(task.id)
        row = self.rows.pop(task.id, None)
        if row:
            row.destroy()

    def _open(self, task) -> None:
        target = task.result_path
        if target.exists():
            try:
                import os

                os.startfile(target.parent)
            except Exception:
                pass

    def _bridge_download(self, url: str, filename: str | None) -> None:
        self.after(0, lambda: self.manager.add(url, filename=filename))

    def _open_settings(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Settings")
        dialog.geometry("440x470")
        dialog.resizable(False, False)
        dialog.configure(fg_color=SURFACE)
        dialog.transient(self)

        def section(text):
            ctk.CTkLabel(
                dialog, text=text, font=ctk.CTkFont(size=13, weight="bold")
            ).pack(padx=20, pady=(16, 6), anchor="w")

        # --- browser integration ---
        section("Browser integration")

        bridge_state = tk.StringVar(
            value=f"Listening on {self.bridge.endpoint}" if self.bridge.running else "Off"
        )
        ctk.CTkLabel(
            dialog, textvariable=bridge_state, font=ctk.CTkFont(size=11), text_color=TEXT_DIM
        ).pack(padx=20, anchor="w")

        token_entry = ctk.CTkEntry(
            dialog, height=30, corner_radius=6, fg_color=SURFACE_2, border_color=BORDER,
            font=ctk.CTkFont(size=11, family="Consolas"),
        )
        token_entry.pack(padx=20, pady=(8, 4), fill="x")
        token_entry.insert(0, self.bridge.token)
        token_entry.configure(state="readonly")

        ctk.CTkLabel(
            dialog,
            text="Paste this token into the ODM browser extension. You only "
                 "need to do this once.",
            font=ctk.CTkFont(size=10), text_color=TEXT_DIM,
        ).pack(padx=20, anchor="w")

        def toggle_bridge():
            if self.bridge.running:
                self.bridge.stop()
                bridge_state.set("Off")
                bridge_btn.configure(text="Start bridge")
            else:
                try:
                    self.bridge.start()
                except OSError as exc:
                    bridge_state.set(f"Could not start: {exc}")
                    return
                bridge_state.set(f"Listening on {self.bridge.endpoint}")
                bridge_btn.configure(text="Stop bridge")

        def copy_token():
            self.clipboard_clear()
            self.clipboard_append(self.bridge.token)
            bridge_state.set("Token copied to clipboard")

        def new_token():
            """Issue a new token, for when the old one has been shared."""
            token_entry.configure(state="normal")
            token_entry.delete(0, "end")
            token_entry.insert(0, self.bridge.regenerate_token())
            token_entry.configure(state="readonly")
            bridge_state.set("New token - paste it into the extension again")

        row = ctk.CTkFrame(dialog, fg_color="transparent")
        row.pack(padx=20, pady=(8, 0), fill="x")
        bridge_btn = ctk.CTkButton(
            row, text="Stop bridge" if self.bridge.running else "Start bridge",
            width=110, height=30, corner_radius=6, fg_color=ACCENT, hover_color="#2558c0",
            font=ctk.CTkFont(size=11), command=toggle_bridge,
        )
        bridge_btn.pack(side="left")
        ctk.CTkButton(
            row, text="Copy token", width=100, height=30, corner_radius=6,
            fg_color=SURFACE_2, hover_color=BORDER, border_width=1, border_color=BORDER,
            font=ctk.CTkFont(size=11), command=copy_token,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            row, text="New token", width=95, height=30, corner_radius=6,
            fg_color=SURFACE_2, hover_color=BORDER, border_width=1, border_color=BORDER,
            font=ctk.CTkFont(size=11), command=new_token,
        ).pack(side="left", padx=(8, 0))

        # --- schedule ---
        section("Schedule")

        sched_var = tk.BooleanVar(value=self.scheduler.enabled)
        window_entry = ctk.CTkEntry(
            dialog, height=30, corner_radius=6, fg_color=SURFACE_2, border_color=BORDER,
            font=ctk.CTkFont(size=11), placeholder_text="23:00-06:00",
        )
        if self.scheduler.window:
            w = self.scheduler.window
            window_entry.insert(0, f"{w.start:%H:%M}-{w.end:%H:%M}")

        sched_status = tk.StringVar(value="")

        def apply_schedule():
            text = window_entry.get().strip()
            if sched_var.get():
                if not text:
                    sched_status.set("Enter a window like 23:00-06:00")
                    sched_var.set(False)
                    return
                try:
                    self.scheduler.window = parse_window(text)
                except (ValueError, IndexError):
                    sched_status.set("Could not read that time range")
                    sched_var.set(False)
                    return
                self.scheduler.enabled = True
                self.scheduler.start()
                sched_status.set(f"Downloads run {text}")
            else:
                self.scheduler.enabled = False
                self.scheduler.stop()
                sched_status.set("Downloads run any time")

        ctk.CTkSwitch(
            dialog, text="Only download during a time window", variable=sched_var,
            font=ctk.CTkFont(size=11), progress_color=ACCENT, command=apply_schedule,
        ).pack(padx=20, anchor="w")

        window_entry.pack(padx=20, pady=(8, 4), fill="x")
        ctk.CTkLabel(
            dialog, textvariable=sched_status, font=ctk.CTkFont(size=10), text_color=TEXT_DIM
        ).pack(padx=20, anchor="w")

        ctk.CTkButton(
            dialog, text="Apply window", width=110, height=30, corner_radius=6,
            fg_color=SURFACE_2, hover_color=BORDER, border_width=1, border_color=BORDER,
            font=ctk.CTkFont(size=11), command=apply_schedule,
        ).pack(padx=20, pady=(6, 0), anchor="w")

        ctk.CTkButton(
            dialog, text="Close", height=32, corner_radius=8, fg_color=SURFACE_2,
            hover_color=BORDER, border_width=1, border_color=BORDER, command=dialog.destroy,
        ).pack(side="bottom", padx=20, pady=16, fill="x")

    def _clear_finished(self) -> None:
        for task in self.manager.tasks():
            if task.state is State.DONE:
                self._remove(task)

    # refresh ----------------------------------------------------------

    def _tick(self) -> None:
        tasks = self.manager.tasks()

        # Drop rows whose task the manager retired, e.g. the audio half of a
        # muxed pair once the merge finished.
        live = {t.id for t in tasks}
        for task_id in [tid for tid in self.rows if tid not in live]:
            self.rows.pop(task_id).destroy()

        for index, task in enumerate(tasks):
            row = self.rows.get(task.id)
            if row is None:
                row = TaskRow(self.list_frame, task, self._pause, self._resume, self._remove, self._open)
                self.rows[task.id] = row
            row.grid(row=index, column=0, sticky="ew", pady=4)
            row.refresh()

        if tasks:
            self.empty_label.grid_remove()
        else:
            self.empty_label.grid(row=0, column=0, pady=40)

        self.manager.pump()

        active, speed = self.manager.totals()
        if getattr(self, "_summary_before_hover", None) is None:
            if active:
                self.summary_label.configure(text=f"{active} active   {human_bytes(speed)}/s")
            elif tasks and all(t.state is State.DONE for t in tasks):
                self.summary_label.configure(text="All downloads complete")
            elif not tasks:
                self.summary_label.configure(text="Idle")

        self.after(400, self._tick)

    def _on_close(self) -> None:
        self.monitor.stop()
        self.scheduler.stop()
        self.bridge.stop()
        self.manager.pause_all()
        self.destroy()


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
