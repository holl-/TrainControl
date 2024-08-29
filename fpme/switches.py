import random
import time
from threading import Thread
from typing import Dict, Optional, Tuple, Sequence

from .relay8 import list_devices, open_device, Relay8
from .signal_gen import SignalGenerator, SubprocessGenerator

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

    @property
    def is_connected(self):
        return self._device is not None

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

    def set_switches(self, state: Dict[int, bool], refresh=False):
        for switch, curved in state.items():
            needs_change = refresh or (self._states[switch] != curved if switch in self._states else True)
            if needs_change:
                self._operate_switch(switch, curved)


class StationSwitchesController:

    CONFIGS = {
        0: {1: False},
        1: {1: True, 2: True},
        2: {1: True, 2: False, 3: True},
        3: {1: True, 2: False, 3: False},
    }

    def __init__(self, switches: SwitchManager, generator: SubprocessGenerator, port: str, max_train_count: int):
        self.switches = switches
        self.generator = generator
        self.port = port
        self.max_train_count = max_train_count
        self.last_occupancy: tuple = (None, None, None)
        self.start_operation()

    @property
    def error(self):
        if not self.generator.is_open(self.port):
            return f"{self.port} is not open. Occupancy unknown."
        for device in self.switches.get_devices():
            error = self.switches.get_error(device)
            if error:
                return error
        return ''

    def start_operation(self):
        def loop():
            while True:
                time.sleep(1.)
                self.update_switches()
        Thread(target=loop).start()

    def update_switches(self):
        if not self.switches.is_connected:
            return
        if not self.generator.is_open(self.port):
            return
        state = tuple(self.generator.contact_status(self.port))
        assert len(state) == 3
        if state == self.last_occupancy:
            return  # switches already correct
        unaccounted = self.max_train_count - sum(state)
        state = [*state, unaccounted > 0]
        free = [i for i, s in enumerate(state) if not s]
        target_track = random.choice(free)
        config = StationSwitchesController.CONFIGS[target_track]
        self.last_occupancy = state
        self.switches.set_switches(config, refresh=True)
