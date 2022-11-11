import math
import platform
import queue
import sys
import time
from random import random, randint
from threading import Thread, Lock
from typing import Tuple

from fpme import trains
from fpme.helper import schedule_at_fixed_rate
from fpme.museum_track import *
from fpme.ubuntu_helpers import *

sys.path.append('..')


class Controller:

    def __init__(self, train: trains.Train, last_position: State or None):
        self.train = train
        self.state = last_position
        train.on_post_update = self._update
        self._target_signed_distance: float = None
        self._increase_position: bool = None
        self._increase_signed_distance: bool = None
        self._next_pause: float = None
        self._executing = False
        self._t_started_waiting = None
        self._trip = []
        self._contact_to_target = []
        self._last_print = -1
        self._braking = False
        self._update_lock = Lock()
        self._max_speed = None
        self._use_emergency_stop = None

    def wait(self):
        while self._executing:
            time.sleep(.2)

    def drive(self, target_position, pause: float or None, trip: List[Tuple[str, float]] = (), wait_for=None, max_speed=80., use_emergency_stop=False):
        """
        Blocks until previous operation finished.

        :param target_position: Target position on the track in mm.
        :param pause: Duration to wait after stopping in seconds.
        :param trip: Contacts to trip along the way, (pin, position)
        :param wait_for: One of 'brake', 'done', None
        """
        print(f"{self.train.name} add command to queue: drive to {target_position} tripping {len(trip)}")
        self.wait()
        pause /= trains.TIME_DILATION
        if VIRTUAL:
            trip = []
        self._max_speed = max_speed
        self._use_emergency_stop = use_emergency_stop
        self._t_started_waiting = None
        distance_mm = (target_position - self.position) * (1 if self.aligned else -1)  # distance from the train's orientation
        self._target_signed_distance = self.state.cumulative_signed_distance + distance_mm
        self._increase_position = target_position >= self.position
        self._increase_signed_distance = self._increase_position ^ (not self.aligned)
        self._next_pause = pause
        self._trip = list(trip)
        self._contact_to_target = [abs(target_position - pos) for _, pos in self._trip]
        self._braking = False
        print(self._contact_to_target)
        # trains.GENERATOR.register(self)
        print(f">>> {self.train.name} -> drive {distance_mm:.0f} mm to position {State(0, self.outer_track, target_position, self.aligned)}. Trip: {', '.join([CONTACT_NAMES[pin] + f' @ {pos:.0f}' for pin, pos in self._trip])}"
              f"{' with emergency stop' if use_emergency_stop else ''}")
        if abs(distance_mm) < 10:
            print("Already there.")
            return
        self._executing = True
        Thread(target=self._count_triggers).start()
        if wait_for == 'brake':
            while self._executing and not self._braking:
                time.sleep(.2)
        elif wait_for == 'done':
            while self._executing:
                time.sleep(.2)
        elif wait_for is not None:
            raise ValueError(wait_for)

    def _count_triggers(self):
        assert isinstance(self._trip, list)
        while self._trip:
            pin, position = self._trip[0]
            print(f"{self.train} waiting for {pin}")
            trains.GENERATOR.await_event([pin], [False], timeout=None)
            p_position = project_position(position, self.outer_track)
            self_prev = str(self)
            with self._update_lock:
                self.state = update_state(self.state, self.train.cumulative_signed_distance)
                proj_delta = p_position - self.position
                original_delta = position - self.position
                delta = original_delta if abs(original_delta) < abs(proj_delta) else proj_delta
                self.state = State(self.train.cumulative_signed_distance, self.outer_track, p_position, self.aligned)
                self.state = update_state(self.state, self.state.cumulative_signed_distance)
                self._target_signed_distance -= delta
                print(f"🛈 {self} triggered {CONTACT_NAMES[pin]}, position updated by {delta} mm (actual - predicted) from {self_prev}", file=sys.stderr)
                self._trip.pop(0)
                self._contact_to_target.pop(0)
                distance_in_drive_direction = (self._target_signed_distance - self.train.cumulative_signed_distance) * (1 if self._increase_signed_distance else -1)  # positive unless overshot
                if distance_in_drive_direction < 0 and not self._trip:
                    print(f"Emergency stop {self} due to contact-induced position update", file=sys.stderr)
                    self.emergency_stop()

    @property
    def position(self):
        return self.state.position
    
    @property
    def aligned(self):
        return self.state.aligned
    
    @property
    def outer_track(self):
        return self.state.outer_track

    @property
    def inner_track(self):
        return not self.state.outer_track
    
    def emergency_stop(self):
        self.train.emergency_stop()

    def _update(self):
        with self._update_lock:
            prev_state: State = self.state
            self.state = update_state(self.state, self.train.cumulative_signed_distance)
            if not self._executing:
                return
            braking_distance = .5 * (self.train.deceleration / 3.6) * (abs(self.train.signed_actual_speed) / self.train.deceleration) ** 2 * 1000 / 87  # always positive
            distance_in_drive_direction = (self._target_signed_distance - self.train.cumulative_signed_distance) * (1 if self._increase_signed_distance else -1)  # positive unless overshot
            if self._trip and trains.GENERATOR.serial_port:
                if self._contact_to_target[0] > distance_in_drive_direction:
                    distance_in_drive_direction = self._contact_to_target[0]
                    self._target_signed_distance += self.state.cumulative_signed_distance - prev_state.cumulative_signed_distance
                    self.state = State(self.state.cumulative_signed_distance, prev_state.outer_track, prev_state.position, prev_state.aligned)
            if time.perf_counter() - self._last_print >= 5.:
                print(f"    {self}\t speed={self.train.signed_actual_speed:.0f}->{self.train.signed_target_speed}\tto drive: {distance_in_drive_direction:.0f}\tbrake: {braking_distance:.0f}\t(trip={', '.join([CONTACT_NAMES[pin] + f' @ {pos:.0f}' for pin, pos in self._trip])})")
                self._last_print = time.perf_counter()
            if distance_in_drive_direction < 0 and abs(self.train._speed) > 0 and self._use_emergency_stop:
                print(f"Emergency stop {self} due to overshoot.", file=sys.stderr)
                self.train.emergency_stop()
            if distance_in_drive_direction <= braking_distance:
                self._brake_wait()
            elif distance_in_drive_direction <= braking_distance + 100:  # Go slowly for the last 4 cm
                target_speed = min(abs(self.train._speed), 20) if self._braking else 20
                self.train.set_target_speed(target_speed * (1 if self._increase_signed_distance else -1))
            else:
                target_speed = min(abs(self.train._speed), self._max_speed) if self._braking else self._max_speed
                self.train.set_target_speed(target_speed * (1 if self._increase_signed_distance else -1))

    def _brake_wait(self):
        """ Breaks if driving, else sets executing=False if pause is over. """
        if self._trip and trains.GENERATOR.serial_port:
            print(f"⚠ Cannot brake/wait because {CONTACT_NAMES[self._trip[0][0]]} contact has not been tripped.", file=sys.stderr)
            return
        self._braking = True
        if self.train.target_speed == 0:
            if self._t_started_waiting is None:
                if abs(self.train.signed_actual_speed) < 1:
                    self._t_started_waiting = time.perf_counter()
            elif time.perf_counter() - self._t_started_waiting >= self._next_pause:
                if self._executing:
                    print(f"{self.train.name} done {self.state}")
                    self._executing = False
        else:
            self.train.set_target_speed(0)

    def __repr__(self):
        if self._target_signed_distance is not None:
            status = f"{self._target_signed_distance - self.train.cumulative_signed_distance:.0f} mm from target"
        else:
            status = "done"
        return f"{self.train.name} @ {self.state} {status}"


def program():
    print(f"🛈 Starting signal output on {trains.GENERATOR.serial_port}.")
    trains.power_on()
    print("🛈 Waiting for contacts to be initialized")
    try:  # Wait for contacts to be initialized.
        trains.GENERATOR.await_event([], [True, False], timeout=1)
    except queue.Empty:
        pass
    while trains.GENERATOR.is_short_circuited:  # no power or short-circuited
        print("⚠ No power on tracks. Program will start once tracks are on-line.", file=sys.stderr)
        time.sleep(10)
    print(f"Status: outer={trains.GENERATOR.get_state(OUTER_CONTACT)}, inner={trains.GENERATOR.get_state(INNER_CONTACT)}, airport={trains.GENERATOR.get_state(AIRPORT_CONTACT)}")
    if math.isnan(GTO.position) or math.isnan(IGBT.position):
        detect_train_positions_from_scratch()
        GTO.drive(O_MUNICH, pause=5)  # trip=[(OUTER_CONTACT, O_CONTACT_NORTH-TRAIN_CONTACT)])
        IGBT.drive(0, pause=0, trip=[(INNER_CONTACT, I_CONTACT_NORTH - TRAIN_CONTACT)])
    else:
        move_to_standard_pos()
    if 'opening' in sys.argv:
        opening_round()
        regular_round(pause=8., pause_random=10.)
    else:
        if 'no-sound' not in sys.argv:
            GTO.train.sound_on()
            IGBT.train.sound_on()
    modules = [regular_round, outside_fast, both_outside]
    module_index = randint(0, len(modules) - 1)
    if 'regular' in sys.argv:
        module_index = 0
    if 'fast' in sys.argv:
        module_index = 1
    if 'outside' in sys.argv:
        module_index = 2
    while True:
        if not DEBUG:
            # AC is checked by power monitor, no need to do it here.
            now = datetime.datetime.now()
            if now.minute % 15 > 1:  # :00:00 - :01:59 (2 minutes)
                IGBT.wait()
                GTO.wait()
                time.sleep(10)
                trains.power_off()
                now = datetime.datetime.now()
                if now.hour == 16 and now.minute > 45:
                    print(f"The museum is closing. Time: {now}. Shutting down.")
                    write_current_state()
                    set_wake_time(tomorrow_at(), shutdown_now=True)
                    exit()
                    return
                wait_minutes = 15 - (now.minute % 15)
                next_minute = (now.minute + wait_minutes) % 60
                next_time = now.replace(hour=now.hour if next_minute else now.hour + 1, minute=next_minute, second=0, microsecond=0)
                wait_sec = (next_time - now).total_seconds()
                print(f"---------------- Waiting {wait_minutes} minutes ({wait_sec:.0f} s, power 30s earlier) ----------------")
                time.sleep(max(0., wait_sec - 30))
                trains.power_on()
                time.sleep(30)
                correct_positions_based_on_contacts()
        module = modules[module_index]
        if 'measure' in sys.argv:
            IGBT.wait()
            GTO.wait()
            print("~~ Beginning measurement ~~")
            module_start_time = time.perf_counter()
        print("                         Queuing module")
        module(pause=10., pause_random=15)
        module_index = (module_index + 1) % len(modules)
        if 'measure' in sys.argv:
            IGBT.wait()
            GTO.wait()
            module_end_time = time.perf_counter()
            print(f"~~ Module took {module_end_time - module_start_time} seconds ({(module_end_time - module_start_time) * trains.TIME_DILATION / 60:.1f} minutes real time). ~~")

        
def regular_round(pause: float, pause_random: float, rounds=2):
    for i in range(rounds):
        print(f"------------------ Regular round {i} / {rounds} ------------------")
        IGBT.drive(I_AIRPORT, pause=pause + random() * pause_random)
        GTO.drive(OUTER + O_ERDING, pause=pause + random() * pause_random)
        IGBT.drive(I_ERDING, pause=pause + random() * pause_random)
        GTO.drive(O_AIRPORT, pause=pause + random() * pause_random)
        IGBT.drive(INNER + abs(I_SAFE_REVERSAL), pause=0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
        GTO.drive(O_MUNICH, pause=pause + random() * pause_random, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
        IGBT.drive(0, pause=pause + random() * pause_random)


def opening_round():
    print("------------------------- Opening Round ----------------------")
    IGBT.drive(I_AIRPORT, pause=0, wait_for='done')
    print()
    print("Press Enter to Start")
    input()
    if 'no-sound' not in sys.argv:
        GTO.train.sound_on()
        IGBT.train.sound_on()
    GTO.drive(OUTER + O_ERDING, pause=25)
    time.sleep(6)
    IGBT.drive(I_ERDING, pause=20)
    # Keep going to standard position
    IGBT.drive(INNER, pause=5)
    GTO.drive(O_AIRPORT, pause=7)
    IGBT.drive(INNER + abs(I_SAFE_REVERSAL), pause=0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
    GTO.drive(O_MUNICH, pause=8, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])


def outside_fast(pause: float, pause_random: float, rounds=4):
    print("------------------ Outside fast ------------------")
    contacts = [(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT + OUTER * (i + 1)) for i in range(rounds)]
    for i in range(2):
        GTO.drive(OUTER * rounds + O_MUNICH, pause=pause + random() * pause_random, trip=contacts)
        IGBT.drive(I_AIRPORT, pause=pause + random() * pause_random)
        IGBT.drive(I_ERDING, pause=pause + random() * pause_random)
        IGBT.drive(INNER + abs(I_SAFE_REVERSAL), pause=0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
        IGBT.drive(I_MUNICH, pause=pause + random() * pause_random)


def both_outside(pause: float, pause_random: float, rounds=1):
    assert rounds >= 1, "not implemented for rounds=0"
    if not IGBT.aligned:
        print("---------------------- Switching direction of inner ---------------")
        IGBT.drive(INNER + abs(I_SAFE_REVERSAL), pause=0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
    print("------------------ Exiting inner round -------------------")
    if HALF_TRAIN + 100 < GTO.position < O_SAFE_WAIT:
        GTO.drive(OUTER + O_SAFE_WAIT, pause=0, wait_for='brake')
    IGBT.drive(-INTERIM - INNER_CONNECTION - (OUTER_UNTIL_SWITCH - O_ERDING), pause=pause/2 + random() * pause_random / 2, trip=[(AIRPORT_CONTACT, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT)])
    for i in range(rounds):
        print(f"-------------------- Both outer {i} / {rounds} ----------------------")
        GTO.drive(O_MUNICH, pause=pause + random() * pause_random, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
        IGBT.drive(O_AIRPORT, pause=pause + random() * pause_random, wait_for='brake')
        GTO.drive(OUTER + O_ERDING, pause=pause + random() * pause_random, wait_for='brake')
        IGBT.drive(O_MUNICH, pause=pause + random() * pause_random, wait_for='brake', trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
        GTO.drive(O_AIRPORT, pause=pause + random() * pause_random, wait_for='brake')
        IGBT.drive(OUTER + O_ERDING, pause=pause + random() * pause_random, wait_for='brake')
    print("----------------------- Entering inner round -----------------------")
    GTO.drive(O_SAFE_WAIT, pause=0)
    IGBT.drive(- OUTER_CONNECTION - HALF_TRAIN - 250, pause=0, trip=[(INNER_CONTACT, I_CONTACT_SOUTH_O)], wait_for='done')
    GTO.drive(O_MUNICH, pause=pause + random() * pause_random, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
    IGBT.drive(I_MUNICH, pause=pause + random() * pause_random)


def detect_train_positions_from_scratch():
    print("--------------- Detecting positions ----------------")
    trains.GENERATOR.register('detect')
    GTO.state = State(GTO.train.cumulative_signed_distance, True, NAN, True)
    IGBT.state = State(GTO.train.cumulative_signed_distance, None, NAN, None)
    if trains.GENERATOR.get_state(AIRPORT_CONTACT) is False:
        print("IGBT already on inner")
        IGBT.train.set_target_speed(-50)
        try:
            trains.GENERATOR.await_event([OUTER_CONTACT, INNER_CONTACT, AIRPORT_CONTACT], [True], timeout=10, listener='detect')
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT, False)
            IGBT.emergency_stop()
        except queue.Empty:
            print("IGBT not moving.")
    else:
        print("Moving IGBT")
        IGBT.train.set_target_speed(50)
    print("Moving GTO")
    GTO.train.set_target_speed(50)
    while math.isnan(GTO.position) or math.isnan(IGBT.position):
        try:
            pin, _ = trains.GENERATOR.await_event([OUTER_CONTACT, INNER_CONTACT, AIRPORT_CONTACT], [False], timeout=60, listener='detect')
            print(f"Tripped {pin}")
        except queue.Empty:
            print("Train not moving. Outer contact timeout after 60s.")
            return
        if pin == OUTER_CONTACT:
            print("Outer contact tripped: which train is it?")
            GTO.emergency_stop()
            IGBT.emergency_stop()
            if IGBT.outer_track is False:
                print("It must have been GTO because IGBT is inside.")
                GTO.state = State(GTO.train.cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
            else:
                time.sleep(1)
                GTO.train.set_target_speed(-50)
                try:
                    trains.GENERATOR.await_event([pin], [True], timeout=5, listener='detect')
                    print("It was GTO (outer)")
                    GTO.state = State(GTO.train.cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
                    IGBT.train.set_target_speed(50)
                except queue.Empty:
                    IGBT.train.set_target_speed(-50)
                    try:
                        trains.GENERATOR.await_event([pin], [True], timeout=5, listener='detect')
                        print("It was IGBT (usually inner)")
                        IGBT.state = State(IGBT.train.cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
                    except queue.Empty:
                        print("Train failed to move backwards. Check contact")
                        GTO.train.set_target_speed(50)
                        IGBT.train.set_target_speed(50)
                GTO.emergency_stop()
        elif pin == AIRPORT_CONTACT:
            print("Airport contact")
            IGBT.emergency_stop()
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT, False)
        elif pin == INNER_CONTACT:
            print("Inner contact tripped")
            pass  # this does not tell us much yet. We only know IGBT is on inner track now
    trains.GENERATOR.unregister('detect')
    print(f"Detection complete. Trains in starting positions.")


def correct_positions_based_on_contacts():
    print("Checking contacts and updating positions")
    if trains.GENERATOR.get_state(AIRPORT_CONTACT) is False:
        print("IGBT on airport contact")
        if IGBT.position > I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT or IGBT.outer_track:
            print("correcting IGBT position to airport contact")
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT, IGBT.aligned)
    if trains.GENERATOR.get_state(OUTER_CONTACT) is False and not IGBT.outer_track:
        print("GTO on outer contact")
        if GTO.position < O_CONTACT_NORTH - TRAIN_CONTACT:
            print("correcting GTO position to outer contact")
            GTO.state = State(GTO.train.cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT + 10, True)
    if trains.GENERATOR.get_state(INNER_CONTACT) is False:
        if IGBT.outer_track:
            print("correcting IGBT position to inner contact (from outer ring)")
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, (I_CONTACT_SOUTH + I_CONTACT_NORTH) / 2, IGBT.aligned)
        elif IGBT.position > I_CONTACT_SOUTH + TRAIN_CONTACT:
            print("correcting IGBT position to inner contact (from inner ring)")
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_CONTACT_SOUTH - 100, IGBT.aligned if IGBT.position < 1000 else not IGBT.aligned)
            if IGBT.position >= 1000:
                print("correcting IGBT alignment, assuming it finished the ring.")
        elif IGBT.position < I_CONTACT_NORTH - TRAIN_CONTACT:
            print("correcting IGBT position to inner contact (from airport)")
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_CONTACT_NORTH + 100, IGBT.aligned)


def move_to_standard_pos():
    print("---------------- Moving to standard positions -----------------")
    print(f"Current position estimate: {GTO}, {IGBT}")
    # --- Check contacts, update train positions if tripped ---
    correct_positions_based_on_contacts()
    print(f"Assumed positions: {GTO}, {IGBT}")
    # --- Move trains to standard positions ---
    # --- IGBT on inner track ---
    if IGBT.inner_track and IGBT.position > -INNER_CONNECTION-INTERIM+2*HALF_TRAIN + 100:
        if IGBT.inner_track and -20 < IGBT.position < 2000:
            IGBT.drive(I_SAFE_REVERSAL, 0, trip=[(INNER_CONTACT, I_CONTACT_SOUTH + TRAIN_CONTACT)])
        elif IGBT.inner_track and IGBT.position >= 2000:
            IGBT.drive(INNER + abs(I_SAFE_REVERSAL), 0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
        elif IGBT.inner_track and -INNER_CONNECTION-INTERIM+2*HALF_TRAIN + 100 < IGBT.position <= -20:  # On interim
            IGBT.drive(I_AIRPORT_CONTACT_WEST, 0, trip=[(AIRPORT_CONTACT, I_AIRPORT_CONTACT_WEST+TRAIN_CONTACT)], use_emergency_stop=True, max_speed=40)
            IGBT.drive(I_AIRPORT_CONTACT_WEST+TRAIN_CONTACT+100, 0)
        if GTO.position < O_CONTACT_NORTH-TRAIN_CONTACT and check_not_triggered(OUTER_CONTACT):
            GTO.drive(O_MUNICH, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)], max_speed=50)
        else:
            GTO.drive(OUTER + O_ERDING, 0)
            GTO.drive(O_MUNICH, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH-TRAIN_CONTACT)], max_speed=50, use_emergency_stop=True)
        IGBT.drive(I_MUNICH, 0)
    # --- IGBT on outer ---
    elif IGBT.inner_track:  # IGBT on airport switch
        if GTO.position < OUTER_UNTIL_SWITCH:
            GTO.drive(HALF_TRAIN + 100, 0)
        else:
            GTO.drive(O_MUNICH, 0)
        IGBT.drive(-INTERIM - INNER_CONNECTION - (OUTER_UNTIL_SWITCH - O_ERDING), 0)
        IGBT.drive(OUTER + HALF_TRAIN + 100, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH-HALF_TRAIN)])
        if GTO.position > OUTER - HALF_TRAIN - 100:
            GTO.drive(O_SAFE_WAIT + OUTER, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH-HALF_TRAIN)])
        else:
            GTO.drive(O_SAFE_WAIT, 0)
        IGBT.drive(- OUTER_CONNECTION - HALF_TRAIN - 250, 0, trip=[(INNER_CONTACT, I_CONTACT_SOUTH_O)], wait_for='done')
        GTO.drive(O_MUNICH, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)], use_emergency_stop=True)
        IGBT.drive(I_MUNICH, 0)
    elif IGBT.outer_track and IGBT.position < GTO.position < O_CONTACT_NORTH - TRAIN_CONTACT and check_not_triggered(OUTER_CONTACT):
        print("Reversing IGBT into inner track")
        IGBT.drive(- OUTER_CONNECTION - HALF_TRAIN - 250, 0, trip=[(INNER_CONTACT, I_CONTACT_SOUTH_O)], wait_for='done')
        GTO.drive(O_MUNICH, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)], use_emergency_stop=True)
        IGBT.drive(I_MUNICH, 0)
    elif IGBT.outer_track:
        IGBT.drive(OUTER + HALF_TRAIN + 100, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - HALF_TRAIN)])
        if GTO.position > OUTER - HALF_TRAIN - 100:
            GTO.drive(O_SAFE_WAIT + OUTER, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - HALF_TRAIN)])
        else:
            GTO.drive(O_SAFE_WAIT, 0)
        IGBT.drive(- OUTER_CONNECTION - HALF_TRAIN - 250, 0, trip=[(INNER_CONTACT, I_CONTACT_SOUTH_O)], wait_for='done')
        GTO.drive(O_MUNICH, 0, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)], use_emergency_stop=True)
        IGBT.drive(I_MUNICH, 0)
    else:
        print(f"Unknown configuration: {GTO}, {IGBT}", file=sys.stderr)
        raise NotImplementedError(f"Unknown configuration: {GTO}, {IGBT}")
    print(f"Finished move to standard pos. Now {GTO}, {IGBT}")


def check_not_triggered(contact):
    return VIRTUAL or trains.GENERATOR.get_state(contact) is True


def check_triggered(contact):
    return VIRTUAL or trains.GENERATOR.get_state(contact) is False


def measure_speeds():
    controller = GTO
    print(f"Measuring speed of {GTO.train.name}")
    trains.GENERATOR.register('timer')
    controller.train.set_target_speed(100)
    controller.train.acceleration = 1000
    trains.power_on()
    measured = [0] + [None] * 14
    for speed_i, target_speed in reversed(tuple(enumerate(controller.train.speeds))):
        # if speed_i >= 13:
        #     continue
        print(f"Speed {speed_i} (prior {target_speed} kmh)")
        controller.train.set_target_speed(target_speed)
        for round_i in range(2 if speed_i > 5 else 1):
            t0 = time.perf_counter()
            trains.GENERATOR.await_event([OUTER_CONTACT], [False], listener='timer')
            t = time.perf_counter() - t0
            kmh = OUTER / t * 87 * 3.6 / 1000
            if round_i == 0 and speed_i > 5:
                print(f"Warmup: {t}")
            else:
                print(f"Round time: {t}, kmh={kmh}")
            measured[speed_i] = kmh
            print(f"({', '.join([f'{v:.1f}' if v is not None else '0' for v in measured])})")


def choose_index(counts):
    max_count = max(counts)
    for i, c in enumerate(counts):
        if c < max_count / 2:
            return i
    return randint(0, len(counts) - 1)


def write_current_state(_dt=None):
    LOG.write(f"{str(GTO.state)},{str(IGBT.state)}\n")
    LOG.flush()


def monitor_power():
    print("🛈 Power monitor engaged.")
    while True:
        time.sleep(1)
        if not trains.GENERATOR:
            continue
        if trains.GENERATOR.is_short_circuited and pc_has_power():  # likely short-circuited
            print("⚠ No power on track or short-circuited but PC still has power. (power monitor)", file=sys.stderr)
            time.sleep(19)
            trains.GENERATOR.start()
        if not pc_has_power():
            print("⚠ PC has no power. Shutting down. (power monitor)", file=sys.stderr)
            write_current_state()
            set_wake_time(tomorrow_at(), shutdown_now=True)
            exit()
            return


if __name__ == '__main__':
    print("sys.argv:", sys.argv)
    VIRTUAL = 'virtual' in sys.argv
    DEBUG = 'debug' in sys.argv
    if VIRTUAL and DEBUG:
        trains.TIME_DILATION = 10

    launch_time = time.perf_counter()
    if not DEBUG:
        while not pc_has_power():
            print(f"Waiting for AC... ({time.perf_counter() - launch_time:.0f} / {5 * 60} s)")
            if time.perf_counter() - launch_time < 5 * 60:
                time.sleep(5)
            else:
                set_wake_time(tomorrow_at(), shutdown_now=True)
        Thread(target=monitor_power).start()

    _LAST_POSITIONS = read_last_positions()
    GTO = Controller(trains.get_by_name('GTO'), _LAST_POSITIONS[0] or State(0, True, NAN, True))
    IGBT = Controller(trains.get_by_name('IGBT'), _LAST_POSITIONS[1] or State(0, None, NAN, None))

    if not VIRTUAL:
        LOG = create_log_file()
        write_current_state(0)
        schedule_at_fixed_rate(write_current_state, period=2.)

    if VIRTUAL:
        port = None
    elif platform.system() == 'Windows':
        port = 'COM5'
    else:
        port = '/dev/ttyUSB0'
    print(f"🛈 Preparing signal generator for port '{port}'")
    trains.setup(port)

    Thread(target=program).start()

    print(IGBT)
    print(GTO)
    import plan_vis
    plan_vis.show([GTO, IGBT])

