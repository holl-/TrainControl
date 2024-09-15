"""
Requires VR-Park controllers to be in mode C.

Cross-platform unlike winusb. Both can read messages from VR-Park controllers in mode C.
"""
import time
from functools import partial
from threading import Thread
from typing import List, Dict, Optional, Set

import pywinusb.hid as hid

from fpme.terminus import Terminus
from fpme.train_control import TrainControl


class InputManager:

    def __init__(self, control: Optional[TrainControl]):
        self.control = control
        self.terminus = None
        self.connected: Dict[str, Optional[hid.HidDevice]] = {}
        self.disconnected: Set[str] = set()
        self.last_events: Dict[str, Tuple[float, str]] = {}  # (time, text)

    def set_terminus(self, terminus: Terminus):
        self.terminus = terminus

    def check_for_new_devices(self, vid=0x05AC, pid=0x022C):  # 1452, 556
        devices = hid.find_all_hid_devices()
        controllers = {dev.device_path: dev for dev in devices if dev.product_name == "@input.inf,%hid_device_system_game%;HID-compliant game controller"}
        # --- Remove disconnected controllers ---
        for path in tuple(self.connected):
            if path not in controllers:
                del self.connected[path]
                self.disconnected.add(path)
        # --- Add new controllers ---
        for device in [dev for path, dev in controllers.items() if path not in self.connected]:
            try:
                device.open()
                print(f"Opened new controller: {device.device_path}")
                if device.device_path not in CONTROLS:
                    print("This controller has not been assigned to any train! Copy the following Python path")
                    print("'" + device.device_path.replace("\\", "\\\\") + "'")
                device.set_raw_data_handler(partial(self.process_event, device_path=device.device_path))
                if device.device_path in self.disconnected:
                    self.disconnected.remove(device.device_path)
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
        # data is always [4, 127, 127, 127, 128, button_id, 0, hat, 0]
        train = CONTROLS.get(device_path)
        if self.control is None or train is None:
            self.last_events[device_path] = (time.perf_counter(), str(data))
            return
        _, _, _, _, _, pressed, _, hat, _ = data
        hat_pos = VECTOR[hat]
        self.control.set_acceleration_control(train, 'VR-Park', hat_pos[1], cause=device_path)
        if pressed == 16:  # Button A / Trigger 2
            self.control.emergency_stop(train, cause=device_path)
            event_text = "A (stop)"
        elif pressed == 1:  # Button B / Trigger 1
            self.control.reverse(train, cause=device_path)
            event_text = "B (reverse)"
        elif pressed == 8:  # Button C
            if self.terminus:
                self.terminus.request_entry(train)
                # self.control.emergency_stop_all(train, cause=device_path)
            event_text = "C (terminus)"
        elif pressed == 2:  # Button D
            # ToDo or switch on light/sound
            self.control.power_on(None, cause=device_path)
            event_text = "D (Power)"
        else:
            event_text = str(hat_pos)
        self.last_events[device_path] = (time.perf_counter(), event_text)


VECTOR = {
    0: (0, 0),
    7: (0, 1),
    3: (0, -1),
    1: (1, 0),
    5: (-1, 0),
    8: (1, 1),
    2: (1, -1),
    4: (-1, -1),
    6: (-1, 1),
}


from fpme.train_def import *
CONTROLS = {
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_e0eebb488ace&col04#b&316fd37&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': ROT_218,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_fdc80171a4bd&col04#b&2a97252d&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': ICE,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_1e89fff2c7db&col04#b&20fc5261&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': BUS,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_588ea725c7a3&col04#b&13df0efa&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': BEIGE_218,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_45ee447eb09a&col04#b&20a8da1a&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': DIESEL,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_3675eb0ae2f9&col04#b&29342c48&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': S,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_8fd1f0ddfca6&col04#b&2671a960&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': E_RB,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_61f5dd3d7341&col04#b&2c7afc78&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': E40_RE_BLAU,
    '\\\\?\\hid#{00001812-0000-1000-8000-00805f9b34fb}_dev_vid&0205ac_pid&022c_rev&011b_9b64950eee81&col04#b&1cbc610d&0&0003#{4d1e55b2-f16f-11cf-88cb-001111000030}': E_BW_IC,
}

if __name__ == '__main__':
    inputs = InputManager(None)
    inputs.start_detection()