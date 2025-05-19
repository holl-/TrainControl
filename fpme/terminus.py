import json
import os.path
import random
import time
import warnings
from datetime import datetime, timedelta
from random import choice
from threading import Thread, Lock
from typing import Optional, List

from dataclasses import dataclass

from fpme.audio import play_announcement_async, play_audio_async
from fpme.helper import schedule_at_fixed_rate
from fpme.pygame_audio import async_play
from fpme.relay8 import Relay8, RelayManager
from fpme.train_control import TrainControl, TrainState
from fpme.train_def import Train, TRAINS_BY_NAME, ICE, S, E_RB, E_BW_IC, E40_RE_BLAU, DAMPF, BEIGE_218, ROT_218, DIESEL, BUS

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
    dist_clear: float = None  # Signed distance when leaving the sensor, now fully on switches
    # --- For
    dist_reverse: float = None  # Abs distance when the 'reverse' button is clicked for the fist time
    # --- For departure sound ---
    time_stopped: float = None  # perf_counter() when train was first reversed in station. Used to determine whether people could get on/off.
    doors_closing: bool = False
    time_departed: float = None  # Track departure so we don't play sounds multiple times

    @property
    def has_tripped(self):
        return self.dist_trip is not None

    @property
    def has_cleared(self):
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
        if not self.has_tripped:
            return None
        delta = self.state.signed_distance - self.dist_trip
        if not self.was_entry_recorded:
            default_position = 200  # ~middle of platform
            delta = default_position - abs(delta - 200)
        elif not self.entered_forward:  # entered_forward only available if was_entry_recorded
            delta = -delta  # make sure positive in station
        if self.has_reversed:  # here it's hard to know which direction the train is going.
            since_rev = self.state.abs_distance - self.dist_reverse
            return min(250., delta) - since_rev
        return delta

    def get_end_position(self):
        return self.get_position() - self.train_length

    def __repr__(self):
        status = 'cleared' if self.has_cleared else ('tripped' if self.has_tripped else 'requested')
        return f"{self.train.name} on platform {self.platform} ({status})."


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

    def save_state(self, *_args):
        data = {
            'switches': [],
            'trains': [{
                'name': t.train.name,
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
                                           dist_clear=dist_clear + sgn_delta if dist_clear is not None else None,
                                           dist_reverse=dist_reverse + abs_delta if dist_reverse is not None else state.abs_distance,  # train could be reversed by restart
                                           doors_closing=False,
                                           time_stopped=-100,))
            if train in READY_SOUNDS:
                state.custom_acceleration_handler = self.handle_acceleration
                print(f"Terminus blocking acceleration on {train} - {id(state)}")
            else:
                print(f"No sound for {train}")

    def reverse_to_exit(self):
        for train in self.trains:
            if train.state.abs_distance == 0 and train.entered_forward != train.state.is_in_reverse:
                self.control.reverse(train.train, 'terminus')

    def get_train_position(self, train: Train):
        for t in self.trains:
            if t.train == train:
                return t.platform, t.get_position()
        return None, None

    def set_occupied(self, platform: int, train: Train):
        state = self.control[train]
        if any([t.train == train for t in self.trains]):
            t = [t for t in self.trains if t.train == train][0]
            t.platform = platform
        else:
            dist = state.signed_distance
            abs_dist = state.abs_distance
            position = 200
            train_length = 50
            t = ParkedTrain(train, state, platform, None, dist_trip=dist - position, dist_clear=dist - position + train_length + 0.18, dist_reverse=abs_dist, time_stopped=-100)
            self.trains.append(t)

    def set_empty(self, platform: int):
        self.trains = [t for t in self.trains if t.platform != platform]

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
        print(f"Terminus handling acceleration for {train}")
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
                    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'sound', 'departure-effects', sound))
                    is_left = t.platform <= 3
                    async_play(path, int(is_left), 1-int(is_left))
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
            self.control.set_acceleration_control(train, controller, acc_input, cause)

    def request_entry(self, train: Train):
        print(self.trains)
        with self._request_lock:
            print(f"entering = {self.entering}")
            if self.entering:
                if train == self.entering.train:  # clicked again, no effect
                    return
                elif self.entering.has_tripped:
                    print(f"Terminus: {train} cannot enter until {self.entering} has cleared switches")
                    self.control.force_stop(train, "wait for previous train")  # Wait until previous train has passed
                    return
                else:  # Who is first? Previous one might have been an accident. Stop both, block entry
                    print(f"Terminus: Conflict between {train} and {self.entering}")
                    self.control.emergency_stop(train, f"Contested terminus entry: {train} vs {self.entering.train}")
                    self.control.emergency_stop(self.entering.train, f"Contested terminus entry: {train} vs {self.entering.train}")
                    self.relay.close_channel(ENTRY_SIGNAL)
                    self.relay.open_channel(ENTRY_POWER)
                    self.entering = None
                    self.free_exit()
                    return
            if any(t.train == train for t in self.trains):
                t = [t for t in self.trains if t.train == train][0]
                print(f"{train} is already in terminus: {t.platform} @ {t.get_position()}, cleared={t.has_cleared}")
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
                self.relay.close_channel(ENTRY_SIGNAL)
                self.relay.open_channel(ENTRY_POWER)
                self.control.emergency_stop(train, "train did not enter terminus")
                self.entering = None
                self.trains.remove(entering)
                return
            # --- Contact tripped ---
            entering.dist_trip = entering.state.signed_distance
            if entering.dist_trip == entering.dist_request:
                entering.dist_request -= -1e-3 if entering.state.is_in_reverse else 1e-3
            driven = entering.dist_trip - entering.dist_request
            if (entering.state.speed > 0) != entering.entered_forward:
                warnings.warn(f"Train switched direction while entering? driven={driven}, speed={entering.state.speed}")
            if self.control.sound >= 1:
                play_terminus_announcement(train, platform)
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
                elif entering.dist_clear is not None and entering.get_end_position(entering.state.signed_distance) < 30:  # another wheel entered
                    print("Another wheel entered")
                    entering.dist_clear = None  # enable above block to re-trigger
                    # self.relay.close_channel(ENTRY_POWER)
                    continue
                if entering.get_position() > max_train_length and entering.dist_clear is None:
                    entering.dist_clear = entering.state.signed_distance
                    print(f"Max train length reached. Setting as cleared. End = {entering.get_end_position()}")
                # --- cleared switches ---
                if self.entering.dist_clear is not None and entering.get_end_position() > 40:  # approx. 57 cm
                    print("Train cleared switches.")
                    self.free_exit()
                    self.entering = None
                    self.relay.open_channel(ENTRY_POWER)
                    return

        Thread(target=process_entry, args=(entering,)).start()

    def check_exited(self, *_):
        # print(f"Check exited for {self.trains}")
        for t in tuple(self.trains):
            if t.has_cleared:
                pos = t.get_position()
                exited = pos < 0
                if exited:
                    self.trains.remove(t)
                    self.control.set_speed_limit(t.train, 'terminus', None)
                # else:
                    # print(f"{t} still in station")

    def update(self, *_):
        for train in self.trains:
            if train.time_stopped is None and not train.state.speed and train.has_cleared:
                print(f"{train} came to a stop in terminus")
                train.time_stopped = time.perf_counter()
            elif train.time_departed is None and train.time_stopped is not None and train.has_reversed and train.state.speed:
                print(f"{train} is departing")
                train.time_departed = time.perf_counter()
                if self.control.sound >= 2 and train.train in DEPARTURE_SOUNDS:
                    if time.perf_counter() - train.time_stopped > 4.:
                        sound = DEPARTURE_SOUNDS[train.train]
                        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'assets', 'sound', 'departure', sound))
                        is_left = train.platform <= 3
                        async_play(path, int(is_left), 1 - int(is_left))

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
        cost = {p: base_cost[p] for p in can_enter}
        # cost = {}
        # for track in [t for t, c in can_enter.items() if c]:
        #     wait_cost = 0
        #     for waiting_track in PREVENT_EXIT[track]:
        #         if state[waiting_track] == 'parked':
        #             controlled = get_train(waiting_track).has_driver()
        #             if controlled:
        #                 parking_duration = time.perf_counter() - parking_time[waiting_track]
        #                 wait_cost += ...  # ToDo maximum cost at 5-10 seconds after parking
        #     # ToDo check that trains currently on the track (not in terminus) can be assigned a proper track (e.g. keep 4/5 open for ICE) Weighted by expected arrival time.
        #     cost[track] = base_cost[track] + wait_cost
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
        1: ('I C E, 86',  'Neuffen'),
        2: ('I C E, 109', 'Waldbrunn, über: Neuffen'),
        3: ('I C E, 170', 'Böblingen, über: Waldbrunn'),
        4: ('I C E, 18',  'Waldbrunn, über: Böblingen'),
        5: ('I C E, 34',  'Radeburg, über: Waldbrunn'),
    },
    S: {
        1: ('S 3', "Neuenbürg"),
        2: ('S 5', "Neuffen"),
        3: ('S 1', "Waldbrunn"),
        4: ('S 2', "Radeburg"),
        5: ('S 4', "Böblingen"),
    },
    E_BW_IC: {
        1: ("Intercity", "Neuffen"),
        2: ("Intercity", "Neuffen"),
        3: ("Intercity", "Neuffen"),
        4: ("Intercity", "Radeburg"),
        5: ("Intercity", "Radeburg"),
    },
    E_RB: {
        1: ("Regionalbahn", "Neuffen"),
        2: ("Regionalbahn", "Neuffen"),
        3: ("Regionalbahn", "Neuffen"),
        4: ("Regionalbahn", "Radeburg"),
        5: ("Regionalbahn", "Waldbrunn"),
    },
    E40_RE_BLAU: {
        1: ("Regional-Express", "Neuffen"),
        2: ("Regional-Express", "Neuffen"),
        3: ("Regional-Express", "Neuffen"),
        4: ("Regional-Express", "Radeburg"),
        5: ("Regional-Express", "Wiesbaden"),
    }
}


def play_terminus_announcement(train: Train, platform: int):
    if train in TARGETS:
        connection, target = TARGETS[train][platform]
        delay = max(0, random.randint(int(-train.max_delay * (1 - train.delay_rate)), train.max_delay))
        hour, minute, delay = delayed_now(delay)
        delay_text = f", heute circa {delay} Minuten später." if delay else ". Vorsicht bei der Einfahrt."
        speech = f"Gleis {platform}, Einfahrt. {connection}, nach: {target}, Abfahrt {hour} Uhr {minute}{delay_text}"
    else:
        speech = f"Vorsicht auf Gleis {platform}, ein Zug fährt ein."
    play_announcement_async(speech)


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


def play_special_announcement():
    sentences = [
        "Information zu, Hoggworts Express, nach: Hoggworts: Heube ab Gleis 8 Drei Viertel, direkt gegenüber.",
        "I C E 397, nach: Atlantis, fällt heute aus.",
        "Achtung Passagiere des Polarexpresses: Bitte halten Sie Ihr goldenes Ticket bereit.",
        "Information zu Orient Express: Der Zug verspätet sich aufgrund eines Mordes an Bord.",
        "Information zu: Thomas der kleinen Lokomotive: Heute ca. 20 Minuten später, da sie einem Freund auf die Gleise hilft.",
        "Information zu: Zeitreisezug, nach: 1955. Bitte vermeiden Sie Paradoxa",
        # "Information zu I C E, 910, nach: Saarbrücken. Der Zug entfällt aufgrund mangelnder Nachfrage.",
        "Information zum Schienenersatzverkehr zwischen: München, und: Berlin. Bitte benutzen Sie eines der bereitstehenden Fahrräder.",
        "Information zu: I C E, 86, Heute pünktlich. Grund hierfür sind Personen im Gleis, die den Zug anschieben.",
        "Achtung Passagiere des I C E 987, nach: Gotham Sittie. Bitte benutzen Sie ausschließlich Abschnitte D bis F., Grund hierfür ist ein Auftritt des Jokers in Abteil A.",
        "Achtung Passagiere des I C E 456, nach: Wunderland. Bitte folgen Sie dem weißen Kaninchen zum Gleis",
        # "Jim Knopf",
    ]
    # play_announcement_async(sentences[0])
    play_announcement_async(random.choice(sentences))

# ToDo sounds only if enabled
READY_SOUNDS = {
    ICE: ("whistle1.wav", 1.5),
    S: ("door-beep-S-Bahn.wav", 5.),
    E_BW_IC: ("whistle2.wav", 1.5),
    E_RB: ("door-beep-RE.wav", 5.),
    DAMPF: ("steam-horn.wav", 4.),  # oder Horn vom Zug
    E40_RE_BLAU: ("whistle-and-train1.wav", 1.5),
    BEIGE_218: ("diesel-steam.wav", 0.),
    ROT_218: ("diesel-steam.wav", 2.),
    DIESEL: ("diesel-steam.wav", 2.),
    BUS: ("doors-tram.wav", 4.),
}

DEPARTURE_SOUNDS = {  # , "e-train1.wav"
    ICE: "e-train1.wav",
    S: None,  # sound from train
    E_BW_IC: "e-train1.wav",
    E_RB: "e-train1.wav",
    DAMPF: None,  # sound from train
    E40_RE_BLAU: "e-train1.wav",
    BEIGE_218: "diesel-departure.mp3",
    ROT_218: None,
    DIESEL: "diesel-departure.mp3",
    BUS: "e-drive1.wav",
}

if __name__ == '__main__':
    pass
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
    # time.sleep(1)
    # play_terminus_announcement(S, 1)
    # play_special_announcement()
