import math
import time
import warnings
from dataclasses import dataclass
from threading import Thread
from typing import Tuple

import numpy

from winrawin import RawInputEvent, Mouse

from .helper import schedule_at_fixed_rate
from .signal_gen import ProcessSpawningGenerator
from .train_def import TRAINS, Train, CONTROLS


class TrainState:

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
        if self._target_speed == self._speed:
            return
        acceleration = self.acceleration if abs(self._target_speed) > abs(self._speed) else self.acceleration * 2
        if self._target_speed > self._speed:
            self._speed = min(self._speed + acceleration * dt, self._target_speed)
        else:
            self._speed = max(self._speed - acceleration * dt, self._target_speed)
        self._update_signal()

    def _update_signal(self):
        target_idx = int(numpy.argmin([abs(s - abs(self._target_speed)) for s in self.speeds]))  # ≥ 0
        if self.use_built_in_acceleration:
            speed_idx = target_idx
        else:
            if abs(self._target_speed) > abs(self._speed):  # ceil level
                speed_idx = [i for i, s in enumerate(self.speeds) if s >= abs(self._speed)][0] + 1
                speed_idx = min(speed_idx, target_idx)
            elif abs(self._target_speed) < abs(self._speed):  # floor level
                speed_idx = [i for i, s in enumerate(self.speeds) if s <= abs(self._speed)][-1] - 1
                speed_idx = max(speed_idx, target_idx)
            else:  # Equal
                speed_idx = target_idx
        speed_code = self.speed_codes[speed_idx]
        if speed_code == 0 and self.always_use_mm1_stop:
            speed_code = None
        new_state = (speed_code, self.currently_in_reverse, self._func_active)
        if new_state != self._broadcasting_state:
            self._broadcasting_state = new_state
            GENERATOR.set(self.address, speed_code, self.currently_in_reverse, {0: self._func_active}, protocol=self.protocol)

    def emergency_stop(self):
        self._target_speed *= 0.
        self._speed *= 0.
        currently_in_reverse = self._broadcasting_state[1]
        if self.stop_by_mm1_reverse:
            GENERATOR.set(self.address, None, False, {0: self._func_active}, protocol=self.protocol)
            self._broadcasting_state = (0, False, self._func_active)
        else:
            GENERATOR.set(self.address, 0, not currently_in_reverse, {0: self._func_active}, protocol=self.protocol)
            self._broadcasting_state = (0, not currently_in_reverse, self._func_active)
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


EMERGENCY_STOP = 'emergency stop'


class TrainControl:

    def __init__(self, trains=TRAINS):
        self.trains = trains
        self.generators = []
        self.generators_by_train = {train: [] for train in trains}
        self.speed_limit = None
        self.locked_trains = []
        self.target_speeds = {train: 0. for train in trains}  # signed speed in kmh, -0 means parked in reverse
        self.speeds = {train: 0. for train in trains}  # signed speed in kmh, set to EMERGENCY_STOP while train is braking
        self.active_functions = {train: set() for train in trains}  # which functions are active by their TrainFunction handle
        schedule_at_fixed_rate(self.update_trains, period=.1)

    def add_rs232_generator(self, serial_port: str or None, trains):
        generator = ProcessSpawningGenerator()
        generator.setup(serial_port)
        for train in trains:
            self.generators_by_train[train].append(generator)
            self._update_signal(generator, train)  # Broadcast initial states, otherwise trains will keep going with previous speed

    def power_on(self, train):
        for generator in self.generators_by_train[train]:
            generator.start()

    def power_off(self, train):
        for generator in self.generators_by_train[train]:
            generator.stop()

    def is_power_on(self, train):
        return all([generator.is_sending for generator in self.generators_by_train[train]])

    def terminate(self):
        for generator in self.generators:
            generator.terminate()

    def update_trains(self, dt):  # repeatedly called from setup()
        try:
            for train in TRAINS:
                train._update(dt)
        except Exception as exc:
            warnings.warn(f"Exception in update_trains(): {exc}")

    def set_global_speed_limit(self, limit: float or None):
        for train in TRAINS:
            train.set_speed_limit(limit)

    def set_lights_on(self, on: bool):
        for train in TRAINS:
            train._func_active = on
            train._update_signal()


def handle_event(e: RawInputEvent):
    if e.device.name not in CONTROLS:
        return
    train = CONTROLS[e.device.name]
    if isinstance(e.device, Mouse) and e.device.num_buttons == 5:  # wireless mouse
        pass
