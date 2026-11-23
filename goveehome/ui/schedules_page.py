"""Schedules: lights on, off, a colour or a sunrise at set times."""

from __future__ import annotations

import datetime as dt

from gi.repository import Adw, GLib, Gtk

from goveehome import schedules as sch
from goveehome import segments as seg
from goveehome.colors import parse_color, to_hex
from goveehome.ui.widgets import rgb_from_rgba, rgba_from_rgb

SHOW_NAMES = {"sync": "Screen sync", "music": "Music", "effects": "Effects"}


class SchedulesPage(Adw.NavigationPage):
    def __init__(self, window):
        super().__init__(title="Schedules", tag="schedules")
        self.window = window
        self.app = window.app
        self.manager = window.manager
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New schedule")
        add.connect("clicked", lambda *_: self.edit(None))
        header.pack_end(add)
        view.add_top_bar(header)
        self.page = Adw.PreferencesPage()
        view.set_content(self.page)
        self.set_child(view)

        self.group = Adw.PreferencesGroup(
            title="Schedules",
            description="Turn lights on or off, set a colour or wake up with a sunrise at set times. "
                        "Schedules run while the app runs, also in the background: turn on "
                        "“Keep running when the window is closed” and “Start at login” in Preferences.")
        self.page.add(self.group)
        self._rows: list[Gtk.Widget] = []

        quick = Adw.PreferencesGroup(title="Quick start")
        for name, fields in (
            ("Wake up with a sunrise", dict(name="Wake up", time="07:00", days=[0, 1, 2, 3, 4],
                                            action="sunrise", value=20)),
            ("Lights off at night", dict(name="Night", time="23:30", action="off")),
            ("Evening glow", dict(name="Evening", time="19:00", action="sunset", value=60)),
        ):
            row = Adw.ActionRow(title=name, activatable=True)
            row.add_suffix(Gtk.Image(icon_name="list-add-symbolic"))
            row.connect("activated", lambda _r, f=fields: self.edit(sch.new_schedule(**f), new=True))
            quick.add(row)
        self.page.add(quick)
        self.refresh()
        GLib.timeout_add_seconds(30, self._tick)

    def _tick(self):
        if self.get_mapped():
            self.refresh()
        return GLib.SOURCE_CONTINUE

    # list ----------------------------------------------------------------------------------
    def _schedules(self) -> list[dict]:
        return list(self.app.config.get("schedules") or [])

    def _save(self, schedules: list[dict]) -> None:
        self.app.config.set("schedules", schedules)
        self.refresh()

    def target_label(self, target: str) -> str:
        if target == "all":
            return "All lights"
        if target.startswith("group:"):
            group = self.manager.group(target[6:])
            return group["name"] if group else "A deleted group"
        device = self.manager.get(target)
        return device.display_name if device else "A light that isn't found"

    def value_label(self, s: dict) -> str:
        v, action = s.get("value"), s.get("action")
        if action == "color" and v:
            return v
        if action == "brightness" and v:
            return f"{v} %"
        if action in ("sunrise", "sunset"):
            return f"over {v or 15} min"
        if action == "show":
            return SHOW_NAMES.get(v, "")
        if action == "segments":
            return f"“{v}”" if v else ""
        return ""

    def refresh(self) -> None:
        for row in self._rows:
            self.group.remove(row)
        self._rows = []
        items = self._schedules()
        if not items:
            empty = Adw.ActionRow(title="No schedules yet",
                                  subtitle="Add one with + or pick one from Quick start")
            empty.add_css_class("dim-label")
            self.group.add(empty)
            self._rows.append(empty)
            return
        now = dt.datetime.now()
        for s in sorted(items, key=lambda x: x.get("time", "")):
            title = s.get("name") or sch.ACTIONS.get(s.get("action"), "Schedule")
            subtitle = f"{sch.describe(s, self.value_label(s))} · {self.target_label(s.get('target', 'all'))}"
            nxt = sch.next_run(s, now)
            if nxt:
                subtitle += f"\nNext: {nxt.strftime('%a %H:%M')}"
            row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                                subtitle=GLib.markup_escape_text(subtitle), activatable=True)
            row.set_subtitle_lines(3)
            switch = Gtk.Switch(active=s.get("enabled", True), valign=Gtk.Align.CENTER,
                                tooltip_text="On or off")
            switch.connect("notify::active", lambda w, _p, sid=s["id"]: self._set_enabled(sid, w.get_active()))
            run = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="Run now")
            run.add_css_class("flat")
            run.connect("clicked", lambda _b, x=s: self.app.scheduler.run(x))
            delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Delete")
            delete.add_css_class("flat")
            delete.connect("clicked", lambda _b, sid=s["id"]: self._save(
                [x for x in self._schedules() if x["id"] != sid]))
            row.add_suffix(run)
            row.add_suffix(delete)
            row.add_suffix(switch)
            row.connect("activated", lambda _r, x=s: self.edit(x))
            self.group.add(row)
            self._rows.append(row)

    def _set_enabled(self, sid: str, on: bool) -> None:
        items = self._schedules()
        for s in items:
            if s["id"] == sid:
                s["enabled"] = on
        self.app.config.set("schedules", items)

    # editor --------------------------------------------------------------------------------
    def edit(self, schedule: dict | None, new: bool = False) -> None:
        is_new = new or schedule is None
        s = dict(schedule or sch.new_schedule())
        dialog = Adw.MessageDialog(transient_for=self.window, modal=True,
                                   heading="New Schedule" if is_new else "Edit Schedule")
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")

        name = Adw.EntryRow(title="Name")
        name.set_text(s.get("name", ""))
        box.append(name)

        h, m = sch.parse_time(s.get("time", "07:00"))
        hour = Adw.SpinRow.new_with_range(0, 23, 1)
        hour.set_title("Hour")
        hour.set_value(h)
        minute = Adw.SpinRow.new_with_range(0, 59, 1)
        minute.set_title("Minute")
        minute.set_value(m)
        for spin in (hour, minute):
            spin.set_wrap(True)
            spin.connect("output", self._two_digits)
        box.append(hour)
        box.append(minute)

        days_row = Adw.PreferencesRow(activatable=False)
        days_box = Gtk.Box(spacing=4, margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
                           homogeneous=True)
        day_buttons = []
        for i, label in enumerate(sch.DAY_NAMES):
            b = Gtk.ToggleButton(label=label, active=i in s.get("days", []))
            b.add_css_class("day")
            day_buttons.append(b)
            days_box.append(b)
        days_row.set_child(days_box)
        box.append(days_row)

        targets = [("all", "All lights")]
        targets += [(f"group:{g['id']}", f"Group: {g['name']}") for g in self.manager.groups()]
        targets += [(d.id, d.display_name) for d in self.manager.list()]
        if s.get("target") not in [t for t, _ in targets]:
            targets.append((s.get("target", "all"), self.target_label(s.get("target", "all"))))
        target = Adw.ComboRow(title="Lights")
        target.set_model(Gtk.StringList.new([label for _, label in targets]))
        target.set_selected([t for t, _ in targets].index(s.get("target", "all")))
        box.append(target)

        action_ids = list(sch.ACTIONS)
        action = Adw.ComboRow(title="Do")
        action.set_model(Gtk.StringList.new(list(sch.ACTIONS.values())))
        action.set_selected(action_ids.index(s.get("action", "on")) if s.get("action") in action_ids else 0)
        box.append(action)

        # values for the actions
        colour = Adw.ActionRow(title="Colour")
        colour_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        start_colour = (255, 138, 60)
        if s.get("action") == "color" and isinstance(s.get("value"), str):
            try:
                start_colour = parse_color(s["value"])
            except ValueError:
                pass
        colour_btn.set_rgba(rgba_from_rgb(start_colour))
        colour.add_suffix(colour_btn)
        box.append(colour)

        level = Adw.SpinRow.new_with_range(1, 100, 1)
        level.set_title("Brightness (%)")
        level.set_value(int(s["value"]) if s.get("action") == "brightness" and s.get("value") else 60)
        box.append(level)

        minutes = Adw.SpinRow.new_with_range(1, 120, 1)
        minutes.set_title("Takes (minutes)")
        minutes.set_value(int(s["value"]) if s.get("action") in ("sunrise", "sunset") and s.get("value") else 20)
        box.append(minutes)

        show_ids = list(SHOW_NAMES)
        show = Adw.ComboRow(title="Light show")
        show.set_model(Gtk.StringList.new(list(SHOW_NAMES.values())))
        if s.get("action") == "show" and s.get("value") in show_ids:
            show.set_selected(show_ids.index(s["value"]))
        box.append(show)

        preset_names = [p["name"] for p in self.app.config.get("segment_presets") or []] + list(seg.BUILT_IN)
        preset = Adw.ComboRow(title="Preset")
        preset.set_model(Gtk.StringList.new(preset_names))
        if s.get("action") == "segments" and s.get("value") in preset_names:
            preset.set_selected(preset_names.index(s["value"]))
        box.append(preset)

        def update_values(*_):
            a = action_ids[action.get_selected()]
            colour.set_visible(a == "color")
            level.set_visible(a == "brightness")
            minutes.set_visible(a in ("sunrise", "sunset"))
            show.set_visible(a == "show")
            preset.set_visible(a == "segments")
            target.set_visible(a != "show")
        action.connect("notify::selected", update_values)
        update_values()

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      max_content_height=480, width_request=360)
        scroller.set_child(box)
        dialog.set_extra_child(scroller)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response != "save":
                return
            a = action_ids[action.get_selected()]
            value = None
            if a == "color":
                value = to_hex(rgb_from_rgba(colour_btn.get_rgba()))
            elif a == "brightness":
                value = int(level.get_value())
            elif a in ("sunrise", "sunset"):
                value = int(minutes.get_value())
            elif a == "show":
                value = show_ids[show.get_selected()]
            elif a == "segments" and preset_names:
                value = preset_names[preset.get_selected()]
            s.update(name=name.get_text().strip(), action=a, value=value,
                     time=f"{int(hour.get_value()):02d}:{int(minute.get_value()):02d}",
                     days=[i for i, b in enumerate(day_buttons) if b.get_active()],
                     target=targets[target.get_selected()][0])
            items = [x for x in self._schedules() if x["id"] != s["id"]]
            items.append(s)
            self._save(items)
        dialog.connect("response", on_response)
        dialog.present()

    @staticmethod
    def _two_digits(spin):
        text = f"{int(spin.get_value()):02d}"
        if spin.get_text() != text:
            spin.set_text(text)
        return True
