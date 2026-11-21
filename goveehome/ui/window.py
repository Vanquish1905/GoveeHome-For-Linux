from __future__ import annotations

import time

from gi.repository import Adw, Gio, GLib, Gtk

from goveehome import APP_NAME
from goveehome.models import Device
from goveehome.ui.device_page import DevicePage
from goveehome.ui.sync_page import SyncPage
from goveehome.ui.widgets import ColorDot, color_for_state


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, title: str, subtitle: str = "", icon: str | None = None):
        super().__init__()
        box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        if icon:
            self.lead = Gtk.Image(icon_name=icon)
        else:
            self.lead = ColorDot(12)
        box.append(self.lead)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(label=title, xalign=0, ellipsize=3)
        self.subtitle = Gtk.Label(label=subtitle, xalign=0, ellipsize=3)
        self.subtitle.add_css_class("caption")
        self.subtitle.add_css_class("dim-label")
        self.subtitle.set_visible(bool(subtitle))
        text.append(self.title)
        text.append(self.subtitle)
        box.append(text)
        self.set_child(box)


class DeviceRow(SidebarRow):
    def __init__(self, device: Device, manager):
        super().__init__(device.display_name)
        self.device = device
        self.manager = manager
        self.update()

    def update(self):
        d = self.device
        self.title.set_label(d.display_name)
        parts = []
        if d.sku:
            parts.append(d.sku)
        if d.id in self.manager.streaming_devices:
            parts.append("syncing")
        elif d.state.on is False:
            parts.append("off")
        if not d.transports:
            parts.append("offline")
        elif d.preferred_transport:
            parts.append(d.preferred_transport.label)
        self.subtitle.set_label(" · ".join(parts))
        self.subtitle.set_visible(bool(parts))
        self.lead.set_rgb(color_for_state(d.state))


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.manager = app.manager
        self.set_default_size(1000, 720)
        self.set_size_request(360, 480)
        self._device_rows: dict[str, DeviceRow] = {}
        self._pages: dict[str, DevicePage] = {}
        self._last_toast: tuple[str, float] = ("", 0.0)

        self.toasts = Adw.ToastOverlay()
        self.split = Adw.NavigationSplitView(min_sidebar_width=240, max_sidebar_width=300)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)

        self.sync_page = SyncPage(self)
        self.split.set_sidebar(self._build_sidebar())
        self.split.set_content(self.sync_page)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        for device in self.manager.list():
            self._add_row(device)
        self._update_empty()
        self.list.select_row(self.sync_row)

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
        section.append("Add Light by Address…", "app.add-host")
        section.append("Preferences", "app.preferences")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Keyboard Shortcuts", "win.show-help-overlay")
        section.append(f"About {APP_NAME}", "app.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Main menu", primary=True))
        view.add_top_bar(header)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.set_sort_func(self._sort)
        self.list.set_header_func(self._header)
        self.list.connect("row-activated", self._on_row_activated)

        self.sync_row = SidebarRow("Screen sync", "Lights follow your screen", icon="video-display-symbolic")
        self.list.append(self.sync_row)

        self.empty_row = Gtk.ListBoxRow(activatable=False, selectable=False)
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

    # list helpers -----------------------------------------------------------
    def _rank(self, row) -> tuple:
        if row is self.sync_row:
            return (0, "")
        if row is self.empty_row:
            return (2, "")
        return (1, row.device.display_name.lower())

    def _sort(self, a, b) -> int:
        ra, rb = self._rank(a), self._rank(b)
        return (ra > rb) - (ra < rb)

    def _header(self, row, before):
        if before is self.sync_row and row is not self.sync_row:
            label = Gtk.Label(label="Lights", xalign=0, margin_top=12, margin_start=12, margin_bottom=4)
            label.add_css_class("heading")
            label.add_css_class("dim-label")
            row.set_header(label)
        else:
            row.set_header(None)

    def _add_row(self, device: Device) -> None:
        if device.id in self._device_rows:
            return
        row = DeviceRow(device, self.manager)
        self._device_rows[device.id] = row
        self.list.append(row)

    def _update_empty(self) -> None:
        self.empty_row.set_visible(not self._device_rows)

    def refresh_rows(self) -> None:
        for row in self._device_rows.values():
            row.update()

    def _on_row_activated(self, _list, row):
        if row is self.sync_row:
            self.split.set_content(self.sync_page)
        elif isinstance(row, DeviceRow):
            page = self._pages.get(row.device.id)
            if page is None:
                page = self._pages[row.device.id] = DevicePage(self, row.device)
            self.split.set_content(page)
        self.split.set_show_content(True)

    # manager events ------------------------------------------------------------
    def _on_manager_event(self, event, device, message):
        GLib.idle_add(self._handle_event, event, device, message)

    def _handle_event(self, event, device, message):
        if event == "added":
            self._add_row(device)
            self.sync_page.add_device(device)
            self._update_empty()
        elif event == "updated" and device:
            row = self._device_rows.get(device.id)
            if row:
                row.update()
                row.changed()
            else:
                self._add_row(device)
            page = self._pages.get(device.id)
            if page:
                page.refresh()
            self.sync_page.add_device(device)
        elif event == "removed" and device:
            row = self._device_rows.pop(device.id, None)
            if row:
                if self.list.get_selected_row() is row:
                    self.list.select_row(self.sync_row)
                    self.split.set_content(self.sync_page)
                self.list.remove(row)
            self._pages.pop(device.id, None)
            self.sync_page.remove_device(device)
            self._update_empty()
        elif event == "error" and message:
            self.toast(message)
        return GLib.SOURCE_REMOVE

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
        self.manager.unsubscribe(self._on_manager_event)
        return False
