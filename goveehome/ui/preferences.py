from __future__ import annotations

import ipaddress
import threading

from gi.repository import Adw, GLib, Gtk

from goveehome.protocol import ble
from goveehome.protocol.cloud import CloudError


class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, window):
        super().__init__(transient_for=window, modal=True, search_enabled=False)
        self.set_default_size(620, 640)
        self.app = window.app
        self.config = self.app.config
        self.manager = self.app.manager

        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        page.add(self._background_group())
        page.add(self._power_group())
        page.add(self._cloud_group())
        page.add(self._lan_group())
        page.add(self._ble_group())
        self.add(page)

    def _switch(self, group, section, key, title, subtitle=None, on_change=None):
        row = Adw.SwitchRow(title=title, subtitle=subtitle,
                            active=bool(self.config.section(section).get(key)))

        def changed(r, _p):
            self.config.set_in(section, key, r.get_active())
            if on_change:
                on_change(r.get_active())
        row.connect("notify::active", changed)
        group.add(row)
        return row

    def _background_group(self):
        group = Adw.PreferencesGroup(title="Running in the background")
        self._switch(group, "background", "keep_running", "Keep light shows running when the window is closed",
                     "Open GoveeHome again to get the window back")
        self._switch(group, "background", "autostart", "Start at login",
                     "Starts without a window", on_change=self.app.set_autostart)
        self._switch(group, "background", "resume_show", "Continue the last light show on start")
        return group

    def _power_group(self):
        group = Adw.PreferencesGroup(title="Follow the computer")
        self._switch(group, "power", "off_on_sleep", "Turn lights off when the computer sleeps or shuts down")
        self._switch(group, "power", "on_on_wake", "Turn them back on when it wakes up",
                     "Also resumes a light show that was running")
        return group

    def _cloud_group(self):
        group = Adw.PreferencesGroup(
            title="Govee account",
            description="Optional. An API key adds lights that have no LAN control, your own "
                        "light names and scenes. Request one in the Govee Home phone app under "
                        "Profile → Settings → Apply for API Key; it arrives by e-mail.")
        self.key_row = Adw.PasswordEntryRow(title="API key", show_apply_button=True)
        self.key_row.set_text(self.config.get("cloud_api_key", ""))
        self.key_row.connect("apply", self._apply_key)
        group.add(self.key_row)
        return group

    def _lan_group(self):
        group = Adw.PreferencesGroup(
            title="Local network",
            description="Lights are found automatically. If your router blocks multicast, list "
                        "their IP addresses here.")
        self.hosts_row = Adw.EntryRow(title="Extra addresses, comma separated", show_apply_button=True)
        self.hosts_row.set_text(", ".join(self.config.get("extra_hosts", [])))
        self.hosts_row.connect("apply", self._apply_hosts)
        group.add(self.hosts_row)

        rescan = Adw.SpinRow.new_with_range(0, 600, 5)
        rescan.set_title("Search again every")
        rescan.set_subtitle("Seconds, 0 turns it off. Applies after a restart.")
        rescan.set_value(int(self.config.get("rescan_interval", 30)))
        rescan.connect("notify::value", lambda r, _p: self.config.set("rescan_interval", int(r.get_value())))
        group.add(rescan)

        if self.manager.lan.error:
            warn = Adw.ActionRow(title="LAN control is not working", subtitle=self.manager.lan.error)
            warn.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic"))
            group.add(warn)
        return group

    def _ble_group(self):
        has_bleak = ble.available()
        group = Adw.PreferencesGroup(
            title="Bluetooth",
            description=None if has_bleak else "Install the python3-bleak package to use Bluetooth lights.")
        row = Adw.SwitchRow(title="Look for Bluetooth lights", active=bool(self.config.get("bluetooth")),
                            sensitive=has_bleak)
        row.connect("notify::active", self._toggle_ble)
        group.add(row)

        scan = Adw.ActionRow(title="Scan now", subtitle="Takes a few seconds")
        self.scan_button = Gtk.Button(label="Scan", valign=Gtk.Align.CENTER, sensitive=has_bleak)
        self.scan_button.add_css_class("flat")
        self.scan_button.connect("clicked", self._scan_ble)
        scan.add_suffix(self.scan_button)
        group.add(scan)
        return group

    # handlers -----------------------------------------------------------------
    def _apply_key(self, row):
        key = row.get_text().strip()
        if not key:
            self.manager.set_api_key("")
            self.add_toast(Adw.Toast.new("API key removed"))
            return
        row.set_sensitive(False)

        def work():
            try:
                count = self.manager.test_api_key(key)
                GLib.idle_add(done, None, count)
            except CloudError as exc:
                GLib.idle_add(done, str(exc), 0)

        def done(error, count):
            row.set_sensitive(True)
            if error:
                self.add_toast(Adw.Toast.new(error))
            else:
                self.manager.set_api_key(key)
                self.manager.discover()
                self.add_toast(Adw.Toast.new(f"Key accepted, {count} device(s) on the account"))
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, daemon=True).start()

    def _apply_hosts(self, row):
        hosts, bad = [], []
        for part in row.get_text().replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ipaddress.IPv4Address(part)
                hosts.append(part)
            except ValueError:
                bad.append(part)
        if bad:
            self.add_toast(Adw.Toast.new(f"Not an IPv4 address: {', '.join(bad)}"))
            return
        self.config.set("extra_hosts", hosts)
        self.manager.discover()
        self.add_toast(Adw.Toast.new("Saved"))

    def _toggle_ble(self, row, _pspec):
        self.config.set("bluetooth", row.get_active())
        if row.get_active() and not self.manager.ble.start():
            self.add_toast(Adw.Toast.new("Bluetooth support is not available"))

    def _scan_ble(self, button):
        button.set_sensitive(False)
        button.set_label("Scanning…")

        def work():
            try:
                self.manager.ble.start()
                self.manager._discover_ble()
            finally:
                GLib.idle_add(finish)

        def finish():
            button.set_sensitive(True)
            button.set_label("Scan")
            return GLib.SOURCE_REMOVE

        threading.Thread(target=work, daemon=True).start()
