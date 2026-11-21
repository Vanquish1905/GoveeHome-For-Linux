from __future__ import annotations

from gi.repository import Adw, Gdk, GLib, Gtk

from goveehome import skus
from goveehome.colors import NAMED_COLORS, to_hex
from goveehome.models import Device
from goveehome.sync.zones import LAYOUTS
from goveehome.ui.widgets import ColorDot, Debouncer, SliderRow, Swatch, color_for_state

PALETTE = [
    ("Warm white", NAMED_COLORS["warm"]),
    ("White", NAMED_COLORS["white"]),
    ("Red", NAMED_COLORS["red"]),
    ("Orange", NAMED_COLORS["orange"]),
    ("Amber", NAMED_COLORS["amber"]),
    ("Yellow", NAMED_COLORS["yellow"]),
    ("Green", NAMED_COLORS["green"]),
    ("Teal", NAMED_COLORS["teal"]),
    ("Cyan", NAMED_COLORS["cyan"]),
    ("Blue", NAMED_COLORS["blue"]),
    ("Indigo", NAMED_COLORS["indigo"]),
    ("Violet", NAMED_COLORS["violet"]),
    ("Magenta", NAMED_COLORS["magenta"]),
    ("Pink", NAMED_COLORS["pink"]),
]

LAYOUT_IDS = list(LAYOUTS)


class DevicePage(Adw.NavigationPage):
    def __init__(self, window, device: Device):
        super().__init__(title=device.display_name, tag=device.id)
        self.window = window
        self.app = window.app
        self.manager = self.app.manager
        self.device = device
        self._updating = False

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        view.add_top_bar(header)

        self.power = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Power")
        self.power.connect("notify::active", self._on_power)
        header.pack_end(self.power)

        page = Adw.PreferencesPage()
        view.set_content(page)
        self.set_child(view)

        page.add(self._build_summary())
        page.add(self._build_light())
        page.add(self._build_color())
        if device.cloud:
            page.add(self._build_scenes())
        page.add(self._build_sync())
        page.add(self._build_details())

        self.refresh()
        self.connect("showing", lambda *_: self.manager.refresh(self.device))

    # building -----------------------------------------------------------------
    def _build_summary(self) -> Adw.PreferencesGroup:
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
        return group

    def _build_light(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Light")
        self.brightness = SliderRow("Brightness", 1, 100, 1, lambda v: f"{v:.0f} %",
                                    icon="display-brightness-symbolic")
        send = Debouncer(150, lambda v: self.manager.set_brightness(self.device, int(v)))
        self.brightness.scale.connect("value-changed", lambda s: self._updating or send(s.get_value()))
        group.add(self.brightness)

        self.kelvin = SliderRow("White", 2000, 9000, 100, lambda v: f"{v:.0f} K",
                                icon="weather-clear-symbolic")
        for mark, text in ((2700, "Warm"), (4500, None), (6500, "Daylight")):
            self.kelvin.scale.add_mark(mark, Gtk.PositionType.BOTTOM, text)
        send_k = Debouncer(200, lambda v: self.manager.set_kelvin(self.device, int(v)))
        self.kelvin.scale.connect("value-changed", lambda s: self._updating or send_k(s.get_value()))
        group.add(self.kelvin)
        return group

    def _build_color(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Colour")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                           max_children_per_line=14, min_children_per_line=5,
                           column_spacing=4, row_spacing=4,
                           margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        self.swatches = []
        for name, rgb in PALETTE:
            sw = Swatch(name, rgb, self._pick)
            self.swatches.append(sw)
            flow.append(sw)
        swatch_row = Adw.PreferencesRow(activatable=False, title="Preset colours")
        swatch_row.set_child(flow)
        group.add(swatch_row)

        row = Adw.ActionRow(title="Custom colour")
        self.color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                                  valign=Gtk.Align.CENTER)
        self.color_button.connect("notify::rgba", self._on_custom_color)
        row.add_suffix(self.color_button)
        row.set_activatable_widget(self.color_button)
        self.hex_label = Gtk.Label()
        self.hex_label.add_css_class("dim-label")
        self.hex_label.add_css_class("monospace")
        row.add_suffix(self.hex_label)
        group.add(row)
        return group

    def _build_scenes(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Scenes", description="Loaded from your Govee account.")
        self.scene_row = Adw.ComboRow(title="Scene", sensitive=False)
        self.scene_row.set_model(Gtk.StringList.new(["Loading…"]))
        self._scenes: list[dict] = []
        apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER, sensitive=False)
        apply.add_css_class("flat")
        apply.connect("clicked", self._apply_scene)
        self.scene_apply = apply
        self.scene_row.add_suffix(apply)
        group.add(self.scene_row)

        def loaded(scenes):
            GLib.idle_add(self._scenes_loaded, scenes)
        if self.manager.cloud:
            self.manager.load_scenes(self.device, loaded)
        else:
            self.scene_row.set_model(Gtk.StringList.new(["Add an API key in Preferences"]))
        return group

    def _build_sync(self) -> Adw.PreferencesGroup:
        settings = self.manager.stream_settings(self.device)
        info = skus.lookup(self.device.sku)
        group = Adw.PreferencesGroup(title="Screen sync")
        if not self.device.can_stream:
            group.set_description("This light is only reachable through the cloud, which is too slow "
                                  "for screen sync. Turn on LAN Control for it in the phone app.")
        self.sync_switch = Adw.SwitchRow(title="Use for screen sync", active=settings["sync"],
                                         sensitive=self.device.can_stream)
        self.sync_switch.connect("notify::active", lambda r, _p: self._save_sync(sync=r.get_active()))
        group.add(self.sync_switch)

        self.stream_switch = Adw.SwitchRow(
            title="Segment streaming",
            subtitle="Sends a colour per segment. Works on DreamView / Razer capable lights.",
            active=settings["streaming"], sensitive=bool(self.device.ip))
        self.stream_switch.connect("notify::active", lambda r, _p: self._save_sync(streaming=r.get_active()))
        group.add(self.stream_switch)

        self.segments_row = Adw.SpinRow.new_with_range(1, 84, 1)
        self.segments_row.set_title("Segments")
        stored = self.app.config.device_settings(self.device.id)["segments"]
        self.segments_row.set_value(stored or info.segments)
        self.segments_row.connect("notify::value",
                                  lambda r, _p: self._save_sync(segments=int(r.get_value())))
        group.add(self.segments_row)

        self.layout_row = Adw.ComboRow(title="Mounting")
        self.layout_row.set_model(Gtk.StringList.new(list(LAYOUTS.values())))
        self.layout_row.set_selected(LAYOUT_IDS.index(settings["layout"]) if settings["layout"] in LAYOUT_IDS else 0)
        self.layout_row.connect("notify::selected",
                                lambda r, _p: self._save_sync(layout=LAYOUT_IDS[r.get_selected()]))
        group.add(self.layout_row)

        self.reverse_row = Adw.SwitchRow(title="Reverse direction", active=settings["reverse"])
        self.reverse_row.connect("notify::active", lambda r, _p: self._save_sync(reverse=r.get_active()))
        group.add(self.reverse_row)

        self.gradient_row = Adw.SwitchRow(title="Blend between segments", active=settings.get("gradient", True))
        self.gradient_row.connect("notify::active", lambda r, _p: self._save_sync(gradient=r.get_active()))
        group.add(self.gradient_row)
        self._update_sync_sensitivity()
        return group

    def _build_details(self) -> Adw.PreferencesGroup:
        d = self.device
        group = Adw.PreferencesGroup(title="Details")
        self.name_row = Adw.EntryRow(title="Name", show_apply_button=True)
        self.name_row.set_text(d.display_name)
        self.name_row.connect("apply", lambda r: self.manager.rename(d, r.get_text()))
        group.add(self.name_row)

        def info_row(title, value):
            row = Adw.ActionRow(title=title, subtitle=value or "—")
            row.add_css_class("property")
            row.set_subtitle_selectable(True)
            group.add(row)
            return row

        info = skus.lookup(d.sku)
        info_row("Model", f"{d.sku} · {info.name}" if d.sku else None)
        self.address_row = info_row("Network address", d.ip)
        if d.ble_address:
            info_row("Bluetooth address", d.ble_address)
        info_row("Device ID", d.id)
        self.via_row = info_row("Connected via", ", ".join(t.label for t in d.transports))

        forget = Adw.ActionRow(title="Forget this light",
                               subtitle="It shows up again the next time it answers a search.")
        btn = Gtk.Button(label="Forget", valign=Gtk.Align.CENTER)
        btn.add_css_class("destructive-action")
        btn.connect("clicked", lambda *_: self.window.forget_device(d))
        forget.add_suffix(btn)
        group.add(forget)
        return group

    # behaviour ----------------------------------------------------------------
    def refresh(self) -> None:
        d = self.device
        st = d.state
        self._updating = True
        try:
            self.set_title(d.display_name)
            self.title_label.set_label(d.display_name)
            if st.on is None:
                status = "State unknown"
            elif not st.on:
                status = "Off"
            elif st.kelvin:
                status = f"On · white {st.kelvin} K"
            elif st.color:
                status = f"On · {to_hex(st.color)}"
            else:
                status = "On"
            if st.on and st.brightness:
                status += f" · {st.brightness} %"
            if d.id in self.manager.streaming_devices:
                status += " · following the screen"
            self.status_label.set_label(status)
            self.big_dot.set_rgb(color_for_state(st))
            self.power.set_active(bool(st.on))
            if st.brightness:
                self.brightness.set_value(st.brightness)
            if st.kelvin:
                self.kelvin.set_value(st.kelvin)
            if st.color and not st.kelvin:
                rgba = Gdk.RGBA()
                rgba.red, rgba.green, rgba.blue, rgba.alpha = (*(c / 255 for c in st.color), 1.0)
                self.color_button.set_rgba(rgba)
                self.hex_label.set_label(to_hex(st.color))
            for sw in self.swatches:
                sw.set_selected(bool(st.color) and not st.kelvin and sw.rgb == st.color)
            self.address_row.set_subtitle(d.ip or "—")
            self.via_row.set_subtitle(", ".join(t.label for t in d.transports) or "—")
        finally:
            self._updating = False

    def _on_power(self, switch, _pspec):
        if not self._updating:
            self.manager.set_power(self.device, switch.get_active())

    def _pick(self, rgb):
        self.manager.set_color(self.device, rgb)

    def _on_custom_color(self, button, _pspec):
        if self._updating:
            return
        c = button.get_rgba()
        self.manager.set_color(self.device, (round(c.red * 255), round(c.green * 255), round(c.blue * 255)))

    def _scenes_loaded(self, scenes):
        self._scenes = scenes
        if scenes:
            self.scene_row.set_model(Gtk.StringList.new([s["name"] for s in scenes]))
            self.scene_row.set_sensitive(True)
            self.scene_apply.set_sensitive(True)
        else:
            self.scene_row.set_model(Gtk.StringList.new(["No scenes for this light"]))
        return GLib.SOURCE_REMOVE

    def _apply_scene(self, *_):
        idx = self.scene_row.get_selected()
        if 0 <= idx < len(self._scenes):
            self.manager.set_scene(self.device, self._scenes[idx]["value"])

    def _save_sync(self, **changes):
        self.app.config.update_device_settings(self.device.id, **changes)
        self._update_sync_sensitivity()
        self.window.sync_page.device_settings_changed(self.device)

    def _update_sync_sensitivity(self):
        streaming = self.stream_switch.get_active() and bool(self.device.ip)
        for row in (self.segments_row, self.reverse_row, self.gradient_row):
            row.set_sensitive(streaming)
