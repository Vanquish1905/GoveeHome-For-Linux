from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from goveehome import skus
from goveehome.colors import to_hex
from goveehome.models import Device
from goveehome.protocol import cloud
from goveehome.sync.zones import LAYOUTS
from goveehome.ui.control_page import ControlPage
from goveehome.ui.widgets import ColorPanel, Debouncer, SliderRow, color_for_state

LAYOUT_IDS = list(LAYOUTS)


class DevicePage(ControlPage):
    def __init__(self, window, device: Device):
        super().__init__(window, device.display_name, device.id)
        self.device = device
        self._white_preview = False

        self.build_summary()
        self.build_light()
        if device.cloud:
            self._build_scenes()
            self._build_cloud_extras()
        self.build_timer()
        self._build_shows()
        self._build_correction()
        self._build_details()
        self.refresh()

    def targets(self):
        return [self.device]

    def on_showing(self):
        self.manager.refresh(self.device)

    # cloud features -------------------------------------------------------------
    def _build_scenes(self):
        group = Adw.PreferencesGroup(title="Scenes",
                                     description="Scenes and your DIY scenes from the Govee account. "
                                                 "They run on the light itself.")
        self.scene_row = Adw.ComboRow(title="Scene", sensitive=False, enable_search=True)
        self.scene_row.set_model(Gtk.StringList.new(["Loading…"]))
        self._scenes: list[dict] = []
        apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER, sensitive=False)
        apply.add_css_class("flat")
        apply.connect("clicked", self._apply_scene)
        self.scene_apply = apply
        self.scene_row.add_suffix(apply)
        group.add(self.scene_row)
        if self.manager.cloud:
            self.manager.load_scenes(self.device, lambda s: GLib.idle_add(self._scenes_loaded, s))
        else:
            self.scene_row.set_model(Gtk.StringList.new(["Add an API key in Preferences"]))
        self.page.add(group)

    def _build_cloud_extras(self):
        caps = self.device.cloud_capabilities
        count = cloud.segment_count(caps)
        if count > 1 and self.manager.cloud:
            self._segment_buttons: list[Gtk.ToggleButton] = []
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                               max_children_per_line=15, min_children_per_line=5,
                               column_spacing=4, row_spacing=4,
                               margin_top=8, margin_bottom=4, margin_start=8, margin_end=8)
            for i in range(count):
                b = Gtk.ToggleButton(label=str(i + 1))
                self._segment_buttons.append(b)
                flow.append(b)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(flow)
            actions = Gtk.Box(spacing=6, margin_start=8, margin_bottom=8)
            for label, value in (("Select all", True), ("Clear", False)):
                btn = Gtk.Button(label=label)
                btn.add_css_class("flat")
                btn.connect("clicked", lambda _b, v=value: [s.set_active(v) for s in self._segment_buttons])
                actions.append(btn)
            box.append(actions)
            pick = Adw.PreferencesRow(activatable=False, title="Segments")
            pick.set_child(box)
            panel = ColorPanel(self.app, self._paint_segments, title="Segments",
                               description="Pick segments, then a colour. This goes through the "
                                           "cloud, so it takes a moment.", first_row=pick)
            self.page.add(panel.group)

        modes = cloud.music_modes(caps)
        if modes and self.manager.cloud:
            group = Adw.PreferencesGroup(title="Music mode on the light",
                                         description="Uses the microphone built into the light. "
                                                     "For music from this PC use Music in the sidebar.")
            self._music_modes = modes
            self.music_row = Adw.ComboRow(title="Mode")
            self.music_row.set_model(Gtk.StringList.new([name for name, _ in modes]))
            group.add(self.music_row)
            self.music_sens = SliderRow("Sensitivity", 0, 100, 1, lambda v: f"{v:.0f}")
            self.music_sens.set_value(70)
            group.add(self.music_sens)
            start = Adw.ActionRow(title="Start music mode")
            btn = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
            btn.add_css_class("flat")
            btn.connect("clicked", self._start_music_mode)
            start.add_suffix(btn)
            group.add(start)
            self.page.add(group)

        toggles = cloud.toggles(caps)
        if toggles and self.manager.cloud:
            group = Adw.PreferencesGroup(title="Options")
            for instance, label in toggles:
                row = Adw.ActionRow(title=label)
                for text, on in (("Off", False), ("On", True)):
                    b = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
                    b.add_css_class("flat")
                    b.connect("clicked", lambda _b, i=instance, v=on: self.manager.set_toggle(self.device, i, v))
                    row.add_suffix(b)
                group.add(row)
            self.page.add(group)

    def _paint_segments(self, rgb):
        chosen = [i for i, b in enumerate(self._segment_buttons) if b.get_active()]
        if not chosen:
            self.window.toast("Select one or more segments first")
            return
        self.manager.set_segment_color(self.device, chosen, rgb)

    def _start_music_mode(self, *_):
        idx = self.music_row.get_selected()
        if 0 <= idx < len(self._music_modes):
            self.manager.set_music_mode(self.device, self._music_modes[idx][1], int(self.music_sens.get_value()))

    def _scenes_loaded(self, scenes):
        self._scenes = scenes
        if scenes:
            names = [s["name"] + (" (DIY)" if s.get("instance") == "diyScene" else "") for s in scenes]
            self.scene_row.set_model(Gtk.StringList.new(names))
            self.scene_row.set_sensitive(True)
            self.scene_apply.set_sensitive(True)
        else:
            self.scene_row.set_model(Gtk.StringList.new(["No scenes for this light"]))
        return GLib.SOURCE_REMOVE

    def _apply_scene(self, *_):
        idx = self.scene_row.get_selected()
        if 0 <= idx < len(self._scenes):
            self.manager.set_scene(self.device, self._scenes[idx])

    # light shows ------------------------------------------------------------------
    def _build_shows(self):
        settings = self.manager.stream_settings(self.device)
        info = skus.lookup(self.device.sku)
        group = Adw.PreferencesGroup(title="Light shows")
        if not self.device.can_stream:
            group.set_description("This light is only reachable through the cloud, which is too slow "
                                  "for screen sync, music and effects. Turn on LAN Control for it in "
                                  "the phone app.")
        for key, title in (("sync", "Screen sync"), ("music", "Music"), ("effects", "Effects")):
            row = Adw.SwitchRow(title=f"Use for {title.lower()}", active=settings.get(key, True),
                                sensitive=self.device.can_stream)
            row.connect("notify::active", lambda r, _p, k=key: self._save_sync(**{k: r.get_active()}))
            group.add(row)

        self.stream_switch = Adw.SwitchRow(
            title="Segment streaming",
            subtitle="A colour per segment. Works on lights with DreamView / Razer support.",
            active=settings["streaming"], sensitive=bool(self.device.ip))
        self.stream_switch.connect("notify::active", lambda r, _p: self._save_sync(streaming=r.get_active()))
        group.add(self.stream_switch)

        self.segments_row = Adw.SpinRow.new_with_range(1, 84, 1)
        self.segments_row.set_title("Segments")
        stored = self.app.config.device_settings(self.device.id)["segments"]
        self.segments_row.set_value(stored or info.segments)
        self.segments_row.connect("notify::value", lambda r, _p: self._save_sync(segments=int(r.get_value())))
        group.add(self.segments_row)

        self.layout_row = Adw.ComboRow(title="Mounting", subtitle="Where on the screen the light takes its colours from")
        self.layout_row.set_model(Gtk.StringList.new(list(LAYOUTS.values())))
        self.layout_row.set_selected(LAYOUT_IDS.index(settings["layout"]) if settings["layout"] in LAYOUT_IDS else 0)
        self.layout_row.connect("notify::selected", lambda r, _p: self._save_sync(layout=LAYOUT_IDS[r.get_selected()]))
        group.add(self.layout_row)

        self.reverse_row = Adw.SwitchRow(title="Reverse direction", active=settings["reverse"])
        self.reverse_row.connect("notify::active", lambda r, _p: self._save_sync(reverse=r.get_active()))
        group.add(self.reverse_row)

        self.gradient_row = Adw.SwitchRow(title="Blend between segments", active=settings.get("gradient", True))
        self.gradient_row.connect("notify::active", lambda r, _p: self._save_sync(gradient=r.get_active()))
        group.add(self.gradient_row)

        identify = Adw.ActionRow(title="Check the direction",
                                 subtitle="Red lights up where the mounting starts (bottom left for a TV "
                                          "backlight), blue where it ends.")
        btn = Gtk.Button(label="Identify", valign=Gtk.Align.CENTER, sensitive=self.device.can_stream)
        btn.add_css_class("flat")
        btn.connect("clicked", lambda *_: self.manager.identify(self.device))
        identify.add_suffix(btn)
        group.add(identify)
        self._update_sync_sensitivity()
        self.page.add(group)

    def _build_correction(self):
        gains = self.app.config.device_settings(self.device.id).get("gains") or [1.0, 1.0, 1.0]
        group = Adw.PreferencesGroup(
            title="Colour correction",
            description="Many LEDs look bluish or greenish compared to a screen. Lower a channel "
                        "until white looks neutral. Used by light shows.")
        self.gain_rows = []
        send_white = Debouncer(150, lambda _v: self._send_white())
        for i, name in enumerate(("Red", "Green", "Blue")):
            row = SliderRow(name, 0.3, 1.0, 0.01, lambda v: f"{v * 100:.0f} %")
            row.set_value(float(gains[i]))
            row.scale.connect("value-changed", lambda _s: (self._save_gains(), send_white(1)))
            self.gain_rows.append(row)
            group.add(row)
        white = Adw.ActionRow(title="Show white with this correction")
        btn = Gtk.Button(label="Show", valign=Gtk.Align.CENTER, sensitive=self.device.can_stream)
        btn.add_css_class("flat")
        btn.connect("clicked", lambda *_: (setattr(self, "_white_preview", True), self._send_white()))
        white.add_suffix(btn)
        group.add(white)
        self.page.add(group)

    def _save_gains(self):
        gains = [round(r.get_value(), 3) for r in self.gain_rows]
        self.app.config.update_device_settings(self.device.id, gains=gains)
        self._notify_shows()

    def _send_white(self):
        if not self._white_preview:
            return
        gains = [r.get_value() for r in self.gain_rows]
        self.manager.set_color(self.device, tuple(int(255 * g) for g in gains))

    def _build_details(self):
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
        self.page.add(group)

    # behaviour ---------------------------------------------------------------------
    def refresh(self) -> None:
        d = self.device
        st = d.state
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
            status += " · light show running"
        self.set_title(d.display_name)
        self.show_state(d.display_name, status, color_for_state(st), st.on, st.brightness, st.kelvin, st.color)
        self.address_row.set_subtitle(d.ip or "—")
        self.via_row.set_subtitle(", ".join(t.label for t in d.transports) or "—")

    def _save_sync(self, **changes):
        self.app.config.update_device_settings(self.device.id, **changes)
        self._update_sync_sensitivity()
        self._notify_shows()

    def _notify_shows(self):
        self.window.device_settings_changed(self.device)

    def _update_sync_sensitivity(self):
        streaming = self.stream_switch.get_active() and bool(self.device.ip)
        for row in (self.segments_row, self.reverse_row, self.gradient_row):
            row.set_sensitive(streaming)
