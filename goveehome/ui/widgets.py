from __future__ import annotations

import math

from gi.repository import Adw, GLib, Gtk

from goveehome.colors import RGB, kelvin_to_rgb


def color_for_state(state) -> RGB | None:
    if state.on is False:
        return None
    if state.kelvin:
        return kelvin_to_rgb(state.kelvin)
    return state.color


class ColorDot(Gtk.DrawingArea):
    """A filled circle showing a colour, or an empty ring for 'off / unknown'."""

    def __init__(self, size: int = 14):
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self._rgb: RGB | None = None
        self.set_draw_func(self._draw)

    def set_rgb(self, rgb: RGB | None) -> None:
        if rgb != self._rgb:
            self._rgb = rgb
            self.queue_draw()

    def _draw(self, _area, cr, width, height):
        r = min(width, height) / 2
        cr.arc(width / 2, height / 2, r - 1, 0, 2 * math.pi)
        if self._rgb is None:
            fg = self.get_color()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
            cr.set_line_width(1.5)
            cr.stroke()
            return
        cr.set_source_rgb(*(c / 255 for c in self._rgb))
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.set_line_width(1)
        cr.stroke()


class Swatch(Gtk.Button):
    def __init__(self, name: str, rgb: RGB, on_pick):
        super().__init__()
        self.rgb = rgb
        self.add_css_class("swatch")
        self.add_css_class("flat")
        self.set_tooltip_text(name)
        self.update_property([Gtk.AccessibleProperty.LABEL], [name])
        self._selected = False
        area = Gtk.DrawingArea()
        area.set_content_width(30)
        area.set_content_height(30)
        area.set_draw_func(self._draw)
        self._area = area
        self.set_child(area)
        self.connect("clicked", lambda *_: on_pick(rgb))

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self._area.queue_draw()

    def _draw(self, area, cr, width, height):
        cx, cy = width / 2, height / 2
        radius = min(width, height) / 2 - 1
        if self._selected:
            fg = area.get_color()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.9)
            cr.set_line_width(2)
            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.stroke()
            radius -= 4
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.set_source_rgb(*(c / 255 for c in self.rgb))
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.15)
        cr.set_line_width(1)
        cr.stroke()


class SliderRow(Adw.PreferencesRow):
    """Icon, title, slider and value label on one boxed-list row."""

    def __init__(self, title: str, lower: float, upper: float, step: float, fmt, icon: str | None = None):
        super().__init__(title=title)
        self.set_activatable(False)
        self._fmt = fmt
        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        if icon:
            box.append(Gtk.Image(icon_name=icon))
        label = Gtk.Label(label=title, xalign=0)
        label.set_size_request(110, -1)
        box.append(label)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, step)
        self.scale.set_hexpand(True)
        self.scale.set_draw_value(False)
        self.scale.update_property([Gtk.AccessibleProperty.LABEL], [title])
        box.append(self.scale)
        self.value_label = Gtk.Label(xalign=1, width_chars=6)
        self.value_label.add_css_class("dim-label")
        self.value_label.add_css_class("numeric")
        box.append(self.value_label)
        self.set_child(box)
        self.scale.connect("value-changed", lambda s: self.value_label.set_label(self._fmt(s.get_value())))
        self.value_label.set_label(self._fmt(self.scale.get_value()))

    def get_value(self) -> float:
        return self.scale.get_value()

    def set_value(self, value: float) -> None:
        self.scale.set_value(value)
        self.value_label.set_label(self._fmt(self.scale.get_value()))


class Debouncer:
    """Call fn(value) at most every `delay` ms while a slider is being dragged."""

    def __init__(self, delay: int, fn):
        self.delay = delay
        self.fn = fn
        self._pending = None
        self._source = 0

    def __call__(self, value) -> None:
        self._pending = value
        if not self._source:
            self._source = GLib.timeout_add(self.delay, self._fire)

    def _fire(self):
        self._source = 0
        value, self._pending = self._pending, None
        if value is not None:
            self.fn(value)
        return GLib.SOURCE_REMOVE
