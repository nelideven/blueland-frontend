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

        self.known_macs = set()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(box)

        self.device_list = Gtk.ListBox()
        box.append(self.device_list)

        refresh_btn = Gtk.Button(label="Discover Devices")
        refresh_btn.connect("clicked", self.refresh_devices)
        box.append(refresh_btn)

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
        # Clear existing list for a fresh scan
        self.device_list.remove_all()
        self.known_macs.clear()

        # Trigger scanning without blocking GTK
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
        label = Gtk.Label(label=name)
        row = Gtk.ListBoxRow()
        row.set_child(label)
        self.device_list.append(row)

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