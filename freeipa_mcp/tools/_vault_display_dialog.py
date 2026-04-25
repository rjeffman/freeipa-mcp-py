#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Standalone GTK4 dialog for displaying vault data.

This script runs as a subprocess to avoid GTK/asyncio conflicts.
Called by _vault_dialog.py with vault name and base64-encoded data.

Exit codes:
  0  — success
  1  — usage error
  2  — decode error
  3  — GTK4 unavailable or display cannot be opened
"""

import base64
import sys
from pathlib import Path


def main():
    """Display vault data in GTK dialog."""
    if len(sys.argv) < 3:
        print(
            "Usage: _vault_display_dialog.py <vault_name> <base64_data>",
            file=sys.stderr,
        )
        sys.exit(1)

    vault_name = sys.argv[1]
    data_b64 = sys.argv[2]

    try:
        data = base64.b64decode(data_b64)
    except Exception as e:
        print(f"Failed to decode data: {e}", file=sys.stderr)
        sys.exit(2)

    # Import GTK
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("GLib", "2.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, GLib, Gtk
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

    # Create window
    window = Gtk.Window(
        title=f"Vault Data - {vault_name}", default_width=600, default_height=400
    )

    vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    vbox.set_margin_top(20)
    vbox.set_margin_bottom(20)
    vbox.set_margin_start(20)
    vbox.set_margin_end(20)

    # Label
    label = Gtk.Label(label=f"Retrieved data from vault '{vault_name}':")
    label.set_halign(Gtk.Align.START)
    label.set_wrap(True)
    vbox.append(label)

    # Scrolled window with text view
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_hexpand(True)
    scrolled.set_vexpand(True)
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

    textview = Gtk.TextView()
    textview.set_editable(False)
    textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    textview.set_monospace(True)

    # Try to decode as UTF-8, fallback to repr
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = f"Binary data ({len(data)} bytes):\n{repr(data)}"

    textbuffer = textview.get_buffer()
    textbuffer.set_text(text)

    scrolled.set_child(textview)
    vbox.append(scrolled)

    # Button box
    button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    button_box.set_halign(Gtk.Align.END)

    # Copy to clipboard button
    copy_button = Gtk.Button(label="Copy to Clipboard")

    def on_copy(_button):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)

    copy_button.connect("clicked", on_copy)
    button_box.append(copy_button)

    # Save to file button
    save_button = Gtk.Button(label="Save to File...")

    def on_save(_button):
        file_dialog = Gtk.FileDialog()
        file_dialog.set_initial_name(f"{vault_name}.txt")

        def on_save_finish(dialog, result):
            try:
                file = dialog.save_finish(result)
                if file:
                    filepath = file.get_path()
                    try:
                        Path(filepath).write_bytes(data)
                    except Exception as e:
                        error_dialog = Gtk.AlertDialog()
                        error_dialog.set_message(f"Failed to save file: {e}")
                        error_dialog.show(window)
            except Exception:
                # User cancelled
                pass

        file_dialog.save(window, None, on_save_finish)

    save_button.connect("clicked", on_save)
    button_box.append(save_button)

    # OK button to close window
    ok_button = Gtk.Button(label="OK")
    ok_button.add_css_class("suggested-action")
    ok_button.connect("clicked", lambda _: loop.quit())
    button_box.append(ok_button)

    vbox.append(button_box)
    window.set_child(vbox)

    def on_close_request(_: Gtk.Window) -> bool:
        loop.quit()
        return False

    window.connect("close-request", on_close_request)
    window.present()
    loop.run()

    sys.exit(0)


if __name__ == "__main__":
    main()
