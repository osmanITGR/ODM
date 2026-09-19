"""The install window shown when ODM.exe is run outside its install location."""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from . import setup

ACCENT = "#2f6fed"
SURFACE = "#1b1b1f"
SURFACE_2 = "#232329"
BORDER = "#34343c"
TEXT_DIM = "#8b8b96"


def _browser_icon(executable, size: int = 16):
    """A browser's own icon for its button, or None if unavailable.

    Icons are a nicety: a missing one leaves a text-only button rather than
    breaking the window. Shared with the Settings dialog, which shows the
    same buttons.
    """
    path = setup.browser_icon(executable)
    if path is None:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            loaded = image.convert("RGBA")
        return ctk.CTkImage(light_image=loaded, dark_image=loaded, size=(size, size))
    except Exception:
        return None


class SetupWindow(ctk.CTk):
    """First-run installer. Sets self.launch_after when the app should start."""

    def __init__(self) -> None:
        super().__init__()
        self.launch_after = False

        self.title("Install ODM")
        self.geometry("460x420")
        self.resizable(False, False)
        self.configure(fg_color=SURFACE)

        try:
            from .gui import resource_path

            self.iconbitmap(str(resource_path("icons/app.ico")))
        except Exception:
            pass

        ctk.CTkLabel(
            self,
            text="ODM",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(padx=28, pady=(26, 0), anchor="w")
        ctk.CTkLabel(
            self,
            text="Osman Download Manager",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_DIM,
        ).pack(padx=28, anchor="w")

        ctk.CTkLabel(
            self,
            text=f"Install location\n{setup.INSTALL_DIR}",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
            justify="left",
        ).pack(padx=28, pady=(20, 0), anchor="w")

        self.desktop_var = tk.BooleanVar(value=True)
        self.startup_var = tk.BooleanVar(value=False)
        self.extension_var = tk.BooleanVar(value=True)

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(padx=24, pady=(16, 0), fill="x")

        for text, var in (
            ("Create a desktop shortcut", self.desktop_var),
            ("Start ODM when Windows starts", self.startup_var),
            ("Set up browser integration", self.extension_var),
        ):
            ctk.CTkCheckBox(
                opts,
                text=text,
                variable=var,
                font=ctk.CTkFont(size=12),
                fg_color=ACCENT,
                hover_color="#2558c0",
                border_color=BORDER,
                corner_radius=4,
                checkbox_width=18,
                checkbox_height=18,
            ).pack(anchor="w", pady=5)

        self.status = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
            wraplength=400, justify="left",
        )
        self.status.pack(padx=28, pady=(14, 0), anchor="w")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=20)

        self.install_btn = ctk.CTkButton(
            row, text="Install", height=38, corner_radius=8, fg_color=ACCENT,
            hover_color="#2558c0", font=ctk.CTkFont(size=13, weight="bold"),
            command=self._install,
        )
        self.install_btn.pack(side="right")
        ctk.CTkButton(
            row, text="Just run it", width=100, height=38, corner_radius=8,
            fg_color=SURFACE_2, hover_color=BORDER, border_width=1,
            border_color=BORDER, command=self._skip,
        ).pack(side="right", padx=(0, 8))

    def _skip(self) -> None:
        """Run without installing, from wherever the executable happens to be."""
        self.launch_after = True
        self.destroy()

    def _install(self) -> None:
        self.install_btn.configure(state="disabled", text="Installing...")
        self.status.configure(text="Copying files...", text_color=TEXT_DIM)
        self.update_idletasks()

        try:
            setup.install(
                desktop_icon=self.desktop_var.get(),
                run_at_startup=self.startup_var.get(),
            )
        except OSError as exc:
            self.status.configure(text=f"Install failed: {exc}", text_color="#f85149")
            self.install_btn.configure(state="normal", text="Install")
            return

        if self.extension_var.get():
            self._show_extension_step()
        else:
            self._finish()

    def _show_extension_step(self) -> None:
        """Walk the user through Load unpacked, doing every part that can be.

        Chrome removed silent extension installs in 2018, so the final pick
        has to be the user's. Everything leading up to it is automated: the
        folder is on the clipboard before the picker opens, and a button per
        installed browser opens that browser straight at its extensions page.
        """
        for widget in self.winfo_children():
            widget.destroy()

        self.geometry("480x560")

        ctk.CTkLabel(
            self, text="Installed", font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#e6e6ea",
        ).pack(padx=28, pady=(24, 2), anchor="w")
        ctk.CTkLabel(
            self,
            text="Last step: connect your browser.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_DIM,
        ).pack(padx=28, anchor="w")

        browsers = setup.find_browsers()

        # Step 1 -----------------------------------------------------------
        # find_browsers() puts the one in use first, so opening browsers[0] is
        # opening whichever browser the user is actually in.
        self._step_heading("1.  Opening your browser with the steps")

        if browsers:
            grid = ctk.CTkFrame(self, fg_color="transparent")
            grid.pack(padx=24, pady=(6, 0), fill="x")
            # Kept alive on self, or Tk collects the images out from under
            # the buttons still showing them.
            self._browser_icons = []
            for browser in browsers:
                icon = _browser_icon(browser[2])
                if icon is not None:
                    self._browser_icons.append(icon)
                ctk.CTkButton(
                    grid, text=browser[0], image=icon, compound="left",
                    width=106 if icon else 96, height=34, corner_radius=8,
                    fg_color=SURFACE_2, hover_color=BORDER, border_width=1,
                    border_color=BORDER, font=ctk.CTkFont(size=12),
                    command=lambda b=browser: self._open_browser(b),
                ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(
                self, text="Using another browser? Pick it above.",
                font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
            ).pack(padx=28, pady=(6, 0), anchor="w")
        else:
            # No known browser on disk: the address still works if typed.
            ctk.CTkLabel(
                self, text="Type  chrome://extensions  in your browser.",
                font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
            ).pack(padx=28, pady=(6, 0), anchor="w")

        # Steps 2-3 --------------------------------------------------------
        self._step_heading('2.  Turn on "Developer mode" (top right)')
        self._step_heading('3.  Click "Load unpacked", then paste this folder')

        path_row = ctk.CTkFrame(self, fg_color="transparent")
        path_row.pack(padx=24, pady=(6, 0), fill="x")
        path_box = ctk.CTkEntry(
            path_row, height=32, corner_radius=8, fg_color=SURFACE_2,
            border_color=BORDER, text_color="#e6e6ea",
            font=ctk.CTkFont(size=11, family="Consolas"),
        )
        path_box.pack(side="left", fill="x", expand=True)
        path_box.insert(0, str(setup.EXTENSION_DIR))
        path_box.configure(state="readonly")
        ctk.CTkButton(
            path_row, text="Copy", width=64, height=32, corner_radius=8,
            fg_color=SURFACE_2, hover_color=BORDER, border_width=1,
            border_color=BORDER, font=ctk.CTkFont(size=12),
            command=self._copy_path,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            self,
            text="Already copied — press Ctrl+V in the folder picker.",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
        ).pack(padx=28, pady=(4, 0), anchor="w")

        # Step 4 -----------------------------------------------------------
        self._step_heading("4.  Paste the token into the extension popup")
        ctk.CTkLabel(
            self,
            text="ODM opens with the token ready. Click the ODM icon in your "
                 "browser toolbar, paste, and press Save.",
            font=ctk.CTkFont(size=11), text_color=TEXT_DIM,
            wraplength=410, justify="left",
        ).pack(padx=28, pady=(4, 0), anchor="w")

        self.ext_status = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11), text_color="#3fb950",
        )
        self.ext_status.pack(padx=28, pady=(10, 0), anchor="w")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=18)
        ctk.CTkButton(
            row, text="Open ODM", height=38, corner_radius=8, fg_color=ACCENT,
            hover_color="#2558c0", font=ctk.CTkFont(size=13, weight="bold"),
            command=self._finish,
        ).pack(side="right")
        ctk.CTkButton(
            row, text="Open folder", width=110, height=38, corner_radius=8,
            fg_color=SURFACE_2, hover_color=BORDER, border_width=1,
            border_color=BORDER, command=setup.open_extension_folder,
        ).pack(side="right", padx=(0, 8))

        # Have the path waiting before the picker is ever opened.
        self._copy_path(announce=False)

        if browsers:
            # Open the browser the user is in, a moment after this window has
            # drawn — immediately would put it behind the new browser window
            # with no idea why it appeared.
            self.after(900, lambda: self._open_browser(browsers[0], auto=True))

    def _step_heading(self, text: str) -> None:
        # Explicit colour: the theme default is too dim against this
        # background, and these headings are the instructions themselves.
        ctk.CTkLabel(
            self, text=text, font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e6e6ea", justify="left", wraplength=410,
        ).pack(padx=28, pady=(16, 0), anchor="w")

    def _copy_path(self, announce: bool = True) -> None:
        copied = setup.copy_to_clipboard(str(setup.EXTENSION_DIR))
        if announce and hasattr(self, "ext_status"):
            self.ext_status.configure(
                text="Folder path copied" if copied else "Could not copy - "
                     "select the path above and copy it manually",
                text_color="#3fb950" if copied else "#d29922",
            )

    def _open_browser(self, browser, auto: bool = False) -> None:
        if setup.open_extensions_page(browser):
            # The picker is next, so make sure the path is what gets pasted.
            self._copy_path(announce=False)
            self.ext_status.configure(
                text=f"{browser[0]} opened - folder path is on your clipboard",
                text_color="#3fb950",
            )
            # Keep this window visible: the browser takes focus, and these
            # instructions are what the user needs while they are in it.
            self.lift()
            self.attributes("-topmost", True)
            self.after(2500, lambda: self.attributes("-topmost", False))
        elif auto:
            # Nothing the user did failed, so point at the buttons instead of
            # reporting an error they did not cause.
            self.ext_status.configure(
                text="Click your browser above to open its extensions page",
                text_color="#d29922",
            )
        else:
            self.ext_status.configure(
                text=f"Could not open {browser[0]}", text_color="#d29922",
            )

    def _finish(self) -> None:
        # Only after the extension step, where the token is the next thing
        # the user needs.
        setup.launch_installed(copy_token=self.extension_var.get())
        self.destroy()


def run_setup() -> bool:
    """Show the installer. Returns True if this process should continue as the app."""
    ctk.set_appearance_mode("dark")
    window = SetupWindow()
    window.mainloop()
    return window.launch_after


def confirm_uninstall() -> None:
    """Minimal confirm dialog for the Add/Remove Programs entry point."""
    ctk.set_appearance_mode("dark")
    window = ctk.CTk()
    window.title("Uninstall ODM")
    window.geometry("380x180")
    window.resizable(False, False)
    window.configure(fg_color=SURFACE)

    ctk.CTkLabel(
        window, text="Uninstall ODM?", font=ctk.CTkFont(size=16, weight="bold"),
    ).pack(padx=24, pady=(28, 4), anchor="w")
    ctk.CTkLabel(
        window,
        text="Shortcuts and program files will be removed.\n"
             "Downloaded files are kept.",
        font=ctk.CTkFont(size=12), text_color=TEXT_DIM, justify="left",
    ).pack(padx=24, anchor="w")

    row = ctk.CTkFrame(window, fg_color="transparent")
    row.pack(side="bottom", fill="x", padx=24, pady=20)

    def do_uninstall() -> None:
        setup.uninstall()
        window.destroy()

    ctk.CTkButton(
        row, text="Uninstall", height=36, corner_radius=8, fg_color="#c93c37",
        hover_color="#a62f2b", font=ctk.CTkFont(size=13, weight="bold"),
        command=do_uninstall,
    ).pack(side="right")
    ctk.CTkButton(
        row, text="Cancel", width=90, height=36, corner_radius=8,
        fg_color=SURFACE_2, hover_color=BORDER, border_width=1,
        border_color=BORDER, command=window.destroy,
    ).pack(side="right", padx=(0, 8))

    window.mainloop()
