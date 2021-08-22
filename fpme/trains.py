import json
import time

import numpy

from fpme import signal_gen


with open('../config.json') as CONFIG_FILE:
    CONFIG = json.load(CONFIG_FILE)

GENERATOR = signal_gen.SignalGenerator(CONFIG['serial-port'] or None, signal_gen.Motorola2())


class Train:

    def __init__(self, name: str, address: int, snap_to_speeds=(-14, -10, -8, -6, -4, 0, 4, 6, 8, 10, 14), protocol=None):
        self.name: str = name
        self.address: int = address
        self.snap_to_speeds: tuple = snap_to_speeds  # -14 to 14
        self.abs_speed: int = 0  # 0 to 14
        self.in_reverse = False
        self.func_active = False
        self.protocol = protocol  # special protocol for this train

    @property
    def signed_speed(self):
        return -self.abs_speed if self.in_reverse else self.abs_speed

    def reverse(self):
        self.in_reverse = not self.in_reverse
        self.abs_speed = 0

    def set_signed_speed(self, signed_speed: int):
        self.abs_speed = abs(signed_speed)
        if signed_speed != 0:
            self.in_reverse = signed_speed < 0

    def accelerate_snap(self, signed_times: int):
        if signed_times < 0 and self.is_parked:
            return
        if self.signed_speed in self.snap_to_speeds:
            speed_level = self.snap_to_speeds.index(self.signed_speed)
        else:
            speed_level = numpy.argmin([abs(s - self.signed_speed) for s in self.snap_to_speeds])  # closest level
        forward_times = -signed_times if self.in_reverse else signed_times
        new_speed_level = max(0, min(speed_level + forward_times, len(self.snap_to_speeds) - 1))
        self.abs_speed = abs(self.snap_to_speeds[new_speed_level])
        GENERATOR.set(self.address, self.abs_speed, self.in_reverse, self.func_active, protocol=self.protocol)

    def stop(self):
        self.abs_speed = 0
        GENERATOR.set(self.address, 0, not self.in_reverse, self.func_active, protocol=self.protocol)

    @property
    def is_parked(self):
        return self.abs_speed == 0

    def __repr__(self):
        return self.name


TRAINS = [
    Train('ICE', 60, (-12, -9, -6, -4, 0, 4, 6, 9, 14)),
    Train('E-Lok (DB)', 24, (-14, -9, -7, -4, 0, 4, 7, 9, 14), protocol=signal_gen.Motorola1()),
    Train('E-Lok (BW)', 1),
    Train('S-Bahn', 48, (-14, -12, -10, -7, -4, 0, 4, 7, 10, 12, 14)),
    Train('Dampf-Lok', 78, (-12, -9, -7, -6, -5, -4, 0, 4, 5, 6, 7, 9, 14)),
    Train('Diesel-Lok', 72),
]


POWER_OFF_TIME = 0


def power_on():
    print("Power on")
    GENERATOR.start()


def power_off():
    print("Power off")
    GENERATOR.stop()
    global POWER_OFF_TIME
    POWER_OFF_TIME = time.perf_counter()


def is_power_on():
    return GENERATOR.is_sending
