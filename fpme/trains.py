import math
import time
import warnings
from typing import Tuple, Callable

import numpy
import numpy as np

from helper import schedule_at_fixed_rate
from . import signal_gen


class Train:

    def __init__(self,
                 name: str,
                 icon: str,
                 address: int,
                 speeds=tuple([i * 20 for i in range(15)]),
                 acceleration=20.,
                 has_built_in_acceleration=False,
                 protocol=None,
                 stop_by_mm1_reverse=False,
                 image: Tuple[str, int, int] = ("", -1, -1),
                 directional_image: Tuple[str, int, int] = None):
        assert len(speeds) == 15, len(speeds)
        # Properties
        self.name: str = name
        self.address: int = address
        self.icon = icon
        self.protocol = protocol  # special protocol for this train
        self.speeds: tuple = speeds  # 14 entries
        self.locomotive_speeds = speeds  # unencumbered by cars
        self.has_built_in_acceleration: bool = has_built_in_acceleration
        self.acceleration: float = acceleration
        self.deceleration: float = acceleration
        self.stop_by_mm1_reverse = stop_by_mm1_reverse
        self.image: Tuple[str, int, int] = image
        self.directional_image = directional_image
        self.on_post_update: Callable = None
        # State
        self._cumulative_signed_distance = 0.  # mm / s
        self._cumulative_abs_distance = 0.
        self._dst_measured_time = time.perf_counter()
        self._speed_factor = 1.  # 1 = unencumbered, 0 = cannot move
        self.admin_only = False
        self._limit = None
        self._target_speed: float = 0.  # signed speed in kmh, -0 means parked in reverse
        self._speed: float = 0.  # signed speed in kmh
        self.lights = True
        self.sound = False
        self._emergency_stopping = False  # will be set to False when a new speed is set
        self._broadcasting_state = (None, None, {})  # (speed_level: int, in_reverse: bool, func_active: bool)

    def sound_on(self):
        self.sound = True
        self._update_signal()

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
        direction = math.copysign(1, self._target_speed)
        return direction < 0

    @property
    def currently_in_reverse(self):
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
        if self._target_speed != self._speed:
            acceleration = self.acceleration if abs(self._target_speed) > abs(self._speed) else self.deceleration
            if self._target_speed > self._speed:
                self._speed = min(self._speed + acceleration * dt, self._target_speed)
            else:
                self._speed = max(self._speed - acceleration * dt, self._target_speed)
        self._accumulate_distance()
        self._update_signal()
        if self.on_post_update:
            self.on_post_update()

    def _accumulate_distance(self):
        if GENERATOR.is_short_circuited:
            return
        speed_level, in_reverse, _ = self._broadcasting_state
        if speed_level is None:
            return
        if self._emergency_stopping:
            return
        t = time.perf_counter()
        dt = (t - self._dst_measured_time) * TIME_DILATION
        distance_driven = self.speeds[speed_level] / 3.6 * 1000 * dt / 87  # mm/s
        self._cumulative_abs_distance += distance_driven
        self._cumulative_signed_distance += distance_driven * (-1 if in_reverse else 1)
        self._dst_measured_time = t

    def _update_signal(self):
        target_level = int(numpy.argmin([abs(s - abs(self._target_speed)) for s in self.speeds]))  # ≥ 0
        if self.has_built_in_acceleration:
            speed_level = target_level
        else:
            speed_level = int(np.argmin(abs(np.asarray(self.speeds) - abs(self._speed))))
            # if abs(self._target_speed) > abs(self._speed):  # ceil level
            #     speed_level = [i for i, s in enumerate(self.speeds) if s >= abs(self._speed)][0] + 1
            #     speed_level = min(speed_level, target_level)
            # elif abs(self._target_speed) < abs(self._speed):  # floor level
            #     speed_level = [i for i, s in enumerate(self.speeds) if s <= abs(self._speed)][-1] - 1
            #     speed_level = max(speed_level, target_level)
            # else:  # Equal
            #     speed_level = target_level
        new_state = (speed_level, self.currently_in_reverse, self._function_dict)
        if new_state != self._broadcasting_state:
            self._broadcasting_state = new_state
            GENERATOR.set(self.address, speed_level, self.currently_in_reverse, self._function_dict, protocol=self.protocol)

    @property
    def _function_dict(self):
        return {0: self.lights, 1: False, 2: self.sound, 3: False, 4: True}

    def emergency_stop(self):
        self._target_speed *= 0.
        self._speed *= 0.
        currently_in_reverse = self._broadcasting_state[1]
        if self.stop_by_mm1_reverse:
            GENERATOR.set(self.address, None, False, self._function_dict, protocol=self.protocol)
            self._broadcasting_state = (0, False, self._function_dict)
        else:
            GENERATOR.set(self.address, 0, not currently_in_reverse, self._function_dict, protocol=self.protocol)
            self._broadcasting_state = (0, not currently_in_reverse, self._function_dict)
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

    @property
    def image_path(self):
        return self.image[0]

    @property
    def directional_image_path(self):
        return self.directional_image[0] if self.directional_image is not None else self.image_path

    @property
    def image_resolution(self):
        return self.image[1], self.image[2]

    def fit_image_size(self, max_width, max_height):
        image_aspect = self.image[1] / self.image[2]
        max_aspect = max_width / max_height
        if image_aspect > max_aspect:  # wide image: fit width
            return max_width, self.image[2] * max_width / self.image[1]
        else:  # narrow image: fit height
            return self.image[1] * max_height / self.image[2], max_height


TRAINS = [
    Train('GTO', "Ⓢ",
          address=3,
          acceleration=10.,
          speeds=(0, .1, 11, 17, 22, 34.3, 35.6, 42.6, 49.8, 56.7, 63.7, 69.6, 76.5, 82.8, 89.8),
          stop_by_mm1_reverse=True),
# Functions: 2: sound, 3: horn, 4: instant acceleration
    Train('IGBT', "Ⓢ",  # includes sound
          address=6,
          acceleration=4.,
          speeds=(0, .1, 7, 15, 24, 30.8, 38.7, 46.2, 54.3, 62.0, 70.3, 78.1, 85.3, 93.4, 100.6),
          stop_by_mm1_reverse=True),
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


def destroy():
    GENERATOR.terminate()


def update_trains(dt):  # repeatedly called from setup()
    # try:  # ToDo enable again
        for train in TRAINS:
            train._update(dt * TIME_DILATION)
    # except Exception as exc:
    #     warnings.warn(f"Exception in update_trains(): {exc}", RuntimeWarning)


TRAIN_UPDATE_PERIOD = 0.1
TIME_DILATION = 1.


def setup(serial_port: str or None):
    global GENERATOR
    GENERATOR = signal_gen.ProcessSpawningGenerator(serial_port)
    for train in TRAINS:
        train._update_signal()  # Broadcast initial states, otherwise trains will keep going with previous speed
    schedule_at_fixed_rate(update_trains, TRAIN_UPDATE_PERIOD)


def set_global_speed_limit(limit: float or None):
    for train in TRAINS:
        train.set_speed_limit(limit)

