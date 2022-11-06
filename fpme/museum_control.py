import math
import queue
import sys
import time
from threading import Thread
from typing import List, Tuple

from fpme import trains
from fpme.helper import schedule_at_fixed_rate
from fpme.museum_track import *


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

    def drive(self, target_position, pause: float or None, trip: List[Tuple[str, float]] = ()):
        """
        Blocks until previous operation finished.

        :param target_position: Target position on the track in mm.
        :param pause: Duration to wait after stopping in seconds.
        :param trip: Contacts to trip along the way, (pin, position)
        :return:
        """
        print(f"{self.train.name} add command to queue: drive to {target_position} tripping {len(trip)}")
        while self._executing:
            time.sleep(.2)
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

    def _count_triggers(self):
        assert isinstance(self._trip, list)
        while self._trip:
            pin, position = self._trip[0]
            print(f"{self.train} waiting for {pin}")
            trains.GENERATOR.await_event([pin], [False], timeout=None)
            p_position = project_position(position, self.state.outer_track)
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
            self.state = State(self.train._cumulative_signed_distance, self.state.outer_track, p_position, self.aligned)
            self.state = update_state(self.state, self.state.cumulative_signed_distance)
            self._target_signed_distance += delta
            print(f"🛈 {self} triggered {CONTACT_NAMES[pin]}, position updated by {delta} mm (actual - predicted) from {self_prev}")
            self._trip.pop(0)
            self._contact_to_target.pop(0)
        # trains.GENERATOR.unregister(self)

    @property
    def position(self):
        return self.state.position
    
    @property
    def aligned(self):
        return self.state.aligned
    
    def emergency_stop(self):
        self.train.emergency_stop()

    def _update(self):
        prev_state = self.state
        self.state = update_state(self.state, self.train._cumulative_signed_distance)
        if not self._executing:
            return
        braking_distance = .5 * (self.train.deceleration / 3.6) * (abs(self.train.signed_actual_speed) / self.train.deceleration) ** 2 * 1000 / 87  # always positive
        distance_in_drive_direction = (self._target_signed_distance - self.train._cumulative_signed_distance) * (1 if self._increase_signed_distance else -1)  # positive unless overshot
        if self._trip and trains.GENERATOR.serial_port:
            if self._contact_to_target[0] > distance_in_drive_direction:
                distance_in_drive_direction = self._contact_to_target[0]
                self.state = State(self.state.cumulative_signed_distance, prev_state.outer_track, prev_state.position, prev_state.aligned)
        if time.perf_counter() - self._last_print >= 2.:
            print(f"{self}\t speed={self.train.signed_actual_speed:.0f} -> {self.train.signed_target_speed}\t to drive:  {distance_in_drive_direction:.0f}\t  brake: {braking_distance:.0f}\t   (aligned={self.aligned}, in_reverse={self.train.in_reverse}, increase_sd={self._increase_signed_distance}, cumulative={self.train._cumulative_signed_distance:.0f}, #trip={len(self._trip)})")
            self._last_print = time.perf_counter()
        if distance_in_drive_direction <= braking_distance:
            self._brake_wait()
        elif distance_in_drive_direction <= braking_distance + 100:  # Go slowly for the last 4 cm
            target_speed = min(abs(self.train._speed), 20) if self._braking else 20
            self.train.set_target_speed(target_speed * (1 if self._increase_signed_distance else -1))
        else:
            self.train.set_target_speed(80 * (1 if self._increase_signed_distance else -1))

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
            status = f"{self._target_signed_distance - self.train._cumulative_signed_distance:.0f} mm from target"
        else:
            status = "done"
        return f"{self.train.name} @ {self.state} {status}"


def program():
    # GTO.train.sound_on()
    # IGBT.train.sound_on()
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
    # Run to check notebook AC
    # $ cat /proc/acpi/ac_adapter/ACAD/state
    # state:                   on-line
    print(f"Status: outer={trains.GENERATOR.get_state(OUTER_CONTACT)}, inner={trains.GENERATOR.get_state(INNER_CONTACT)}, airport={trains.GENERATOR.get_state(AIRPORT_CONTACT)}")
    if math.isnan(GTO.position) or math.isnan(IGBT.position):
        detect_train_positions_from_scratch()
    else:
        move_to_standard_pos()
    print(f"IGBT at {IGBT.position:.0f}")
    # time.sleep(30)
    IGBT.drive(0, pause=5, trip=[(INNER_CONTACT, I_CONTACT_NORTH - TRAIN_CONTACT)])
    GTO.drive(O_MUNICH, pause=5)
    while True:
        IGBT.drive(I_AIRPORT, pause=5)
        GTO.drive(OUTER + O_ERDING, pause=5)
        IGBT.drive(I_ERDING, pause=5)
        GTO.drive(O_AIRPORT, pause=5)
        IGBT.drive(INNER + abs(I_SAFE_REVERSAL), pause=0, trip=[(INNER_CONTACT, INNER + abs(I_CONTACT_SOUTH) - TRAIN_CONTACT)])
        GTO.drive(O_MUNICH, pause=5, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])
        IGBT.drive(0, pause=5)


def detect_train_positions_from_scratch():
    print(">>> Detecting positions")
    trains.GENERATOR.register('detect')
    GTO.state = State(GTO.train._cumulative_signed_distance, True, NAN, True)
    IGBT.state = State(GTO.train._cumulative_signed_distance, None, NAN, None)
    if trains.GENERATOR.get_state(AIRPORT_CONTACT) is False:
        print("IGBT already on inner")
        IGBT.train.set_target_speed(-50)
        try:
            trains.GENERATOR.await_event([OUTER_CONTACT, INNER_CONTACT, AIRPORT_CONTACT], [True], timeout=10, listener='detect')
            IGBT.state = State(IGBT.train._cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT, False)
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
                GTO.state = State(GTO.train._cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
            else:
                time.sleep(1)
                GTO.train.set_target_speed(-50)
                try:
                    trains.GENERATOR.await_event([pin], [True], timeout=5, listener='detect')
                    print("It was GTO (outer)")
                    GTO.state = State(GTO.train._cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
                    IGBT.train.set_target_speed(50)
                except queue.Empty:
                    IGBT.train.set_target_speed(-50)
                    try:
                        trains.GENERATOR.await_event([pin], [True], timeout=5, listener='detect')
                        print("It was IGBT (usually inner)")
                        IGBT.state = State(IGBT.train._cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
                    except queue.Empty:
                        print("Train failed to move backwards. Check contact")
                        GTO.train.set_target_speed(50)
                        IGBT.train.set_target_speed(50)
                GTO.emergency_stop()
        elif pin == AIRPORT_CONTACT:
            print("Airport contact")
            IGBT.emergency_stop()
            IGBT.state = State(IGBT.train._cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT, False)
        elif pin == INNER_CONTACT:
            print("Inner contact tripped")
            pass  # this does not tell us much yet. We only know IGBT is on inner track now
    trains.GENERATOR.unregister('detect')
    print(f"Detection complete. Trains in starting positions.")


def move_to_standard_pos():
    print(">>> Moving to standard positions")
    print(f"Current position estimate: {GTO}, {IGBT}")
    trains.GENERATOR.register('detect')
    if trains.GENERATOR.get_state(AIRPORT_CONTACT) is False:
        print("IGBT already on inner (airport contact)")
        if IGBT.position > I_AIRPORT_CONTACT_WEST + HALF_TRAIN:
            print("correcting IGBT position to airport contact")
            IGBT.state = State(IGBT.train._cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + HALF_TRAIN, IGBT.aligned)
    if IGBT.state.outer_track:
        print("IGBT presumably on outer track")
        # move GTO to a safe position
        # reverse IGBT until on interim
        raise NotImplementedError
    else:
        print("IGBT presumably on inner track")
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
            IGBT.state = State(IGBT.train._cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST+TRAIN_CONTACT, aligned)
            print("IGBT arrived at airport contact")
        except queue.Empty:
            print("IGBT not moving")

        if trains.GENERATOR.get_state(OUTER_CONTACT) is not False:
            # drive GTO to outer contact
            GTO.train.set_target_speed(50)
            try:
                trains.GENERATOR.await_event([OUTER_CONTACT], [False], timeout=60, listener='detect')
                GTO.state = State(GTO.train._cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=aligned)
                GTO.emergency_stop()
            except queue.Empty:
                print("GTO not moving")
                
    trains.GENERATOR.unregister('detect')
    print(f"Finished move to standard pos. Now {GTO}, {IGBT}")
    time.sleep(2)


def measure_time():
    controller = GTO
    print(f"Measuring speed of {GTO.train.name}")
    trains.GENERATOR.register('timer')
    controller.train.set_target_speed(100)
    controller.train.acceleration = 1000
    trains.power_on()
    measured = [0] + [None] * 14
    for speed_i, target_speed in reversed(tuple(enumerate(controller.train.speeds))):
        print(f"Speed {speed_i} (prior {target_speed} kmh)")
        controller.train.set_target_speed(target_speed)
        for round_i in range(2):
            t0 = time.perf_counter()
            trains.GENERATOR.await_event([OUTER_CONTACT], [False], listener='timer')
            t = time.perf_counter() - t0
            kmh = OUTER / t * 87 * 3.6 / 1000
            if round_i == 0:
                print(f"Warmup: {t}")
            else:
                print(f"Round time: {t}, kmh={kmh}")
                measured[speed_i] = kmh
                print(f"({', '.join([f'{v:.1f}' if v is not None else '0' for v in measured])})")


def regular_round(pause=2.):
    assert not GTO.state.outer_track
    assert GTO.position < 0
    assert GTO.aligned
    assert IGBT.state.outer_track
    assert IGBT.position > 4000
    assert IGBT.aligned
    for i in range(2):
        IGBT.drive(O_ERDING + OUTER, pause=pause)
        time.sleep(2)
        GTO.drive(I_AIRPORT, pause=pause)
        IGBT.drive(O_AIRPORT, pause=pause)
        GTO.drive(I_ERDING, pause=pause)
        IGBT.drive(O_MUNICH, pause=pause, trip=[(OUTER_CONTACT, 4609)])
        GTO.drive(I_MUNICH + INNER, pause=pause, trip=[(INNER_CONTACT, INNER + INNER_CONNECTION - TRAIN_CONTACT)])


def write_current_state(_dt):
    LOG.write(f"{str(GTO.state)},{str(IGBT.state)}\n")
    LOG.flush()


if __name__ == '__main__':
    _LAST_POSITIONS = read_last_positions()
    GTO = Controller(trains.get_by_name('GTO'), _LAST_POSITIONS[0] or State(0, True, NAN, True))
    IGBT = Controller(trains.get_by_name('IGBT'), _LAST_POSITIONS[1] or State(0, None, NAN, None))

    LOG = create_log_file()
    write_current_state(0)
    schedule_at_fixed_rate(write_current_state, period=2.)

    trains.setup('COM5')

    Thread(target=program).start()
    import plan_vis
    plan_vis.show([GTO, IGBT])

