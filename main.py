"""ODM entry point.

The executable doubles as its own installer: run from outside the install
directory it offers to install itself, and `--uninstall` is what the
Add/Remove Programs entry invokes.
"""

import sys


def main() -> int:
    if "--uninstall" in sys.argv:
        from odm.setup_ui import confirm_uninstall

        confirm_uninstall()
        return 0

    from odm import setup

    if not setup.is_installed() and "--no-setup" not in sys.argv:
        from odm.setup_ui import run_setup

        if not run_setup():
            return 0  # installed and relaunched, or cancelled

    from odm.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
