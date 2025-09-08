#!/usr/bin/env python3

import os
import socket
import json
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gio", "2.0")
from gi.repository import Gtk, GLib, Gio

SOCKET_PATH = f"/run/user/{os.getuid()}/blueland/blueland.sock"

class BluelandUI(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Blueland Control Panel")
        self.set_default_size(500, 400)
        self.connected = set()
        self.known_macs = set()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(box)

        # FlowBox for device buttons instead of ListBox
        self.device_grid = Gtk.FlowBox()
        self.device_grid.set_valign(Gtk.Align.START)
        box.append(self.device_grid)

        refresh_btn = Gtk.Button(label="Discover Devices")
        refresh_btn.connect("clicked", self.refresh_devices)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        action_box.set_halign(Gtk.Align.CENTER)  # Center horizontally
        action_box.set_valign(Gtk.Align.END)     # Stick to bottom
        action_box.append(refresh_btn)
        box.append(action_box)

        self.frontend = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.blueland.Frontend",
            "/org/blueland/Frontend",
            "org.blueland.Frontend",
            None
        )

        self.refresh_devices()
        self.start_socket_listener()

    def refresh_devices(self, *_):
        oldchild = self.device_grid.get_first_child()
        child = oldchild
        while child:
            self.device_grid.remove(child)
            child = self.device_grid.get_first_child()
        self.known_macs.clear()

        self.frontend.call(
            "DiscoverDevices",
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            self._on_discover_finished,
            None
        )

    def _on_discover_finished(self, proxy, result, user_data):
        try:
            proxy.call_finish(result)
            print("Discovery finished.")
        except Exception as e:
            print(f"D-Bus async error: {e}")

    def add_device(self, msg):
        mac = msg.get('mac')
        if not mac or mac in self.known_macs:
            return  # Skip duplicates

        self.known_macs.add(mac)
        name = msg.get('name', f"Device ({mac})")

        # Create visual button
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name("bluetooth")
        icon.set_pixel_size(32)  # or 48 for larger buttons
        label = Gtk.Label(label=name)
        box.append(icon)
        box.append(label)

        btn = Gtk.Button()
        btn.set_child(box)
        btn.connect("clicked", lambda *_: self.show_device_popup(mac, name))

        if name.lower() == "unknown":
            return  # Skip unknown devices
        self.device_grid.append(btn)

    def show_device_popup(self, mac, name):
        dialog = Gtk.Dialog(title=f"{name} Options", transient_for=self, modal=True)
        dialog.set_default_size(300, 150)
        content_area = dialog.get_content_area()

        # Get live device state first
        def _on_device_state_ready(proxy, result, user_data):
            state = proxy.call_finish(result).unpack()[0]
            connected = state.get("Connected", False)

            # Info label
            info_label = Gtk.Label(label=f"MAC: {mac}\nDevice: {name}")
            content_area.append(info_label)

            # Connect/Disconnect logic
            if connected:
                connect_btn = Gtk.Button(label="Disconnect")
                connect_btn.set_tooltip_text("Disconnect from this device")
                connect_btn.connect("clicked", lambda *_: self.frontend.call(
                    "DisconnectDevice",
                    GLib.Variant('(s)', (mac,)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                    self._on_connect_finished,
                    None
                ))
            else:
                connect_btn = Gtk.Button(label="Connect")
                connect_btn.set_tooltip_text("Connect to this device")
                connect_btn.connect("clicked", lambda *_: self.frontend.call(
                    "PairConnDevice",
                    GLib.Variant('(s)', (mac,)),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                    self._on_connect_finished,
                    None
                ))

            cancel_btn = Gtk.Button(label="Cancel")
            cancel_btn.connect("clicked", lambda *_: dialog.close())

            # Actions
            action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            action_box.set_halign(Gtk.Align.CENTER)
            action_box.set_valign(Gtk.Align.END)
            action_box.append(connect_btn)
            action_box.append(cancel_btn)
            content_area.append(action_box)

            dialog.present()

        self.frontend.call(
            "DeviceState",
            GLib.Variant('(s)', (mac,)),
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            _on_device_state_ready,
            None
        )

    def _on_connect_finished(self, proxy, result, user_data):
        try:
            reply = proxy.call_finish(result)
            print("Connection successful:", reply.print_(True))
            # Optionally show success banner or update button
        except Exception as e:
            print(f"Connect failed: {e}")
            # Optionally show error dialog or toast

    def start_socket_listener(self):
        def listen():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(SOCKET_PATH)
                while True:
                    data = sock.recv(4096)
                    if not data:
                        break
                    for line in data.decode().splitlines():
                        try:
                            msg = json.loads(line)
                            GLib.idle_add(self.add_device, msg)
                            print("Device added:", msg)
                        except Exception as e:
                            print(f"Socket parse error: {e}")
            except Exception as e:
                print(f"Socket connection error: {e}")

        threading.Thread(target=listen, daemon=True).start()

def main():
    app = Gtk.Application()
    app.connect("activate", lambda a: BluelandUI(app).present())
    app.run([])

if __name__ == "__main__":
    main()