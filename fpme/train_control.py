import math
import warnings
from typing import Sequence, Optional

import numpy

from .helper import schedule_at_fixed_rate
from .signal_gen import SubprocessGenerator, MM1, MM2
from .train_def import TRAINS, Train


def get_preferred_protocol(train: Train):
    return MM2 if train.supports_mm2 else MM1


EMERGENCY_STOP = 'emergency stop'


class TrainControl:

    def __init__(self, trains=TRAINS):
        self.trains = trains
        self.ports_by_train = {train: [] for train in trains}
        self.generator = SubprocessGenerator(max_generators=2)
        self.speed_limit = None
        self.locked_trains = set()
        self.target_speeds = {train: 0. for train in trains}  # signed speed in kmh, -0 means parked in reverse
        self.speeds = {train: 0. for train in trains}  # signed speed in kmh, set to EMERGENCY_STOP while train is braking
        self.active_functions = {train: set() for train in trains}  # which functions are active by their TrainFunction handle
        self.controls = {train: 0. for train in trains}
        for train in trains:
            self.generator.set(train.address, 0, False, {}, get_preferred_protocol(train))
        schedule_at_fixed_rate(self.update_trains, period=.1)
        self.generator.setup()

    def add_rs232_generator(self, serial_port: str or None, trains: Sequence[Train] = None):
        self.generator.open_port(serial_port, None if trains is None else tuple([train.address for train in trains]))
        # the new generator will automatically send the previously set states of relevant trains, no need to update here
        for train in trains or self.trains:
            self.ports_by_train[train].append(serial_port)

    def power_on(self, train: Optional[Train]):
        for port in (self.ports_by_train[train] if train else self.generator.get_open_ports()):
            self.generator.start(port)

    def power_off(self, train: Optional[Train]):
        for port in (self.ports_by_train[train] if train else self.generator.get_open_ports()):
            self.generator.stop(port)

    def is_power_on(self, train: Optional[Train]):
        return all([self.generator.is_sending_on(port) for port in (self.ports_by_train[train] if train else self.generator.get_open_ports())])

    def terminate(self):
        import time, os
        self.generator.terminate()
        time.sleep(.5)
        os._exit(0)

    def is_locked(self, train: Train):
        return train in self.locked_trains

    def set_locked(self, train: Train, locked: bool):
        if locked:
            self.locked_trains.add(train)
        elif train in self.locked_trains:
            self.locked_trains.remove(train)

    def get_target_speed(self, train: Train) -> float:
        """Signed target speed"""
        return self.target_speeds[train]

    def get_speed(self, train: Train):
        """Signed current speed"""
        return self.speeds[train]

    def is_emergency_stopping(self, train: Train):
        return self.speeds[train] is None

    def is_parked(self, train: Train):
        return self.speeds[train] == 0 and self.target_speeds[train] == 0

    def is_in_reverse(self, train: Train):
        direction = math.copysign(1, self.target_speeds[train])
        return direction < 0

    def reverse(self, train: Train):
        self.target_speeds[train] = - math.copysign(0, self.target_speeds[train])

    def set_target_speed(self, train: Train, signed_speed: float):
        if signed_speed != 0:
            if self.is_emergency_stopping(train):
                self.speeds[train] = math.copysign(0, self.target_speeds[train])
        if signed_speed == 0:
            self.target_speeds[train] = -0. if self.is_in_reverse(train) else 0.
        else:
            max_speed = train.max_speed if self.speed_limit is None else min(train.max_speed, self.speed_limit)
            self.target_speeds[train] = max(-max_speed, min(signed_speed, max_speed))

    def accelerate(self, train: Train, signed_times: int):
        in_reverse = self.is_in_reverse(train)
        target_level = int(numpy.argmin([abs(s - abs(self.target_speeds[train])) for s in train.speeds]))  # ≥ 0
        new_target_level = int(numpy.clip(target_level + signed_times, 0, 14))
        new_target_speed = train.speeds[new_target_level]
        self.set_target_speed(train, -new_target_speed if in_reverse else new_target_speed)

    def set_acceleration_control(self, train: Train, signed_factor: float):
        self.controls[train] = signed_factor

    def emergency_stop(self, train: Train):
        self.target_speeds[train] *= 0.
        self.speeds[train] = None
        currently_in_reverse = self.generator.is_in_reverse(train.address)
        functions = {f.id: f in self.active_functions[train] for f in train.functions}
        if train.stop_by_mm1_reverse:
            self.generator.set(train.address, None, False, functions, get_preferred_protocol(train))
        else:
            self.generator.set(train.address, 0, not currently_in_reverse, functions, get_preferred_protocol(train))

    def set_global_speed_limit(self, limit: float or None):
        self.speed_limit = limit
        for train in self.trains:
            if limit is not None and self.target_speeds[train] > limit:
                self.target_speeds[train] = limit

    def set_lights_on(self, on: bool):
        for train in self.trains:
            train._func_active = on
            train._update_signal()

    def update_trains(self, dt):  # repeatedly called from setup()
        # try:
            for train in TRAINS:
                self._update_train(train, dt)
        # except Exception as exc:
        #     warnings.warn(f"Exception in update_trains(): {exc}")

    def _update_train(self, train: Train, dt: float):  # called by update_trains()
        if not self.is_power_on(train):
            self.speeds[train] = 0
            return
        if self.controls[train] != 0:
            self.target_speeds[train] = self.speeds[train] + dt * train.acceleration * self.controls[train]
        if self.target_speeds[train] == self.speeds[train]:
            return
        speed = self.speeds[train]
        if speed is None:
            return  # emergency brake
        acc = train.acceleration if abs(self.target_speeds[train]) > abs(speed) else train.deceleration
        if self.target_speeds[train] > speed:
            self.speeds[train] = min(speed + acc * dt, self.target_speeds[train])
        else:
            self.speeds[train] = max(speed - acc * dt, self.target_speeds[train])
        self._update_signal(train)

    def _update_signal(self, train: Train):
        speed = self.speeds[train]
        target_speed = self.target_speeds[train]
        target_idx = int(numpy.argmin([abs(s - abs(target_speed)) for s in train.speeds]))  # ≥ 0
        if False:  # self.use_built_in_acceleration:
            speed_idx = target_idx
        else:
            if abs(target_speed) > abs(speed):  # ceil level
                speed_idx = [i for i, s in enumerate(train.speeds) if s >= abs(speed)][0] + 1
                speed_idx = min(speed_idx, target_idx)
            elif abs(target_speed) < abs(speed):  # floor level
                speed_idx = [i for i, s in enumerate(train.speeds) if s <= abs(speed)][-1] - 1
                speed_idx = max(speed_idx, target_idx)
            else:  # Equal
                speed_idx = target_idx
        speed_code = train.speed_codes[speed_idx]
        functions = {f.id: f in self.active_functions[train] for f in train.functions}
        direction = math.copysign(1, speed if speed != 0 else self.target_speeds[train])
        currently_in_reverse = direction < 0
        self.generator.set(train.address, speed_code, currently_in_reverse, functions, get_preferred_protocol(train))


# def handle_event(e: RawInputEvent):
#     if e.device.name not in CONTROLS:
#         return
#     train = CONTROLS[e.device.name]
#     if isinstance(e.device, Mouse) and e.device.num_buttons == 5:  # wireless mouse
#         pass
