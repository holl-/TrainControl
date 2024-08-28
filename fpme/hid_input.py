"""
Requires VR-Park controllers to be in mode C.

Cross-platform unlike winusb. Both can read messages from VR-Park controllers in mode C.
"""
import time
from functools import partial
from threading import Thread
from typing import List, Dict, Optional, Set

import pywinusb.hid as hid

from fpme.train_control import TrainControl


class InputManager:

    def __init__(self, control: Optional[TrainControl]):
        self.control = control
        self.connected: Dict[str, Optional[hid.HidDevice]] = {}
        self.disconnected: Set[str] = set()
        self.last_events: Dict[str, Tuple[float, str]] = {}  # (time, text)

    def check_for_new_devices(self, vid=0x05AC, pid=0x022C):  # 1452, 556
        print("Checking for controllers")
        devices = hid.find_all_hid_devices()
        controllers = {dev.device_path: dev for dev in devices if dev.product_name == "@input.inf,%hid_device_system_game%;HID-compliant game controller"}
        # --- Remove disconnected controllers ---
        for path in self.connected:
            if path not in controllers:
                del self.connected[path]
                self.disconnected.add(path)
        # --- Add new controllers ---
        for device in [dev for path, dev in controllers.items() if path not in self.connected]:
            try:
                device.open()
                print(f"Opened new controller: {device.device_path}")
                device.set_raw_data_handler(partial(self.process_event, device_path=device.device_path))
                self.last_events[device.device_path], self.connected[device.device_path] = (time.perf_counter(), 'connected'), device
            except OSError as e:
                print(f"Failed to open bluetooth controller: {e}")
                self.connected[device.device_path] = None

    def start_detection(self, interval_sec=1.):
        def detection_loop():
            while True:
                self.check_for_new_devices()
                time.sleep(interval_sec)
        Thread(target=detection_loop).start()

    def process_event(self, data: List, device_path: str):
        if self.control is None:
            self.last_events[device_path] = (time.perf_counter(), str(data))
            return
        train = CONTROLS[device_path]
        event_text = None
        hat_pos_x = data[5]
        hat_pos_y = data[6]
        self.control.set_acceleration_control(train, hat_pos_y, cause=device_path)
        # acc = 0 if event.delta_y == 0 else train.acceleration if event.delta_y < 0 else -train.deceleration
        # event_period = 0.03
        # target_speed = max(0, abs(control.get_speed(train) or 0.) + (event_period * 2.1) * acc)
        # control.set_target_speed(train, target_speed * (-1 if control.is_in_reverse(train) else 1), cause=event.device.path)
        if data:  # Button A
            self.control.reverse(train, cause=device_path)
            event_text = "A (reverse)"
        elif data:  # Button B
            self.control.emergency_stop_all(train, cause=device_path)
            event_text = "B (stop all)"
        elif data:  # Button C
            self.control.emergency_stop(train, cause=device_path)
            event_text = "C (stop)"
        elif data:  # Button D
            self.control.power_on(None, cause=device_path)
            event_text = "D (Power)"
        else:
            event_text = f"({hat_pos_x}, {hat_pos_y})"
        self.last_events[device_path] = (time.perf_counter(), event_text)


"""
A
Raw data: [4, 127, 127, 127, 128, 16, 0, 0, 0]
B
Raw data: [4, 127, 127, 127, 128, 1, 0, 0, 0]
C
Raw data: [4, 127, 127, 127, 128, 8, 0, 0, 0]
D
Raw data: [4, 127, 127, 127, 128, 2, 0, 0, 0]
Trigger 1
Raw data: [4, 127, 127, 127, 128, 1, 0, 0, 0]
Trigger 2
Raw data: [4, 127, 127, 127, 128, 16, 0, 0, 0]
Up
[4, 127, 127, 127, 128, 0, 0, 7, 0]
Down
[4, 127, 127, 127, 128, 0, 0, 3, 0]
Right
[4, 127, 127, 127, 128, 0, 0, 1, 0]
Left
[4, 127, 127, 127, 128, 0, 0, 5, 0]
UP right
[4, 127, 127, 127, 128, 0, 0, 8, 0]
Down right
[4, 127, 127, 127, 128, 0, 0, 2, 0]
Down left
[4, 127, 127, 127, 128, 0, 0, 4, 0]
Up left
[4, 127, 127, 127, 128, 0, 0, 6, 0]
Nothing
[4, 127, 127, 127, 128, 0, 0, 0, 0]
"""

from fpme.train_def import *
CONTROLS = {
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_fdc80171a4bd&Col01#b&2a97252d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': ICE,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_588ea725c7a3&Col01#b&13df0efa&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': BEIGE_218,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_45ee447eb09a&Col01#b&20a8da1a&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': DIESEL,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_e0eebb488ace&Col01#b&316fd37&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': ROT_218,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_1e89fff2c7db&Col01#b&20fc5261&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': BUS,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_3675eb0ae2f9&Col01#b&29342c48&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': S,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_8fd1f0ddfca6&Col01#b&2671a960&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': E_RB,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_61f5dd3d7341&Col01#b&2c7afc78&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': E40_RE_BLAU,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_9b64950eee81&Col01#b&1cbc610d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': E_BW_IC,
}

""" VR Park Controllers:
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_588ea725c7a3&Col01#b&13df0efa&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_9b64950eee81&Col01#b&1cbc610d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_e0eebb488ace&Col01#b&316fd37&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_1e89fff2c7db&Col01#b&20fc5261&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_45ee447eb09a&Col01#b&20a8da1a&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_61f5dd3d7341&Col01#b&2c7afc78&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_8fd1f0ddfca6&Col01#b&2671a960&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_3675eb0ae2f9&Col01#b&29342c48&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_fdc80171a4bd&Col01#b&2a97252d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
"""

if __name__ == '__main__':
    inputs = InputManager(None)
    inputs.start_detection()