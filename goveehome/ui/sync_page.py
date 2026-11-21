from __future__ import annotations

from gi.repository import Adw, Gdk, GLib, Gtk

from goveehome import capture
from goveehome.models import Device
from goveehome.sync.engine import Preview, SyncEngine
from goveehome.sync.zones import LAYOUTS
from goveehome.ui.widgets import ColorDot, Debouncer, SliderRow

MODES = [("vivid", "Vivid"), ("average", "Average")]


class PreviewArea(Gtk.Overlay):
    """The captured frame with each light's zones drawn on top."""

    def __init__(self):
        super().__init__()
        self.add_css_class("preview")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.FILL, can_shrink=True)
        self.set_child(self.picture)
        self.zones = Gtk.DrawingArea()
        self.zones.set_draw_func(self._draw)
        self.add_overlay(self.zones)
        self.placeholder = Gtk.Label(label="The preview shows up here while sync is running.",
                                     wrap=True, justify=Gtk.Justification.CENTER)
        self.placeholder.add_css_class("dim-label")
        self.add_overlay(self.placeholder)
        self._targets: dict = {}

    def show_preview(self, preview: Preview | None) -> None:
        if preview is None:
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
                if (x0, y0, x1, y1) == (0.0, 0.0, 1.0, 1.0):
                    continue  # whole screen; drawn as a dot in the list instead
                x, y = x0 * width, y0 * height
                w, h = (x1 - x0) * width, (y1 - y0) * height
                cr.rectangle(x + 1, y + 1, w - 2, h - 2)
                cr.set_source_rgba(1, 1, 1, 0.55)
                cr.set_line_width(1)
                cr.stroke()
                if i < len(colors):
                    size = max(4.0, min(w, h) * 0.45)
                    cr.rectangle(x + (w - size) / 2, y + (h - size) / 2, size, size)
                    cr.set_source_rgb(*(c / 255 for c in colors[i]))
                    cr.fill_preserve()
                    cr.set_source_rgba(0, 0, 0, 0.5)
                    cr.stroke()


class LightRow(Adw.ActionRow):
    def __init__(self, page: "SyncPage", device: Device):
        super().__init__()
        self.page = page
        self.device = device
        self.dot = ColorDot(14)
        self.add_prefix(self.dot)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("notify::active", self._toggled)
        self.add_suffix(self.switch)
        self.set_activatable_widget(self.switch)
        self.update()

    def update(self):
        d = self.device
        manager = self.page.manager
        settings = manager.stream_settings(d)
        self.set_title(GLib.markup_escape_text(d.display_name))
        if not d.can_stream:
            self.set_subtitle("Cloud only, too slow for screen sync")
            self.set_sensitive(False)
            self.switch.set_active(False)
            return
        self.set_sensitive(True)
        layout = LAYOUTS.get(settings["layout"], settings["layout"])
        if settings["streaming"]:
            self.set_subtitle(f"{settings['segments']} segments · {layout}")
        else:
            self.set_subtitle(f"Single colour · {layout}")
        self.page.updating = True
        self.switch.set_active(settings["sync"])
        self.page.updating = False

    def _toggled(self, switch, _pspec):
        if self.page.updating:
            return
        self.page.app.config.update_device_settings(self.device.id, sync=switch.get_active())
        self.page.engine.reload()


class SyncPage(Adw.NavigationPage):
    def __init__(self, window):
        super().__init__(title="Screen sync", tag="sync")
        self.window = window
        self.app = window.app
        self.manager = self.app.manager
        self.config = self.app.config
        self.updating = False
        self.engine = SyncEngine(
            self.manager,
            on_preview=lambda p: GLib.idle_add(self._on_preview, p),
            on_state=lambda running, msg: GLib.idle_add(self._on_state, running, msg),
        )
        self.app.engine = self.engine
        self._rows: dict[str, LightRow] = {}

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.toggle = Gtk.Button(label="Start")
        self.toggle.add_css_class("suggested-action")
        self.toggle.connect("clicked", self._on_toggle)
        header.pack_end(self.toggle)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        view.set_content(page)
        self.set_child(view)

        page.add(self._build_preview())
        page.add(self._build_lights())
        page.add(self._build_picture())
        page.add(self._build_capture())

    # building -----------------------------------------------------------------
    def _build_preview(self):
        group = Adw.PreferencesGroup()
        frame = Gtk.AspectFrame(ratio=16 / 9, obey_child=False)
        frame.set_size_request(-1, 300)
        self.preview = PreviewArea()
        frame.set_child(self.preview)
        group.add(frame)
        self.status = Gtk.Label(xalign=0, margin_top=8, wrap=True)
        self.status.add_css_class("dim-label")
        self.status.set_label("Not running")
        group.add(self.status)
        return group

    def _build_lights(self):
        self.lights_group = Adw.PreferencesGroup(
            title="Lights",
            description="Lights need LAN control (or Bluetooth) to follow the screen. "
                        "Open a light to set how it is mounted.")
        self.no_lights = Adw.ActionRow(title="No lights found yet")
        self.no_lights.add_css_class("dim-label")
        self.lights_group.add(self.no_lights)
        for device in self.manager.list():
            self.add_device(device)
        return self.lights_group

    def _build_picture(self):
        sync = self.config.sync
        group = Adw.PreferencesGroup(title="Picture")
        self.mode_row = Adw.ComboRow(title="Colour pick",
                                     subtitle="Vivid favours strong colours over grey areas")
        self.mode_row.set_model(Gtk.StringList.new([label for _, label in MODES]))
        ids = [m for m, _ in MODES]
        self.mode_row.set_selected(ids.index(sync["mode"]) if sync["mode"] in ids else 0)
        self.mode_row.connect("notify::selected",
                              lambda r, _p: self.config.set_sync("mode", ids[r.get_selected()]))
        group.add(self.mode_row)

        save = Debouncer(400, lambda kv: self.config.set_sync(*kv))

        def slider(title, key, lo, hi, step, fmt):
            row = SliderRow(title, lo, hi, step, fmt)
            row.set_value(float(sync[key]))
            row.scale.connect("value-changed", lambda s: (
                self.config.sync.__setitem__(key, s.get_value()),   # live for the engine
                save((key, s.get_value()))))
            group.add(row)
            return row

        slider("Saturation", "saturation", 0.0, 2.5, 0.05, lambda v: f"{v * 100:.0f} %")
        slider("Brightness", "brightness", 0.1, 1.5, 0.05, lambda v: f"{v * 100:.0f} %")
        slider("Smoothing", "smoothing", 0.0, 0.95, 0.05, lambda v: f"{v * 100:.0f} %")
        slider("Black level", "black_level", 0, 60, 1, lambda v: f"{v:.0f}")
        return group

    def _build_capture(self):
        sync = self.config.sync
        group = Adw.PreferencesGroup(title="Capture")
        found = capture.available_backends()
        self._backend_ids = ["auto"] + found
        labels = []
        for b in self._backend_ids:
            if b == "auto":
                try:
                    labels.append(f"Automatic ({capture.BACKENDS[capture.auto_backend()]})")
                except capture.CaptureError:
                    labels.append("Automatic")
            else:
                labels.append(capture.BACKENDS[b])
        self.backend_row = Adw.ComboRow(title="Source")
        self.backend_row.set_model(Gtk.StringList.new(labels))
        current = sync.get("backend", "auto")
        self.backend_row.set_selected(self._backend_ids.index(current) if current in self._backend_ids else 0)
        self.backend_row.connect("notify::selected", lambda r, _p: self.config.set_sync(
            "backend", self._backend_ids[r.get_selected()]))
        group.add(self.backend_row)

        fps = Adw.SpinRow.new_with_range(5, 60, 1)
        fps.set_title("Updates per second")
        fps.set_subtitle("Lights without segment streaming are capped at 15")
        fps.set_value(int(sync["fps"]))
        fps.connect("notify::value", lambda r, _p: self.config.set_sync("fps", int(r.get_value())))
        group.add(fps)

        depth = SliderRow("Edge depth", 0.05, 0.5, 0.01, lambda v: f"{v * 100:.0f} %")
        depth.set_value(float(sync["edge_depth"]))
        save = Debouncer(400, lambda v: (self.config.set_sync("edge_depth", v), self.engine.reload()))
        depth.scale.connect("value-changed", lambda s: save(s.get_value()))
        group.add(depth)

        restore = Adw.SwitchRow(title="Restore colours when stopping", active=sync["restore_on_stop"])
        restore.connect("notify::active", lambda r, _p: self.config.set_sync("restore_on_stop", r.get_active()))
        group.add(restore)

        if "portal" in found:
            forget = Adw.ActionRow(title="Shared screen",
                                   subtitle="The choice from the share dialog is remembered.")
            btn = Gtk.Button(label="Ask again", valign=Gtk.Align.CENTER)
            btn.add_css_class("flat")
            btn.connect("clicked", self._forget_portal)
            forget.add_suffix(btn)
            group.add(forget)
        return group

    # device list ------------------------------------------------------------------
    def add_device(self, device: Device):
        if device.id in self._rows:
            self._rows[device.id].update()
            return
        row = LightRow(self, device)
        self._rows[device.id] = row
        self.lights_group.add(row)
        self.no_lights.set_visible(False)

    def remove_device(self, device: Device):
        row = self._rows.pop(device.id, None)
        if row:
            self.lights_group.remove(row)
        self.no_lights.set_visible(not self._rows)
        self.engine.reload()

    def device_settings_changed(self, device: Device):
        if device.id in self._rows:
            self._rows[device.id].update()
        self.engine.reload()

    # engine ------------------------------------------------------------------
    def _on_toggle(self, *_):
        if self.engine.running:
            self.toggle.set_sensitive(False)
            self.status.set_label("Stopping…")
            self.engine.stop(wait=False)
        else:
            self.status.set_label("Starting… If a screen share dialog opens, pick the screen to follow.")
            self.toggle.set_sensitive(False)
            self.engine.start()

    def _on_state(self, running: bool, message: str | None):
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
            self.preview.show_preview(None)
            for row in self._rows.values():
                row.dot.set_rgb(None)
            if message:
                self.window.toast(message)
        self.window.refresh_rows()
        return GLib.SOURCE_REMOVE

    def _on_preview(self, preview: Preview):
        if not self.engine.running:
            return GLib.SOURCE_REMOVE
        self.preview.show_preview(preview)
        self.status.set_label(f"Running · {preview.backend} · {preview.fps:.0f} updates/s")
        for device_id, (_rects, colors) in preview.targets.items():
            row = self._rows.get(device_id)
            if row and colors:
                avg = tuple(int(sum(c[i] for c in colors) / len(colors)) for i in range(3))
                row.dot.set_rgb(avg)
        return GLib.SOURCE_REMOVE

    def _forget_portal(self, *_):
        self.config.set("portal_restore_token", "")
        self.window.toast("The screen share dialog will ask again next time")
