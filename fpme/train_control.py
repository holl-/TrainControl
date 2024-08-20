import math
import time
import warnings
from typing import Sequence, Optional, Dict, Set

import numpy

from .helper import schedule_at_fixed_rate
from .signal_gen import SubprocessGenerator, MM1, MM2
from .train_def import TRAINS, Train, TAG_DEFAULT_LIGHT, TAG_DEFAULT_SOUND


def get_preferred_protocol(train: Train):
    return MM2 if train.supports_mm2 else MM1


EMERGENCY_STOP = 'emergency stop'


class TrainControl:

    def __init__(self, trains=TRAINS):
        self.trains = trains
        self.ports_by_train: Dict[Train, Set[str]] = {train: set() for train in trains}
        self.generator = SubprocessGenerator(max_generators=2)
        self.speed_limit = None
        self.locked_trains = set()
        self.target_speeds = {train: 0. for train in trains}  # signed speed in kmh, -0 means parked in reverse
        self.speeds = {train: 0. for train in trains}  # signed speed in kmh, set to EMERGENCY_STOP while train is braking
        self.active_functions = {train: {f: True for f in train.functions if f.default_status} for train in trains}  # which functions are active by their TrainFunction handle
        self.controls = {train: 0. for train in trains}
        self.last_emergency_break = {train: 0. for train in trains}
        self.inactive_time = {train: 0. for train in trains}
        self.drivers: Dict[Train, Set[str]] = {train: set() for train in trains}
        self.global_status_by_tag: Dict[str, bool] = {}
        self.sound = None
        self.light = None
        self.paused = False
        for train in trains:
            self.generator.set(train.address, 0, False, {}, get_preferred_protocol(train))
        schedule_at_fixed_rate(self.update_trains, period=.03)
        self.generator.setup()

    def add_rs232_generator(self, serial_port: str, trains: Sequence[Train] = None):
        self.generator.open_port(serial_port, None if trains is None else tuple([train.address for train in trains]))
        # the new generator will automatically send the previously set states of relevant trains, no need to update here
        for train in trains or self.trains:
            self.ports_by_train[train].add(serial_port)

    def power_on(self, train: Optional[Train]):
        if self.paused:
            return
        for port in (self.ports_by_train[train] if train else self.generator.get_open_ports()):
            self.generator.start(port)

    def power_off(self, train: Optional[Train]):
        for port in (self.ports_by_train[train] if train else self.generator.get_open_ports()):
            self.generator.stop(port)

    def is_power_on(self, train: Optional[Train]):
        return any([self.generator.is_sending_on(port) for port in (self.ports_by_train[train] if train else self.generator.get_open_ports())])

    def pause(self):
        self.paused = True
        for port in self.generator.get_open_ports():
            self.generator.stop(port)

    def resume(self):
        self.paused = False
        for port in self.generator.get_open_ports():
            self.generator.start(port)

    def terminate(self):
        import time
        import os
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
        # ToDo integrate train to time.perf_counter()
        return self.speeds[train]

    def is_emergency_stopping(self, train: Train):
        return self.speeds[train] is None

    def is_parked(self, train: Train):
        return self.speeds[train] is None or (self.speeds[train] == 0 and self.target_speeds[train] == 0)

    def is_in_reverse(self, train: Train):
        direction = math.copysign(1, self.target_speeds[train])
        return direction < 0

    def reverse(self, train: Train, driver: Optional[str]):
        if not self.is_active(train):
            self.activate(train, driver)
            return
        self.target_speeds[train] = - math.copysign(0, self.target_speeds[train])

    def set_target_speed(self, train: Train, signed_speed: float, driver: Optional[str]):
        if not self.is_active(train) and signed_speed != 0:
            self.activate(train, driver)  # accelerate and simultaneously enable sound, so we don't have to wait
        if signed_speed != 0:
            if self.is_emergency_stopping(train):
                self.speeds[train] = math.copysign(0, self.target_speeds[train])
        if signed_speed == 0:
            self.target_speeds[train] = -0. if self.is_in_reverse(train) else 0.
        else:
            max_speed = train.max_speed if self.speed_limit is None else min(train.max_speed, self.speed_limit)
            self.target_speeds[train] = max(-max_speed, min(signed_speed, max_speed))

    def accelerate(self, train: Train, signed_times: int, driver: Optional[str]):
        in_reverse = self.is_in_reverse(train)
        target_level = int(numpy.argmin([abs(s - abs(self.target_speeds[train])) for s in train.speeds]))  # ≥ 0
        new_target_level = int(numpy.clip(target_level + signed_times, 0, 14))
        new_target_speed = train.speeds[new_target_level]
        self.set_target_speed(train, -new_target_speed if in_reverse else new_target_speed, driver)

    def set_acceleration_control(self, train: Train, signed_factor: float, driver: Optional[str]):
        if not self.is_active(train):
            if signed_factor <= 0:
                self.activate(train, driver)
                return
            else:
                self.activate(train, driver)  # accelerate and simultaneously enable sound, so we don't have to wait
        if signed_factor != 0 and self.controls[train] * signed_factor <= 0:
            speed_idx = self._get_speed_index(train, signed_factor, False, False)
            abs_speed = train.speeds[speed_idx]
            prev_speed = self.speeds[train]
            self.speeds[train] = math.copysign(abs_speed + signed_factor * 1e-2, self.target_speeds[train])
            print(f"Acceleration {train.name} = {signed_factor} (speed = {prev_speed} ({speed_idx}) -> {self.speeds[train]}, target={self.target_speeds[train]})")
        self.controls[train] = signed_factor

    def emergency_stop_all(self, train: Optional[Train]):
        """Immediately stop all trains on the same track as `train`."""
        if train is None:
            trains = self.trains
        else:
            ports: Set[str] = self.ports_by_train[train]
            trains = {t for t in self.trains if self.ports_by_train[t] & ports}
        for t in trains:
            self.emergency_stop(t)

    def emergency_stop(self, train: Train):
        """Immediately stop `train`."""
        self.target_speeds[train] *= 0.
        self.speeds[train] = None
        currently_in_reverse = self.generator.is_in_reverse(train.address)
        functions = {f.id: on for f, on in self.active_functions[train].items()}
        self.last_emergency_break[train] = time.perf_counter()
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
        if self.light == on:
            return
        self.light = on
        self.set_functions_by_tag(TAG_DEFAULT_LIGHT, on)

    def set_sound_on(self, on: bool):
        if self.sound == on:
            return
        self.sound = on
        self.set_functions_by_tag(TAG_DEFAULT_SOUND, on)

    def set_functions_by_tag(self, tag: str, on: bool):
        self.global_status_by_tag[tag] = on
        for train in self.trains:
            self.set_train_functions_by_tag(train, tag, on and self.is_active(train))

    def set_train_functions_by_tag(self, train: Train, tag: str, on: bool):
        for func in train.functions:
            if tag in func.tags:
                print(f"setting {train}.{tag} = {on}")
                self.active_functions[train][func] = on

    def activate(self, train: Train, driver: Optional[str]):
        """ user: If no user specified, will auto-deactivate again soon. """
        if driver is None:
            self.drivers[train].add('default')
        else:
            self.drivers[train].add(driver)
            if 'default' in self.drivers[train]:
                self.drivers[train].remove('default')
        self.inactive_time[train] = 0.
        for tag, on in self.global_status_by_tag.items():
            self.set_train_functions_by_tag(train, tag, on)

    def deactivate(self, train: Train, driver: Optional[str]):
        """ user: If `None`, will remove all users. """
        if driver is None:
            self.drivers[train].clear()
        else:
            if driver in self.drivers[train]:
                self.drivers[train].remove(driver)
            elif self.drivers[train]:
                warnings.warn(f"Trying to remove unregistered driver from {train}: {driver}.\nRegistered: {self.drivers[train]}")
        if not self.drivers[train]:
            self.set_train_functions_by_tag(train, TAG_DEFAULT_LIGHT, False)
            self.set_train_functions_by_tag(train, TAG_DEFAULT_SOUND, False)
            self.set_target_speed(train, 0, driver)

    def is_active(self, train: Train):
        return len(self.drivers[train]) > 0 and self.inactive_time[train] <= 30.

    def update_trains(self, dt):  # repeatedly called from setup()
        if self.paused:
            return
        for train in self.trains:
            self._update_train(train, dt)

    def _update_train(self, train: Train, dt: float):  # called by update_trains()
        if not self.is_power_on(train):
            self.speeds[train] = 0
            return
        if self.controls[train] == 0 and self.speeds[train] == 0 and self.is_active(train):
            self.inactive_time[train] += dt
            if not self.is_active(train):
                self.set_train_functions_by_tag(train, TAG_DEFAULT_LIGHT, False)
                self.set_train_functions_by_tag(train, TAG_DEFAULT_SOUND, False)
        elif self.controls[train] != 0 or self.speeds[train] != 0:
            self.inactive_time[train] = 0
        if self.controls[train] != 0:
            abs_target = max(0, abs(self.speeds[train] or 0.) + dt * train.acceleration * self.controls[train])
            self.target_speeds[train] = abs_target * (-1. if self.is_in_reverse(train) else 1.)
        speed = self.speeds[train]
        if speed is None:
            speed = 0. * self.target_speeds[train]  # update next time
            if self.controls[train] > 0 or time.perf_counter() > self.last_emergency_break[train] + .5:
                self.speeds[train] = speed
            else:
                return  # emergency brake, don't update signal
        acc = train.acceleration if abs(self.target_speeds[train]) > abs(speed) else train.deceleration
        if self.target_speeds[train] > speed:
            self.speeds[train] = min(speed + acc * dt, self.target_speeds[train])
        else:
            self.speeds[train] = max(speed - acc * dt, self.target_speeds[train])
        self._update_signal(train)

    def _update_signal(self, train: Train):
        speed = self.speeds[train]
        speed_idx = self._get_speed_index(train, abs(self.target_speeds[train]) - abs(speed), True)
        # if train.has_built_in_acceleration:
        speed_code = train.speed_codes[speed_idx]
        functions = {f.id: on for f, on in self.active_functions[train].items()}
        direction = math.copysign(1, speed if speed != 0 else self.target_speeds[train])
        currently_in_reverse = direction < 0
        self.generator.set(train.address, speed_code, currently_in_reverse, functions, get_preferred_protocol(train))

    def _get_speed_index(self, train: Train, abs_acceleration, limit_by_target: bool, round_up_to_first=True):
        abs_speed = abs(self.speeds[train])
        target_idx = int(numpy.argmin([abs(s - abs(self.target_speeds[train])) for s in train.speeds]))  # ≥ 0
        if abs_acceleration > 0:  # ceil level
            greater = [i for i, s in enumerate(train.speeds) if s >= abs_speed]
            speed_idx = greater[0] if greater else len(train.speeds) - 1
            if limit_by_target:
                speed_idx = min(speed_idx, target_idx)
        elif abs_acceleration < 0:  # floor level
            speed_idx = [i for i, s in enumerate(train.speeds) if s <= abs_speed][-1]
            if limit_by_target:
                speed_idx = max(speed_idx, target_idx)
        else:  # Equal
            speed_idx = target_idx
        if round_up_to_first and abs_speed > 0 and speed_idx == 0:
            speed_idx = 1  # this ensures we don't wait for startup sound to finish
        return speed_idx


# def handle_event(e: RawInputEvent):
#     if e.device.name not in CONTROLS:
#         return
#     train = CONTROLS[e.device.name]
#     if isinstance(e.device, Mouse) and e.device.num_buttons == 5:  # wireless mouse
#         pass
