"""The "Update GoveeHome" window."""

from __future__ import annotations

import threading
import time

from gi.repository import Adw, GLib, Gtk

from goveehome import GITHUB_REPO, updater


class UpdateWindow(Adw.Window):
    def __init__(self, app, parent, info: updater.UpdateInfo | None = None):
        super().__init__(transient_for=parent, modal=True, title="Updates")
        self.set_default_size(560, 560)
        self.app = app
        self.info = info
        self.current = updater.installed()
        self._busy = False

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)

        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("title-2")
        box.append(self.title)
        self.subtitle = Gtk.Label(xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        box.append(self.subtitle)

        self.changes_title = Gtk.Label(label="What's new", xalign=0, margin_top=6)
        self.changes_title.add_css_class("heading")
        box.append(self.changes_title)
        self.changes = Gtk.Label(xalign=0, yalign=0, wrap=True, selectable=True)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=120)
        scroller.set_child(self.changes)
        self.changes_scroller = scroller
        box.append(scroller)

        self.progress = Gtk.ProgressBar(visible=False, pulse_step=0.08)
        box.append(self.progress)
        self.log_view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                     cursor_visible=False)
        log_scroll = Gtk.ScrolledWindow(min_content_height=140, hscrollbar_policy=Gtk.PolicyType.NEVER)
        log_scroll.set_child(self.log_view)
        self.log_scroll = log_scroll
        self.expander = Gtk.Expander(label="Details", visible=False)
        self.expander.set_child(log_scroll)
        box.append(self.expander)

        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        self.secondary = Gtk.Button(label="Check again")
        self.secondary.connect("clicked", self._on_secondary)
        self.primary = Gtk.Button(label="Update")
        self.primary.add_css_class("suggested-action")
        self.primary.connect("clicked", self._on_primary)
        buttons.append(self.secondary)
        buttons.append(self.primary)
        box.append(buttons)

        view.set_content(box)
        self.set_content(view)
        if info is None:
            self.start_check()
        else:
            self._show_info(info)

    def _on_secondary(self, *_):
        if self.secondary.get_label() == "Skip this version":
            self.app.skip_update()
            self.app.update_installed()
            self.close()
        else:
            self.start_check()

    # checking -----------------------------------------------------------------
    def start_check(self):
        self._set_busy(True, "Checking GitHub…")
        self.title.set_label("Looking for updates")
        self.subtitle.set_label(f"Installed: {self._current_text()}")
        self.changes_title.set_visible(False)
        self.changes_scroller.set_visible(False)
        self.primary.set_visible(False)
        self.secondary.set_label("Check again")

        def work():
            try:
                info = updater.check(self.current)
                GLib.idle_add(self._checked, info, None)
            except updater.UpdateError as exc:
                GLib.idle_add(self._checked, None, str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, info, error):
        self._set_busy(False)
        self.app.config.set_in("updates", "last_check", time.time())
        if error:
            self.title.set_label("Couldn't check for updates")
            self.subtitle.set_label(error)
            return GLib.SOURCE_REMOVE
        self.info = info
        self._show_info(info)
        return GLib.SOURCE_REMOVE

    def _current_text(self) -> str:
        c = self.current
        text = f"version {c.version}"
        if c.short_commit:
            text += f" ({c.short_commit})"
        return text

    def _show_info(self, info: updater.UpdateInfo):
        latest = f"version {info.version} ({info.commit[:7]})"
        if not info.available:
            self.title.set_label("GoveeHome is up to date")
            self.subtitle.set_label(f"Installed: {self._current_text()}\nNewest on GitHub: {latest}")
            self.changes_title.set_visible(False)
            self.changes_scroller.set_visible(False)
            self.primary.set_label("Reinstall")
            self.primary.remove_css_class("suggested-action")
            self.primary.set_visible(self.current.can_update and self.current.mode == "installer")
            return
        count = f"{info.ahead_by} new change{'s' if info.ahead_by != 1 else ''}" if info.ahead_by else "New version"
        self.title.set_label(f"Update to {info.version}")
        self.subtitle.set_label(f"{count} on GitHub ({GITHUB_REPO}).\n"
                                f"Installed: {self._current_text()} → {latest}")
        self.changes.set_label("\n".join(f"•  {line}" for line in info.changes) or "No details available.")
        self.changes_title.set_visible(True)
        self.changes_scroller.set_visible(True)
        self.primary.set_label("Update")
        self.primary.add_css_class("suggested-action")
        self.primary.set_visible(True)
        self.secondary.set_label("Skip this version")
        if not self.current.can_update:
            self.primary.set_visible(False)
            self.subtitle.set_label(self.subtitle.get_label() + "\n\nThis copy wasn't installed with install.sh, "
                                    "so update it the way you installed it.")

    # updating -----------------------------------------------------------------
    def _on_primary(self, *_):
        if self.primary.get_label() == "Restart now":
            self.app.restart()
            return
        if self.info is None:
            return
        self._set_busy(True, "Installing…")
        self.expander.set_visible(True)
        self.primary.set_visible(False)
        self.title.set_label(f"Updating to {self.info.version}")
        info = self.info

        def log_line(line):
            GLib.idle_add(self._append_log, line)

        def work():
            try:
                updater.apply(self.current, info, log_line)
                GLib.idle_add(self._done, None)
            except updater.UpdateError as exc:
                GLib.idle_add(self._done, str(exc))
            except Exception as exc:  # never leave the window spinning
                GLib.idle_add(self._done, f"Update failed: {exc}")
        threading.Thread(target=work, daemon=True).start()

    def _append_log(self, line):
        buf = self.log_view.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")
        adj = self.log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return GLib.SOURCE_REMOVE

    def _done(self, error):
        self._set_busy(False)
        if error:
            self.title.set_label("The update didn't work")
            self.subtitle.set_label(error + "\n\nYour current version still works. The details below "
                                    "show what happened; SETUP.md has the commands to update by hand.")
            self.expander.set_expanded(True)
            self.primary.set_label("Try again")
            self.primary.set_visible(True)
            return GLib.SOURCE_REMOVE
        self.title.set_label("Update installed")
        self.subtitle.set_label("Restart GoveeHome to use the new version. A running light show "
                                "starts again by itself.")
        self.primary.set_label("Restart now")
        self.primary.add_css_class("suggested-action")
        self.primary.set_visible(True)
        self.secondary.set_visible(False)
        self.app.update_installed()
        return GLib.SOURCE_REMOVE

    def _set_busy(self, busy: bool, text: str = ""):
        self._busy = busy
        self.secondary.set_sensitive(not busy)
        self.set_deletable(not busy)
        self.progress.set_visible(busy)
        if busy:
            self.progress.set_text(text)
            self.progress.set_show_text(True)
            GLib.timeout_add(100, self._pulse)

    def _pulse(self):
        if not self._busy:
            return GLib.SOURCE_REMOVE
        self.progress.pulse()
        return GLib.SOURCE_CONTINUE
