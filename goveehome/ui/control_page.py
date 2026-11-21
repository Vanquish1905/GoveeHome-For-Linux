"""Shared layout for pages that control lights directly (a light or a group)."""

from __future__ import annotations

import time

from gi.repository import Adw, GLib, Gtk

from goveehome.models import Device
from goveehome.ui.widgets import ColorDot, ColorPanel, Debouncer, SliderRow

TIMER_CHOICES = [(0, "Off"), (5, "5 minutes"), (15, "15 minutes"), (30, "30 minutes"),
                 (60, "1 hour"), (120, "2 hours"), (240, "4 hours")]


class ControlPage(Adw.NavigationPage):
    def __init__(self, window, title: str, tag: str):
        super().__init__(title=title, tag=tag)
        self.window = window
        self.app = window.app
        self.manager = self.app.manager
        self._updating = False

        view = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        view.add_top_bar(self.header)
        self.power = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Power")
        self.power.connect("notify::active", self._on_power)
        self.header.pack_end(self.power)
        self.page = Adw.PreferencesPage()
        view.set_content(self.page)
        self.set_child(view)
        self.connect("showing", lambda *_: (self.colors.reload_favorites(), self.on_showing()))

    # to override --------------------------------------------------------------
    def targets(self) -> list[Device]:
        raise NotImplementedError

    def timer_key(self) -> str:
        return self.get_tag()

    def on_showing(self):
        pass

    # building -----------------------------------------------------------------
    def build_summary(self):
        group = Adw.PreferencesGroup()
        box = Gtk.Box(spacing=16, margin_bottom=6)
        self.big_dot = ColorDot(56)
        box.append(self.big_dot)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=2)
        self.title_label = Gtk.Label(xalign=0, wrap=True)
        self.title_label.add_css_class("title-2")
        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.status_label.add_css_class("dim-label")
        text.append(self.title_label)
        text.append(self.status_label)
        box.append(text)
        group.add(box)
        self.page.add(group)

    def build_light(self):
        group = Adw.PreferencesGroup(title="Light")
        self.brightness = SliderRow("Brightness", 1, 100, 1, lambda v: f"{v:.0f} %",
                                    icon="display-brightness-symbolic")
        send = Debouncer(150, lambda v: self._each(lambda d: self.manager.set_brightness(d, int(v))))
        self.brightness.scale.connect("value-changed", lambda s: self._updating or send(s.get_value()))
        group.add(self.brightness)
        self.kelvin = SliderRow("White", 2000, 9000, 100, lambda v: f"{v:.0f} K", icon="weather-clear-symbolic")
        for mark, text in ((2700, "Warm"), (4500, None), (6500, "Daylight")):
            self.kelvin.scale.add_mark(mark, Gtk.PositionType.BOTTOM, text)
        send_k = Debouncer(200, lambda v: self._each(lambda d: self.manager.set_kelvin(d, int(v))))
        self.kelvin.scale.connect("value-changed", lambda s: self._updating or send_k(s.get_value()))
        group.add(self.kelvin)
        self.page.add(group)

        self.colors = ColorPanel(self.app, lambda rgb: self._each(lambda d: self.manager.set_color(d, rgb)))
        self.page.add(self.colors.group)

    def build_timer(self):
        group = Adw.PreferencesGroup(title="Timer")
        self.timer_row = Adw.ComboRow(title="Turn off after")
        self.timer_row.set_model(Gtk.StringList.new([label for _, label in TIMER_CHOICES]))
        self.timer_row.connect("notify::selected", self._on_timer)
        group.add(self.timer_row)
        self.page.add(group)
        GLib.timeout_add_seconds(20, self._tick_timer)
        self._show_timer()

    # behaviour -----------------------------------------------------------------
    def _each(self, fn):
        for device in self.targets():
            fn(device)

    def _on_power(self, switch, _pspec):
        if not self._updating:
            on = switch.get_active()
            self._each(lambda d: self.manager.set_power(d, on))

    def _on_timer(self, row, _pspec):
        if self._updating:
            return
        minutes = TIMER_CHOICES[row.get_selected()][0]
        self.app.set_timer(self.timer_key(), minutes,
                           lambda: self._each(lambda d: self.manager.set_power(d, False)))
        self._show_timer()

    def _show_timer(self):
        end = self.app.timer_end(self.timer_key())
        if end:
            self.timer_row.set_subtitle("Turns off at " + time.strftime("%H:%M", time.localtime(end)))
        else:
            self.timer_row.set_subtitle("")
            self._updating = True
            self.timer_row.set_selected(0)
            self._updating = False

    def _tick_timer(self):
        if self.get_root() is None:
            return GLib.SOURCE_REMOVE
        self._show_timer()
        return GLib.SOURCE_CONTINUE

    def show_state(self, title: str, status: str, rgb, on: bool | None, brightness: int | None,
                   kelvin: int | None, color):
        self._updating = True
        try:
            self.title_label.set_label(title)
            self.status_label.set_label(status)
            self.big_dot.set_rgb(rgb)
            self.power.set_active(bool(on))
            if brightness:
                self.brightness.set_value(brightness)
            if kelvin:
                self.kelvin.set_value(kelvin)
            self.colors.set_current(color if color and not kelvin else None)
        finally:
            self._updating = False
