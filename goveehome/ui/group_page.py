from __future__ import annotations

from gi.repository import Adw, GLib, Gtk

from goveehome.ui.control_page import ControlPage
from goveehome.ui.widgets import ColorDot, color_for_state

ALL_LIGHTS = "all-lights"


class GroupPage(ControlPage):
    """Controls several lights at once. group=None means every light."""

    def __init__(self, window, group: dict | None):
        self.group = group
        super().__init__(window, group["name"] if group else "All lights",
                         group["id"] if group else ALL_LIGHTS)
        if group:
            edit = Gtk.Button(icon_name="document-edit-symbolic", tooltip_text="Edit group")
            edit.connect("clicked", lambda *_: edit_group_dialog(self.window, self.group))
            self.header.pack_start(edit)
        self.build_summary()
        self.build_light()
        self.build_timer()
        self._build_members()
        if group:
            delete = Adw.PreferencesGroup()
            row = Adw.ActionRow(title="Delete this group", subtitle="The lights themselves are not affected.")
            btn = Gtk.Button(label="Delete", valign=Gtk.Align.CENTER)
            btn.add_css_class("destructive-action")
            btn.connect("clicked", lambda *_: self.manager.delete_group(self.group["id"]))
            row.add_suffix(btn)
            delete.add(row)
            self.page.add(delete)
        self.refresh()

    def targets(self):
        if self.group is None:
            return self.manager.list()
        group = self.manager.group(self.group["id"]) or self.group
        return self.manager.group_devices(group)

    def _build_members(self):
        self.members_group = Adw.PreferencesGroup(title="Lights in this group")
        self.page.add(self.members_group)
        self._member_rows: list = []

    def refresh(self):
        if self.group:
            self.group = self.manager.group(self.group["id"]) or self.group
            self.set_title(self.group["name"])
        devices = self.targets()
        for row in self._member_rows:
            self.members_group.remove(row)
        self._member_rows = []
        for d in devices:
            row = Adw.ActionRow(title=GLib.markup_escape_text(d.display_name),
                                subtitle="Off" if d.state.on is False else (d.sku or ""))
            dot = ColorDot(14)
            dot.set_rgb(color_for_state(d.state))
            row.add_prefix(dot)
            self.members_group.add(row)
            self._member_rows.append(row)
        if not devices:
            row = Adw.ActionRow(title="No lights in this group yet")
            row.add_css_class("dim-label")
            self.members_group.add(row)
            self._member_rows.append(row)

        on = [d for d in devices if d.state.on]
        first = on[0] if on else (devices[0] if devices else None)
        name = self.group["name"] if self.group else "All lights"
        count = len(devices)
        status = f"{len(on)} of {count} on" if count else "Empty"
        st = first.state if first else None
        self.show_state(name, status, color_for_state(st) if st and on else None, bool(on),
                        st.brightness if st else None, st.kelvin if st else None, st.color if st else None)


def edit_group_dialog(window, group: dict | None = None) -> None:
    """Create a new group, or edit an existing one."""
    manager = window.app.manager
    dialog = Adw.MessageDialog(transient_for=window, modal=True,
                               heading="Edit Group" if group else "New Group")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    name = Gtk.Entry(placeholder_text="Living room", activates_default=True)
    name.set_text(group["name"] if group else "")
    box.append(name)
    listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    listbox.add_css_class("boxed-list")
    checks = {}
    members = set(group["members"]) if group else set()
    for d in manager.list():
        row = Adw.ActionRow(title=GLib.markup_escape_text(d.display_name), subtitle=d.sku)
        check = Gtk.CheckButton(active=d.id in members, valign=Gtk.Align.CENTER)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        listbox.append(row)
        checks[d.id] = check
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                  max_content_height=360)
    scroller.set_child(listbox)
    box.append(scroller)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("save", "Save")
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("save")
    dialog.set_close_response("cancel")

    def on_response(_d, response):
        if response != "save":
            return
        chosen = [i for i, c in checks.items() if c.get_active()]
        saved = manager.save_group(name.get_text() or "Group", chosen, group["id"] if group else None)
        window.open_group(saved["id"])
    dialog.connect("response", on_response)
    dialog.present()
