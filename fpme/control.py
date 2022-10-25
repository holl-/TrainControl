import math
import os.path
import queue
import time
from dataclasses import dataclass
from threading import Thread
from typing import List, Tuple

from fpme import trains
from fpme.helper import schedule_at_fixed_rate

HALF_TRAIN = 366
TRAIN_CONTACT = 195
INNER = 4137.7
OUTER = 5201.2
INNER_CONNECTION = 565.5
OUTER_CONNECTION = 643.0
INTERIM = 1794.8
OUTER_UNTIL_SWITCH = 2565.4

I_AIRPORT = 1832.5
I_ERDING = 2835.6
I_MUNICH = HALF_TRAIN + 50
O_ERDING = 1595.6
O_AIRPORT = 2565.4
O_MUNICH = 4746.7

OUTER_CONTACT = 'RI'  # contact 1 (red)
INNER_CONTACT = 'DSR'  # contact 2 (yellow)
AIRPORT_CONTACT = 'CD'  # contact 3 (green)


@dataclass
class State:
    cumulative_signed_distance: float
    outer_track: bool  # None if unknown
    position: float  # Position of the train center on the track in mm, nan if unknown
    aligned: bool  # Whether driving forward increases the position, None if unknown

    def __str__(self):
        return f"{'?' if self.outer_track is None else 'outer' if self.outer_track else 'inner'} {self.position:.1f} {'?' if self.aligned is None else 'fwd' if self.aligned else 'bwd'}"

    @staticmethod
    def from_line(line: str):
        track, pos, aligned = line.strip().split(' ')
        track = {'outer': True, 'inner': False, '?': None}[track]
        aligned = {'fwd': True, 'bwd': False, '?': None}[aligned]
        return State(0, track, float(pos), aligned)


def update_state(state: State, cumulative_signed_distance):
    delta = (int(state.aligned) * 2 - 1) * (cumulative_signed_distance - state.cumulative_signed_distance)
    position = state.position + delta
    outer_track = state.outer_track
    aligned = state.aligned
    if outer_track and position > OUTER + HALF_TRAIN:
        position -= OUTER
    elif outer_track and position < -OUTER_CONNECTION - HALF_TRAIN:
        outer_track = False
        position += (OUTER_CONNECTION - INNER_CONNECTION)
    elif not outer_track and position > INNER + HALF_TRAIN:
        position = - (position - INNER)
        aligned = not aligned
    elif not outer_track and position < -(INNER_CONNECTION + INTERIM + HALF_TRAIN):
        outer_track = True
        position = OUTER_UNTIL_SWITCH - (-position - INNER_CONNECTION - INTERIM)
    return State(cumulative_signed_distance, outer_track, position, aligned)





# def exit_unsafe_switches(state: State) -> float:
#     if state.outer_track and -HALF_TRAIN - OUTER_CONNECTION < state.position < HALF_TRAIN - OUTER_CONNECTION:
#         return state.position - OUTER_CONNECTION - HALF_TRAIN
#         # ToDo Kontaktgleis testen
#     elif not state.outer_track and False:
#         return 0  # ToDo
#     else:
#         return 0

# print(exit_unsafe_switches(State(0, True, 0, True)))


def get_last_log_index() -> int or None:
    if not os.path.isdir('logs'):
        return 0
    logs = [f for f in os.listdir('logs') if f.startswith('pos_') and f.endswith('.txt')]
    if not logs:
        return 0
    i = [int(f[4:f.index('.')]) for f in logs]
    last_log_index = max(i)
    return last_log_index


def read_last_positions() -> List[State or None]:
    last_log_index = get_last_log_index()
    if not last_log_index:
        return [None, None]
    with open(f'logs/pos_{last_log_index}.txt', 'r') as f:
        lines = f.readlines()
    if not lines:
        return [None, None]
    return [State.from_line(s) for s in lines[-1].split(',')]


def create_log_file():
    os.path.isdir('logs') or os.makedirs('logs')
    return open(f'logs/pos_{get_last_log_index() + 1}.txt', 'w')


class Controller:

    def __init__(self, train: trains.Train, last_position: State or None):
        print(f"Creating controller for {train}")
        self.train = train
        self.state = last_position
        train.on_post_update = self._update
        self._target_signed_distance: float = None
        self._next_pause: float = None
        self._executing = False
        self._t_started_waiting = None
        self._trip = None

    def drive(self, target_position, pause: float or None, trip: List[Tuple[str, float]] = ()):
        """
        Blocks until previous operation finished.

        :param target_position: Target position on the track in mm.
        :param pause: Duration to wait after stopping in seconds.
        :return:
        """
        print(f"{self.train.name} -> drive to {target_position}")
        while self._executing:
            time.sleep(.2)
        self._executing = True
        self._t_started_waiting = None
        distance_mm = (target_position - self.position) * (1 if self.state.aligned else -1)  # distance from the train's orientation
        self._target_signed_distance = self.state.cumulative_signed_distance + distance_mm
        self._next_pause = pause
        self._trip = list(trip)
        trains.GENERATOR.register(self)
        Thread(target=self._count_triggers).start()
        self.train.set_target_speed(math.copysign(1, distance_mm))

    def _count_triggers(self):
        assert isinstance(self._trip, list)
        while self._trip:
            pin, position = self._trip[0]
            print(f"{self.train} waiting for {pin}")
            trains.GENERATOR.await_event([pin], [False], timeout=60, listener=self)
            print(f"{self.train} triggered {pin}")
            self._trip.pop(0)
        trains.GENERATOR.unregister(self)

    @property
    def position(self):
        return self.state.position

    def _update(self):
        if not self._executing:
            return
        self.state = update_state(self.state, self.train._cumulative_signed_distance)
        print(self.train._cumulative_signed_distance)
        # print(self.state)
        if self._target_signed_distance is None:
            if not self._trip:
                self.train.set_target_speed(0)
                self._executing = False
            else:
                self.train.set_target_speed(50)
        elif not self.train.in_reverse and self.train._cumulative_signed_distance > self._target_signed_distance:
            self._break_wait()
        elif self.train.in_reverse and self.train._cumulative_signed_distance < self._target_signed_distance:
            self._break_wait()
        else:
            distance = self._target_signed_distance - self.train._cumulative_signed_distance
            self.train.set_target_speed(math.copysign(80, distance))

    def _break_wait(self):
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
    try:
        trains.GENERATOR.await_event([OUTER_CONTACT], [True, False], timeout=2)
    except queue.Empty:
        pass
    IGBT.train.set_target_speed(50)
    try:
        trains.GENERATOR.await_event([OUTER_CONTACT], [False], timeout=60)
    except queue.Empty:
        print("Train not moving. Outer contact timeout after 60s.")
        return
    print("Tripped")
    IGBT.train.emergency_stop()
    IGBT.train.sound_on()
    GTO.train.sound_on()
    time.sleep(30)
    IGBT.drive(OUTER + O_AIRPORT, 20, trip=[(OUTER_CONTACT, -1.)])
    IGBT.drive(OUTER - O_AIRPORT + OUTER, 20, trip=[(OUTER_CONTACT, -1.)])
    IGBT.drive(OUTER * 2, 20, trip=[(OUTER_CONTACT, -1.)])

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


def measure_time():
    trains.GENERATOR.register('timer')
    IGBT.train.set_target_speed(100)
    IGBT.train.acceleration = 1000
    measured = []
    for i, target_speed in reversed(tuple(enumerate(IGBT.train.speeds))):
        print(f"Speed {i} (prior {target_speed} kmh)")
        IGBT.train.set_target_speed(target_speed)
        for i in range(2):
            t0 = time.perf_counter()
            trains.GENERATOR.await_event([OUTER_CONTACT], [False], listener='timer')
            t = time.perf_counter() - t0
            kmh = OUTER / t * 87 * 3.6 / 1000
            if i == 0:
                print(f"Warmup: {t}")
            else:
                print(f"Round time: {t}, kmh={kmh}")
                measured.insert(0, kmh)
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
    GTO = Controller(trains.get_by_name('GTO'), _LAST_POSITIONS[0] or State(0, None, float('nan'), None))
    IGBT = Controller(trains.get_by_name('IGBT'), _LAST_POSITIONS[1] or State(0, True, float('nan'), True))

    LOG = create_log_file()
    write_current_state(0)
    schedule_at_fixed_rate(write_current_state, period=2.)

    trains.setup('COM5')
    trains.power_on()

    Thread(target=program).start()
    # import plan_vis
    # plan_vis.show([GTO, IGBT])

