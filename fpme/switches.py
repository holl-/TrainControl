import random
import time
from threading import Thread
from typing import Dict, Optional, Tuple, Sequence

from .relay8 import list_devices, open_device, Relay8, RelayManager
from .signal_gen import SignalGenerator, SubprocessGenerator
from .train_def import Train


SWITCH_POWER_CHANNEL = 1
RELAY_STATE_BY_SWITCH_STATE = {
    (1, True): (2, 'open'),
    (1, False): (2, 'closed'),
    (2, True): (3, 'open'),
    (2, False): (3, 'closed'),
    (3, True): (4, 'open'),
    (3, False): (4, 'closed'),
    (4, True): (4, 'open'),
    (4, False): (4, 'closed'),
}

SIGNALS = {  # Gleis -> Channels to switch
    'in': [5, 8],
    2: [6],
    3: [6],
    4: [7],
}


class SwitchManager:

    def __init__(self, relays: RelayManager):
        self.relays = relays
        self._states: Dict[int, bool] = {}  # switch -> curved

    def _operate_switch(self, switch: int, curved: bool):
        """ Sends a signal to the specified track switch. """
        if not self.relays.is_connected:
            return False
        try:
            channel, state = RELAY_STATE_BY_SWITCH_STATE[(switch, curved)]
            if state == 'open':
                self.relays.device.open_channel(channel)
            else:
                self.relays.device.close_channel(channel)
            self.relays.device.pulse(SWITCH_POWER_CHANNEL)
            self._states[switch] = curved
        except BaseException as exc:
            print(f"Failed to operate switch {switch}: {exc}")

    def set_switches(self, state: Dict[int, bool], refresh=False):
        for switch, curved in state.items():
            needs_change = refresh or (self._states[switch] != curved if switch in self._states else True)
            if needs_change:
                self._operate_switch(switch, curved)


class StationSwitchesController:

    CONFIGS = {
        1: {1: False},
        2: {1: True, 2: True},
        3: {1: True, 2: False, 3: True},
        4: {1: True, 2: False, 3: False},
        5: {1: True, 2: False, 3: False},
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

    def select_track(self, train: Train):
        state = {}  # empty, parked, entering, exiting
        can_enter = {
            1: state[1] == 'empty' and state[2] != 'exiting' and state[3] != 'exiting',
            2: state[2] == 'empty' and state[3] != 'exiting',
            3: state[3] == 'empty',
            4: state[4] == 'empty',
            5: state[5] == 'empty' and state[4] != 'exiting',
        }
        future_collision_cost = .1
        cost_regional = 1 - train.regional_fac
        cost_far_distance = train.regional_fac
        base_cost = {
            1: cost_regional,
            2: cost_regional + future_collision_cost,
            3: cost_regional + 2 * future_collision_cost,
            4: cost_far_distance + future_collision_cost,
            5: cost_far_distance,
        }
        prevent_exit = {  # when entering platform x, train on platforms y must wait
            1: [2, 3],
            2: [3],
            5: [4],
        }
        cost = {}
        for track in [t for t, c in can_enter.items() if c]:
            wait_cost = 0
            for waiting_track in prevent_exit[track]:
                if state[waiting_track] == 'parked':
                    controlled = get_train(waiting_track).has_driver()
                    if controlled:
                        parking_duration = time.perf_counter() - parking_time[waiting_track]
                        wait_cost += ...  # ToDo maximum cost at 5-10 seconds after parking
            # ToDo check that trains currently on the track (not in terminus) can be assigned a proper track (e.g. keep 4/5 open for ICE) Weighted by expected arrival time.
            cost[track] = base_cost[track] + wait_cost
        return min(cost, key=cost.get)
