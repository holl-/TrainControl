""" Adapted from https://github.com/pavel-a/usb-relay-hid/blob/master/Test/test2m.py

"""
import platform
from ctypes import CDLL, sizeof, c_void_p, c_char_p, string_at, c_int
import os
from threading import Timer
from typing import Sequence

if platform.system() == 'Linux':
    assert sizeof(c_void_p) == 8, "Only Linux 64 bit supported"
    bin_path = os.path.join(os.path.dirname(__file__), "usb_relay_device_lib_devel", "Linux64", "usb_relay_device.so")
else:  # Windows
    if sizeof(c_void_p) == 8:
        bin_path = os.path.join(os.path.dirname(__file__), "usb_relay_device_lib_devel", "Win64", "USB_RELAY_DEVICE.dll")
    else:
        bin_path = os.path.join(os.path.dirname(__file__), "usb_relay_device_lib_devel", "Win32", "USB_RELAY_DEVICE.dll")
NATIVE = CDLL(bin_path)
for fun_name, result_type, arg_types in [
    ("usb_relay_device_enumerate", c_void_p, []),
    ("usb_relay_device_close", c_int, [c_void_p]),
    ("usb_relay_device_open_with_serial_number", c_void_p, [c_char_p, c_int]),
    ("usb_relay_device_get_num_relays", c_int, [c_void_p]),
    ("usb_relay_device_get_id_string", c_char_p, [c_void_p]),
    ("usb_relay_device_next_dev", c_void_p, [c_void_p]),
    ("usb_relay_device_get_status_bitmap", c_int, [c_void_p]),
    ("usb_relay_device_open_one_relay_channel", c_int, [c_void_p, c_int]),
    ("usb_relay_device_close_one_relay_channel", c_int, [c_void_p, c_int]),
    ("usb_relay_device_close_all_relay_channel", c_int, [c_void_p])
]:
    fun = getattr(NATIVE, fun_name)
    fun.restype = result_type
    fun.argtypes = arg_types


_INIT = False
# print(f"USB Relay library version: {DLL.usb_relay_device_lib_version()}")


class Relay8:

    def __init__(self, name, handle):
        self.name = name
        self.handle = handle

    def close(self):
        if self.handle:
            NATIVE.usb_relay_device_close(self.handle)

    def open_channel(self, channel):
        assert NATIVE.usb_relay_device_open_one_relay_channel(self.handle, channel) == 0

    def close_channel(self, channel):
        assert NATIVE.usb_relay_device_close_one_relay_channel(self.handle, channel) == 0

    def close_all_channels(self):
        NATIVE.usb_relay_device_close_all_relay_channel(self.handle)

    def pulse(self, channel: int, duration=0.2):
        """
        Args:
            channel: Between 1 and 8
            duration: How long the on state should persist (in seconds)
        """
        assert self.handle
        self.open_channel(channel)
        Timer(duration, lambda: self.close_channel(channel)).start()

    @property
    def num_channels(self):
        return NATIVE.usb_relay_device_get_num_relays(self.handle)


def list_devices() -> Sequence[str]:
    global _INIT
    if not _INIT:
        assert NATIVE.usb_relay_init() == 0, "Failed to initialize USB Relay"
        _INIT = True
    names = []
    enum_info = NATIVE.usb_relay_device_enumerate()
    while enum_info:
        name = str(string_at(NATIVE.usb_relay_device_get_id_string(enum_info)), 'ascii')
        assert len(name) == 5
        enum_info = NATIVE.usb_relay_device_next_dev(enum_info)
        names.append(name)
    return names


def open_device(name: str) -> Relay8:
    handle = NATIVE.usb_relay_device_open_with_serial_number(bytes(name, "ascii"), 5)
    assert handle, "Failed to open device"
    return Relay8(name, handle)


def destroy():
    NATIVE.usb_relay_exit()


if __name__ == '__main__':
    devices = list_devices()
    print(f"Relays: {devices}")
    device = open_device(devices[0])
