#!/usr/bin/env python3
import os, socket, json, threading
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

        # Layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_child(box)

        self.device_grid = Gtk.FlowBox(valign=Gtk.Align.START)
        box.append(self.device_grid)

        refresh_btn = Gtk.Button(label="Discover Devices")
        refresh_btn.connect("clicked", self.refresh_devices)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        action_box.append(refresh_btn)
        box.append(action_box)

        # DBus proxy
        self.frontend = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.blueland.Agent",
            "/org/blueland/Agent",
            "org.blueland.Agent",
            None
        )

        self.refresh_devices()
        self.start_socket_listener()

    # --- Helpers ---
    def _show_dialog(self, title, message):
        dialog = Gtk.Dialog(title=title, transient_for=self, modal=True)
        label = Gtk.Label(label=message)
        dialog.get_content_area().append(label)
        dialog.present()

    def refresh_devices(self, *_):
        self.device_grid.remove_all()
        self.known_macs.clear()
        self.frontend.call(
            "DiscoverDevices", None,
            Gio.DBusCallFlags.NONE, -1, None,
            self._on_discover_finished, None
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
            return
        self.known_macs.add(mac)
        name = msg.get('name', f"Device ({mac})")
        if name.lower() == "unknown":
            return

        # Icon mapping
        icon_name = "bluetooth-active-symbolic"
        try:
            reply = self.frontend.call_sync(
                "DeviceState", GLib.Variant('(s)', (mac,)),
                Gio.DBusCallFlags.NONE, -1, None
            )
            state = reply.unpack()[0]
            if isinstance(state, dict) and "Icon" in state:
                icon_name = state["Icon"]
        except Exception:
            print("Failed to get device state for icon. Ignoring.")
            pass

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(32)
        label = Gtk.Label(label=name)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(icon)
        box.append(label)

        btn = Gtk.Button()
        btn.set_child(box)
        btn.connect("clicked", lambda *_: self.show_device_popup(mac, name))
        self.device_grid.append(btn)

    def show_device_popup(self, mac, name):
        dialog = Gtk.Dialog(title=f"{name} Options", transient_for=self, modal=True)
        dialog.set_default_size(300, 150)
        content_area = dialog.get_content_area()

        def _on_device_state_ready(proxy, result, user_data):
            try:
                reply = proxy.call_finish(result)
                state = reply.unpack()[0] if isinstance(reply.unpack()[0], dict) else {}
            except Exception as e:
                self._show_dialog("Error", f"DeviceState failed: {e}")
                return

            connected = state.get("Connected", False)
            paired = state.get("Paired", False)

            info_label = Gtk.Label(label=f"MAC: {mac}\nDevice: {name}")
            content_area.append(info_label)

            # Buttons
            connect_btn = Gtk.Button(label="Disconnect" if connected else "Connect")
            connect_btn.connect("clicked", lambda *_: self.frontend.call(
                "DisconnectDevice" if connected else "PairConnDevice",
                GLib.Variant('(s)', (mac,)),
                Gio.DBusCallFlags.NONE, -1, None,
                self._on_connect_finished, None
            ))

            info_btn = Gtk.Button(label="Information")
            info_btn.connect("clicked", lambda *_: self.frontend.call(
                "DeviceState", GLib.Variant('(s)', (mac,)),
                Gio.DBusCallFlags.NONE, -1, None,
                self._on_devstate_finished, None
            ))

            cancel_btn = Gtk.Button(label="Cancel")
            cancel_btn.connect("clicked", lambda *_: dialog.close())

            action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                                 halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
            action_box.append(connect_btn)
            if paired:
                forget_btn = Gtk.Button(label="Forget")
                forget_btn.connect("clicked", lambda *_: self.frontend.call(
                    "RemoveDevice", GLib.Variant('(s)', (mac,)),
                    Gio.DBusCallFlags.NONE, -1, None,
                    self._on_forget_finished, None
                ))
                action_box.append(forget_btn)
            action_box.append(info_btn)
            action_box.append(cancel_btn)
            content_area.append(action_box)

            dialog.present()

        self.frontend.call(
            "DeviceState", GLib.Variant('(s)', (mac,)),
            Gio.DBusCallFlags.NONE, -1, None,
            _on_device_state_ready, None
        )

    def _on_connect_finished(self, proxy, result, user_data):
        try:
            reply = proxy.call_finish(result)
            self._show_dialog("Connection Status", reply.unpack()[0])
        except Exception as e:
            print(f"Error: {e}")
            self._show_dialog("Connection Status", f"Error: {e}")

    def _on_forget_finished(self, proxy, result, user_data):
        try:
            reply = proxy.call_finish(result)
            self._show_dialog("Forget Device Status", reply.unpack()[0])
        except Exception as e:
            print(f"Error: {e}")
            self._show_dialog("Forget Device Status", f"Error: {e}")

    def _on_devstate_finished(self, proxy, result, user_data):
        try:
            reply = proxy.call_finish(result)
            state = reply.unpack()[0]
            self._show_dialog("Device Information", json.dumps(state, indent=4))
        except Exception as e:
            print(f"Error: {e}")
            self._show_dialog("Device Information", f"Error: {e}")

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