import math
import platform
import queue
import time
from random import random, randint
import sys
from threading import Thread, Lock
from typing import Tuple

from fpme import trains
from fpme.helper import schedule_at_fixed_rate
from fpme.museum_track import *
from fpme.ubuntu_helpers import *
import math
import queue
import sys
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
        print(f"Creating controller for {train}")
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

    def drive(self, target_position, pause: float or None, trip: List[Tuple[str, float]] = (), wait_for=None):
        """
        Blocks until previous operation finished.

        :param target_position: Target position on the track in mm.
        :param pause: Duration to wait after stopping in seconds.
        :param trip: Contacts to trip along the way, (pin, position)
        :param wait_for: One of 'brake', 'done', None
        """
        print(f"{self.train.name} add command to queue: drive to {target_position} tripping {len(trip)}")
        while self._executing:
            time.sleep(.2)
        if VIRTUAL:
            trip = []
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
        print(f">>> {self.train.name} -> drive {distance_mm:.0f} mm to position {State(0, self.state.outer_track, target_position, self.aligned)}. Trip: {', '.join([CONTACT_NAMES[pin] + f' @ {pos:.0f}' for pin, pos in self._trip])}")
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
            p_position = project_position(position, self.state.outer_track)
            with self._update_lock:
                self.state = update_state(self.state, self.train.cumulative_signed_distance)
                delta = p_position - self.position
                self_prev = str(self)
                if abs(delta) > 1000:
                    if abs(position - self.position) < 1000:  # The train has not crossed projection threshold yet
                        p_position = position
                        delta = position - self.position
                        print(f"⚠ {self} triggered {CONTACT_NAMES[pin]} before crossing projection threshold. Using non-projected position to compute delta.", file=sys.stderr)
                    else:
                        print(f"⚠ {self} triggered {CONTACT_NAMES[pin]}, would update position by {delta} mm (actual - predicted) which is no plausible. Stopping train. Specified position={position}, projected={p_position}", file=sys.stderr)
                        self.emergency_stop()
                        continue
                self.state = State(self.train.cumulative_signed_distance, self.state.outer_track, p_position, self.aligned)
                self.state = update_state(self.state, self.state.cumulative_signed_distance)
                self._target_signed_distance -= delta
                print(f"🛈 {self} triggered {CONTACT_NAMES[pin]}, position updated by {delta} mm (actual - predicted) from {self_prev}", file=sys.stderr)
                self._trip.pop(0)
                self._contact_to_target.pop(0)

    @property
    def position(self):
        return self.state.position
    
    @property
    def aligned(self):
        return self.state.aligned
    
    def emergency_stop(self):
        self.train.emergency_stop()

    def _update(self):
        with self._update_lock:
            prev_state = self.state
            self.state = update_state(self.state, self.train.cumulative_signed_distance)
            if not self._executing:
                return
            braking_distance = .5 * (self.train.deceleration / 3.6) * (abs(self.train.signed_actual_speed) / self.train.deceleration) ** 2 * 1000 / 87  # always positive
            distance_in_drive_direction = (self._target_signed_distance - self.train.cumulative_signed_distance) * (1 if self._increase_signed_distance else -1)  # positive unless overshot
            if self._trip and trains.GENERATOR.serial_port:
                if self._contact_to_target[0] > distance_in_drive_direction:
                    distance_in_drive_direction = self._contact_to_target[0]
                    self.state = State(self.state.cumulative_signed_distance, prev_state.outer_track, prev_state.position, prev_state.aligned)
            if time.perf_counter() - self._last_print >= 4.:
                print(f"{self}\t speed={self.train.signed_actual_speed:.0f} -> {self.train.signed_target_speed}\t to drive:  {distance_in_drive_direction:.0f}\t  brake: {braking_distance:.0f}\t   (cumulative={self.train.cumulative_signed_distance:.0f}, trip={', '.join([CONTACT_NAMES[pin] + f' @ {pos:.0f}' for pin, pos in self._trip])})")
                self._last_print = time.perf_counter()
            if distance_in_drive_direction <= braking_distance:
                self._brake_wait()
            elif distance_in_drive_direction <= braking_distance + 100:  # Go slowly for the last 4 cm
                target_speed = min(abs(self.train._speed), 20) if self._braking else 20
                self.train.set_target_speed(target_speed * (1 if self._increase_signed_distance else -1))
            else:
                target_speed = min(abs(self.train._speed), 80) if self._braking else 80
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
    print("Power on")
    trains.power_on()
    print("Waiting for contacts to be initialized")
    try:  # Wait for contacts to be initialized.
        trains.GENERATOR.await_event([], [True, False], timeout=1)
    except queue.Empty:
        pass
    while trains.GENERATOR.is_short_circuited:  # no power or short-circuited
        print("No power on tracks")
        time.sleep(10)
    print(f"Status: outer={trains.GENERATOR.get_state(OUTER_CONTACT)}, inner={trains.GENERATOR.get_state(INNER_CONTACT)}, airport={trains.GENERATOR.get_state(AIRPORT_CONTACT)}")
    if math.isnan(GTO.position) or math.isnan(IGBT.position):
        detect_train_positions_from_scratch()
    else:
        move_to_standard_pos()
    GTO.drive(O_MUNICH, pause=5)  # trip=[(OUTER_CONTACT, O_CONTACT_NORTH-TRAIN_CONTACT)])
    if 'opening' in sys.argv:
        opening_round()
        regular_round(pause=8., pause_random=10.)
    else:
        IGBT.drive(0, pause=0, trip=[(INNER_CONTACT, I_CONTACT_NORTH - TRAIN_CONTACT)])
        if 'no-sound' not in sys.argv:
            GTO.train.sound_on()
            IGBT.train.sound_on()
    modules = [regular_round, outside_fast, both_outside]
    module_stats = [0] * len(modules)
    while True:
        if not DEBUG:
            if not pc_has_power():
                write_current_state()
                set_wake_time(tomorrow_at(), shutdown_now=True)
                exit()
                return
            now = datetime.datetime.now()
            if now.minute % 20 > 5:
                module_stats = [0] * len(modules)  # Reset module counter
                wait_minutes = 20 - (now.minute % 20)
                next_minute = (now.minute + wait_minutes) % 60
                next_time = now.replace(hour=now.hour if next_minute else now.hour + 1, minute=next_minute, second=0, microsecond=0)
                wait_sec = (next_time - now).total_seconds()
                print(f"---------------- Waiting {wait_minutes} minutes ({wait_sec} s) ----------------")
                time.sleep(wait_sec)
        module = modules[choose_index(module_stats)]
        print("                         Queuing module")
        module(pause=5. if DEBUG else 10., pause_random=0 if DEBUG else 15)

        
def regular_round(pause: float, pause_random: float, rounds=1):
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
    if 'no-sound' not in sys.argv:
        GTO.train.sound_on()
        IGBT.train.sound_on()
    GTO.drive(OUTER + O_ERDING, pause=25)
    time.sleep(6)
    IGBT.drive(I_ERDING + 50, pause=20)
    # Keep going to standard position
    IGBT.drive(INNER, pause=5)
    GTO.drive(O_AIRPORT, pause=7)
    IGBT.drive(INNER + abs(I_SAFE_REVERSAL), pause=0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
    GTO.drive(O_MUNICH, pause=8, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])


def outside_fast(pause: float, pause_random: float, rounds=3):
    print("------------------ Outside fast ------------------")
    contacts = [(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT + OUTER * (i + 1)) for i in range(rounds)]
    GTO.drive(OUTER * rounds + O_MUNICH, pause=pause + random() * pause_random, trip=contacts)
    for i in range(1 + rounds // 5):
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
    GTO.drive(OUTER + 3500, pause=0, wait_for='brake')
    IGBT.drive(-INTERIM - INNER_CONNECTION - (OUTER_UNTIL_SWITCH - O_ERDING), pause=pause + random() * pause_random, trip=[(AIRPORT_CONTACT, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT)])
    for i in range(rounds):
        print(f"-------------------- Both outer {i} / {rounds} ----------------------")
        GTO.drive(O_MUNICH, pause=pause + random() * pause_random, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
        IGBT.drive(O_AIRPORT, pause=pause + random() * pause_random, wait_for='brake')
        GTO.drive(OUTER + O_ERDING, pause=pause + random() * pause_random, wait_for='brake')
        IGBT.drive(O_MUNICH, pause=pause + random() * pause_random, wait_for='brake', trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
        GTO.drive(O_AIRPORT, pause=pause + random() * pause_random, wait_for='brake')
        IGBT.drive(OUTER + O_ERDING, pause=pause + random() * pause_random, wait_for='brake')
    print("----------------------- Entering inner round -----------------------")
    GTO.drive(3500, pause=0)
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
            if IGBT.state.outer_track is False:
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


def move_to_standard_pos():
    print("---------------- Moving to standard positions -----------------")
    print(f"Current position estimate: {GTO}, {IGBT}")
    trains.GENERATOR.register('detect')
    if trains.GENERATOR.get_state(AIRPORT_CONTACT) is False:
        print("IGBT already on inner (airport contact)")
        if IGBT.position > I_AIRPORT_CONTACT_WEST + HALF_TRAIN:
            print("correcting IGBT position to airport contact")
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + HALF_TRAIN, IGBT.aligned)
        elif IGBT.position < - INNER_CONNECTION - INTERIM + HALF_TRAIN:
            print("IGBT on airport switch")
            raise NotImplementedError
    if IGBT.state.outer_track:
        print("IGBT last seen on outer track")
        # move GTO to a safe position
        # reverse IGBT until on interim
        raise NotImplementedError
    elif trains.GENERATOR.get_state(AIRPORT_CONTACT) is True:
        print("IGBT last seen on inner track")
        if -INTERIM < IGBT.position < -HALF_TRAIN:
            print("Driving IGBT to airport contact")
            IGBT.train.set_target_speed(-50 if IGBT.aligned else 50)
            aligned = IGBT.aligned
        elif IGBT.position < -INTERIM:
            # move GTO to a safe position
            # drive a full round
            raise NotImplementedError
        elif IGBT.position < 2000:
            print("Driving IGBT to airport contact, reverse-exiting the circle")
            IGBT.train.set_target_speed(-50 if IGBT.aligned else 50)
            aligned = IGBT.aligned
        else:  # on inner circle
            print("IGBT continue driving circle")
            IGBT.train.set_target_speed(50 if IGBT.aligned else -50)
            aligned = not IGBT.aligned
        try:
            trains.GENERATOR.await_event([AIRPORT_CONTACT], [False], timeout=60, listener='detect')
            IGBT.emergency_stop()
            IGBT.state = State(IGBT.train.cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST+TRAIN_CONTACT, aligned)
            print("IGBT arrived at airport contact")
        except queue.Empty:
            print("IGBT not moving")

    if trains.GENERATOR.get_state(OUTER_CONTACT) is not False:
        # drive GTO to outer contact
        GTO.train.set_target_speed(50)
        try:
            trains.GENERATOR.await_event([OUTER_CONTACT], [False], timeout=60, listener='detect')
            GTO.state = State(GTO.train.cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
            GTO.emergency_stop()
        except queue.Empty:
            print("GTO not moving")
                
    trains.GENERATOR.unregister('detect')
    print(f"Finished move to standard pos. Now {GTO}, {IGBT}")
    time.sleep(2)


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


if __name__ == '__main__':
    print("sys.argv:", sys.argv)
    DEBUG = 'debug' in sys.argv

    launch_time = time.perf_counter()
    if not DEBUG:
        while not pc_has_power():
            print("Waiting for AC...")
            if time.perf_counter() - launch_time < 5 * 60:
                time.sleep(5)
            else:
                set_wake_time(tomorrow_at(), shutdown_now=True)

    _LAST_POSITIONS = read_last_positions()
    GTO = Controller(trains.get_by_name('GTO'), _LAST_POSITIONS[0] or State(0, True, NAN, True))
    IGBT = Controller(trains.get_by_name('IGBT'), _LAST_POSITIONS[1] or State(0, None, NAN, None))

    LOG = create_log_file()
    write_current_state(0)
    schedule_at_fixed_rate(write_current_state, period=2.)

    VIRTUAL = 'virtual' in sys.argv
    if VIRTUAL:
        port = None
    elif platform.system() == 'Windows':
        port = 'COM5'
    else:
        port = '/dev/ttyUSB0'
    print(f"Setting up signal generator on port '{port}'")
    trains.setup(port)

    Thread(target=program).start()
    if 'gui' in sys.argv:
        import plan_vis
        plan_vis.show([GTO, IGBT])

