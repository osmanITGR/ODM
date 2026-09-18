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
        """Explain the load-unpacked step, which browsers require by design."""
        for widget in self.winfo_children():
            widget.destroy()

        ctk.CTkLabel(
            self, text="Installed", font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(padx=28, pady=(26, 2), anchor="w")
        ctk.CTkLabel(
            self,
            text="One step left for browser integration.",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_DIM,
        ).pack(padx=28, anchor="w")

        steps = (
            "1.  Open  chrome://extensions  or  edge://extensions",
            '2.  Turn on "Developer mode" (top right)',
            '3.  Click "Load unpacked" and pick the folder that opens',
            "4.  In ODM: Settings → Browser integration → Start bridge",
            "5.  Copy the token and paste it into the extension popup",
        )
        box = ctk.CTkFrame(self, fg_color=SURFACE_2, corner_radius=10,
                           border_width=1, border_color=BORDER)
        box.pack(padx=24, pady=(16, 0), fill="x")
        for line in steps:
            ctk.CTkLabel(
                box, text=line, font=ctk.CTkFont(size=12), justify="left",
                wraplength=380,
            ).pack(padx=16, pady=3, anchor="w")

        ctk.CTkLabel(
            self,
            text="Browsers block silent extension installs from disk, so this "
                 "part cannot be automated.",
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM,
            wraplength=400,
            justify="left",
        ).pack(padx=28, pady=(12, 0), anchor="w")

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(side="bottom", fill="x", padx=24, pady=20)
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

        setup.open_extension_folder()

    def _finish(self) -> None:
        setup.launch_installed()
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
