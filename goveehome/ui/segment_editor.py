"""Paint single segments of a light: pick segments, give them a colour."""

from __future__ import annotations

import math

import numpy as np

from gi.repository import Adw, Gdk, GLib, Gtk

from goveehome import paintings
from goveehome import segments as seg
from goveehome.colors import to_hex
from goveehome.ui.widgets import ColorPanel, ColorStrip, Debouncer, SliderRow, rgb_from_rgba, rgba_from_rgb

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

        files = Adw.ActionRow(title="Your presets and animations",
                              subtitle="Save them to a file to keep or share them, or load a file")
        for label, handler in (("Import…", self._import), ("Export…", self._export)):
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
            b.add_css_class("flat")
            b.connect("clicked", handler)
            files.add_suffix(b)
        tools.add(files)

        self._build_animation()
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
            for engine in self.app.engines.values():
                if engine.running:
                    engine.stop(wait=True)
            self.page.window.toast("The light show was stopped for the segment colours")
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
        self._frame_edited()

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
        self._frame_edited()

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
        self._frame_edited()

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

    # import / export ---------------------------------------------------------------------
    def _file_dialog(self, title: str):
        from gi.repository import Gio
        dialog = Gtk.FileDialog(title=title, modal=True)
        json_filter = Gtk.FileFilter(name="GoveeHome paintings (JSON)")
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(json_filter)
        return dialog

    def _export(self, *_):
        if not (self.app.config.get("segment_presets") or self.app.config.get("animations")):
            self.page.window.toast("Save a preset or make an animation first")
            return
        dialog = self._file_dialog("Export presets and animations")
        dialog.set_initial_name("goveehome-paintings.json")

        def done(d, result):
            try:
                gfile = d.save_finish(result)
            except GLib.Error:
                return      # cancelled
            try:
                with open(gfile.get_path(), "w") as fh:
                    fh.write(paintings.export_json(self.app.config))
            except OSError as exc:
                self.page.window.toast(f"Couldn't save: {exc.strerror or exc}")
                return
            self.page.window.toast(f"Saved to {gfile.get_basename()}")
        dialog.save(self.page.window, None, done)

    def _import(self, *_):
        dialog = self._file_dialog("Import presets and animations")

        def done(d, result):
            try:
                gfile = d.open_finish(result)
            except GLib.Error:
                return
            try:
                with open(gfile.get_path()) as fh:
                    presets, anims = paintings.import_data(self.app.config, fh.read())
            except (OSError, ValueError) as exc:
                self.page.window.toast(f"Couldn't import {gfile.get_basename()}: {exc}")
                return
            self._load_presets()
            self._load_animations()
            parts = []
            if presets:
                parts.append(f"{presets} preset" + ("s" if presets != 1 else ""))
            if anims:
                parts.append(f"{anims} animation" + ("s" if anims != 1 else ""))
            self.page.window.toast("Imported " + " and ".join(parts))
        dialog.open(self.page.window, None, done)

    # animation -----------------------------------------------------------------------------
    def _build_animation(self):
        group = Adw.PreferencesGroup(
            title="Animation",
            description="An animation is a row of frames, each with its own segment colours. "
                        "Select a frame to show it on the light and change it with the colours above. "
                        "It plays as a light show, also on other lights (Effects → Your paintings).")
        self.groups.append(group)
        self.anim: dict | None = None
        self.frame: int | None = None
        self._updating_anim = False

        self.anim_row = Adw.ComboRow(title="Animation")
        new = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, tooltip_text="New animation")
        new.add_css_class("flat")
        new.connect("clicked", self._new_animation)
        self.anim_delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                      tooltip_text="Delete this animation")
        self.anim_delete.add_css_class("flat")
        self.anim_delete.connect("clicked", self._delete_animation)
        self.anim_row.add_suffix(self.anim_delete)
        self.anim_row.add_suffix(new)
        self.anim_row.connect("notify::selected", lambda *_: self._animation_chosen())
        group.add(self.anim_row)

        self.anim_name = Adw.EntryRow(title="Name", show_apply_button=True)
        self.anim_name.connect("apply", self._rename)
        group.add(self.anim_name)

        frames_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                             margin_top=10, margin_bottom=10, margin_start=12, margin_end=12)
        self.frames_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                       max_children_per_line=10, min_children_per_line=3,
                                       column_spacing=4, row_spacing=4)
        frames_box.append(self.frames_flow)
        self.frame_hint = Gtk.Label(xalign=0, wrap=True)
        self.frame_hint.add_css_class("dim-label")
        self.frame_hint.add_css_class("caption")
        frames_box.append(self.frame_hint)
        bar = Gtk.Box(spacing=4)
        self.frame_buttons = {}
        for key, label, tip in (
                ("add", "Add frame", "A new frame with the colours on the light now, after the selected one"),
                ("left", "◀", "Move the selected frame earlier"),
                ("right", "▶", "Move the selected frame later"),
                ("delete", "Delete frame", "Delete the selected frame"),
                ("run", "Make it run along", "Frames that move the colours on the light one segment at a "
                                             "time until they're back at the start")):
            b = Gtk.Button(label=label, tooltip_text=tip)
            b.add_css_class("flat")
            b.connect("clicked", lambda _b, k=key: self._frame_action(k))
            self.frame_buttons[key] = b
            bar.append(b)
        frames_box.append(bar)
        frames_row = Adw.PreferencesRow(activatable=False, title="Frames")
        frames_row.set_child(frames_box)
        group.add(frames_row)

        self.frame_time = SliderRow("Time per frame", 0.05, 5.0, 0.05, lambda v: f"{v:.2f} s")
        self.frame_time.scale.connect("value-changed", lambda s: self._set_anim(frame_time=round(s.get_value(), 2)))
        group.add(self.frame_time)
        self.fade_row = Adw.SwitchRow(title="Fade between frames", subtitle="Off: jump from frame to frame")
        self.fade_row.connect("notify::active", lambda r, _p: self._set_anim(fade=r.get_active()))
        group.add(self.fade_row)
        self.mode_ids = list(paintings.MODES)
        self.mode_row = Adw.ComboRow(title="Play")
        self.mode_row.set_model(Gtk.StringList.new(list(paintings.MODES.values())))
        self.mode_row.connect("notify::selected",
                              lambda r, _p: self._set_anim(mode=self.mode_ids[r.get_selected()]))
        group.add(self.mode_row)

        play = Adw.ActionRow(title="Play on this light",
                             subtitle="Needs segment streaming for a colour per segment (light page → Light shows)")
        self.play_btn = Gtk.Button(label="Play", valign=Gtk.Align.CENTER)
        self.play_btn.add_css_class("suggested-action")
        self.play_btn.connect("clicked", self._play)
        play.add_suffix(self.play_btn)
        group.add(play)
        self.anim_detail_rows = [self.anim_name, frames_row, self.frame_time, self.fade_row, self.mode_row, play]
        self._load_animations()
        GLib.timeout_add_seconds(1, self._update_play)

    def _animations(self) -> list[dict]:
        return list(self.app.config.get("animations") or [])

    def _load_animations(self, select: str | None = None):
        anims = self._animations()
        select = select or (self.anim["id"] if self.anim else None)
        self._anim_ids = [a["id"] for a in anims]
        self._updating_anim = True
        self.anim_row.set_model(Gtk.StringList.new([a["name"] for a in anims] or ["None yet, press +"]))
        self.anim_row.set_sensitive(bool(anims))
        if select in self._anim_ids:
            self.anim_row.set_selected(self._anim_ids.index(select))
        self._updating_anim = False
        self._animation_chosen()

    def _animation_chosen(self):
        if self._updating_anim:
            return
        idx = self.anim_row.get_selected()
        anims = self._animations()
        self.anim = dict(anims[idx]) if anims and 0 <= idx < len(anims) else None
        self.frame = None
        self.anim_delete.set_visible(self.anim is not None)
        for row in self.anim_detail_rows:
            row.set_visible(self.anim is not None)
        if self.anim is None:
            return
        self._updating_anim = True
        self.anim_name.set_text(self.anim["name"])
        self.frame_time.set_value(float(self.anim.get("frame_time", 0.5)))
        self.fade_row.set_active(bool(self.anim.get("fade", True)))
        self.mode_row.set_selected(self.mode_ids.index(self.anim.get("mode", "loop")))
        self._updating_anim = False
        self._show_frames()

    def _save_anim(self):
        if self.anim is None:
            return
        anims = [a if a["id"] != self.anim["id"] else dict(self.anim) for a in self._animations()]
        self.app.config.set("animations", anims)

    def _set_anim(self, **changes):
        if self.anim is None or self._updating_anim:
            return
        self.anim.update(changes)
        self._save_anim()

    def _new_animation(self, *_):
        anims = self._animations()
        name = paintings.unique_name("My animation", [a["name"] for a in anims])
        first = [to_hex(c) if c else None for c in self.strip.colours]
        anim = paintings.new_animation(name, [first])
        anims.append(anim)
        self.app.config.set("animations", anims)
        self._load_animations(select=anim["id"])
        self._select_frame(0)
        self.page.window.toast(f"“{name}” has one frame with the colours on the light. Add more frames.")

    def _delete_animation(self, *_):
        if self.anim is None:
            return
        self._stop_if_playing()
        self.app.config.set("animations", [a for a in self._animations() if a["id"] != self.anim["id"]])
        self.anim = None
        self._load_animations()

    def _rename(self, row):
        name = row.get_text().strip()
        if not name or self.anim is None:
            return
        others = [a["name"] for a in self._animations() if a["id"] != self.anim["id"]]
        self.anim["name"] = paintings.unique_name(name, others)
        self._save_anim()
        self._load_animations(select=self.anim["id"])

    # frames --------------------------------------------------------------------------------
    def _show_frames(self):
        child = self.frames_flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.frames_flow.remove(child)
            child = nxt
        self._frame_widgets = []
        for i, frame in enumerate(self.anim["frames"] if self.anim else []):
            button = Gtk.ToggleButton(active=i == self.frame, tooltip_text=f"Frame {i + 1}")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            strip = ColorStrip(64, 12)
            strip.set_colors([c for c in paintings.frame_array(frame).astype(int).tolist()])
            box.append(strip)
            box.append(Gtk.Label(label=str(i + 1)))
            button.set_child(box)
            button.connect("toggled", lambda b, k=i: self._frame_toggled(b, k))
            self.frames_flow.append(button)
            self._frame_widgets.append((button, strip))
        self._update_frame_hint()

    def _update_frame_hint(self):
        count = len(self.anim["frames"]) if self.anim else 0
        if self.frame is None:
            self.frame_hint.set_label(f"{count} frames. Select a frame to show and change it.")
        else:
            self.frame_hint.set_label(f"Frame {self.frame + 1} of {count}: what you paint above goes into "
                                      "this frame. Click it again when you're done.")
        for key in ("left", "right", "delete"):
            self.frame_buttons[key].set_sensitive(self.frame is not None and count > 1)

    def _frame_toggled(self, button, index):
        if self._updating_anim:
            return
        if button.get_active():
            self._select_frame(index)
        elif self.frame == index:
            self.frame = None
            self._update_frame_hint()

    def _select_frame(self, index: int):
        self.frame = index
        self._updating_anim = True
        for i, (b, _s) in enumerate(getattr(self, "_frame_widgets", [])):
            b.set_active(i == index)
        self._updating_anim = False
        if self.anim and 0 <= index < len(self.anim["frames"]):
            frame = paintings.frame_array(self.anim["frames"][index])
            xs = (np.arange(self.strip.count) + 0.5) / self.strip.count
            colours = [tuple(int(v) for v in c) for c in paintings.sample(frame, xs)]
            self.strip.colours = colours
            self.strip.queue_draw()
            self._selection_changed()
            self._stop_if_playing()
            self._send(list(colours))
        self._update_frame_hint()

    def _frame_edited(self):
        """Painting goes into the selected frame."""
        if self.anim is None or self.frame is None or not 0 <= self.frame < len(self.anim["frames"]):
            return
        self.anim["frames"][self.frame] = [to_hex(c) if c else None for c in self.strip.colours]
        self._save_anim()
        if self.frame < len(self._frame_widgets):
            self._frame_widgets[self.frame][1].set_colors(
                [c if c else (0, 0, 0) for c in self.strip.colours])

    def _frame_action(self, key: str):
        if self.anim is None:
            return
        frames = self.anim["frames"]
        current = [to_hex(c) if c else None for c in self.strip.colours]
        i = self.frame
        if key == "add":
            if len(frames) >= paintings.MAX_FRAMES:
                self.page.window.toast(f"An animation can have up to {paintings.MAX_FRAMES} frames")
                return
            at = (i + 1) if i is not None else len(frames)
            frames.insert(at, current)
            self._save_anim()
            self.frame = at
            self._show_frames()
            self._select_frame(at)
            return
        if key == "run":
            made = paintings.shifted_frames(current)
            if len(made) < 2:
                return
            self.anim["frames"] = made[:paintings.MAX_FRAMES]
            self.anim["fade"] = True
            self._save_anim()
            self._animation_chosen()
            self.page.window.toast(f"{len(made)} frames: the colours move one segment per frame")
            return
        if i is None:
            return
        if key == "delete" and len(frames) > 1:
            del frames[i]
            self.frame = min(i, len(frames) - 1)
        elif key == "left" and i > 0:
            frames[i - 1], frames[i] = frames[i], frames[i - 1]
            self.frame = i - 1
        elif key == "right" and i < len(frames) - 1:
            frames[i + 1], frames[i] = frames[i], frames[i + 1]
            self.frame = i + 1
        else:
            return
        self._save_anim()
        self._show_frames()
        self._select_frame(self.frame)

    # playing ------------------------------------------------------------------------------
    def _playing(self) -> bool:
        engine = self.app.engines["effects"]
        return bool(self.anim) and engine.running and \
            self.app.config.section("effects").get("effect") == f"anim:{self.anim['id']}"

    def _update_play(self):
        if not self.play_btn.get_root():
            return GLib.SOURCE_CONTINUE
        playing = self._playing()
        self.play_btn.set_label("Stop" if playing else "Play")
        self.play_btn.remove_css_class("suggested-action" if playing else "destructive-action")
        self.play_btn.add_css_class("destructive-action" if playing else "suggested-action")
        return GLib.SOURCE_CONTINUE

    def _stop_if_playing(self):
        if self._playing():
            self.app.engines["effects"].stop(wait=True)
            self._update_play()

    def _play(self, *_):
        if self.anim is None:
            return
        if self._playing():
            self.app.engines["effects"].stop(wait=False)
        else:
            self.frame = None
            for b, _s in getattr(self, "_frame_widgets", []):
                self._updating_anim = True
                b.set_active(False)
                self._updating_anim = False
            self._update_frame_hint()
            self.app.config.set_in("effects", "effect", f"anim:{self.anim['id']}")
            self.app.start_show("effects", [self.device.id])
        GLib.timeout_add(400, lambda: (self._update_play(), False)[1])
