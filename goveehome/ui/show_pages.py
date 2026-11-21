"""Pages for the three light shows: screen sync, music and effects."""

from __future__ import annotations

import math

import numpy as np

from gi.repository import Adw, Gdk, GLib, Gtk

from goveehome import capture
from goveehome.capture import x11
from goveehome.models import Device
from goveehome.sync import colors as sc
from goveehome.sync import effects as fx
from goveehome.sync import music
from goveehome.sync.engine import Preview
from goveehome.sync.zones import LAYOUTS
from goveehome.ui.widgets import ColorStrip, Debouncer, SliderRow, rgb_from_rgba, rgba_from_rgb


class PreviewArea(Gtk.Overlay):
    """The captured / rendered frame with each light's zones drawn on top."""

    def __init__(self, placeholder: str):
        super().__init__()
        self.add_css_class("preview")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.FILL, can_shrink=True)
        self.set_child(self.picture)
        self.zones = Gtk.DrawingArea()
        self.zones.set_draw_func(self._draw)
        self.add_overlay(self.zones)
        self.placeholder = Gtk.Label(label=placeholder, wrap=True, justify=Gtk.Justification.CENTER)
        self.placeholder.add_css_class("dim-label")
        self.add_overlay(self.placeholder)
        self._targets: dict = {}

    def show_preview(self, preview: Preview | None) -> None:
        if preview is None or preview.frame is None:
            self.picture.set_paintable(None)
            self._targets = {}
            self.placeholder.set_visible(True)
            self.zones.queue_draw()
            return
        frame = preview.frame
        h, w = frame.shape[:2]
        texture = Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8,
                                        GLib.Bytes.new(frame.tobytes()), w * 3)
        self.picture.set_paintable(texture)
        self.placeholder.set_visible(False)
        self._targets = preview.targets
        self.zones.queue_draw()

    def _draw(self, _area, cr, width, height):
        for rects, colors in self._targets.values():
            for i, (x0, y0, x1, y1) in enumerate(rects):
                if (x1 - x0) * (y1 - y0) > 0.5:
                    continue  # whole-screen zones are shown as the dot in the list instead
                x, y = x0 * width, y0 * height
                w, h = (x1 - x0) * width, (y1 - y0) * height
                cr.rectangle(x + 1, y + 1, w - 2, h - 2)
                cr.set_source_rgba(1, 1, 1, 0.5)
                cr.set_line_width(1)
                cr.stroke()
                if i < len(colors):
                    size = max(5.0, min(w, h) * 0.45)
                    cr.rectangle(x + (w - size) / 2, y + (h - size) / 2, size, size)
                    cr.set_source_rgb(*(c / 255 for c in colors[i]))
                    cr.fill_preserve()
                    cr.set_source_rgba(0, 0, 0, 0.5)
                    cr.stroke()


class LightRow(Adw.ActionRow):
    def __init__(self, page: "ShowPage", device: Device):
        super().__init__()
        self.page = page
        self.device = device
        self._updating = False
        # what the light is getting right now, segment by segment
        self.strip = ColorStrip()
        self.strip.set_tooltip_text("The colours this light is getting right now")
        self.add_suffix(self.strip)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._toggled)
        self.add_suffix(self.switch)
        self.set_activatable_widget(self.switch)
        self.update()

    def update(self):
        d = self.device
        settings = self.page.manager.stream_settings(d)
        self.set_title(GLib.markup_escape_text(d.display_name))
        if not d.can_stream:
            self.set_subtitle("Needs LAN Control (Govee app → light settings) or Bluetooth")
            self.set_sensitive(False)
            self._set_switch(False)
            return
        self.set_sensitive(True)
        if self.page.kind == "sync":
            layout = LAYOUTS.get(settings["layout"], settings["layout"])
            detail = f"{settings['segments']} segments" if settings["streaming"] else "Single colour"
            self.set_subtitle(f"{detail} · {layout}")
        else:
            self.set_subtitle(f"{settings['segments']} segments" if settings["streaming"] else "Single colour")
        self._set_switch(settings.get(self.page.kind, True))

    def _set_switch(self, value: bool):
        self._updating = True
        self.switch.set_active(bool(value))
        self._updating = False

    def _toggled(self, switch, _pspec):
        if self._updating:
            return
        self.page.app.config.update_device_settings(self.device.id, **{self.page.kind: switch.get_active()})
        self.page.engine.reload()
        self.page._update_count()


class ShowPage(Adw.NavigationPage):
    kind = "sync"
    page_title = "Light show"
    placeholder = "The preview shows up here while it runs."
    lights_text = ""
    preview_ratio = 16 / 9
    preview_height = 300

    def __init__(self, window):
        super().__init__(title=self.page_title, tag=self.kind)
        self.window = window
        self.app = window.app
        self.manager = self.app.manager
        self.config = self.app.config
        self.engine = self.app.engines[self.kind]
        self._rows: dict[str, LightRow] = {}

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.toggle = Gtk.Button(label="Start")
        self.toggle.add_css_class("suggested-action")
        self.toggle.connect("clicked", self.on_toggle)
        header.pack_end(self.toggle)
        view.add_top_bar(header)
        self.page = Adw.PreferencesPage()
        view.set_content(self.page)
        self.set_child(view)

        self.page.add(self._build_preview())
        self.page.add(self._build_lights())
        self.build_top()
        self.build_bottom()
        if self.engine.running:
            self.on_state(True, None)

    # to override -------------------------------------------------------------
    def build_top(self):
        pass

    def build_bottom(self):
        pass

    def status_text(self, preview: Preview) -> str:
        return f"Running · {preview.backend} · {preview.fps:.0f} updates/s"

    # building -----------------------------------------------------------------
    def _build_preview(self):
        group = Adw.PreferencesGroup()
        frame = Gtk.AspectFrame(ratio=self.preview_ratio, obey_child=False)
        frame.set_size_request(-1, self.preview_height)
        self.preview = PreviewArea(self.placeholder)
        frame.set_child(self.preview)
        group.add(frame)
        self.status = Gtk.Label(xalign=0, margin_top=8, wrap=True, label="Not running")
        self.status.add_css_class("dim-label")
        group.add(self.status)
        self.details = Gtk.Label(xalign=0, wrap=True, visible=False, selectable=True)
        self.details.add_css_class("dim-label")
        self.details.add_css_class("caption")
        group.add(self.details)
        return group

    def _build_lights(self):
        self.lights_group = Adw.PreferencesGroup(title="Lights", description=self.lights_text or None)
        pick = Gtk.Box(spacing=6)
        for label, value in (("All", True), ("None", False)):
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda _b, v=value: self.select_lights(None if v else []))
            pick.append(btn)
        self.group_menu = Gtk.MenuButton(label="Group", tooltip_text="Use the lights of a group")
        self.group_menu.add_css_class("flat")
        self.group_menu.set_create_popup_func(self._fill_group_menu)
        pick.append(self.group_menu)
        self.lights_group.set_header_suffix(pick)
        self.no_lights = Adw.ActionRow(title="No lights found yet")
        self.no_lights.add_css_class("dim-label")
        self.lights_group.add(self.no_lights)
        for device in self.manager.list():
            self.add_device(device)
        return self.lights_group

    def slider(self, group, section: str, title: str, key: str, lo, hi, step, fmt, reload=False):
        values = self.config.section(section)
        row = SliderRow(title, lo, hi, step, fmt)
        row.set_value(float(values[key]))
        save = Debouncer(400, lambda v: (self.config.set_in(section, key, v),
                                         self.engine.reload() if reload else None))

        def changed(scale):
            values[key] = scale.get_value()   # the engine reads it live
            save(scale.get_value())
        row.scale.connect("value-changed", changed)
        group.add(row)
        return row

    def combo(self, group, section: str, title: str, key: str, options: dict, subtitle: str | None = None):
        values = self.config.section(section)
        ids = list(options)
        row = Adw.ComboRow(title=title, subtitle=subtitle)
        row.set_model(Gtk.StringList.new(list(options.values())))
        row.set_selected(ids.index(values[key]) if values[key] in ids else 0)
        row.connect("notify::selected", lambda r, _p: self.config.set_in(section, key, ids[r.get_selected()]))
        group.add(row)
        return row

    # choosing lights -----------------------------------------------------------
    def select_lights(self, ids: list[str] | None) -> None:
        """ids=None turns on every light that can take part."""
        for device in self.manager.list():
            if not device.can_stream:
                continue
            on = ids is None or device.id in ids
            self.config.update_device_settings(device.id, save=False, **{self.kind: on})
        self.config.save()
        for row in self._rows.values():
            row.update()
        self.engine.reload()
        self._update_count()

    def _fill_group_menu(self, button):
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6)
        groups = self.manager.groups()
        if not groups:
            hint = Gtk.Label(label="No groups yet. Create one with\n“New group…” in the sidebar.",
                             margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
            hint.add_css_class("dim-label")
            box.append(hint)
        for group in groups:
            item = Gtk.Button(label=group["name"])
            item.add_css_class("flat")
            item.get_child().set_xalign(0)

            def use(_b, g=group):
                popover.popdown()
                self.select_lights(list(g["members"]))
            item.connect("clicked", use)
            box.append(item)
        popover.set_child(box)
        button.set_popover(popover)

    def _update_count(self):
        usable = [d for d in self.manager.list() if d.can_stream]
        chosen = [d for d in usable if self.manager.stream_settings(d).get(self.kind, True)]
        text = self.lights_text or ""
        if usable:
            count = f"{len(chosen)} of {len(usable)} lights take part."
            text = f"{count} {text}".strip()
        self.lights_group.set_description(text or None)

    # device list --------------------------------------------------------------
    def add_device(self, device: Device):
        if device.id in self._rows:
            self._rows[device.id].update()
            return
        row = LightRow(self, device)
        self._rows[device.id] = row
        self.lights_group.add(row)
        self.no_lights.set_visible(False)
        self._update_count()

    def remove_device(self, device: Device):
        row = self._rows.pop(device.id, None)
        if row:
            self.lights_group.remove(row)
        self.no_lights.set_visible(not self._rows)

    def device_settings_changed(self, device: Device):
        if device.id in self._rows:
            self._rows[device.id].update()
        self._update_count()

    # engine --------------------------------------------------------------------
    def on_toggle(self, *_):
        if self.engine.running:
            self.toggle.set_sensitive(False)
            self.status.set_label("Stopping…")
            self.config.set_in("background", "last_show", "")
            self.engine.stop(wait=False)
        else:
            self.status.set_label("Starting…")
            self.toggle.set_sensitive(False)
            self.app.start_show(self.kind)

    def on_state(self, running: bool, message: str | None):
        self.toggle.set_sensitive(True)
        if running:
            self.toggle.set_label("Stop")
            self.toggle.remove_css_class("suggested-action")
            self.toggle.add_css_class("destructive-action")
            self.status.set_label(f"Running · {self.engine.backend_name}")
        else:
            self.toggle.set_label("Start")
            self.toggle.remove_css_class("destructive-action")
            self.toggle.add_css_class("suggested-action")
            self.status.set_label(message or "Not running")
            self.details.set_visible(False)
            self.preview.show_preview(None)
            for row in self._rows.values():
                row.strip.set_colors([])

    def on_preview(self, preview: Preview):
        if not self.engine.running:
            return
        self.preview.show_preview(preview)
        self.status.set_label(self.status_text(preview))
        self.details.set_label(preview.details)
        self.details.set_visible(bool(preview.details))
        for device_id, (_rects, colors) in preview.targets.items():
            row = self._rows.get(device_id)
            if row and colors:
                row.strip.set_colors(colors)


class ScreenSyncPage(ShowPage):
    kind = "sync"
    page_title = "Screen sync"
    placeholder = "The preview shows up here while screen sync runs."
    lights_text = "Open a light to set how it is mounted. Lights need LAN control or Bluetooth."

    def build_top(self):
        group = Adw.PreferencesGroup(title="Colours")
        self.combo(group, "sync", "Colour pick", "mode", sc.MODES,
                   "Colourful lets the colours in a zone win over white and grey areas")
        vivid = self.slider(group, "sync", "Vividness", "vividness", 1.0, 8.0, 0.1,
                            lambda v: "off" if v <= 1.01 else f"{v:.1f}")
        vivid.set_tooltip_text("How pure the light colours are, like Saturation in Govee's own app. "
                               "Lights with white LEDs (RGBWW, e.g. the H6056) turn mixed colours white, "
                               "so keep this high for them.")
        self.slider(group, "sync", "Saturation", "saturation", 0.0, 2.0, 0.05, lambda v: f"{v * 100:.0f} %")
        self.slider(group, "sync", "Brightness", "brightness", 0.1, 1.5, 0.05, lambda v: f"{v * 100:.0f} %")
        self.slider(group, "sync", "Black level", "black_level", 0, 60, 1, lambda v: f"{v:.0f}")

        gamma = SliderRow("LED gamma", 1.0, 3.0, 0.05, lambda v: f"{v:.2f}")
        gamma.set_tooltip_text("Lights are much brighter than a screen at half power. Higher values "
                               "give deeper colours and darker shadows. Applies to all light shows.")
        gamma.set_value(float(self.config.get("gamma", 2.0)))
        save = Debouncer(400, lambda v: self.config.set("gamma", v))

        def gamma_changed(scale):
            self.config.data["gamma"] = scale.get_value()
            save(scale.get_value())
        gamma.scale.connect("value-changed", gamma_changed)
        group.add(gamma)

        letterbox = Adw.SwitchRow(title="Ignore black bars", subtitle="For films with letterboxing",
                                  active=bool(self.config.sync.get("letterbox", True)))
        letterbox.connect("notify::active", lambda r, _p: self.config.set_sync("letterbox", r.get_active()))
        group.add(letterbox)

        follow = Adw.SwitchRow(title="Follow the video",
                               subtitle="When a video or game runs in a window, take the colours from it "
                                        "instead of the screen edges",
                               active=bool(self.config.sync.get("follow_video", True)))
        follow.connect("notify::active", lambda r, _p: self.config.set_sync("follow_video", r.get_active()))
        group.add(follow)

        boost = Adw.SwitchRow(title="Colour boost",
                              subtitle="Brings back the colour when the captured picture is washed out, "
                                       "e.g. on KDE Plasma with HDR on",
                              active=bool(self.config.sync.get("auto_boost", True)))
        boost.connect("notify::active", lambda r, _p: self.config.set_sync("auto_boost", r.get_active()))
        group.add(boost)
        self.page.add(group)

        speed = Adw.PreferencesGroup(title="Response")
        self.slider(speed, "sync", "Smoothing", "smoothing", 0.0, 0.5, 0.01,
                    lambda v: "off" if v < 0.005 else f"{v * 1000:.0f} ms")
        fps = Adw.SpinRow.new_with_range(10, 60, 1)
        fps.set_title("Updates per second")
        fps.set_subtitle("Lights without segment streaming are capped at 15")
        fps.set_value(int(self.config.sync["fps"]))
        fps.connect("notify::value", lambda r, _p: self.config.set_sync("fps", int(r.get_value())))
        speed.add(fps)
        self.page.add(speed)

    def build_bottom(self):
        sync = self.config.sync
        group = Adw.PreferencesGroup(title="Capture")
        found = capture.available_backends()
        ids = ["auto"] + found
        labels = []
        for b in ids:
            if b == "auto":
                try:
                    labels.append(f"Automatic ({capture.BACKENDS[capture.auto_backend()]})")
                except capture.CaptureError:
                    labels.append("Automatic")
            else:
                labels.append(capture.BACKENDS[b])
        row = Adw.ComboRow(title="Source")
        row.set_model(Gtk.StringList.new(labels))
        current = sync.get("backend", "auto")
        row.set_selected(ids.index(current) if current in ids else 0)
        row.connect("notify::selected", lambda r, _p: self.config.set_sync("backend", ids[r.get_selected()]))
        group.add(row)

        monitors = x11.monitors() if "x11" in found else []
        if len(monitors) > 2:  # [all, m1, m2, ...]
            names = ["All monitors"] + [f"Monitor {m['index']} ({m['width']}×{m['height']})"
                                        for m in monitors[1:]]
            mon = Adw.ComboRow(title="Monitor", subtitle="X11 only; on Wayland the share dialog decides")
            mon.set_model(Gtk.StringList.new(names))
            mon.set_selected(min(int(sync.get("monitor", 1)), len(names) - 1))
            mon.connect("notify::selected", lambda r, _p: self.config.set_sync("monitor", r.get_selected()))
            group.add(mon)

        self.slider(group, "sync", "Edge depth", "edge_depth", 0.05, 0.5, 0.01,
                    lambda v: f"{v * 100:.0f} %", reload=True)
        restore = Adw.SwitchRow(title="Restore colours when stopping", active=sync["restore_on_stop"])
        restore.connect("notify::active", lambda r, _p: self.config.set_sync("restore_on_stop", r.get_active()))
        group.add(restore)
        if "portal" in found:
            forget = Adw.ActionRow(title="Shared screen", subtitle="The choice from the share dialog is remembered.")
            btn = Gtk.Button(label="Ask again", valign=Gtk.Align.CENTER)
            btn.add_css_class("flat")
            btn.connect("clicked", self._forget_portal)
            forget.add_suffix(btn)
            group.add(forget)
        self.page.add(group)

    def _build_preview(self):
        group = super()._build_preview()
        row = Gtk.Box(spacing=6, margin_top=6)
        copy = Gtk.Button(label="Copy report", tooltip_text="Copies a short report about capture and "
                          "lights, to paste into a bug report")
        copy.add_css_class("flat")
        copy.connect("clicked", self._copy_report)
        row.append(copy)
        group.add(row)
        return group

    def _copy_report(self, *_):
        from goveehome import diagnostics
        text = diagnostics.report_from_engine(self.engine, self.manager)
        Gdk.Display.get_default().get_clipboard().set(text)
        self.window.toast("Report copied to the clipboard")

    def status_text(self, preview):
        text = f"Running · {preview.backend} · {preview.fps:.0f} updates/s"
        if preview.delay is not None:
            text += f" · {preview.delay * 1000:.0f} ms from capture to light"
        return text

    def on_toggle(self, *_):
        if not self.engine.running:
            super().on_toggle()
            self.status.set_label("Starting… If a screen share dialog opens, pick the screen the lights are behind.")
            return
        super().on_toggle()

    def _forget_portal(self, *_):
        self.config.set("portal_restore_token", "")
        self.window.toast("The screen share dialog will ask again next time")


class GradientCard(Gtk.ToggleButton):
    """A card with a colour strip and a name; used for effects and palettes."""

    def __init__(self, label: str, colors_fn):
        super().__init__()
        self.colors_fn = colors_fn
        self.add_css_class("effect-card")
        self.add_css_class("flat")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.swatch = Gtk.DrawingArea()
        self.swatch.set_content_height(40)
        self.swatch.set_content_width(96)
        self.swatch.set_draw_func(self._draw)
        box.append(self.swatch)
        box.append(Gtk.Label(label=label, ellipsize=3))
        self.set_child(box)

    def _draw(self, _area, cr, width, height):
        import cairo
        colors = self.colors_fn() or [(128, 128, 128)]
        grad = cairo.LinearGradient(0, 0, width, 0)
        for i, c in enumerate(colors):
            grad.add_color_stop_rgb(i / max(1, len(colors) - 1), *(v / 255 for v in c))
        r = 8
        cr.new_sub_path()
        cr.arc(width - r, r, r, -math.pi / 2, 0)
        cr.arc(width - r, height - r, r, 0, math.pi / 2)
        cr.arc(r, height - r, r, math.pi / 2, math.pi)
        cr.arc(r, r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source(grad)
        cr.fill()


def _card_flow():
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                       max_children_per_line=6, min_children_per_line=2,
                       column_spacing=6, row_spacing=6)


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


class MusicPage(ShowPage):
    kind = "music"
    page_title = "Music"
    placeholder = "Play something and press Start. The lights follow what your speakers play, no microphone needed."
    preview_ratio = 16 / 6
    preview_height = 180
    MAX_COLORS = 6

    def build_top(self):
        group = Adw.PreferencesGroup(title="Style")
        self.combo(group, "music", "Mode", "mode", music.MODES)
        self.slider(group, "music", "Sensitivity", "sensitivity", 0.3, 2.5, 0.05, lambda v: f"{v * 100:.0f} %")
        self.slider(group, "music", "Brightness", "brightness", 0.1, 1.0, 0.05, lambda v: f"{v * 100:.0f} %")
        self.page.add(group)

        from goveehome.sync import palettes
        colors = Adw.PreferencesGroup(title="Colours")
        flow = _card_flow()
        self.palette_cards: dict[str, GradientCard] = {}
        current = self.config.section("music").get("palette", "rainbow")
        for pid, (label, _hexes) in palettes.PALETTES.items():
            card = GradientCard(label, lambda pid=pid: palettes.preview_colors(
                pid, self.config.section("music").get("colors")))
            card.set_active(pid == current)
            card.connect("clicked", self._pick_palette, pid)
            self.palette_cards[pid] = card
            flow.append(card)
        colors.add(flow)
        self.page.add(colors)

        own = Adw.PreferencesGroup(title="Your colours",
                                   description="Used by the “Your colours” palette. Changing one switches to it.")
        self.custom_box = Gtk.Box(spacing=8, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        row = Adw.PreferencesRow(activatable=False, title="Your colours")
        row.set_child(self.custom_box)
        own.add(row)
        self.page.add(own)
        self._build_custom_buttons()

    def _build_custom_buttons(self):
        from goveehome.colors import parse_color
        child = self.custom_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.custom_box.remove(child)
            child = nxt
        hexes = list(self.config.section("music").get("colors") or [])
        for i, h in enumerate(hexes):
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
            try:
                button.set_rgba(rgba_from_rgb(parse_color(h)))
            except ValueError:
                pass
            button.connect("notify::rgba", self._custom_changed, i)
            self.custom_box.append(button)
        spacer = Gtk.Box(hexpand=True)
        self.custom_box.append(spacer)
        remove = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Remove the last colour",
                            valign=Gtk.Align.CENTER, sensitive=len(hexes) > 1)
        remove.add_css_class("flat")
        remove.connect("clicked", lambda *_: self._set_custom(hexes[:-1]))
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add a colour",
                         valign=Gtk.Align.CENTER, sensitive=len(hexes) < self.MAX_COLORS)
        add.add_css_class("flat")
        add.connect("clicked", lambda *_: self._set_custom(hexes + ["#ffffff"]))
        self.custom_box.append(remove)
        self.custom_box.append(add)

    def _set_custom(self, hexes):
        self.config.set_in("music", "colors", hexes)
        self._use_palette("custom")
        self._build_custom_buttons()

    def _custom_changed(self, button, _pspec, index):
        hexes = list(self.config.section("music").get("colors") or [])
        if index < len(hexes):
            hexes[index] = _hex(rgb_from_rgba(button.get_rgba()))
            self.config.set_in("music", "colors", hexes)
            self._use_palette("custom")

    def _pick_palette(self, card, pid):
        self._use_palette(pid)

    def _use_palette(self, pid):
        self.config.set_in("music", "palette", pid)
        for key, card in self.palette_cards.items():
            card.set_active(key == pid)
            card.swatch.queue_draw()

    def status_text(self, preview):
        return f"Listening to {preview.backend.lower()} · {preview.fps:.0f} updates/s"


class EffectsPage(ShowPage):
    kind = "effects"
    page_title = "Effects"
    placeholder = "Pick an effect. It runs on your PC, so it works without the cloud."
    preview_ratio = 16 / 3
    preview_height = 90

    def params(self) -> fx.Params:
        return fx.params_from(self.config.section("effects"))

    def build_top(self):
        from goveehome.colors import parse_color
        section = self.config.section("effects")
        opts = Adw.PreferencesGroup(title="Options")
        self.slider(opts, "effects", "Speed", "speed", 0.1, 4.0, 0.05, lambda v: f"{v:.2f}×")
        self.slider(opts, "effects", "Brightness", "brightness", 0.05, 1.0, 0.05, lambda v: f"{v * 100:.0f} %")
        self.size_row = self.slider(opts, "effects", "Size", "size", 0.05, 1.0, 0.05, lambda v: f"{v * 100:.0f} %")
        reverse = Adw.SwitchRow(title="Reverse direction", active=bool(section.get("reverse", False)))
        reverse.connect("notify::active", lambda r, _p: self.config.set_in("effects", "reverse", r.get_active()))
        opts.add(reverse)
        self.color_rows = []
        for key, title in (("color_a", "First colour"), ("color_b", "Second colour"), ("color_c", "Third colour")):
            row = Adw.ActionRow(title=title)
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
            try:
                button.set_rgba(rgba_from_rgb(parse_color(section.get(key) or "#ffffff")))
            except ValueError:
                pass
            button.connect("notify::rgba", self._color_changed, key)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            opts.add(row)
            self.color_rows.append(row)
        self.page.add(opts)

        self.cards: list[GradientCard] = []
        import time as _time
        self._t0 = _time.monotonic()
        self._anim = 0
        self.connect("showing", self._start_card_animation)
        self.connect("hiding", self._stop_card_animation)
        self.connect("map", self._start_card_animation)
        current = section["effect"]
        for category in fx.CATEGORIES:
            group = Adw.PreferencesGroup(title=category)
            flow = _card_flow()
            for effect in (e for e in fx.EFFECTS.values() if e.category == category):
                card = GradientCard(effect.label, lambda e=effect: self._card_frame(e))
                card.effect = effect
                card.set_active(effect.id == current)
                card.connect("clicked", self._pick)
                self.cards.append(card)
                flow.append(card)
            group.add(flow)
            self.page.add(group)
        self._update_option_rows()

    # animated previews: every card plays its effect while the page is visible
    def _card_frame(self, effect):
        import time as _time
        params = self.params()
        params.reverse = False
        t = _time.monotonic() - self._t0
        cols = fx.render(effect.id, np.linspace(0, 1, 24), t, params)
        return [tuple(int(v) for v in c) for c in cols]

    def _start_card_animation(self, *_):
        if not self._anim:
            self._anim = GLib.timeout_add(80, self._animate_cards)

    def _stop_card_animation(self, *_):
        if self._anim:
            GLib.source_remove(self._anim)
            self._anim = 0

    def _animate_cards(self):
        if not self.get_mapped():
            self._anim = 0
            return GLib.SOURCE_REMOVE
        for card in self.cards:
            if card.get_mapped():
                card.swatch.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _color_changed(self, button, _pspec, key):
        self.config.set_in("effects", key, _hex(rgb_from_rgba(button.get_rgba())))
        for card in self.cards:
            card.swatch.queue_draw()

    def _update_option_rows(self):
        effect = fx.EFFECTS.get(self.config.section("effects")["effect"], fx.EFFECTS["rainbow"])
        for i, row in enumerate(self.color_rows):
            row.set_sensitive(effect.uses_colors > i)
        self.size_row.set_sensitive(effect.uses_size)

    def _pick(self, card):
        for other in self.cards:
            if other is not card:
                other.set_active(False)
        card.set_active(True)
        self.config.set_in("effects", "effect", card.effect.id)
        self._update_option_rows()
        if not self.engine.running:
            self.on_toggle()

    def status_text(self, preview):
        return f"Running · {preview.backend}"
