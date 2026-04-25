#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Standalone GTK4 dialog for vault password input.

This script runs as a subprocess to avoid GTK/asyncio conflicts.
Called by _vault_dialog.py with vault name as argument.
Returns password to stdout or exits with error code.

Exit codes:
  0  — password printed to stdout
  1  — usage error
  2  — user cancelled
  3  — GTK4 unavailable or display cannot be opened
"""

import sys


def main():
    """Prompt for vault password in GTK dialog."""
    if len(sys.argv) < 2:
        print("Usage: _vault_password_dialog.py <vault_name>", file=sys.stderr)
        sys.exit(1)

    vault_name = sys.argv[1]

    # Import GTK
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import GLib, Gtk
    except (ImportError, ValueError) as e:
        print(f"GTK4 not available: {e}", file=sys.stderr)
        sys.exit(3)

    GLib.set_prgname("freeipa-mcp")

    # Check display
    try:
        display = Gtk.init_check()
        if not display:
            raise RuntimeError("Gtk.init_check() returned False")
    except Exception as exc:
        print(f"Cannot open display: {exc}", file=sys.stderr)
        sys.exit(3)

    loop = GLib.MainLoop()
    outcome: dict = {"state": "unset", "password": None}

    # Create window
    window = Gtk.Window(title=f"Vault Password - {vault_name}", default_width=400)

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    vbox.set_margin_top(20)
    vbox.set_margin_bottom(20)
    vbox.set_margin_start(20)
    vbox.set_margin_end(20)

    # Label
    label = Gtk.Label(label=f"Enter password for vault '{vault_name}':")
    label.set_halign(Gtk.Align.START)
    label.set_wrap(True)
    vbox.append(label)

    # Password entry
    entry = Gtk.PasswordEntry(placeholder_text="Vault password", show_peek_icon=True)
    entry.set_margin_top(6)
    vbox.append(entry)

    # Button box
    btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    btn_box.set_halign(Gtk.Align.END)
    btn_box.set_margin_top(12)

    def quit_with(state: str, pwd: str | None = None) -> None:
        outcome["state"] = state
        outcome["password"] = pwd
        loop.quit()

    # Cancel button
    cancel_btn = Gtk.Button(label="Cancel")
    cancel_btn.connect("clicked", lambda _: quit_with("cancelled"))
    btn_box.append(cancel_btn)

    # OK button
    ok_btn = Gtk.Button(label="OK")
    ok_btn.add_css_class("suggested-action")

    def on_ok(_: Gtk.Button | None) -> None:
        pwd = entry.get_text()
        if pwd:
            quit_with("ok", pwd)

    ok_btn.connect("clicked", on_ok)
    btn_box.append(ok_btn)

    vbox.append(btn_box)
    window.set_child(vbox)
    window.set_default_widget(ok_btn)
    entry.grab_focus()
    entry.connect("activate", lambda _: on_ok(None))

    def on_close_request(_: Gtk.Window) -> bool:
        if outcome["state"] == "unset":
            quit_with("cancelled")
        return False

    window.connect("close-request", on_close_request)
    window.present()
    loop.run()

    # Return result
    state = outcome.get("state", "unset")
    if state == "ok":
        print(outcome["password"])
        sys.exit(0)
    else:
        # User cancelled
        sys.exit(2)


if __name__ == "__main__":
    main()
