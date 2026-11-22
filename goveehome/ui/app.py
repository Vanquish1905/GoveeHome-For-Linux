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
              <property name="accelerator">&lt;Primary&gt;1</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Start or stop music sync</property>
              <property name="accelerator">&lt;Primary&gt;2</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Start or stop effects</property>
              <property name="accelerator">&lt;Primary&gt;3</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Stop all light shows</property>
              <property name="accelerator">&lt;Primary&gt;period</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">New group</property>
              <property name="accelerator">&lt;Primary&gt;g</property></object></child>
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


AUTOSTART_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / f"{APP_ID}.desktop"


class Application(Adw.Application):
    def __init__(self, background: bool = False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        GLib.set_application_name(APP_NAME)
        self.config = Config()
        self.manager = DeviceManager(self.config)
        self.window = None
        self.start_hidden = background
        self._held = False
        self._timers: dict[str, tuple[int, float]] = {}
        self._asleep: dict = {}
        self.power = None
        self.restart_requested = False
        self.update_info = None

        from goveehome.sync.effects import EffectSource
        from goveehome.sync.engine import LightEngine, ScreenSource
        from goveehome.sync.music import MusicSource
        factories = {
            "sync": lambda: ScreenSource(self.config),
            "music": lambda: MusicSource(self.config),
            "effects": lambda: EffectSource(self.config),
        }
        self.engines = {
            kind: LightEngine(
                self.manager, factory, kind=kind,
                on_preview=lambda p, k=kind: GLib.idle_add(self._engine_preview, k, p),
                on_state=lambda running, msg, k=kind: GLib.idle_add(self._engine_state, k, running, msg))
            for kind, factory in factories.items()
        }

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._action("refresh", lambda *_: self.manager.discover(), ["<Primary>r", "F5"])
        self._action("toggle-sync", lambda *_: self._toggle_show("sync"), ["<Primary>1"])
        self._action("toggle-music", lambda *_: self._toggle_show("music"), ["<Primary>2"])
        self._action("toggle-effects", lambda *_: self._toggle_show("effects"), ["<Primary>3"])
        self._action("stop-shows", lambda *_: self.stop_shows(), ["<Primary>period"])
        self._action("new-group", self._new_group, ["<Primary>g"])
        self._action("preferences", self._preferences, ["<Primary>comma"])
        self._action("add-host", self._add_host)
        self._action("about", self._about)
        self._action("check-updates", lambda *_: self.show_updates())
        self._action("show-window", lambda *_: self.do_activate())
        self._action("quit", lambda *_: self._quit(), ["<Primary>q"])
        self.set_accels_for_action("win.show-help-overlay", ["<Primary>question"])
        self.manager.start()

        GLib.timeout_add_seconds(20, self._auto_check_updates)

        from goveehome.power import PowerWatcher
        self.power = PowerWatcher(self._on_sleep, self._on_wake)
        self.power.start()

        bg = self.config.section("background")
        resume_once = bg.get("resume_once")
        if resume_once:
            self.config.set_in("background", "resume_once", "")
        if resume_once in self.engines:
            GLib.timeout_add_seconds(3, lambda: (self.start_show(resume_once), False)[1])
        elif bg.get("resume_show") and bg.get("last_show") in self.engines:
            # give discovery a moment so the lights are known
            GLib.timeout_add_seconds(3, lambda: (self.start_show(bg["last_show"]), False)[1])

    def _action(self, name, callback, accels=None):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def _ensure_window(self):
        if self.window is None:
            from goveehome.ui.window import MainWindow
            self.window = MainWindow(self)
            builder = Gtk.Builder.new_from_string(SHORTCUTS, -1)
            self.window.set_help_overlay(builder.get_object("help_overlay"))
        return self.window

    def do_activate(self):
        window = self._ensure_window()
        if self.start_hidden:
            self.start_hidden = False
            self._hold()
            return
        window.present()

    def do_shutdown(self):
        for engine in self.engines.values():
            engine.stop()
        if self.power:
            self.power.stop()
        self.manager.stop()
        Adw.Application.do_shutdown(self)

    # light shows -------------------------------------------------------------
    def start_show(self, kind: str) -> None:
        for other, engine in self.engines.items():
            if other != kind and engine.running:
                engine.stop(wait=True)
        self.config.set_in("background", "last_show", kind)
        self.engines[kind].start()

    def stop_shows(self) -> None:
        self.config.set_in("background", "last_show", "")
        for engine in self.engines.values():
            if engine.running:
                engine.stop(wait=False)

    def _toggle_show(self, kind):
        if self.engines[kind].running:
            self.stop_shows()
        else:
            self.start_show(kind)
        if self.window:
            self.window.open_show(kind)

    def _engine_state(self, kind, running, message):
        if self.window:
            self.window.show_pages[kind].on_state(running, message)
            self.window.refresh_rows()
            if message and not running:
                self.window.toast(message)
        if not running and not any(e.running for e in self.engines.values()):
            if self.window is not None and not self.window.get_visible():
                self._release()
        return GLib.SOURCE_REMOVE

    def _engine_preview(self, kind, preview):
        if self.window and self.window.get_visible():
            self.window.show_pages[kind].on_preview(preview)
        return GLib.SOURCE_REMOVE

    # background ---------------------------------------------------------------
    def keep_in_background(self) -> bool:
        """Called when the window is closed: keep running if a show is on."""
        if self.config.section("background").get("keep_running", True) and \
                any(e.running for e in self.engines.values()):
            self._hold()
            return True
        return False

    def _hold(self):
        if not self._held:
            self.hold()
            self._held = True

    def _release(self):
        if self._held:
            self._held = False
            self.release()

    def _quit(self):
        self.stop_shows()
        self.quit()

    @staticmethod
    def set_autostart(enabled: bool) -> None:
        if not enabled:
            AUTOSTART_FILE.unlink(missing_ok=True)
            return
        import shutil
        exe = shutil.which("goveehome") or f"{sys.executable} -m goveehome"
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            "[Desktop Entry]\nType=Application\nName=GoveeHome\n"
            f"Exec={exe} --background\nIcon={APP_ID}\nX-GNOME-Autostart-enabled=true\n"
            "NoDisplay=true\n")

    # updates ------------------------------------------------------------------
    def show_updates(self, info=None):
        from goveehome.ui.update_window import UpdateWindow
        UpdateWindow(self, self._ensure_window(), info or self.update_info).present()

    def _auto_check_updates(self):
        import threading
        import time

        from goveehome import updater
        updates = self.config.section("updates")
        if not updates.get("auto_check", True) or time.time() - updates.get("last_check", 0) < 20 * 3600:
            return GLib.SOURCE_REMOVE

        def work():
            try:
                info = updater.check(updater.installed())
            except updater.UpdateError:
                return  # offline or rate limited; try again next start
            GLib.idle_add(found, info)

        def found(info):
            self.config.set_in("updates", "last_check", time.time())
            if info.available and info.commit != updates.get("skipped"):
                self.update_info = info
                if self.window:
                    self.window.show_update_banner(info)
            return GLib.SOURCE_REMOVE
        threading.Thread(target=work, daemon=True).start()
        return GLib.SOURCE_REMOVE

    def skip_update(self):
        if self.update_info:
            self.config.set_in("updates", "skipped", self.update_info.commit)

    def update_installed(self):
        self.update_info = None
        if self.window:
            self.window.hide_update_banner()

    def restart(self):
        running = next((k for k, e in self.engines.items() if e.running), "")
        self.config.set_in("background", "resume_once", running)
        self.restart_requested = True
        self._quit()

    # timers ------------------------------------------------------------------
    def set_timer(self, key: str, minutes: int, action) -> None:
        old = self._timers.pop(key, None)
        if old:
            GLib.source_remove(old[0])
        if minutes <= 0:
            return

        def fire():
            self._timers.pop(key, None)
            action()
            return GLib.SOURCE_REMOVE
        source = GLib.timeout_add_seconds(int(minutes * 60), fire)
        import time
        self._timers[key] = (source, time.time() + minutes * 60)

    def timer_end(self, key: str) -> float | None:
        entry = self._timers.get(key)
        return entry[1] if entry else None

    # sleep / wake -------------------------------------------------------------------
    def _on_sleep(self):
        power = self.config.section("power")
        running = next((k for k, e in self.engines.items() if e.running), None)
        on = [d.id for d in self.manager.list() if d.state.on]
        self._asleep = {"show": running, "on": on}
        if running:
            self.engines[running].stop(wait=True)
        if power.get("off_on_sleep"):
            for device_id in on:
                device = self.manager.get(device_id)
                if device:
                    self.manager.set_power(device, False)

    def _on_wake(self):
        power = self.config.section("power")
        state, self._asleep = self._asleep, {}
        if not power.get("on_on_wake") or not state:
            return

        def restore():
            for device_id in state.get("on", []):
                device = self.manager.get(device_id)
                if device:
                    self.manager.set_power(device, True)
            if state.get("show"):
                self.start_show(state["show"])
            return GLib.SOURCE_REMOVE
        # the network needs a few seconds after resume
        GLib.timeout_add_seconds(4, restore)

    # actions -----------------------------------------------------------------
    def _new_group(self, *_):
        from goveehome.ui.group_page import edit_group_dialog
        edit_group_dialog(self._ensure_window())

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
            developer_name="vanquish1905",
            developers=["vanquish1905"],
            version=__version__,
            website="https://github.com/Vanquish1905/GoveeHome-For-Linux",
            issue_url="https://github.com/Vanquish1905/GoveeHome-For-Linux/issues",
            copyright="© 2026 vanquish1905",
            license_type=Gtk.License.CUSTOM,
            license="Distributed under the Eclipse Public License 2.0.",
            comments="Control Govee lights on Linux, sync them with your screen and music.\n\n"
                     "An independent project, not affiliated with or endorsed by Govee.",
        )
        about.present()


def main() -> int:
    logging.basicConfig(level=logging.DEBUG if os.environ.get("GOVEEHOME_DEBUG") else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    argv = [a for a in sys.argv if a != "--background"]
    app = Application(background="--background" in sys.argv)
    code = app.run(argv)
    if app.restart_requested:
        # the app has let go of its D-Bus name by now, so a new instance can start
        from goveehome import updater
        cmd = updater.launcher()
        os.execv(cmd[0], cmd)
    return code


if __name__ == "__main__":
    sys.exit(main())
