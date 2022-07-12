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
        self.has_built_in_acceleration: bool = has_built_in_acceleration
        self.acceleration: float = acceleration
        self.break_acc: float = 2 * acceleration
        # State
        self._target_speed: float = 0.  # signed speed in kmh, -0 means parked in reverse
        self._speed: float = 0.  # signed speed in kmh
        self._func_active = False
        self._broadcasting_state = (None, None, None)  # (speed_level: int, in_reverse: bool, func_active: bool)

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

    def update(self, dt: float):
        if not is_power_on():
            self._speed = 0
            return
        if self._target_speed == self._speed:
            return
        acceleration = self.acceleration if abs(self._target_speed) > abs(self._speed) else self.break_acc
        if self._target_speed > self._speed:
            self._speed = min(self._speed + acceleration * dt, self._target_speed)
        else:
            self._speed = max(self._speed - acceleration * dt, self._target_speed)
        self.update_signal()

    def update_signal(self):
        send_speed = self._target_speed if self.has_built_in_acceleration else self._speed
        speed_level = int(numpy.argmin([abs(s - abs(send_speed)) for s in self.speeds]))
        new_state = (speed_level, self.in_reverse, self._func_active)
        if new_state != self._broadcasting_state:
            self._broadcasting_state = new_state
            GENERATOR.set(self.address, speed_level, self.in_reverse, self._func_active, protocol=self.protocol)
            # print(f"Updating signal to speed {-speed_level if self.in_reverse else speed_level}")

    def emergency_stop(self):
        self._target_speed = 0.
        self._speed = 0.
        in_reverse = not self._broadcasting_state[1]
        GENERATOR.set(self.address, 0, in_reverse, self._func_active, protocol=self.protocol)
        self._broadcasting_state = (0., in_reverse, self._func_active)

    def reverse(self):
        self._target_speed = - math.copysign(0, self._target_speed)

    def set_target_speed(self, signed_speed: float):
        self._target_speed = max(-self.max_speed, min(signed_speed, self.max_speed))

    def accelerate(self, signed_times: int, resolution=6):
        if signed_times < 0 and self.is_parked:
            return
        in_reverse = self.in_reverse
        abs_speed = max(0, abs(self._target_speed) + self.max_speed / resolution * signed_times)
        self.set_target_speed(-abs_speed if in_reverse else abs_speed)

    @property
    def is_parked(self):
        return self._speed == 0

    def __repr__(self):
        return self.name


TRAINS = [
    Train('ICE', address=60, acceleration=40., speeds=(0, 21, 43, 64, 86, 107, 129, 150, 171, 193, 214, 236, 257, 279, 300)),
    Train('E-Lok (DB)', address=24, protocol=signal_gen.Motorola1(), speeds=(0, 18, 36, 54, 71, 89, 107, 125, 143, 161, 179, 196, 214, 232, 250)),
    Train('E-Lok (BW)', address=1, acceleration=30., has_built_in_acceleration=True, speeds=(0, 18, 36, 54, 71, 89, 107, 125, 143, 161, 179, 196, 214, 232, 250)),
    Train('S-Bahn', address=48, acceleration=20., has_built_in_acceleration=True, speeds=(0, 16, 31, 47, 63, 79, 94, 110, 126, 141, 157, 173, 189, 204, 220)),
    Train('Dampf-Lok', address=78, speeds=(0, 14, 29, 43, 57, 71, 86, 100, 114, 129, 143, 157, 171, 186, 200)),
    Train('Diesel-Lok', address=72, speeds=(0, 14, 29, 43, 57, 71, 86, 100, 114, 129, 143, 157, 171, 186, 200)),
]


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


def update_trains(dt):
    try:
        for train in TRAINS:
            train.update(dt)
    except Exception as exc:
        warnings.warn(f"Exception in update_trains(): {exc}")


TRAIN_UPDATE_PERIOD = 0.1


def setup(serial_port: str or None):
    global GENERATOR
    GENERATOR = signal_gen.ProcessSpawningGenerator(serial_port)
    schedule_at_fixed_rate(update_trains, TRAIN_UPDATE_PERIOD)
