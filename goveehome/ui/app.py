from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from goveehome import APP_ID, APP_NAME, __version__  # noqa: E402
from goveehome.config import Config  # noqa: E402
from goveehome.manager import DeviceManager  # noqa: E402

HERE = Path(__file__).resolve().parent

SHORTCUTS = """
<interface>
  <object class="GtkShortcutsWindow" id="help_overlay">
    <property name="modal">1</property>
    <child>
      <object class="GtkShortcutsSection">
        <property name="section-name">shortcuts</property>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">General</property>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Search for lights</property>
              <property name="accelerator">&lt;Primary&gt;r F5</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Start or stop screen sync</property>
              <property name="accelerator">&lt;Primary&gt;s</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Preferences</property>
              <property name="accelerator">&lt;Primary&gt;comma</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Keyboard shortcuts</property>
              <property name="accelerator">&lt;Primary&gt;question</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Quit</property>
              <property name="accelerator">&lt;Primary&gt;q</property></object></child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>
"""


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        GLib.set_application_name(APP_NAME)
        self.config = Config()
        self.manager = DeviceManager(self.config)
        self.engine = None
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._action("refresh", lambda *_: self.manager.discover(), ["<Primary>r", "F5"])
        self._action("toggle-sync", self._toggle_sync, ["<Primary>s"])
        self._action("preferences", self._preferences, ["<Primary>comma"])
        self._action("add-host", self._add_host)
        self._action("about", self._about)
        self._action("quit", lambda *_: self.quit(), ["<Primary>q"])
        self.set_accels_for_action("win.show-help-overlay", ["<Primary>question"])
        self.manager.start()

    def _action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def do_activate(self):
        if self.window is None:
            from goveehome.ui.window import MainWindow
            self.window = MainWindow(self)
            builder = Gtk.Builder.new_from_string(SHORTCUTS, -1)
            self.window.set_help_overlay(builder.get_object("help_overlay"))
        self.window.present()

    def do_shutdown(self):
        if self.engine is not None:
            self.engine.stop()
        self.manager.stop()
        Adw.Application.do_shutdown(self)

    # actions -----------------------------------------------------------------
    def _toggle_sync(self, *_):
        if self.window:
            self.window.sync_page._on_toggle()

    def _preferences(self, *_):
        from goveehome.ui.preferences import PreferencesWindow
        PreferencesWindow(self.window).present()

    def _add_host(self, *_):
        dialog = Adw.MessageDialog(
            transient_for=self.window, modal=True, heading="Add Light by Address",
            body="Enter the IP address of a light with LAN Control on. You can find it in your "
                 "router's list of connected devices.")
        entry = Gtk.Entry(placeholder_text="192.168.1.50", activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("add")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response):
            text = entry.get_text().strip()
            if response == "add" and text:
                import ipaddress
                try:
                    ipaddress.IPv4Address(text)
                except ValueError:
                    self.window.toast(f"{text} is not an IPv4 address")
                    return
                self.manager.add_host(text)
                self.window.toast(f"Asking {text}…")
        dialog.connect("response", on_response)
        dialog.present()

    def _about(self, *_):
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="Colin",
            developers=["Colin"],
            version=__version__,
            website="https://github.com/Vanquish1905/GoveeHome-For-Linux",
            issue_url="https://github.com/Vanquish1905/GoveeHome-For-Linux/issues",
            copyright="© 2026 Colin",
            license_type=Gtk.License.CUSTOM,
            license="Distributed under the Eclipse Public License 2.0.",
            comments="Control Govee lights on Linux and let them follow your screen.\n\n"
                     "An independent project, not affiliated with or endorsed by Govee.",
        )
        about.present()


def main() -> int:
    logging.basicConfig(level=logging.DEBUG if os.environ.get("GOVEEHOME_DEBUG") else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return Application().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
