from __future__ import annotations

import time

from gi.repository import Adw, Gio, GLib, Gtk

from goveehome import APP_NAME
from goveehome.models import Device
from goveehome.ui.device_page import DevicePage
from goveehome.ui.group_page import ALL_LIGHTS, GroupPage, edit_group_dialog
from goveehome.ui.show_pages import EffectsPage, MusicPage, ScreenSyncPage
from goveehome.ui.widgets import ColorDot, color_for_state

SHOWS = [
    ("sync", "Screen sync", "Lights follow your screen", "video-display-symbolic"),
    ("music", "Music", "Lights follow what you play", "audio-x-generic-symbolic"),
    ("effects", "Effects", "Animated scenes", "starred-symbolic"),
]

SECTION_TITLES = {0: "Light shows", 1: "Groups", 2: "Lights"}


class SidebarRow(Gtk.ListBoxRow):
    section = 0

    def __init__(self, title: str, subtitle: str = "", icon: str | None = None):
        super().__init__()
        box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        self.lead = Gtk.Image(icon_name=icon) if icon else ColorDot(12)
        box.append(self.lead)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        self.title = Gtk.Label(label=title, xalign=0, ellipsize=3)
        self.subtitle = Gtk.Label(label=subtitle, xalign=0, ellipsize=3)
        self.subtitle.add_css_class("caption")
        self.subtitle.add_css_class("dim-label")
        self.subtitle.set_visible(bool(subtitle))
        text.append(self.title)
        text.append(self.subtitle)
        box.append(text)
        self.badge = Gtk.Image(icon_name="media-playback-start-symbolic", visible=False,
                               tooltip_text="Running")
        self.badge.add_css_class("accent")
        box.append(self.badge)
        self.set_child(box)

    def sort_key(self) -> tuple:
        return (self.section, "")


class ShowRow(SidebarRow):
    section = 0

    def __init__(self, kind, title, subtitle, icon, order):
        super().__init__(title, subtitle, icon)
        self.kind = kind
        self.order = order

    def sort_key(self):
        return (0, str(self.order))


class GroupRow(SidebarRow):
    section = 1

    def __init__(self, group: dict | None):
        name = group["name"] if group else "All lights"
        super().__init__(name, icon="view-app-grid-symbolic" if group else "view-grid-symbolic")
        self.group_id = group["id"] if group else ALL_LIGHTS

    def sort_key(self):
        return (1, "" if self.group_id == ALL_LIGHTS else self.title.get_label().lower())


class NewGroupRow(SidebarRow):
    section = 1

    def __init__(self):
        super().__init__("New group…", icon="list-add-symbolic")
        self.title.add_css_class("dim-label")

    def sort_key(self):
        return (1, "￿")


class DeviceRow(SidebarRow):
    section = 2

    def __init__(self, device: Device, manager):
        super().__init__(device.display_name)
        self.device = device
        self.manager = manager
        self.update()

    def sort_key(self):
        return (2, self.device.display_name.lower())

    def update(self):
        d = self.device
        self.title.set_label(d.display_name)
        parts = []
        if d.sku:
            parts.append(d.sku)
        if d.state.on is False:
            parts.append("off")
        if not d.transports:
            parts.append("offline")
        elif d.preferred_transport:
            parts.append(d.preferred_transport.label)
        self.subtitle.set_label(" · ".join(parts))
        self.subtitle.set_visible(bool(parts))
        self.lead.set_rgb(color_for_state(d.state))
        self.badge.set_visible(d.id in self.manager.streaming_devices)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.manager = app.manager
        self.set_default_size(1040, 760)
        self.set_size_request(360, 480)
        self._device_rows: dict[str, DeviceRow] = {}
        self._group_rows: dict[str, GroupRow] = {}
        self._device_pages: dict[str, DevicePage] = {}
        self._group_pages: dict[str, GroupPage] = {}
        self._last_toast: tuple[str, float] = ("", 0.0)

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=250, max_sidebar_width=310)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)

        self.show_pages = {
            "sync": ScreenSyncPage(self),
            "music": MusicPage(self),
            "effects": EffectsPage(self),
        }
        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self.show_pages["sync"])

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        for device in self.manager.list():
            self._add_device_row(device)
        self._sync_group_rows()
        self._update_empty()
        self.list.select_row(self.show_rows["sync"])
        self.refresh_rows()

        self.manager.subscribe(self._on_manager_event)
        self.connect("close-request", self._on_close)

    def _build_sidebar(self) -> Adw.NavigationPage:
        page = Adw.NavigationPage(title="GoveeHome", tag="sidebar")
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Search for lights")
        refresh.set_action_name("app.refresh")
        header.pack_start(refresh)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("New Group…", "app.new-group")
        section.append("Add Light by Address…", "app.add-host")
        section.append("Preferences", "app.preferences")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Keyboard Shortcuts", "win.show-help-overlay")
        section.append(f"About {APP_NAME}", "app.about")
        section.append("Quit", "app.quit")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Main menu", primary=True))
        view.add_top_bar(header)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.set_sort_func(self._sort)
        self.list.set_header_func(self._header)
        self.list.connect("row-activated", self._on_row_activated)

        self.show_rows = {}
        for order, (kind, title, subtitle, icon) in enumerate(SHOWS):
            row = ShowRow(kind, title, subtitle, icon, order)
            self.show_rows[kind] = row
            self.list.append(row)

        self.new_group_row = NewGroupRow()
        self.list.append(self.new_group_row)

        self.empty_row = Gtk.ListBoxRow(activatable=False, selectable=False)
        self.empty_row.sort_key = lambda: (3, "")
        hint = Gtk.Label(
            label="Searching your network…\n\nMake sure LAN Control is switched on for each light "
                  "in the Govee Home phone app.",
            wrap=True, xalign=0, margin_top=12, margin_start=12, margin_end=12)
        hint.add_css_class("dim-label")
        hint.add_css_class("caption")
        self.empty_row.set_child(hint)
        self.list.append(self.empty_row)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self.list)
        view.set_content(scroller)
        page.set_child(view)
        return page

    # list helpers ---------------------------------------------------------------
    def _sort(self, a, b) -> int:
        ra, rb = a.sort_key(), b.sort_key()
        return (ra > rb) - (ra < rb)

    def _header(self, row, before):
        section = row.sort_key()[0]
        prev = before.sort_key()[0] if before is not None else None
        title = SECTION_TITLES.get(section)
        if title and section != prev:
            label = Gtk.Label(label=title, xalign=0, margin_top=14, margin_start=12, margin_bottom=4)
            label.add_css_class("heading")
            label.add_css_class("dim-label")
            row.set_header(label)
        else:
            row.set_header(None)

    def _add_device_row(self, device: Device) -> None:
        if device.id in self._device_rows:
            return
        row = DeviceRow(device, self.manager)
        self._device_rows[device.id] = row
        self.list.append(row)

    def _sync_group_rows(self) -> None:
        wanted = {ALL_LIGHTS: None}
        wanted.update({g["id"]: g for g in self.manager.groups()})
        for gid in list(self._group_rows):
            if gid not in wanted:
                row = self._group_rows.pop(gid)
                if self.list.get_selected_row() is row:
                    self._open(self.show_rows["sync"])
                self.list.remove(row)
                self._group_pages.pop(gid, None)
        for gid, group in wanted.items():
            row = self._group_rows.get(gid)
            if row is None:
                row = self._group_rows[gid] = GroupRow(group)
                self.list.append(row)
            elif group:
                row.title.set_label(group["name"])
            page = self._group_pages.get(gid)
            if page:
                page.refresh()
        self.list.invalidate_sort()
        self.list.invalidate_headers()

    def _update_empty(self) -> None:
        self.empty_row.set_visible(not self._device_rows)

    def refresh_rows(self) -> None:
        for row in self._device_rows.values():
            row.update()
        for kind, row in self.show_rows.items():
            running = self.app.engines[kind].running
            row.badge.set_visible(running)

    def _open(self, row):
        self.list.select_row(row)
        self._on_row_activated(self.list, row)

    def _on_row_activated(self, _list, row):
        if isinstance(row, ShowRow):
            self.split.set_content(self.show_pages[row.kind])
        elif isinstance(row, NewGroupRow):
            edit_group_dialog(self)
            return
        elif isinstance(row, GroupRow):
            page = self._group_pages.get(row.group_id)
            if page is None:
                group = None if row.group_id == ALL_LIGHTS else self.manager.group(row.group_id)
                page = self._group_pages[row.group_id] = GroupPage(self, group)
            page.refresh()
            self.split.set_content(page)
        elif isinstance(row, DeviceRow):
            page = self._device_pages.get(row.device.id)
            if page is None:
                page = self._device_pages[row.device.id] = DevicePage(self, row.device)
            self.split.set_content(page)
        self.split.set_show_content(True)

    def open_group(self, group_id: str) -> None:
        self._sync_group_rows()
        row = self._group_rows.get(group_id)
        if row:
            self._open(row)

    def open_show(self, kind: str) -> None:
        self._open(self.show_rows[kind])

    # events ------------------------------------------------------------------------
    def _on_manager_event(self, event, device, message):
        GLib.idle_add(self._handle_event, event, device, message)

    def _handle_event(self, event, device, message):
        if event == "added":
            self._add_device_row(device)
            for page in self.show_pages.values():
                page.add_device(device)
            self._update_empty()
            self._refresh_groups()
        elif event == "updated" and device:
            row = self._device_rows.get(device.id)
            if row:
                row.update()
                row.changed()
            else:
                self._add_device_row(device)
            page = self._device_pages.get(device.id)
            if page:
                page.refresh()
            for page in self.show_pages.values():
                page.add_device(device)
            self._refresh_groups()
        elif event == "removed" and device:
            row = self._device_rows.pop(device.id, None)
            if row:
                if self.list.get_selected_row() is row:
                    self._open(self.show_rows["sync"])
                self.list.remove(row)
            self._device_pages.pop(device.id, None)
            for page in self.show_pages.values():
                page.remove_device(device)
            self._update_empty()
        elif event == "groups":
            self._sync_group_rows()
        elif event == "error" and message:
            self.toast(message)
        return GLib.SOURCE_REMOVE

    def _refresh_groups(self):
        current = self.split.get_content()
        if isinstance(current, GroupPage):
            current.refresh()

    def device_settings_changed(self, device: Device):
        for page in self.show_pages.values():
            page.device_settings_changed(device)
        for engine in self.app.engines.values():
            engine.reload()

    def toast(self, message: str) -> None:
        last, when = self._last_toast
        now = time.monotonic()
        if message == last and now - when < 15:
            return
        self._last_toast = (message, now)
        self.toasts.add_toast(Adw.Toast.new(message))

    def forget_device(self, device: Device) -> None:
        self.manager.forget(device)

    def _on_close(self, *_):
        if self.app.keep_in_background():
            self.set_visible(False)
            return True
        self.manager.unsubscribe(self._on_manager_event)
        return False
