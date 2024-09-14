import json
import os.path
import time
import warnings
from threading import Thread
from typing import Optional, List

from etils.edc import dataclass

from fpme.helper import schedule_at_fixed_rate
from fpme.relay8 import Relay8, RelayManager
from fpme.train_control import TrainControl
from fpme.train_def import Train, TRAINS_BY_NAME


SWITCH_STATE = {
    1: {6: False, 8: True},  # True -> open_channel, False -> close_channel
    2: {6: False, 8: False},  # ToDo switch 4 not properly connected
    3: {6: True, 7: True},
    4: {6: True, 7: False, 8: False},
    5: {6: True, 7: False, 8: True},
}

SIGNAL_CHANNELS = {  # Gleis -> Channels to switch
    2: [1],
    3: [1],
    4: [2],
}

PREVENT_EXIT = {  # when entering platform x, train on platforms y must wait
    1: [2, 3],
    2: [3],
    5: [4],
}

ENTRY_SIGNAL = 3
ENTRY_POWER = 4


@dataclass
class ParkedTrain:
    train: Train
    platform: int
    dist_request: float = None  # Signed distance when enter request was sent
    dist_trip: float = None  # Signed distance when entering the switches
    dist_clear: float = None  # Signed distance when leaving the sensor, now fully on switches

    @property
    def has_tripped(self):
        return self.dist_trip is not None

    @property
    def train_length(self):
        return abs(self.dist_clear - self.dist_trip) + 0.18  # detector track length

    @property
    def entered_forward(self):
        if self.dist_clear is None:
            return (self.dist_trip - self.dist_request) > 0
        else:
            return (self.dist_clear - self.dist_trip) > 0


class Terminus:

    def __init__(self, relay: Relay8, control: TrainControl, port: str):
        assert control.generator.is_open(port), f"Terminus cannot be managed without entry sensor but {port} is not open."
        self.relay = relay
        self.control = control
        self.port = port
        self.trains: List[ParkedTrain] = []
        self.entering: Optional[ParkedTrain] = None
        self.load_state()
        schedule_at_fixed_rate(self.save_state, 5.)

    def save_state(self):
        data = {
            'switches': [],
            'trains': [{
                'name': t.train.name,
                'platform': t.platform,
                'dist': self.control[t.train].signed_distance,
                'dist_request': t.dist_request,
                'dist_trip': t.dist_trip,
                'dist_clear': t.dist_clear,
            } for t in self.trains]
        }
        with open("terminus.json", 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=2)

    def load_state(self):
        if not os.path.isfile("terminus.json"):
            return
        with open("terminus.json", 'r', encoding='utf-8') as file:
            data = json.load(file)
        for train_data in data['trains']:
            train = TRAINS_BY_NAME[train_data['name']]
            platform = data['platform']
            dist_request = data['dist_request']
            dist_trip = data['dist_trip']
            dist_clear = data['dist_clear']
            delta = self.control[train].signed_distance - data['dist']
            self.trains.append(ParkedTrain(train, platform, dist_request + delta, dist_trip + delta, dist_clear + delta))

    def request_entry(self, train: Train):
        if self.entering:
            if train == self.entering.train:  # clicked again, no effect
                return
            elif self.entering.has_tripped:
                self.control.force_stop(train, "wait for previous train")  # Wait until previous train has passed
                return
            else:  # Who is first? Previous one might have been an accident. Stop both, block entry
                self.control.emergency_stop(train, f"Contested terminus entry: {train} vs {self.entering.train}")
                self.control.emergency_stop(self.entering.train, f"Contested terminus entry: {train} vs {self.entering.train}")
                self.relay.close_channel(ENTRY_SIGNAL)
                self.relay.close_channel(ENTRY_POWER)
                self.entering = None
                self.free_exit()
                return
        # --- prepare entry ---
        platform = self.select_track(train)
        if platform is None:  # cannot enter
            self.control.force_stop(train, "no platform")
            return
        self.prevent_exit(platform)
        self.set_switches_for(platform)
        self.relay.open_channel(ENTRY_SIGNAL)
        self.relay.open_channel(ENTRY_POWER)
        self.entering = entering = ParkedTrain(train, platform)
        entering.dist_request = self.control[train].signed_distance
        self.trains.append(entering)
        self.control.add_speed_limit(train, "terminus", 80)

        def process_entry(entering, duration=5, interval=0.01):
            for _ in range(int(duration / interval)):
                if self.control.generator.contact_status(self.port)[0]:
                    entering.dist_trip = self.control[train].signed_distance
                    driven = entering.dist_trip - entering.dist_request
                    if self.control[train].speed > 0 != entering.enter_forward:
                        warnings.warn(f"Train switched direction while entering? driven={driven}, speed={self.control[train].speed}")
                    self.play_announcement(train, platform)
                    def red_when_entered():
                        time.sleep(0.1)
                        if abs(self.control[train].signed_distance - entering.dist_trip) > 20:
                            self.relay.close_channel(ENTRY_SIGNAL)  # red when train has driven for 20cm
                    Thread(target=red_when_entered).start()
                    # --- wait for clear ---
                    while True:
                        time.sleep(interval)
                        if not self.control.generator.contact_status(self.port)[0]:
                            entering.dist_clear = self.control[train].signed_distance
                            self.relay.close_channel(ENTRY_POWER)
                            # --- wait for clear switches ---
                            while True:
                                time.sleep(interval)
                                if self.control[train].signed_distance > entering.dist_clear + ...:
                                    self.free_exit()
                                    entering = None
                                    return
                time.sleep(interval)
            # --- not tripped ---
            self.relay.close_channel(ENTRY_SIGNAL)
            self.relay.close_channel(ENTRY_POWER)
            self.control.force_stop(train, "train did not enter terminus")
        Thread(target=process_entry, args=(entering,)).start()

    def set_switches_for(self, platform: int):
        for channel, req_open in SWITCH_STATE[platform].items():
            self.relay.set_channel_open(channel, req_open)
        time.sleep(.01)
        self.relay.pulse(5)

    def prevent_exit(self, entering_platform):
        if entering_platform == 1:
            self.relay.close_channel(1)
        elif entering_platform == 2:
            self.relay.close_channel(1)
        elif entering_platform == 5:
            self.relay.close_channel(2)
        trains = [t for t in self.trains if t.platform in PREVENT_EXIT.get(entering_platform, [])]
        for t in trains:
            ...
            # self.control.block(t.train, self)

    def free_exit(self):
        self.relay.open_channel(1)
        self.relay.open_channel(2)
        for t in self.trains:
            ...
            # self.control.unblock(t.train, self)

    def get_platform_state(self):
        """For each platform returns one of (empty, parked, entering, exiting) """
        state = {i: 'empty' for i in range(1, 6)}
        for t in self.trains:
            speed = self.control[t.train].speed
            if speed == 0:
                state[t.platform] = 'parked'
            elif speed > 0 == t.entered_forward:
                state[t.platform] = 'entering'
            else:
                state[t.platform] = 'exiting'
        return state

    def select_track(self, train: Train) -> Optional[int]:
        """ Returns `None` if the train cannot enter because of collisions. """
        state = self.get_platform_state()
        can_enter = {
            1: state[1] == 'empty' and state[2] != 'exiting' and state[3] != 'exiting',
            2: state[2] == 'empty' and state[3] != 'exiting',
            3: state[3] == 'empty',
            4: state[4] == 'empty',
            5: state[5] == 'empty' and state[4] != 'exiting',
        }
        if not any(can_enter.values()):
            return None
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
        cost = {}
        for track in [t for t, c in can_enter.items() if c]:
            wait_cost = 0
            for waiting_track in PREVENT_EXIT[track]:
                if state[waiting_track] == 'parked':
                    controlled = get_train(waiting_track).has_driver()
                    if controlled:
                        parking_duration = time.perf_counter() - parking_time[waiting_track]
                        wait_cost += ...  # ToDo maximum cost at 5-10 seconds after parking
            # ToDo check that trains currently on the track (not in terminus) can be assigned a proper track (e.g. keep 4/5 open for ICE) Weighted by expected arrival time.
            cost[track] = base_cost[track] + wait_cost
        return min(cost, key=cost.get)

    def play_announcement(self, train: Train, platform: int):
        pass


if __name__ == '__main__':
    relays = RelayManager()
    def main(relay: Relay8):
        relay.open_channel(1)
        relay.open_channel(2)
        relay.open_channel(3)
    relays.on_connected(main)
    time.sleep(1)
