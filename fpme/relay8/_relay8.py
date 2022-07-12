""" Adapted from https://github.com/pavel-a/usb-relay-hid/blob/master/Test/test2m.py

"""
from ctypes import CDLL, sizeof, c_void_p, c_char_p, string_at, c_int
import os
from threading import Timer


if sizeof(c_void_p) == 8:
    directory = os.path.join(os.path.dirname(__file__), "usb_relay_device_lib_devel", "Win64")
else:
    directory = os.path.join(os.path.dirname(__file__), "usb_relay_device_lib_devel", "Win32")
NATIVE = CDLL(os.path.join(directory, "USB_RELAY_DEVICE.dll"))
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


# print(f"USB Relay library version: {DLL.usb_relay_device_lib_version()}")
assert NATIVE.usb_relay_init() == 0, "Failed to initialize USB Relay"


def list_devices():
    names = []
    enum_info = NATIVE.usb_relay_device_enumerate()
    while enum_info:
        name = str(string_at(NATIVE.usb_relay_device_get_id_string(enum_info)), 'ascii')
        assert len(name) == 5
        enum_info = NATIVE.usb_relay_device_next_dev(enum_info)
        names.append(name)
    return names


DEVICES = list_devices()
assert DEVICES, "No USB Relay connected"
DEVICE_HANDLE = NATIVE.usb_relay_device_open_with_serial_number(bytes(DEVICES[0], "ascii"), 5)
assert DEVICE_HANDLE, "Failed to open device"
# num_channels = DLL.usb_relay_device_get_num_relays(DEVICE_HANDLE)

NATIVE.usb_relay_device_close_all_relay_channel(DEVICE_HANDLE)


def pulse(channel: int, duration=0.2):
    """
    Args:
        channel: Between 1 and 8
        duration: How long the on state should persist (in seconds)
    """
    status = NATIVE.usb_relay_device_open_one_relay_channel(DEVICE_HANDLE, channel)
    Timer(duration, lambda: NATIVE.usb_relay_device_close_one_relay_channel(DEVICE_HANDLE, channel)).start()
    return status == 0


def destroy():
    NATIVE.usb_relay_device_close(DEVICE_HANDLE)
    NATIVE.usb_relay_exit()
