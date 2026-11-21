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


PALETTE = [
    ("Warm white", (255, 180, 107)),
    ("White", (255, 255, 255)),
    ("Red", (255, 0, 0)),
    ("Orange", (255, 110, 0)),
    ("Amber", (255, 160, 20)),
    ("Yellow", (255, 220, 0)),
    ("Green", (0, 255, 40)),
    ("Teal", (0, 255, 170)),
    ("Cyan", (0, 230, 255)),
    ("Blue", (0, 60, 255)),
    ("Indigo", (80, 0, 255)),
    ("Violet", (170, 0, 255)),
    ("Magenta", (255, 0, 200)),
    ("Pink", (255, 60, 120)),
]


def rgba_from_rgb(rgb):
    from gi.repository import Gdk
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0
    return c


def rgb_from_rgba(c) -> RGB:
    return round(c.red * 255), round(c.green * 255), round(c.blue * 255)


def _flow(min_per_line=5):
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                       max_children_per_line=14, min_children_per_line=min_per_line,
                       column_spacing=4, row_spacing=4,
                       margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)


class ColorPanel:
    """Preset swatches, saved favourites and a custom colour picker.

    Used by lights, groups and the segment painter. `on_pick(rgb)` is called
    for every choice; favourites are shared app wide.
    """

    def __init__(self, app, on_pick, title: str = "Colour", description: str | None = None,
                 first_row: Gtk.Widget | None = None):
        self.app = app
        self.on_pick = on_pick
        self._updating = False
        self.group = Adw.PreferencesGroup(title=title, description=description)
        if first_row is not None:
            self.group.add(first_row)

        presets = _flow()
        self.swatches = []
        for name, rgb in PALETTE:
            sw = Swatch(name, rgb, self._pick)
            self.swatches.append(sw)
            presets.append(sw)
        row = Adw.PreferencesRow(activatable=False, title="Preset colours")
        row.set_child(presets)
        self.group.add(row)

        fav_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.favorites = _flow()
        fav_box.append(self.favorites)
        self.fav_hint = Gtk.Label(label="Saved colours show up here. Right-click one to remove it.",
                                  xalign=0, wrap=True, margin_start=12, margin_end=12, margin_bottom=10)
        self.fav_hint.add_css_class("dim-label")
        self.fav_hint.add_css_class("caption")
        fav_box.append(self.fav_hint)
        fav_row = Adw.PreferencesRow(activatable=False, title="Saved colours")
        fav_row.set_child(fav_box)
        self.group.add(fav_row)

        custom = Adw.ActionRow(title="Custom colour")
        self.button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                            valign=Gtk.Align.CENTER)
        self.button.connect("notify::rgba", self._on_custom)
        self.hex_label = Gtk.Label()
        self.hex_label.add_css_class("dim-label")
        self.hex_label.add_css_class("monospace")
        save = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER,
                          tooltip_text="Save this colour")
        save.add_css_class("flat")
        save.connect("clicked", self._save_favorite)
        custom.add_suffix(self.hex_label)
        custom.add_suffix(self.button)
        custom.add_suffix(save)
        custom.set_activatable_widget(self.button)
        self.group.add(custom)
        self.reload_favorites()

    def _pick(self, rgb):
        self.on_pick(tuple(rgb))

    def _on_custom(self, button, _pspec):
        rgb = rgb_from_rgba(button.get_rgba())
        self.hex_label.set_label("#{:02x}{:02x}{:02x}".format(*rgb))
        if not self._updating:
            self.on_pick(rgb)

    def _save_favorite(self, *_):
        rgb = rgb_from_rgba(self.button.get_rgba())
        hex_ = "#{:02x}{:02x}{:02x}".format(*rgb)
        favs = list(self.app.config.get("favorite_colors") or [])
        if hex_ not in favs:
            favs.append(hex_)
            self.app.config.set("favorite_colors", favs[-28:])
        self.reload_favorites()

    def _remove_favorite(self, hex_):
        favs = [f for f in self.app.config.get("favorite_colors") or [] if f != hex_]
        self.app.config.set("favorite_colors", favs)
        self.reload_favorites()

    def reload_favorites(self):
        from goveehome.colors import parse_color
        child = self.favorites.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.favorites.remove(child)
            child = nxt
        favs = self.app.config.get("favorite_colors") or []
        for hex_ in favs:
            try:
                rgb = parse_color(hex_)
            except ValueError:
                continue
            sw = Swatch(hex_, rgb, self._pick)
            click = Gtk.GestureClick(button=3)
            click.connect("released", lambda *_a, h=hex_: self._remove_favorite(h))
            sw.add_controller(click)
            self.favorites.append(sw)
        self.favorites.set_visible(bool(favs))

    def set_current(self, rgb: RGB | None):
        for sw in self.swatches:
            sw.set_selected(rgb is not None and sw.rgb == tuple(rgb))
        if rgb:
            self._updating = True
            self.button.set_rgba(rgba_from_rgb(rgb))
            self._updating = False
