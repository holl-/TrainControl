import random
import time
from threading import Thread
from typing import Dict, Optional, Tuple, Sequence

from fpme.relay8 import Relay8, RelayManager
from fpme.signal_gen import SignalGenerator, SubprocessGenerator
from fpme.train_def import Train


SWITCH_STATE = {
    1: {6: False, 8: True},  # True -> open_channel, False -> close_channel
    2: {6: False, 8: False},  # ToDo switch 4 not properly connected
    3: {6: True, 7: True},
    4: {6: True, 7: False, 8: False},
    5: {6: True, 7: False, 8: True},
}

SIGNALS = {  # Gleis -> Channels to switch
    'in': [5, 8],
    2: [6],
    3: [6],
    4: [7],
}


class Terminus:

    def __init__(self, relay: Relay8, generator: SubprocessGenerator, port: str):
        self.relay = relay
        self.generator = generator
        self.port = port
        # for each track: which train, start position, length
        self.last_occupancy: tuple = (None, None, None)
        self.start_operation()

    def set_switches_for(self, platform: int):
        for channel, req_open in SWITCH_STATE[platform].items():
            if req_open:
                self.relay.open_channel(channel)
            else:
                self.relay.close_channel(channel)
        time.sleep(.01)
        self.relay.pulse(5)

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


if __name__ == '__main__':
    relays = RelayManager()
    def main(relay: Relay8):
        relay.open_channel(1)
        relay.open_channel(2)
        relay.open_channel(3)
    relays.on_connected(main)
    time.sleep(1)
