import math
import threading
import time
import warnings
from threading import Thread
from typing import Sequence, Optional, Dict, Set, Tuple, Callable

import numpy
from dataclasses import dataclass, field

from .helper import schedule_at_fixed_rate
from .signal_gen import SubprocessGenerator, MM1, MM2
from .train_def import TRAINS, Train, TAG_DEFAULT_LIGHT, TAG_DEFAULT_SOUND, TAG_SPECIAL_SOUND


def get_preferred_protocol(train: Train):
    return MM2 if train.supports_mm2 else MM1


EMERGENCY_STOP = 'emergency stop'


@dataclass
class TrainState:
    train: Train
    ports: Set[str]
    active_functions: dict  # which functions are active by their TrainFunction handle
    speed: float = 0.  # signed speed in kmh, set to EMERGENCY_STOP while train is braking
    target_speed: float = 0.  # signed speed in kmh, -0 means parked in reverse
    acc_input: float = 0.
    inactive_time: float = 0.
    controllers: Set[str] = field(default_factory=set)
    last_emergency_break: Tuple[float, str] = (0., "")
    speed_limits: Dict[str, float] = field(default_factory=dict)
    force_stopping: Optional[str] = None
    signed_distance: float = 0.  # distance travelled in cm
    abs_distance: float = 0.  # distance travelled in cm
    primary_ability_last_used = 0.
    modify_lock = threading.RLock()
    custom_acceleration_handler: Callable = None

    def __repr__(self):
        return f"{self.train.name} {self.speed:.0f} -> {self.target_speed:.0f} func={self.active_functions} controlled by {len(self.controllers)}"

    @property
    def is_emergency_stopping(self):
        return self.speed is None

    @property
    def is_parked(self):
        return self.speed is None or (self.speed == 0 and self.target_speed == 0)

    @property
    def is_in_reverse(self):
        direction = math.copysign(1, self.target_speed)
        return direction < 0

    @property
    def is_active(self):
        return len(self.controllers) > 0 and self.inactive_time <= 30.

    def set_speed_limit(self, name: str, limit: Optional[float], jerk=True):
        with self.modify_lock:
            if limit is None:
                if name in self.speed_limits:
                    del self.speed_limits[name]
            else:
                self.speed_limits[name] = max(0., limit)
                if jerk and self.speed is not None and abs(self.speed) > limit:
                    self.speed *= limit / abs(self.speed)
                self.set_target_speed(self.target_speed)

    def set_target_speed(self, target_speed):
        with self.modify_lock:
            if not self.speed_limits:
                self.target_speed = target_speed
            else:
                self.target_speed = math.copysign(min(abs(target_speed), *self.speed_limits.values()), target_speed)

    @property
    def can_use_primary_ability(self):
        ability = self.train.primary_ability
        if ability is None:
            return False
        if not self.primary_ability_last_used:
            return True
        return time.perf_counter() - self.primary_ability_last_used > ability.cooldown


class TrainControl:

    def __init__(self, trains=TRAINS):
        self.trains = trains
        self.states = {train: TrainState(train, set(), active_functions={f: True for f in train.functions if f.default_status}) for train in trains}
        self.generator = SubprocessGenerator(max_generators=2)
        self.speed_limit = None
        self.global_status_by_tag: Dict[str, bool] = {}
        self.sound: int = 0  # 0=off 1=announcements 2=all
        self.light = None
        self.paused = False
        self.last_emergency_break_all = (0., "")
        self.last_power_off = (0., "")
        self.last_power_on = (0., "")
        for train in trains:
            self.generator.set(train.address, 0, False, {}, get_preferred_protocol(train))
        schedule_at_fixed_rate(self.update_trains, period=.03)
        self.generator.setup()

    def add_rs232_generator(self, serial_port: str, trains: Sequence[Train] = None):
        self.generator.open_port(serial_port, None if trains is None else tuple([train.address for train in trains]))
        # the new generator will automatically send the previously set states of relevant trains, no need to update here
        for train in trains or self.trains:
            self.states[train].ports.add(serial_port)

    def power_on(self, train: Optional[Train], cause: str):
        if self.paused:
            return
        for port in (self[train].ports if train else self.generator.get_open_ports()):
            self.generator.start(port)
        self.last_power_on = (time.perf_counter(), cause)

    def power_off(self, train: Optional[Train], cause: str):
        for port in (self[train].ports if train else self.generator.get_open_ports()):
            self.generator.stop(port)
        self.last_power_off = (time.perf_counter(), cause)

    def is_power_on(self, train: Optional[Train]):
        return any([self.generator.is_sending_on(port) for port in (self[train].ports if train else self.generator.get_open_ports())])

    def pause(self):
        self.paused = True
        for port in self.generator.get_open_ports():
            self.generator.stop(port)
        self.last_power_off = (time.perf_counter(), "master pause")

    def resume(self):
        self.paused = False
        for port in self.generator.get_open_ports():
            self.generator.start(port)
        self.last_power_on = (time.perf_counter(), "master resume")

    def __getitem__(self, item):
        if isinstance(item, Train):
            return self.states[item]
        raise KeyError(item)

    def reverse(self, train: Train, cause: str):
        state = self[train]
        if not state.is_active:
            self.activate(train, cause)
            return
        state.target_speed = - math.copysign(0, state.target_speed)

    # def set_target_speed(self, train: Train, signed_speed: float, cause: str):
    #     if not self.is_active(train) and signed_speed != 0:
    #         self.activate(train, cause)  # accelerate and simultaneously enable sound, so we don't have to wait
    #     if signed_speed != 0:
    #         if self.is_emergency_stopping(train):
    #             self.speeds[train] = math.copysign(0, self.target_speeds[train])
    #     if signed_speed == 0:
    #         self.target_speeds[train] = -0. if self.is_in_reverse(train) else 0.
    #     else:
    #         max_speed = train.max_speed if self.speed_limit is None else min(train.max_speed, self.speed_limit)
    #         self.target_speeds[train] = max(-max_speed, min(signed_speed, max_speed))
    #
    # def accelerate(self, train: Train, signed_times: int, cause: str):
    #     in_reverse = self.is_in_reverse(train)
    #     target_level = int(numpy.argmin([abs(s - abs(self.target_speeds[train])) for s in train.speeds]))  # ≥ 0
    #     new_target_level = int(numpy.clip(target_level + signed_times, 0, 14))
    #     new_target_speed = train.speeds[new_target_level]
    #     self.set_target_speed(train, -new_target_speed if in_reverse else new_target_speed, cause)

    def set_acceleration_control(self, train: Train, controller: str, acc_input: float, cause: str):
        state = self[train]
        with state.modify_lock:
            state.controllers.add(controller)
            if not state.is_active:
                if acc_input <= 0:
                    self.activate(train, cause)
                    return
                else:
                    self.activate(train, cause)  # accelerate and simultaneously enable sound, so we don't have to wait
            if state.custom_acceleration_handler is not None:
                state.custom_acceleration_handler(train, controller, acc_input, cause)
            else:
                if acc_input != 0 and state.acc_input * acc_input <= 0:  # switching acceleration direction
                    speed_idx = get_speed_index(train, state, acc_input, False, False)
                    abs_speed = train.speeds[speed_idx]
                    # prev_speed = state.speed
                    state.speed = math.copysign(abs_speed + acc_input * 1e-2, state.target_speed)
                    # print(f"Acceleration {train.name} = {acc_input} (speed = {prev_speed} ({speed_idx}) -> {state.speed}, target={state.target_speed})")
                state.acc_input = acc_input

    def emergency_stop_all(self, train: Optional[Train], cause: str):
        """Immediately stop all trains on the same track as `train`."""
        self.last_emergency_break_all = (time.perf_counter(), cause)
        if train is None:
            trains = self.trains
        else:
            ports: Set[str] = self[train].ports
            trains = {t for t in self.trains if self[t].ports & ports}
        for t in trains:
            self.emergency_stop(t, cause)

    def emergency_stop(self, train: Train, cause: str):
        """Immediately stop `train`."""
        state = self[train]
        with state.modify_lock:
            state.target_speed *= 0.
            state.speed = None
            currently_in_reverse = self.generator.is_in_reverse(train.address)
            functions = {f.id: on for f, on in state.active_functions.items()}
            state.last_emergency_break = (time.perf_counter(), cause)
        if train.stop_by_mm1_reverse:
            self.generator.set(train.address, None, False, functions, get_preferred_protocol(train))
        else:
            self.generator.set(train.address, 0, not currently_in_reverse, functions, get_preferred_protocol(train))

    def set_global_speed_limit(self, limit: Optional[float]):
        self.speed_limit = limit
        for train in self.trains:
            self[train].set_speed_limit('global', limit)

    def set_speed_limit(self, train: Train, cause: str, limit: Optional[float]):
        self[train].set_speed_limit(cause, limit)

    def force_stop(self, train: Train, cause: str):
        state = self[train]
        with state.modify_lock:
            state.force_stopping = cause

    def set_lights_on(self, on: bool):
        if self.light == on:
            return
        self.light = on
        self.set_functions_by_tag(TAG_DEFAULT_LIGHT, on)

    def set_sound_on(self, on: bool):
        level = max(0, min(self.sound + (1 if on else -1), 2))
        if self.sound != level:
            self.sound = level
            self.set_functions_by_tag(TAG_DEFAULT_SOUND, level >= 2)

    def set_functions_by_tag(self, tag: str, on: bool):
        self.global_status_by_tag[tag] = on
        for train in self.trains:
            self.set_train_functions_by_tag(train, tag, on and self[train].is_active)

    def set_train_functions_by_tag(self, train: Train, tag: str, on: bool):
        for func in train.functions:
            if tag in func.tags:
                print(f"setting {train}.{func.name} = {on}")
                state = self[train]
                with state.modify_lock:
                    state.active_functions[func] = on

    def use_ability(self, train: Train, cause: str):
        func = train.primary_ability
        state = self[train]
        with state.modify_lock:
            state.active_functions[func] = True
            state.primary_ability_last_used = time.perf_counter()
            if TAG_SPECIAL_SOUND in func.tags:
                def deactivate():
                    time.sleep(1.1)
                    state.active_functions[func] = False
                Thread(target=deactivate).start()

    def activate(self, train: Train, cause: str):
        """ user: If no user specified, will auto-deactivate again soon. """
        state = self[train]
        with state.modify_lock:
            if cause is None:
                state.controllers.add('default')
            else:
                state.controllers.add(cause)
                if 'default' in state.controllers:
                    state.controllers.remove('default')
            state.inactive_time = 0.
            for tag, on in self.global_status_by_tag.items():
                self.set_train_functions_by_tag(train, tag, on)

    def remove_controller(self, controller: str):
        for train in self.trains:
            state = self[train]
            if controller in state.controllers:
                with state.modify_lock:
                    state.controllers.remove(controller)
                    if not state.controllers:
                        print(f"Deactivating {train} because it has no more controllers (triggered by removal of {controller})")
                        self.set_train_functions_by_tag(train, TAG_DEFAULT_LIGHT, False)
                        self.set_train_functions_by_tag(train, TAG_DEFAULT_SOUND, False)
                        self.force_stop(train, 'deactivation')

    # def deactivate(self, train: Train, cause: str):
    #     """ user: If `None`, will remove all users. """
    #     state = self[train]

    def update_trains(self, dt):  # repeatedly called from setup()
        if self.paused:
            return
        failing = [port for port in self.generator.get_open_ports() if self.generator.is_short_circuited(port)]
        if failing:
            self.last_power_off = (time.perf_counter(), f"Power failure on {failing}")
        for train in self.trains:
            self._update_train(train, dt)

    def _update_train(self, train: Train, dt: float):  # called by update_trains()
        state = self[train]
        with state.modify_lock:
            if not self.is_power_on(train):
                state.speed = 0
                return
            # --- Signed distance ---
            if state.speed:
                speed_cm_s = state.speed * 27.78 / 87
                state.signed_distance += speed_cm_s * dt
                state.abs_distance += abs(speed_cm_s) * dt
            # --- Deactivate after 30 seconds of inactivity ---
            if state.acc_input == 0 and state.speed == 0 and state.is_active:
                state.inactive_time += dt
                if not state.is_active:
                    self.set_train_functions_by_tag(train, TAG_DEFAULT_LIGHT, False)
                    self.set_train_functions_by_tag(train, TAG_DEFAULT_SOUND, False)
            elif state.acc_input != 0 or state.speed != 0:
                state.inactive_time = 0
            # --- Input ---
            if state.force_stopping:
                state.target_speed = math.copysign(0, state.target_speed)
                if abs(state.speed) == 0:
                    state.force_stopping = False
            elif state.acc_input != 0:
                acc = train.acceleration if state.acc_input > 0 else train.deceleration
                abs_target = max(0., abs(state.speed or 0.) + dt * acc * state.acc_input)
                state.target_speed = abs_target * (-1. if state.is_in_reverse else 1.)
            # --- Compute new speed ---
            speed = state.speed
            if speed is None:
                speed = 0. * state.target_speed  # update next time
                if state.acc_input > 0 or time.perf_counter() > state.last_emergency_break[0] + .5:
                    state.speed = speed
                else:
                    return  # emergency brake, don't update signal
            if state.acc_input != 0:
                acc = train.deceleration if state.acc_input < 0 else train.acceleration
            else:
                acc = train.acceleration if abs(state.target_speed) > abs(speed) else train.deceleration
            if state.target_speed > speed:
                state.speed = min(speed + acc * dt, state.target_speed)
            else:
                state.speed = max(speed - acc * dt, state.target_speed)
        self._update_signal(train)

    def _update_signal(self, train: Train):
        state = self[train]
        speed_idx = get_speed_index(train, state, abs(state.target_speed) - abs(state.speed), True)
        # if train.has_built_in_acceleration:
        speed_code = train.speed_codes[speed_idx]
        functions = {f.id: on for f, on in state.active_functions.items()}
        direction = math.copysign(1, state.speed if state.speed != 0 else state.target_speed)
        currently_in_reverse = direction < 0
        self.generator.set(train.address, speed_code, currently_in_reverse, functions, get_preferred_protocol(train))


def get_speed_index(train: Train, state: TrainState, abs_acceleration, limit_by_target: bool, round_up_to_first=True):
    if state.speed is None:
        return 0
    abs_speed = abs(state.speed)
    target_idx = int(numpy.argmin([abs(s - abs(state.target_speed)) for s in train.speeds]))  # ≥ 0
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
