import json
import os.path
import random
import time
import warnings
from datetime import datetime, timedelta
from functools import cached_property
from threading import Thread, Lock
from typing import Optional, List, Tuple

from dataclasses import dataclass

from fpme.audio import play_announcement, play_background_loop, async_play, set_background_volume
from fpme.helper import schedule_at_fixed_rate
from fpme.relay8 import Relay8, RelayManager
from fpme.train_control import TrainControl, TrainState
from fpme.train_def import Train, TRAINS_BY_NAME, ICE, S, E_RB, E_BW, E40, DAMPF, BEIGE, ROT, DIESEL, BUS

SWITCH_STATE = {  # True -> open_channel, False -> close_channel
    1: {6: False, 8: True},
    2: {6: False, 8: False},
    3: {6: True, 7: True},
    4: {6: True, 7: False, 8: False},
    5: {6: True, 7: False, 8: True},
}

PREVENT_EXIT = {  # when entering platform x, train on platforms y must wait
    1: [2, 3],
    2: [3],
    5: [4],
}

ENTRY_SIGNAL = 3
ENTRY_POWER = 4  # no power when open

SPEED_LIMIT = 80.


@dataclass
class ParkedTrain:
    train: Train
    state: TrainState
    platform: int
    dist_request: float = None  # Signed distance when enter request was sent. None for trains set through the UI.
    dist_trip: float = None  # Signed distance when entering the switches
    time_trip: float = None
    dist_clear: float = None  # Signed distance when leaving the sensor, now fully on switches
    dist_reverse: float = None  # Abs distance when the 'reverse' button is clicked for the fist time
    # --- For departure sound ---
    time_stopped: float = None  # perf_counter() when train came to rest in station. Can be updated.
    dist_stopped: float = None  # Signed distance when last stopped.
    doors_closing: bool = False
    time_departed: float = None  # Track departure so we don't play sounds multiple times
    # --- For special announcements ---
    announcements_played = ()  # can contain 'connections', 'delay/real', 'delay/fake', 'general/real', 'general/fake'
    time_last_announcement = -100  # start time of last train announcement. Must be at least 15 seconds until next one.
    duration_last_announcement = 0  # 15s for delay reasons, 15? seconds for connections

    def __post_init__(self):
        print(f"Creating ParkedTrain for {self.train}")

    @property
    def has_tripped_contact(self):
        return self.dist_trip is not None

    @property
    def has_cleared_contact(self):
        return self.dist_clear is not None

    @property
    def train_length(self):
        computed_length = abs(self.dist_clear - self.dist_trip) - 0.18  # detector track length
        return min(120., computed_length)

    @property
    def entered_forward(self):
        if self.dist_clear is None:
            return (self.dist_trip - self.dist_request) > 0
        else:
            return (self.dist_clear - self.dist_trip) > 0

    @property
    def was_entry_recorded(self):
        return self.dist_request is not None

    @property
    def has_reversed(self):
        return self.dist_reverse is not None

    def get_position(self):
        """Positive towards station."""
        if not self.has_tripped_contact:
            return None
        delta = self.state.signed_distance - self.dist_trip
        if not self.was_entry_recorded:
            default_position = 220  # ~middle of platform
            delta = default_position - abs(delta - 220)
        elif not self.entered_forward:  # entered_forward only available if was_entry_recorded
            delta = -delta  # make sure positive in station
        if self.has_reversed:  # here it's hard to know which direction the train is going.
            since_rev = self.state.abs_distance - self.dist_reverse
            return min(300., delta) - since_rev * .8  # safety margin
        return delta

    def get_end_position(self):
        return self.get_position() - self.train_length

    @cached_property
    def delay_minutes(self):
        if random.random() < self.train.info.delay_rate:
            return random.randint(1, self.train.info.max_delay)
        else:
            return 0

    def __repr__(self):
        status = 'cleared' if self.has_cleared_contact else ('tripped' if self.has_tripped_contact else 'requested')
        return f"{self.train} on platform {self.platform} ({status})."


# @dataclass
# class TrackedTrain:
#     train: Train
#     state: TrainState
#     track: str
#     dist_start: float
#     num_reverse: int
#
#     def


class Terminus:

    def __init__(self, relay: Relay8, control: TrainControl, port: str):
        assert control.generator.is_open(port), f"Terminus cannot be managed without entry sensor but {port} is not open."
        self.relay = relay
        self.control = control
        self.port = port
        self.trains: List[ParkedTrain] = []  # trains in Terminal
        self.entering: Optional[ParkedTrain] = None
        self._request_lock = Lock()
        relay.close_channel(1)
        relay.close_channel(2)
        relay.close_channel(ENTRY_SIGNAL)
        relay.open_channel(ENTRY_POWER)
        self.load_state()
        for t in self.trains:
            control.set_speed_limit(t.train, 'terminus', SPEED_LIMIT)
        schedule_at_fixed_rate(self.save_state, 5.)
        schedule_at_fixed_rate(self.check_exited, 1.)
        schedule_at_fixed_rate(self.update, 0.1)
        play_background_loop(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'sound', 'ambient', 'station.mp3')))

    def save_state(self, *_args):
        data = {
            'switches': [],
            'trains': [{
                'name': t.train.id,
                'platform': t.platform,
                'sgn_dist': t.state.signed_distance,
                'abs_dist': t.state.abs_distance,
                'dist_request': t.dist_request,
                'dist_trip': t.dist_trip,
                'dist_clear': t.dist_clear,
                'dist_reverse': t.dist_reverse,
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
            state = self.control[train]
            platform = train_data['platform']
            dist_request = train_data['dist_request']
            dist_trip = train_data['dist_trip']
            dist_clear = train_data['dist_clear']
            dist_reverse = train_data['dist_reverse']
            sgn_delta = state.signed_distance - train_data['sgn_dist']
            abs_delta = state.abs_distance - train_data['abs_dist']  # typically < 0
            self.trains.append(ParkedTrain(train, state, platform,
                                           dist_request=dist_request + sgn_delta if dist_request is not None else None,
                                           dist_trip=dist_trip + sgn_delta if dist_trip is not None else None,
                                           time_trip=-100,
                                           dist_clear=dist_clear + sgn_delta if dist_clear is not None else None,
                                           dist_reverse=dist_reverse + abs_delta if dist_reverse is not None else state.abs_distance,  # train could be reversed by restart
                                           doors_closing=False,
                                           dist_stopped=state.signed_distance,
                                           time_stopped=-100,))
            if train in READY_SOUNDS:
                state.custom_acceleration_handler = self.handle_acceleration
                print(f"Terminus blocking acceleration on {train} - {id(state)}")
            else:
                print(f"No sound for {train}")

    def reverse_to_exit(self):
        for train in self.trains:
            if train.state.abs_distance == 0 and train.entered_forward != train.state.is_in_reverse:
                self.control.reverse(train.train, 'terminus', auto_activate=False)

    def get_train_position(self, train: Train):
        for t in self.trains:
            if t.train == train:
                return t.platform, t.get_position()
        return None, None

    def set_occupied(self, platform: int, train: Train):
        state = self.control[train]
        if self.entering.train == train:
            self.clear_entering()
        if any([t.train == train for t in self.trains]):
            t = [t for t in self.trains if t.train == train][0]
            t.platform = platform
            print(f"Moved {train} to platform {platform}")
        else:
            dist = state.signed_distance
            abs_dist = state.abs_distance
            position = 200
            train_length = 50
            t = ParkedTrain(train, state, platform, None, dist_trip=dist - position, dist_clear=dist - position + train_length + 0.18, dist_reverse=abs_dist, time_stopped=-100)
            self.trains.append(t)
            print(f"Added {t}")
        print(self.trains)

    def set_empty(self, platform: int):
        self.trains = [t for t in self.trains if t.platform != platform]
        if self.entering is not None and self.entering.platform == platform:
            self.clear_entering()
        print(self.trains)

    def on_reversed(self, train: Train):
        for t in self.trains:
            if t.train == train:
                if t.dist_reverse is None:  # ignore subsequent reverses
                    t.dist_reverse = t.state.abs_distance
                    print(f"Reversed: {train}")
                    if t.train in READY_SOUNDS:
                        print(f"Blocking input for sound {READY_SOUNDS[t.train]}")
                        t.state.custom_acceleration_handler = self.handle_acceleration

    def handle_acceleration(self, train: Train, controller: str, acc_input: float, cause: str):
        # print(f"Terminus handling acceleration for {train}")
        for t in self.trains:
            if t.train == train:
                if acc_input > 0:
                    if t.doors_closing:
                        return
                    t.doors_closing = True
                    if self.control.sound < 2:
                        t.state.custom_acceleration_handler = None
                        break
                    # --- Play sound ---
                    sound, duration = READY_SOUNDS[t.train]
                    is_left = t.platform <= 3
                    async_play('departure-effects/' + sound, int(is_left), 1-int(is_left))
                    # --- Wait, then release control ---
                    def release_block(t=t):
                        time.sleep(duration)
                        print(f"Terminus: door closing complete for {t.train}")
                        t.state.custom_acceleration_handler = None
                        # self.control.set_acceleration_control(train, controller, self.blocked_inputs[t.train], 'terminus-release')
                    Thread(target=release_block).start()
                break
        else:
            warnings.warn(f"Terminus got input for {train} but train is not in station")
            self.control[train].custom_acceleration_handler = None
            self.control.set_acceleration_control(train, controller, acc_input, cause)

    def request_entry(self, train: Train):  # Button C
        print(f"{train} requrests entry. Already registered: ", self.trains)
        with self._request_lock:
            print(f"entering = {self.entering}")
            if self.entering:
                if train == self.entering.train:  # clicked again, no effect
                    return
                elif self.entering.has_tripped_contact:
                    print(f"Terminus: {train} cannot enter until {self.entering} has cleared switches")
                    self.control.force_stop(train, "wait for previous train")  # Wait until previous train has passed
                    return
                else:  # Who is first? Previous one might have been an accident. Stop both, block entry
                    print(f"Terminus: Conflict between {train} and {self.entering}")
                    self.control.emergency_stop(train, f"Contested terminus entry: {train} vs {self.entering.train}")
                    self.control.emergency_stop(self.entering.train, f"Contested terminus entry: {train} vs {self.entering.train}")
                    self.clear_entering()
                    return
            if any(t.train == train for t in self.trains):
                t = [t for t in self.trains if t.train == train][0]
                print(f"{train} is already in terminus: {t.platform} @ {t.get_position()}, cleared={t.has_cleared_contact}")
                # --- Play sound if parked ---
                if t.state.speed == 0 and self.control.sound >= 1 and len(t.announcements_played) < 2 and time.perf_counter() > t.time_last_announcement + t.duration_last_announcement:
                    print(f"Previous announcements: {t.announcements_played}")
                    if 'connections' not in t.announcements_played and time.perf_counter() < t.time_stopped + 15:  # first announcement is about other trains in station (only if any)
                        passenger_trains = [t_ for t_ in self.trains if t_ != t and t_.train.is_passenger_train and (t_.state.speed == 0 or (t_.state.speed > 0) == t_.entered_forward)]
                        if passenger_trains:
                            connections = [(t_.train, t_.platform) for t_ in passenger_trains]
                            t.announcements_played += ('connections',)
                            t.time_last_announcement = time.perf_counter()
                            t.duration_last_announcement = play_connections(t.platform, connections)
                    else:
                        t.announcements_played += ('delay',)
                        t.time_last_announcement = time.perf_counter()
                        t.duration_last_announcement = play_special_announcement(t.train, t.platform, t.delay_minutes, time.perf_counter() - t.time_stopped)
                else:
                    print(f"Cannot play announcement. sound={self.control.sound}, speed={t.state.speed}, previous={t.announcements_played}, time={time.perf_counter() - t.time_last_announcement - t.duration_last_announcement}")
                return
            # --- prepare entry ---
            platform = self.select_track(train)
            print(f"Terminus: {train} assigned to platform {platform}")
            if platform is None:  # cannot enter
                self.control.force_stop(train, "no platform")
                return
            self.entering = entering = ParkedTrain(train, self.control[train], platform)
            entering.dist_request = entering.state.signed_distance
            self.trains.append(entering)
        self.control.set_speed_limit(train, 'terminus', SPEED_LIMIT)
        self.prevent_exit(platform)
        set_switches_for(self.relay, platform)
        self.relay.open_channel(ENTRY_SIGNAL)
        self.relay.close_channel(ENTRY_POWER)

        def process_entry(entering: ParkedTrain, duration=6, interval=0.01, max_train_length=130):
            for _ in range(int(duration / interval)):
                if self.control.generator.contact_status(self.port)[0]:
                    print(f"Terminus: Contact tripped. {entering}")
                    break
                time.sleep(interval)
            else:  # --- not tripped - maybe button pressed on accident or train too far ---
                self.clear_entering()
                self.control.emergency_stop(train, "train did not enter terminus")
                self.trains.remove(entering)
                return
            # --- Contact tripped ---
            entering.dist_trip = entering.state.signed_distance
            entering.time_trip = time.perf_counter()
            if entering.dist_trip == entering.dist_request:
                entering.dist_request -= -1e-3 if entering.state.is_in_reverse else 1e-3
            driven = entering.dist_trip - entering.dist_request
            if (entering.state.speed > 0) != entering.entered_forward:
                warnings.warn(f"Train switched direction while entering? driven={driven}, speed={entering.state.speed}")
            if self.control.sound >= 1:
                play_entry_announcement(train, platform, entering.delay_minutes)
            def red_when_entered():
                while True:
                    time.sleep(0.1)
                    if entering.get_position() > 20:
                        self.relay.close_channel(ENTRY_SIGNAL)  # red when train has driven for 20cm
                        return
            print("-> (async) Red when entered...")
            Thread(target=red_when_entered).start()
            # --- wait for clear sensor ---
            print("Waiting for clear...")
            while True:
                time.sleep(interval)
                # print(f"Sensor: {self.control.generator.contact_status(self.port)[0]}")
                if not self.control.generator.contact_status(self.port)[0]:  # possible sensor clear
                    if entering.dist_clear is None:
                        print("Sensor clear. Waiting for possible next wheel...")
                        entering.dist_clear = entering.state.signed_distance
                        # self.relay.open_channel(ENTRY_POWER)
                elif entering.dist_clear is not None and entering.get_end_position() < 30:  # another wheel entered
                    print("Another wheel entered")
                    entering.dist_clear = None  # enable above block to re-trigger
                    # self.relay.close_channel(ENTRY_POWER)
                    continue
                if entering.get_position() > max_train_length and entering.dist_clear is None:
                    entering.dist_clear = entering.state.signed_distance
                    print(f"Max train length reached. Setting as cleared. End = {entering.get_end_position()}")
                # --- cleared switches ---
                if self.entering is not None and self.entering.dist_clear is not None and entering.get_end_position() > 60:  # approx. 57 cm
                    print("Train cleared switches.")
                    self.clear_entering()
                    return

        Thread(target=process_entry, args=(entering,)).start()

    def check_exited(self, *_):
        # print(f"Check exited for {self.trains}")
        for t in tuple(self.trains):
            if t.has_cleared_contact:
                pos = t.get_position()
                exited = pos < 0
                if exited:
                    self.trains.remove(t)
                    self.control.set_speed_limit(t.train, 'terminus', None)
                    print(f"{t} left the station.")
                # else:
                    # print(f"{t} still in station")

    def update(self, *_):
        set_background_volume(.2 if self.control.sound >= 2 else 0)
        for train in self.trains:
            if not train.state.speed and train.has_cleared_contact:  # stopped after contact
                if train.time_stopped is None:
                    print(f"{train} came to a stop in terminus")
                    train.time_stopped = time.perf_counter()
                    train.dist_stopped = train.state.signed_distance
                    if self.entering == train:
                        self.clear_entering()
                elif not train.has_reversed and train.state.signed_distance != train.dist_stopped:  # Continued a bit further and stopped again
                    print(f"{train} came to a stop in terminus again, distance from previous: {abs(train.state.signed_distance - train.dist_stopped)}")
                    train.time_stopped = time.perf_counter()
                    train.dist_stopped = train.state.signed_distance
            elif train.time_departed is None and train.time_stopped is not None and train.has_reversed and train.state.speed:
                print(f"{train} is departing")
                train.time_departed = time.perf_counter()
                if self.control.sound >= 2 and train.train in DEPARTURE_SOUNDS:
                    if time.perf_counter() - train.time_stopped > 4.:
                        sound = DEPARTURE_SOUNDS[train.train]
                        is_left = train.platform <= 3
                        async_play("departure/"+sound, int(is_left), 1 - int(is_left))
        if self.entering is not None and self.entering.time_trip and time.perf_counter() - self.entering.time_trip > 20:
            print(f"{self.entering} has entered contact {time.perf_counter() - self.entering.time_trip} seconds ago and is still entering. Assuming this was a mistake and clearing entry.")
            self.clear_entering()

    def prevent_exit(self, entering_platform):
        if entering_platform == 1:
            self.relay.close_channel(1)  # Platforms 2, 3
        elif entering_platform == 2:
            self.relay.close_channel(1)  # Platforms 2, 3
        elif entering_platform == 5:
            self.relay.close_channel(2)  # Platform 4
        trains = [t for t in self.trains if t.platform in PREVENT_EXIT.get(entering_platform, [])]
        for t in trains:
            if (t.state.speed < 0) == t.entered_forward:
                self.control.emergency_stop(t.train, 'terminus-conflict')
                self.control.set_speed_limit(t.train, 'terminus-wait', 0)

    def clear_entering(self):
        self.entering = None
        self.relay.close_channel(ENTRY_SIGNAL)
        self.relay.open_channel(ENTRY_POWER)
        self.free_exit()

    def free_exit(self):
        self.relay.open_channel(1)  # Platforms 2, 3
        self.relay.open_channel(2)  # Platform 4
        for t in self.trains:
            self.control.set_speed_limit(t.train, 'terminus-wait', None)

    def get_platform_state(self):
        """For each platform returns one of (empty, parked, entering, exiting) """
        state = {i: 'empty' for i in range(1, 6)}
        for t in self.trains:
            speed = t.state.speed
            if speed == 0:
                state[t.platform] = 'parked'
            elif (speed > 0) == t.entered_forward:
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
        can_enter = [p for p, c in can_enter.items() if c]
        if not can_enter:
            return None
        regional = random.random() < train.info.regional_prob
        cost_regional = int(not regional)
        cost_far_distance = int(regional)
        base_cost = {
            1: cost_regional,
            2: cost_regional + .1,
            3: cost_regional + .2,
            4: cost_far_distance + .1,
            5: cost_far_distance,
        }
        cost = {p: base_cost[p] for p in can_enter}
        best = min(cost, key=cost.get)
        print(f"{train.name} -> platform {best},  costs={cost} (others cannot be entered due to occupancy or currently exiting trains)")
        return best


def set_switches_for(relay, platform: int):
    time.sleep(.01)
    for channel, req_open in SWITCH_STATE[platform].items():
        if channel == 8:  # secondary switches, delay by 1s
            def delayed_switch_secondary(channel=channel, req_open=req_open):
                time.sleep(1.)
                relay.set_channel_open(channel, req_open)
            Thread(target=delayed_switch_secondary).start()
        else:
            relay.set_channel_open(channel, req_open)
            time.sleep(.1)


TARGETS = {
    ICE: {
        1: ('I C E, 86',  "Waldbrunn, über: Neuffen"),
        2: ('I C E, 29', "Neuffen"),
        3: ('I C E, 52', "Wiesbaden, über: Waldbrunn"),
        4: ('I C E, 18',  "Böblingen"),
        5: ('I C E, 34',  "Radeburg, über: Waldbrunn"),
    },
    S: {
        1: ('S 3', "Waldbrunn"),
        2: ('S 5', "Neuffen"),
        3: ('S 1', "Kirchbach"),
        4: ('S zwo', "Böblingen"),
        5: ('S 4', "Kleiningen"),
    },
    BUS: {
        1: ('Schienenbus', "Waldbrunn"),
        2: ('Schienenbus', "Neuffen"),
        3: ('Schienenbus', "Kirchbach"),
        4: ('Schienenbus', "Böblingen"),
        5: ('Schienenbus', "Kleiningen"),
    },
    E_BW: {
        1: ("Intercity", "Waldbrunn, über: Neuffen"),
        2: ("Intercity", "Neuffen"),
        3: ("Intercity", "Wiesbaden, über: Waldbrunn"),
        4: ("Intercity", "Böblingen"),
        5: ("Intercity", "Radeburg, über: Waldbrunn"),
    },
    E_RB: {
        1: ("Regionalbahn", "Waldbrunn"),
        2: ("Regionalbahn", "Neuffen"),
        3: ("Regionalbahn", "Kirchbach"),
        4: ("Regionalbahn", "Böblingen"),
        5: ("Regionalbahn", "Kleiningen"),
    },
    ROT: {
        1: ("Regional-Express", "Waldbrunn, über: Neuffen"),
        2: ("Regional-Express", "Neuffen"),
        3: ("Regional-Express", "Wiesbaden"),
        4: ("Regional-Express", "Böblingen"),
        5: ("Regional-Express", "Radeburg"),
    },
    BEIGE: {
        1: ("Nahverkehrszug", "Waldbrunn"),
        2: ("Nahverkehrszug", "Neuffen"),
        3: ("Nahverkehrszug", "Wiesbaden"),
        4: ("Eilzug", "Böblingen"),
        5: ("Eilzug", "Radeburg"),
    },
}


def play_entry_announcement(train: Train, platform: int, delay_minutes: int):
    if train in TARGETS:
        name, target = TARGETS[train][platform]
        hour, minute, delay = delayed_now(delay_minutes)
        delay_text = f", heute circa {delay} Minuten später." if delay else ". Vorsicht bei der Einfahrt."
        speech = f"Gleis {PL_NUM[platform]}, Einfahrt. {name}, nach: {target}, Abfahrt {hour} Uhr {minute}{delay_text}"
    else:
        speech = f"Vorsicht auf Gleis {platform}, ein Zug fährt ein."
    print(f"Announcement: '{speech}'")
    play_announcement(speech, left_vol=int(platform <= 3), right_vol=int(platform > 3))


OPPOSITE = {
    1: 2,
    2: 1,
    3: 4,
    4: 3,
    5: None,
}
PL_NUM = {
    1: "eins",
    2: "zwo",
    3: "drei",
    4: "vier",
    5: "fünf"
}


def play_connections(platform: int, connections: List[Tuple[Train, int]]):
    if len(connections) > 2:
        connections = random.sample(connections, 2)
    texts = []
    for train, pl in connections:
        name, target = TARGETS[train][pl]
        texts.append(f"{name}, nach: {target} von Gleis {PL_NUM[pl]}{', direkt gegenüber' if OPPOSITE[platform] == pl else ''}.")
    play_announcement(' '.join(texts), left_vol=int(platform <= 3), right_vol=int(platform > 3), cue='anschlüsse', cue_vol=1.)
    return 2 + 4.5 * len(texts)


def play_special_announcement(train: Train, platform: int, delay_minutes: int, entered_seconds_ago: float):
    sentences = [
        "Information zu, Hoggworts Express, nach: Hoggworts: Heube ab Gleis 8 Drei Viertel, direkt gegenüber.",
        "I C E 397, nach: Atlantis, fällt heute aus.",
        "Achtung Passagiere des Polarexpresses: Bitte halten Sie Ihr goldenes Ticket bereit.",
        "Information zu Orient Express: Der Zug verspätet sich aufgrund eines Mordes an Bord.",
        "Information zu: Thomas der kleinen Lokomotive: Heute ca. 20 Minuten später, da sie einem Freund auf die Gleise hilft.",
        "Information zu: Zeitreisezug, nach: 1955. Bitte vermeiden Sie Paradoxa",
        "Information zum Schienenersatzverkehr zwischen: München, und: Berlin. Bitte benutzen Sie eines der bereitstehenden Fahrräder.",
        "Information zu: I C E, 86, Heute pünktlich. Grund hierfür sind Personen im Gleis, die den Zug anschieben.",
        "Achtung Passagiere des I C E 987, nach: Gotham Sittie. Bitte benutzen Sie ausschließlich Abschnitte D bis F., Grund hierfür ist ein Auftritt des Jokers in Abteil A.",
        "Achtung Passagiere des I C E 456, nach: Wunderland. Bitte folgen Sie dem weißen Kaninchen zum Gleis",
        "Bitte lassen Sie Ihr Gepäck nicht unbeaufsichtigt. Sollte Ihnen alleinstehendes Gepäck auffallen, tragen Sie es bitte aus dem Bahnhof.",
        "Letzter Aufruf für Passagier Hubert Bauer, gebucht auf ICE 410 nach Köln. Bitte begeben Sie sich umgehend zum Bahnsteig 3.",
        # "Jim Knopf", / SEV / Tauben / Bordrestaurant teuer
    ]
    real_reasons = [
        "sind Gegenstände im Gleis.",
        "ist eine Störung im Betriebsablauf.",
        "sind Verzögerungen im Betriebsablauf.",
        "sind polizeiliche Ermittlungen.",
        "ist ein Notarzteinsatz im Zug.",
        "ist ein Notarzteinsatz auf der Strecke.",
        "ist eine technische Störung an der Strecke.",
        "ist eine technische Störung am Zug.",
        "ist eine Signalstörung.",
        "sind Personen im Gleis.",
        "ist ein Unfall mit Personenschaden.",
        "ist die ärztliche Versorgung eines Fahrgastes.",
        "ist eine behördliche Maßnahme.",
        "ist eine defekte Tür.",
        "ist die Bereitstellung weiterer Wagen.",
        "ist ein defektes Stellwerk.",
        "ist eine Oberleitungsstörung.",
        "ist ein Polizeieinsatz.",
        "ist eine Reparatur am Zug.",
        "ist eine Reparatur an der Oberleitung.",
        "ist eine Reparatur an einem Signal.",
        "ist die Reparatur an einer Weiche.",
        "ist eine Reparatur an der Strecke.",
        "ist eine Streckensperrung.",
        "ist eine Weichenstörung.",
        "sind Streikauswirkungen.",
        "ist ein technischer Defekt an einem anderen Zug.",
        "sind Tiere auf der Strecke.",
        "sind unbefugte Personen auf der Strecke.",
        "ist die Unterstützung beim Ein- und Ausstieg.",
        "ist ein Unwetter.",
        "ist die verspätete Bereitstellung des Zuges.",
        "ist eine Verspätung aus vorheriger Fahrt.",
        "ist die Verspätung eines vorausfahrenden Zuges.",
        "ist eine Verspätung im Ausland.",
        "ist die Vorfahrt eines anderen Zuges.",
        "ist das Warten auf Anschlussreisende.",
        "ist das Warten auf einen entgegenkommenden Zug.",
        "sind witterungsbedingte Beeinträchtigungen.",
        "sind Tiere im Gleis.",
        "sind ausgebrochene Tiere im Gleis.",
        "sind Bauarbeiten.",
        "ist eine behobene Störung am Zug.",
        "ist eine behobene Störung am Gleis.",
        "ist ein zusätzlicher Halt zum Ein- und Ausstieg.",
        "ist eine derzeit eingeschränkte Verfügbarkeit der Gleise.",
        "ist die Entschärfung einer Fliegerbombe.",
        "ist ein Feuerwehreinsatz auf der Strecke.",
        "ist ein kurzfristiger Personalausfall.",
        "ist eine Pass-und Zollkontrolle.",
        "sind Streikauswirkungen.",
        "ist eine technische Untersuchung am Zug.",
        "ist ein technischer Defekt an einem anderen Zug.",
        "ist die Umleitung des Zuges.",
        "ist ein umgestürzter Baum auf der Strecke.",
        "ist ein Unfall an einem Bahnübergang.",
        "sind Unwetterauswirkungen.",
        "ist verspätetes Personal aus vorheriger Fahrt.",
        "ist die Verspätung eines vorausfahrenden Zuges.",
    ]
    fake_reasons = [
        "ist die Sichtung eines unbekannten Flugobjekts auf der Strecke.",
        # "ist die verspätete Bereitstellung von Gleisen.",
        "ist ein fehlender Bahnhof auf der Strecke.",
        "ist die Verspätung eines nachfolgenden Zuges.",
        "ist eine Überschwemmung im Bordrestaurant.",
        "ist ein Notarzteinsatz auf einem Schiff.",
        "ein auf der Strecke verlorengegangener Wagen.",
        "ist ein geplatzter Reifen.",
        "ist eine Baustelle im Zug.",
        "ist eine Verspätung der Gepäck-Umladung.",
        "ist der Sommer.",
        "ist der Herbst.",
        "ist der Winter.",
        "ist der Frühling.",
        "ist ein umgestürzter Baumkuchen auf der Strecke.",
        "ist ein Unfall in einer Zugtoilette.",
        "ist ein Maulwurf auf der Strecke.",
        "ist eine eingestürzte Brücke auf der Strecke.",
        "ist eine Umleitung wegen eines eingestürzten Tunnels.",
        "ist Gegenwind auf der Strecke.",
        "ist ein Vogelschlag.",
        "ist ein Stromausfall wegen Flügelbruchs einer Bahn-Windrads.",
        "ist ein längeres Telefongespräch des Zugführers.",
        "ist eine technische Untersuchung an einem Reisenden.",
        "ist ein defektes Mobiltelefon.",
        "ist ein Feuerwehreinsatz im Bordrestaurant.",
        "ist eine Zollerhöhung.",
        "ist ein Zwischenhalt zum Zustieg des Schwagers der Zugbegleiterin.",
        "ist eine auf der Streck  abgefallene Ein- und Ausstiegstüre.",
        "ist die Betätigung des Nothalt-Knopfes durch einen Fahrgast.",
        "ist die fehlende Bereitschaft eines Fahrgastes, zuzusteigen.",
        "ist ein Meteoriteneinschlag auf er Strecke.",
        "ist der Fund einer Fliegerbombe.",
        "ist eine Toilettenpause.",
        "sind Beeinträchtigungen aufgrund des Klimawandels.",
        "ist ein Fahrrad in Wagen drei.",
        "sind Verzögerung beim Ausrollen eines roten Teppichs für den Bürgermeister.",
        "ist eine Signalstörungs-Behebungs-Planungs-Besprechung am Gleis.",
        "ist eine Verzögerung bei der Untersuchung von Stellwerk-Störungen.",
        "ist eine Blaskapelle.",
        "ist eine vorübergehenden Sperrung aller Bordtoiletten.",
        "ist die verfrühte Bereitstellung des Zuges.",
        "ist eine Oberleitungsanordnung.",
        "ist die tierärztliche Versorgung eines an Bord befindlichen Hundes.",
        "ist die Landung eines Passagierflugzeugs auf der Strecke.",
        "ist fehlendes Toilettenpapier wegen Hamsterkäufen.",
        "ist die verspätete Pizza-Lieferung des Zugführers.",
        "die Suche nach der EC-Karte eines Mitreisenden.",
        "der Raketenstart für einen GPS-Satelliten.",
        "die blendende Sonne.",
        "ist der Ausfall eines Feuerwehreinsatzes.",
        "ist ein Übersetzungsfehler auf der Speisekarte.",
        "ist eine Aussage des Bundeskanzlers.",
        "ist die Beschädigung einer Kommunikationsleitung der Bahn durch einen Bagger.",
        "ist ein Marderschaden.",
        "ist ein Defekt an der Klimaanlage.",
        "bist du.",
        "sind archäologische Ausgrabungen.",
        "ist die Warnung eines Hellsehers.",
        "ist eine Taube auf dem Zug.",
    ]
    # play_announcement_async(sentences[0])
    if train in TARGETS:
        name, target = TARGETS[train][platform]
        hour, minute, delay = delayed_now(max(5, delay_minutes))
        # delay_text = f", heute circa {delay} Minuten später." if delay else ". Vorsicht bei der Einfahrt."
        # speech = f"Gleis {platform}, Einfahrt. {connection}, nach: {target}, Abfahrt {hour} Uhr {minute}{delay_text}"
        reasons = fake_reasons if random.random() < .3 else real_reasons
        of = {S: 'der', E_RB: 'der'}.get(train, 'des')
        exit_type = "Abfahrt" if entered_seconds_ago > 45 else "Weiterfahrt"
        speech = f"Bitte beachten Sie: Die {exit_type} {of} {name} verzögert sich um circa {delay} Minuten. Grund dafür " + random.choice(reasons)
    else:
        speech = random.choice(sentences)
    play_announcement(speech, left_vol=int(platform <= 3), right_vol=int(platform>3))
    return 15


def delayed_now(delay_minutes: int):
    dt = datetime.now()
    delay_minutes = (delay_minutes // 5) * 5
    minutes = round(dt.minute / 5) * 5
    if minutes >= 60:
        dt += timedelta(hours=1)
        minutes = 0
    minute_text = {
        0: "",
        5: "fünf",
        10: "zehn",
        15: "fünfzehn",
        20: "zwanzig",
        25: "fünfundzwanzig",
        30: "dreißig",
        35: "fünfunddreißig",
        40: "vierzig",
        45: "fünfundvierzig",
        50: "fünfzig",
        55: "fünfundfünfzig",
    }
    dt = dt.replace(minute=minutes, second=0, microsecond=0) - timedelta(minutes=delay_minutes)
    return dt.hour, minute_text[dt.minute], delay_minutes


# ToDo sounds only if enabled
READY_SOUNDS = {
    ICE: ("whistle1.wav", 1.5),
    S: ("door-beep-S-Bahn.wav", 5.),
    E_BW: ("whistle2.wav", 1.5),
    E_RB: ("door-beep-RE.wav", 5.),
    DAMPF: ("steam-horn.wav", 3.5),  # oder Horn vom Zug
    E40: ("whistle-and-train1.wav", 1.5),
    BEIGE: ("diesel-steam.wav", 0.),
    ROT: ("diesel-steam.wav", 2.),
    DIESEL: ("diesel-steam.wav", 2.),
    BUS: ("doors-tram.wav", 4.),
}

DEPARTURE_SOUNDS = {  # , "e-train1.wav"
    ICE: "e-train1.wav",
    # S: None,  # sound from train
    E_BW: "e-train1.wav",
    E_RB: "e-train1.wav",
    # DAMPF: None,  # sound from train
    E40: "e-train1.wav",
    BEIGE: "diesel-departure.mp3",
    # ROT: None,
    DIESEL: "diesel-departure.mp3",
    BUS: "e-drive1.wav",
}

if __name__ == '__main__':
    # play_departure(ICE)
    # relays = RelayManager()
    # def main(relay: Relay8):
    #     relay.close_channel(ENTRY_POWER)
        # for i in range(100):
            # relay.open_channel(6)
            # relay.open_channel(8)
            # relay.open_channel(7)
            # time.sleep(1)
            # relay.close_channel(7)
            # relay.close_channel(6)
            # relay.close_channel(8)
            # time.sleep(1)
    # relays.on_connected(main)
    play_connections(2, [(E_RB, 1), (S, 3)])
    time.sleep(20)
