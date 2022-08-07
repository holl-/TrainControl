import math
import time
import warnings

import numpy

from helper import schedule_at_fixed_rate
from fpme import signal_gen


class Train:

    def __init__(self,
                 name: str,
                 address: int,
                 speeds=tuple([i * 20 for i in range(15)]),
                 acceleration=20.,
                 has_built_in_acceleration=False,
                 protocol=None):
        assert len(speeds) == 15, len(speeds)
        # Properties
        self.name: str = name
        self.address: int = address
        self.protocol = protocol  # special protocol for this train
        self.speeds: tuple = speeds  # 14 entries
        self.locomotive_speeds = speeds  # unencumbered by cars
        self.has_built_in_acceleration: bool = has_built_in_acceleration
        self.acceleration: float = acceleration
        # State
        self._speed_factor = 1.  # 1 = unencumbered, 0 = cannot move
        self.admin_only = False
        self._limit = None
        self._target_speed: float = 0.  # signed speed in kmh, -0 means parked in reverse
        self._speed: float = 0.  # signed speed in kmh
        self._func_active = False
        self._emergency_stopping = False  # will be set to False when a new speed is set
        self._broadcasting_state = (None, None, None)  # (speed_level: int, in_reverse: bool, func_active: bool)

    @property
    def target_speed(self):
        return self._target_speed  # affected by speed limit

    @property
    def signed_target_speed(self):
        return self._target_speed

    @property
    def signed_actual_speed(self):
        return self._speed

    @property
    def max_speed(self):
        return self.speeds[-1]

    @property
    def in_reverse(self):
        direction = math.copysign(1, self._speed if self._speed != 0 else self._target_speed)
        return direction < 0

    def set_speed_factor(self, factor, adjust_limit=False):
        old_factor = self._speed_factor
        self._speed_factor = factor
        self.speeds = tuple(s * factor for s in self.locomotive_speeds)
        self._target_speed *= factor / old_factor
        self._speed *= factor / old_factor
        if adjust_limit and self._limit is not None:
            self._limit *= factor / old_factor

    def set_speed_limit(self, limit: float or None):
        self._limit = limit
        if limit is not None and self._target_speed > limit:
            self._target_speed = limit

    def _update(self, dt: float):  # called by update_trains()
        if not is_power_on():
            self._speed = 0
            return
        if self._target_speed == self._speed:
            return
        acceleration = self.acceleration if abs(self._target_speed) > abs(self._speed) else self.acceleration * 2
        if self._target_speed > self._speed:
            self._speed = min(self._speed + acceleration * dt, self._target_speed)
        else:
            self._speed = max(self._speed - acceleration * dt, self._target_speed)
        self._update_signal()

    def _update_signal(self):
        target_level = int(numpy.argmin([abs(s - abs(self._target_speed)) for s in self.speeds]))  # ≥ 0
        if self.has_built_in_acceleration:
            speed_level = target_level
        else:
            if abs(self._target_speed) > abs(self._speed):  # ceil level
                speed_level = [i for i, s in enumerate(self.speeds) if s >= abs(self._speed)][0] + 1
                speed_level = min(speed_level, target_level)
            elif abs(self._target_speed) < abs(self._speed):  # floor level
                speed_level = [i for i, s in enumerate(self.speeds) if s <= abs(self._speed)][-1] - 1
                speed_level = max(speed_level, target_level)
            else:  # Equal
                speed_level = target_level
        new_state = (speed_level, self.in_reverse, self._func_active)
        if new_state != self._broadcasting_state:
            self._broadcasting_state = new_state
            GENERATOR.set(self.address, speed_level, self.in_reverse, self._func_active, protocol=self.protocol)

    def emergency_stop(self):
        self._target_speed *= 0.
        self._speed *= 0.
        in_reverse = not self._broadcasting_state[1]
        GENERATOR.set(self.address, 0, in_reverse, self._func_active, protocol=self.protocol)
        self._broadcasting_state = (0., in_reverse, self._func_active)
        self._emergency_stopping = True

    @property
    def is_emergency_stopping(self):
        return self._emergency_stopping

    def reverse(self):
        self._target_speed = - math.copysign(0, self._target_speed)

    def set_target_speed(self, signed_speed: float):
        if signed_speed != 0:
            self._emergency_stopping = False
        if signed_speed == 0:
            self._target_speed = -0. if self.in_reverse else 0.
        else:
            max_speed = self.max_speed if self._limit is None else min(self.max_speed, self._limit)
            self._target_speed = max(-max_speed, min(signed_speed, max_speed))

    def accelerate(self, signed_times: int):
        in_reverse = self.in_reverse
        target_level = int(numpy.argmin([abs(s - abs(self._target_speed)) for s in self.speeds]))  # ≥ 0
        new_target_level = int(numpy.clip(target_level + signed_times, 0, 14))
        new_target_speed = self.speeds[new_target_level]
        self.set_target_speed(-new_target_speed if in_reverse else new_target_speed)

    @property
    def is_parked(self):
        return self._speed == 0 and self._target_speed == 0

    def __repr__(self):
        return self.name


TRAINS = [
    Train('ICE', address=60, acceleration=40., speeds=(0, 0.1, 0.2, 11.8, 70, 120, 188.1, 208.8, 222.1, 235.6, 247.3, 258.3, 266.1, 274.5, 288)),
    Train('E-Lok (DB)', address=24, acceleration=30., protocol=signal_gen.Motorola1(), speeds=(0, 1.9, 20.2, 33, 49.2, 62.7, 77.1, 93.7, 109, 124.5, 136.9, 154.7, 168.7, 181.6, 183)),
    Train('E-Lok (BW)', address=1, acceleration=30., has_built_in_acceleration=True, speeds=(0, 13.4, 24.9, 45.6, 66.5, 86.3, 107.6, 124.5, 139.5, 155.6, 173.2, 190.9, 201.1, 215.2, 226)),
    Train('S-Bahn', address=48, acceleration=20., has_built_in_acceleration=True, speeds=(0, 1.9, 5.2, 9.6, 14.8, 22, 29.9, 40.7, 51.2, 64.1, 77.1, 90.8, 106.3, 120.2, 136)),  # ToDo has_built_in_acceleration?
    Train('Dampf-Lok', address=78, acceleration=30., speeds=(0, 0.1, 0.2, 0.3, 48, 80, 100, 110, 120, 140, 165, 180, 192, 202, 210)),
    Train('Diesel-Lok', address=72, acceleration=30., speeds=(0, 0.1, 1, 60, 100, 130, 150, 180, 187, 192, 197, 202, 207, 212, 217)),
]


def get_by_name(train_name):
    for train in TRAINS:
        if train.name == train_name:
            return train
    raise KeyError(f'No train named {train_name}')


POWER_OFF_TIME = 0

GENERATOR: signal_gen.ProcessSpawningGenerator = None


def power_on():
    GENERATOR.start()


def power_off():
    GENERATOR.stop()
    global POWER_OFF_TIME
    POWER_OFF_TIME = time.perf_counter()


def is_power_on():
    return GENERATOR.is_sending


def update_trains(dt):  # repeatedly called from setup()
    try:
        for train in TRAINS:
            train._update(dt)
    except Exception as exc:
        warnings.warn(f"Exception in update_trains(): {exc}")


TRAIN_UPDATE_PERIOD = 0.1


def setup(serial_port: str or None):
    global GENERATOR
    GENERATOR = signal_gen.ProcessSpawningGenerator(serial_port)
    for train in TRAINS:
        train._update_signal()  # Broadcast initial states, otherwise trains will keep going with previous speed
    schedule_at_fixed_rate(update_trains, TRAIN_UPDATE_PERIOD)


def set_global_speed_limit(limit: float or None):
    for train in TRAINS:
        train.set_speed_limit(limit)


def set_train_cars_connected(train_cars):
    if train_cars:
        # get_by_name('ICE').set_speed_factor(288 / 300)
        get_by_name('Dampf-Lok').set_speed_factor(106 / 210)
        get_by_name('Diesel-Lok').set_speed_factor(166 / 210)
    else:
        for train in TRAINS:
            train.set_speed_factor(1)
