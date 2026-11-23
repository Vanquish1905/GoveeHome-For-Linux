"""Paint single segments of a light: pick segments, give them a colour."""

from __future__ import annotations

import math

from gi.repository import Adw, Gdk, GLib, Gtk

from goveehome import segments as seg
from goveehome.colors import to_hex
from goveehome.ui.widgets import ColorPanel, Debouncer, SliderRow, rgb_from_rgba, rgba_from_rgb

ROUTES = {"auto": "Automatic", "lan": "Network (LAN)", "ble": "Bluetooth", "cloud": "Govee cloud"}
CELL = 34
GAP = 4


class SegmentStrip(Gtk.DrawingArea):
    """The segments of a light as boxes. Click to select, drag to select several."""

    def __init__(self, count: int, on_change):
        super().__init__(hexpand=True, focusable=True)
        self.count = count
        self.colours: list = [None] * count
        self.selected: set[int] = set()
        self.on_change = on_change
        self._anchor: int | None = None
        self._drag_from: int | None = None
        self._drag_select = True
        self._before: set[int] = set()
        self._per_row = count
        self.set_draw_func(self._draw)
        self.set_content_height(CELL)
        self.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        self.connect("resize", lambda _a, w, _h: self._layout(w))

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", lambda *_: setattr(self, "_drag_from", None))
        self.add_controller(drag)
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Segments of the light"])

    # geometry ------------------------------------------------------------------------
    def set_count(self, count: int) -> None:
        self.count = count
        self.colours = (self.colours + [None] * count)[:count]
        self.selected = {i for i in self.selected if i < count}
        self._layout(self.get_width())

    def _layout(self, width: int) -> None:
        if width <= 0:
            return
        per_row = max(1, min(self.count, (width + GAP) // (CELL // 1.4 + GAP)))
        if self.count > per_row:
            # even rows look tidier than a long row and a stub
            rows = math.ceil(self.count / per_row)
            per_row = math.ceil(self.count / rows)
        if per_row != self._per_row:
            self._per_row = int(per_row)
            rows = math.ceil(self.count / self._per_row)
            GLib.idle_add(lambda: (self.set_content_height(rows * (CELL + GAP) - GAP), False)[1])
        self.queue_draw()

    def _cell_box(self, i: int, width: int):
        per_row = self._per_row
        w = (width - GAP * (per_row - 1)) / per_row
        row, col = divmod(i, per_row)
        return col * (w + GAP), row * (CELL + GAP), w, CELL

    def cell_at(self, x: float, y: float) -> int | None:
        width = self.get_width()
        for i in range(self.count):
            bx, by, bw, bh = self._cell_box(i, width)
            if bx - GAP / 2 <= x <= bx + bw + GAP / 2 and by - GAP / 2 <= y <= by + bh + GAP / 2:
                return i
        return None

    # selection -----------------------------------------------------------------------
    def _drag_begin(self, gesture, x, y):
        self.grab_focus()
        i = self.cell_at(x, y)
        if i is None:
            return
        state = gesture.get_current_event_state()
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if shift and self._anchor is not None:
            lo, hi = sorted((self._anchor, i))
            self.selected |= set(range(lo, hi + 1))
            self._drag_from = None
        else:
            self._drag_from = i
            self._drag_select = i not in self.selected
            self._before = set(self.selected)
            self._apply_range(i, i)
            self._anchor = i
        self._changed()

    def _drag_update(self, gesture, dx, dy):
        if self._drag_from is None:
            return
        ok, sx, sy = gesture.get_start_point()
        i = self.cell_at(sx + dx, sy + dy)
        if i is not None:
            self._apply_range(self._drag_from, i)
            self._changed()

    def _apply_range(self, a: int, b: int) -> None:
        lo, hi = sorted((a, b))
        span = set(range(lo, hi + 1))
        self.selected = (self._before | span) if self._drag_select else (self._before - span)

    def select(self, which: str) -> None:
        everything = set(range(self.count))
        if which == "all":
            self.selected = everything
        elif which == "none":
            self.selected = set()
        elif which == "invert":
            self.selected = everything - self.selected
        elif which == "odd":
            self.selected = set(range(0, self.count, 2))
        self._changed()

    def _changed(self) -> None:
        self.queue_draw()
        self.on_change()

    # drawing -------------------------------------------------------------------------
    def _draw(self, _area, cr, width, _height):
        fg = self.get_color()
        accent = Adw.StyleManager.get_default().get_accent_color_rgba() \
            if hasattr(Adw.StyleManager.get_default(), "get_accent_color_rgba") else None
        for i in range(self.count):
            x, y, w, h = self._cell_box(i, width)
            radius = 6
            self._round_rect(cr, x + 1, y + 1, w - 2, h - 2, radius)
            colour = self.colours[i]
            if colour is None:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.08)
                cr.fill()
            else:
                cr.set_source_rgb(*(c / 255 for c in colour))
                cr.fill()
            if i in self.selected:
                self._round_rect(cr, x + 1, y + 1, w - 2, h - 2, radius)
                if accent is not None:
                    cr.set_source_rgba(accent.red, accent.green, accent.blue, 1)
                else:
                    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.95)
                cr.set_line_width(3)
                cr.stroke()
            else:
                self._round_rect(cr, x + 1, y + 1, w - 2, h - 2, radius)
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.15)
                cr.set_line_width(1)
                cr.stroke()
            # number
            if w >= 16:
                label = str(i + 1)
                cr.set_font_size(10 if w >= 22 else 8)
                ext = cr.text_extents(label)
                if colour is None:
                    cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
                else:
                    light = 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2] > 140
                    cr.set_source_rgba(0, 0, 0, 0.7) if light else cr.set_source_rgba(1, 1, 1, 0.85)
                cr.move_to(x + (w - ext.width) / 2 - ext.x_bearing, y + (h + ext.height) / 2)
                cr.show_text(label)

    @staticmethod
    def _round_rect(cr, x, y, w, h, r):
        r = min(r, w / 2, h / 2)
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()


class SegmentEditor:
    """Groups for a light's page: the segment strip, colours, fills, presets."""

    def __init__(self, page):
        self.page = page
        self.app = page.app
        self.manager = page.manager
        self.device = page.device
        count = self.manager.segment_count(self.device)
        self.groups: list[Adw.PreferencesGroup] = []

        # the strip ----------------------------------------------------------------------
        self.strip = SegmentStrip(count, self._selection_changed)
        self.strip.colours = self.manager.painted_segments(self.device)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=12, margin_bottom=10, margin_start=12, margin_end=12)
        box.append(self.strip)
        bar = Gtk.Box(spacing=4)
        for label, which in (("All", "all"), ("None", "none"), ("Invert", "invert"), ("Every other", "odd")):
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, w=which: self.strip.select(w))
            bar.append(b)
        self.count_label = Gtk.Label(hexpand=True, xalign=1)
        self.count_label.add_css_class("dim-label")
        self.count_label.add_css_class("caption")
        bar.append(self.count_label)
        box.append(bar)
        strip_row = Adw.PreferencesRow(activatable=False, title="Segments")
        strip_row.set_child(box)

        panel = ColorPanel(
            self.app, self._paint, title="Segment colours",
            description="Click a segment to select it, drag over several, Shift-click for a range. "
                        "Then pick a colour. With nothing selected the colour goes to all "
                        "segments. The light keeps the colours, the app doesn't need to stay open.",
            first_row=strip_row)
        self.panel = panel
        self.groups.append(panel.group)

        # brightness, fills, presets -------------------------------------------------------
        tools = Adw.PreferencesGroup(title="More for segments")
        self.groups.append(tools)

        self.brightness = SliderRow("Brightness of the selected segments", 1, 100, 1, lambda v: f"{v:.0f} %")
        self.brightness.set_value(100)
        send_brightness = Debouncer(250, self._send_brightness)
        self.brightness.scale.connect("value-changed", lambda s: send_brightness(int(s.get_value())))
        tools.add(self.brightness)

        self.fill_ids = list(seg.FILLS)
        self.fill_row = Adw.ComboRow(title="Fill", subtitle="Over the selected segments, or all of them")
        self.fill_row.set_model(Gtk.StringList.new(list(seg.FILLS.values())))
        self.fill_a = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER,
                                            tooltip_text="First colour")
        self.fill_a.set_rgba(rgba_from_rgb((255, 0, 90)))
        self.fill_b = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER,
                                            tooltip_text="Second colour")
        self.fill_b.set_rgba(rgba_from_rgb((0, 120, 255)))
        fill_btn = Gtk.Button(label="Fill", valign=Gtk.Align.CENTER)
        fill_btn.add_css_class("flat")
        fill_btn.connect("clicked", self._fill)
        for w in (self.fill_a, self.fill_b, fill_btn):
            self.fill_row.add_suffix(w)
        self.fill_row.connect("notify::selected", lambda *_: self._update_fill_buttons())
        self._update_fill_buttons()
        tools.add(self.fill_row)

        self.preset_row = Adw.ComboRow(title="Presets", enable_search=True)
        apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        apply.add_css_class("flat")
        apply.connect("clicked", self._apply_preset)
        self.delete_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                     tooltip_text="Delete this saved preset")
        self.delete_btn.add_css_class("flat")
        self.delete_btn.connect("clicked", self._delete_preset)
        self.preset_row.add_suffix(self.delete_btn)
        self.preset_row.add_suffix(apply)
        self.preset_row.connect("notify::selected", lambda *_: self._update_delete())
        tools.add(self.preset_row)

        save = Adw.EntryRow(title="Save these colours as a preset", show_apply_button=True)
        save.connect("apply", self._save_preset)
        tools.add(save)
        self._load_presets()

        routes = self.manager.segment_routes(self.device)
        self.route_ids = ["auto"] + routes
        self.route_row = Adw.ComboRow(
            title="Send through",
            subtitle="If the light doesn't change over the network, try the cloud (needs the API key)")
        self.route_row.set_model(Gtk.StringList.new([ROUTES[r] for r in self.route_ids]))
        self.route_row.set_visible(len(routes) > 1)
        tools.add(self.route_row)

        resend = Adw.ActionRow(title="Send all segment colours again",
                               subtitle="After the light was switched to another mode")
        rb = Gtk.Button(label="Send", valign=Gtk.Align.CENTER)
        rb.add_css_class("flat")
        rb.connect("clicked", lambda *_: self._send(list(self.strip.colours)))
        resend.add_suffix(rb)
        tools.add(resend)
        self._selection_changed()

    # helpers -----------------------------------------------------------------------------
    def set_count(self, count: int) -> None:
        self.strip.set_count(count)
        self.strip.colours = self.manager.painted_segments(self.device)[:count]
        self._selection_changed()

    def _via(self) -> str:
        idx = self.route_row.get_selected()
        return self.route_ids[idx] if 0 <= idx < len(self.route_ids) else "auto"

    def _selection_changed(self):
        n = len(self.strip.selected)
        self.count_label.set_label(f"{n} of {self.strip.count} selected" if n else
                                   f"{self.strip.count} segments")
        chosen = [self.strip.colours[i] for i in self.strip.selected if self.strip.colours[i]]
        if chosen and all(c == chosen[0] for c in chosen):
            self.panel.set_current(chosen[0])
        else:
            self.panel.set_current(None)

    def _targets(self) -> list[int]:
        return sorted(self.strip.selected) or list(range(self.strip.count))

    def _send(self, colours: list) -> None:
        if self.device.id in self.manager.streaming_devices:
            self.page.window.toast("A light show is using this light. It was stopped for the segment colours.")
        self.manager.paint_segments(self.device, colours, via=self._via())

    def _paint(self, rgb):
        rgb = tuple(int(v) for v in rgb)
        changes = [None] * self.strip.count
        for i in self._targets():
            self.strip.colours[i] = rgb
            changes[i] = rgb
        self.strip.queue_draw()
        self._send(changes)
        self._selection_changed()

    def _send_brightness(self, percent: int):
        targets = self._targets()
        self.manager.paint_segments(self.device, [None] * self.strip.count, via=self._via(),
                                    brightness={percent: targets})

    def _update_fill_buttons(self):
        kind = self.fill_ids[self.fill_row.get_selected()]
        for b in (self.fill_a, self.fill_b):
            b.set_visible(kind != "rainbow")

    def _fill(self, *_):
        kind = self.fill_ids[self.fill_row.get_selected()]
        a, b = rgb_from_rgba(self.fill_a.get_rgba()), rgb_from_rgba(self.fill_b.get_rgba())
        filled = seg.apply_fill([None] * self.strip.count, self.strip.selected, kind, a, b)
        for i, c in enumerate(filled):
            if c is not None:
                self.strip.colours[i] = c
        self.strip.queue_draw()
        self._send(filled)

    # presets -------------------------------------------------------------------------------
    def _saved(self) -> list[dict]:
        return list(self.app.config.get("segment_presets") or [])

    def _load_presets(self, select: str | None = None):
        saved = self._saved()
        self._presets = [(p["name"], p["colours"], True) for p in saved] + \
                        [(name, name, False) for name in seg.BUILT_IN]
        labels = [f"{n} (saved)" if mine else n for n, _c, mine in self._presets]
        self.preset_row.set_model(Gtk.StringList.new(labels))
        if select:
            for i, (n, _c, mine) in enumerate(self._presets):
                if mine and n == select:
                    self.preset_row.set_selected(i)
        self._update_delete()

    def _update_delete(self):
        idx = self.preset_row.get_selected()
        self.delete_btn.set_visible(0 <= idx < len(self._presets) and self._presets[idx][2])

    def _apply_preset(self, *_):
        idx = self.preset_row.get_selected()
        if not 0 <= idx < len(self._presets):
            return
        colours = seg.preset_colours(self._presets[idx][1], self.strip.count)
        self.strip.colours = list(colours)
        self.strip.queue_draw()
        self._send(colours)
        self._selection_changed()

    def _save_preset(self, row):
        name = row.get_text().strip()
        if not name:
            return
        if any(c is None for c in self.strip.colours):
            self.page.window.toast("Give every segment a colour first")
            return
        saved = [p for p in self._saved() if p["name"] != name]
        saved.append({"name": name, "colours": [to_hex(c) for c in self.strip.colours]})
        self.app.config.set("segment_presets", saved)
        row.set_text("")
        self._load_presets(select=name)
        self.page.window.toast(f"Saved “{name}”")

    def _delete_preset(self, *_):
        idx = self.preset_row.get_selected()
        if not (0 <= idx < len(self._presets) and self._presets[idx][2]):
            return
        name = self._presets[idx][0]
        self.app.config.set("segment_presets", [p for p in self._saved() if p["name"] != name])
        self._load_presets()
