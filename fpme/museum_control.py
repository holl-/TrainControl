import math
import queue
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
        self._next_pause: float = None
        self._executing = False
        self._t_started_waiting = None
        self._trip = None

    def drive(self, target_position, pause: float or None, trip: List[Tuple[str, float]] = ()):
        """
        Blocks until previous operation finished.

        :param target_position: Target position on the track in mm.
        :param pause: Duration to wait after stopping in seconds.
        :param trip: Contacts to trip along the way, (pin, position)
        :return:
        """
        print(f"{self.train.name} -> drive to {target_position}")
        while self._executing:
            time.sleep(.2)
        self._t_started_waiting = None
        distance_mm = (target_position - self.position) * (1 if self.state.aligned else -1)  # distance from the train's orientation
        self._target_signed_distance = self.state.cumulative_signed_distance + distance_mm
        self._increase_position = target_position >= self.position
        self._next_pause = pause
        self._trip = list(trip)
        trains.GENERATOR.register(self)
        self._executing = True
        Thread(target=self._count_triggers).start()
        self.train.set_target_speed(math.copysign(1, distance_mm))

    def _count_triggers(self):
        assert isinstance(self._trip, list)
        while self._trip:
            pin, position = self._trip[0]
            print(f"{self.train} waiting for {pin}")
            trains.GENERATOR.await_event([pin], [False], timeout=60, listener=self)
            delta = position - self.position
            self.state = State(self.train._cumulative_signed_distance, self.state.outer_track, position, self.state.aligned)
            print(f"{self.train} triggered {pin}, position updated by {delta} mm (actual - predicted)")
            self._trip.pop(0)
        trains.GENERATOR.unregister(self)

    @property
    def position(self):
        return self.state.position

    def _update(self):
        if not self._executing:
            return
        self.state = update_state(self.state, self.train._cumulative_signed_distance)
        braking_time = abs(self.train.signed_actual_speed) / self.train.acceleration
        braking_distance_m = .5 * (self.train.acceleration / 3.6) * braking_time ** 2 * (-1) ** (not self.state.aligned) * (-1) ** self.train.currently_in_reverse * (-1) ** (not self._increase_position) # * (-1 if self.state.aligned ^ (not self.train.currently_in_reverse) ^ (not self._increase_position) else 1)
        braking_distance_mm = braking_distance_m * 1000 / 87
        distance_to_drive = (self._target_signed_distance - self.train._cumulative_signed_distance)
        if self._trip:  # keep going slowly if trigger not yet triggered (calculate minimum distance to drive)
            _, contact_pos = self._trip[0]
            contact_to_goal = self._target_signed_distance - contact_pos
            distance_to_drive = max(distance_to_drive, contact_to_goal) if self._increase_position else min(distance_to_drive, contact_to_goal)
        print(f"{self.train.name}\t speed={self.train.signed_actual_speed:.0f}\t braking distance: {braking_distance_mm:.0f}\t  to drive: {distance_to_drive:.0f}   (aligned={self.state.aligned}, in_reverse={self.train.in_reverse}, increase_pos={self._increase_position}, cumulative={self.train._cumulative_signed_distance:.0f})")
        aligned_distance_to_drive = distance_to_drive * (1 if self._increase_position else -1)  # positive unless overshot
        if aligned_distance_to_drive <= braking_distance_mm:
            self._brake_wait()
        elif aligned_distance_to_drive <= braking_distance_mm + 100:  # Go slowly for the last 4 cm
            self.train.set_target_speed(20)
        # if self._target_signed_distance is None:
        #     if not self._trip:
        #         self.train.set_target_speed(0)
        #         self._executing = False
        #     else:
        #         self.train.set_target_speed(50)
        else:
            self.train.set_target_speed(80 * (1 if self._increase_position else -1))
            # distance = self._target_signed_distance - self.train._cumulative_signed_distance
            # self.train.set_target_speed(math.copysign(80, distance))

    def _brake_wait(self):
        """ Breaks if driving, else sets executing=False if pause is over. """
        if self.train.target_speed == 0:
            if self._t_started_waiting is None:
                self._t_started_waiting = time.perf_counter()
            elif time.perf_counter() - self._t_started_waiting >= self._next_pause:
                if self._executing:
                    print(f"{self.train.name} done {self.state}")
                    self._executing = False
        else:
            self.train.set_target_speed(0)

    def __repr__(self):
        if self._target_signed_distance is not None:
            status = f"{self._target_signed_distance - self.train._cumulative_signed_distance} from target"
        else:
            status = "done"
        return f"{self.train.name} {status}"


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
    print(f"Status: outer={trains.GENERATOR.get_state(OUTER_CONTACT)}, inner={trains.GENERATOR.get_state(INNER_CONTACT)}, airport={trains.GENERATOR.get_state(AIRPORT_CONTACT)}")
    detect_train_positions_from_scratch()
    # time.sleep(30)
    GTO.drive(OUTER + O_ERDING, 5)
    GTO.drive(O_AIRPORT, 5)
    GTO.drive(O_MUNICH, 5, trip=[(OUTER_CONTACT, O_CONTACT_NORTH - TRAIN_CONTACT)])

    # while True:
    #     pin, state = trains.GENERATOR.await_event([OUTER_CONTACT], [False, True], timeout=30, listener='0')
    #     print(f"{pin} -> {state}")

    # # Move trains to initial position
    # if GTO.position == float('nan'):  # no log file
    #     # if INNER_CONTACT on, GTO must be on inner, around -?.
    #     # if outer on, check which train it is.
    #     # can only test this with actual hardware
    #     raise NotImplementedError  # ToDo
    # else:  # log file present but move safely just in case
    #     if GTO.state.outer_track:
    #         GTO.train.set_target_speed(40)
    #         IGBT.train.set_target_speed(40)
    #         trigger = trains.GENERATOR.await_activated([INNER_CONTACT, OUTER_CONTACT, AIRPORT_CONTACT])
    #     else:  # GTO on inner
    #         IGBT.train.set_target_speed(40)
    #         trains.GENERATOR.await_activated([OUTER_CONTACT], timeout=20.)

    # trains.GENERATOR.on_activated(INNER_CONTACT, lambda: )
    # trains.GENERATOR.on_activated(OUTER_CONTACT, lambda: )


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
            IGBT.train.emergency_stop()
        except queue.Empty:
            print("IGBT not moving.")
    else:
        IGBT.train.set_target_speed(50)
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
            GTO.train.emergency_stop()
            IGBT.train.emergency_stop()
            if IGBT.state.outer_track is False:
                print("It must have been GTO because IGBT is inside.")
                GTO.state = State(GTO.train._cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
            else:
                time.sleep(5)
                GTO.train.set_target_speed(-50)
                try:
                    trains.GENERATOR.await_event([pin], [True], timeout=5, listener='detect')
                    print("It was GTO (outer)")
                    GTO.state = State(GTO.train._cumulative_signed_distance, True, O_CONTACT_NORTH - TRAIN_CONTACT, aligned=True)
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
                GTO.train.emergency_stop()
        elif pin == AIRPORT_CONTACT:
            print("Airport contact")
            IGBT.train.emergency_stop()
            IGBT.state = State(IGBT.train._cumulative_signed_distance, False, I_AIRPORT_CONTACT_WEST + TRAIN_CONTACT, False)
        elif pin == INNER_CONTACT:
            print("Inner contact tripped")
            pass  # this does not tell us much yet. We only know IGBT is on inner track now
    trains.GENERATOR.unregister('detect')
    print(f"Detection complete. Trains in starting positions.")


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
                print(tuple(measured))


def regular_round(pause=2.):
    assert not GTO.state.outer_track
    assert GTO.position < 0
    assert GTO.state.aligned
    assert IGBT.state.outer_track
    assert IGBT.position > 4000
    assert IGBT.state.aligned
    for i in range(2):
        IGBT.drive(O_ERDING + OUTER, pause=pause)
        time.sleep(2)
        GTO.drive(I_AIRPORT, pause=pause)
        IGBT.drive(O_AIRPORT, pause=pause)
        GTO.drive(I_ERDING, pause=pause)
        IGBT.drive(O_MUNICH, pause=pause, trip=[(OUTER_CONTACT, 4609)])
        GTO.drive(I_MUNICH + INNER, pause=pause, trip=[(INNER_CONTACT, INNER + INNER_CONNECTION - TRAIN_CONTACT)])


def adjust_position_tripwire(pin: str, tripped: bool):
    if pin in ('RI', 'DSR'):
        train = GTO

    else:
        train = GTO if GTO.state.outer_track and GTO.state.position > IGBT.state.position else IGBT
        # could possibly trip with back wheel
        # train.position_measured(True, new_position)


def write_current_state(_dt):
    LOG.write(f"{str(GTO.state)},{str(IGBT.state)}\n")
    LOG.flush()


if __name__ == '__main__':
    _LAST_POSITIONS = read_last_positions()
    GTO = Controller(trains.get_by_name('GTO'), _LAST_POSITIONS[1] or State(0, True, NAN, True))
    IGBT = Controller(trains.get_by_name('IGBT'), _LAST_POSITIONS[0] or State(0, None, NAN, None))

    LOG = create_log_file()
    write_current_state(0)
    schedule_at_fixed_rate(write_current_state, period=2.)

    trains.setup('COM5')

    Thread(target=program).start()
    # import plan_vis
    # plan_vis.show([GTO, IGBT])

