import time
from threading import Thread
from typing import Dict, Optional, Tuple

from .relay8 import list_devices, open_device, Relay8


RELAY_CHANNEL_BY_SWITCH_STATE = {
    1: {False: 1, True: 2},
    2: {False: 3, True: 4},
    3: {False: 8, True: 7},
}


class SwitchManager:

    def __init__(self):
        self._error = ""
        self._device: Optional[Relay8] = None
        self._states: Dict[int, bool] = {}  # switch -> curved
        Thread(target=self._connect_continuously).start()

    def get_devices(self) -> Tuple[str]:
        return 'Relay8',

    def get_error(self, device):
        return self._error

    def _connect_continuously(self):
        while self._device is None:
            try:
                devices = list_devices()
                if len(devices) == 0:
                    self._error = "No USB Relay found"
                elif len(devices) > 1:
                    self._error = f"Multiple USB relays found: {devices}"
                else:
                    self._device = open_device(devices[0])
                    self._error = ""
            except Exception as exc:
                self._error = str(exc)
            time.sleep(2.)

    def _operate_switch(self, switch: int, curved: bool):
        """ Sends a signal to the specified track switch. """
        self._states[switch] = curved
        try:
            channel = RELAY_CHANNEL_BY_SWITCH_STATE[switch][curved]
            if not self._device.pulse(channel):
                print(f"Failed to operate switch {switch} to state curved={curved}")
        except BaseException as exc:
            print(f"Failed to operate switch {switch}: {exc}")
