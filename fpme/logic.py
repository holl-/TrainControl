import json

import numpy

from fpme import signal_gen


with open('../config.json') as CONFIG_FILE:
    CONFIG = json.load(CONFIG_FILE)

GENERATOR = signal_gen.SignalGenerator(CONFIG['serial-port'] or None, signal_gen.Motorola2())


class Train:

    def __init__(self, name, address, speeds=(-14, -10, -8, -6, -4, 0, 4, 6, 8, 10, 14), protocol=None):
        self.name = name
        self.address = address
        self.speeds = speeds
        self.speed_level = speeds.index(0)
        self.func_active = False
        self.protocol = protocol

    def accelerate(self, delta_level):
        old_speed = self.speeds[self.speed_level]
        self.speed_level = max(0, min(self.speed_level + delta_level, len(self.speeds) - 1))
        new_speed = self.speeds[self.speed_level]
        if new_speed != 0:
            reverse = new_speed < 0
        else:
            reverse = old_speed < 0
        GENERATOR.set(self.address, abs(new_speed), reverse, self.func_active, protocol=self.protocol)

    def stop(self):
        old_speed = self.speeds[self.speed_level]
        was_reverse = old_speed < 0
        self.speed_level = self.speeds.index(0)
        GENERATOR.set(self.address, 0, not was_reverse, self.func_active, protocol=self.protocol)

    @property
    def speed(self):
        zero_level = self.speeds.index(0)
        current_level = self.speed_level
        if current_level == zero_level:
            return 0
        elif current_level > zero_level:
            return (current_level - zero_level) / (len(self.speeds) - 1 - zero_level)
        else:
            return (current_level - zero_level) / zero_level

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
TRAINS = {train.name: train for train in TRAINS}

DRIVERS = {}  # name -> Train


def load_drivers(file='../users.json'):
    with open(file) as users:
        user_dict = json.load(users)
        DRIVERS.clear()
        for user_name, train_name in user_dict.items():
            DRIVERS[user_name] = TRAINS[train_name]


load_drivers()


def switch_drivers():
    perm = numpy.random.permutation(len(DRIVERS))
    drivers = numpy.array(tuple(DRIVERS.keys()))[perm]
    trains = list([DRIVERS[d] for d in drivers])
    trains.append(trains.pop(0))
    DRIVERS.clear()
    for driver, train in zip(drivers, trains):
        DRIVERS[driver] = train
    print(DRIVERS)


def can_control(name):
    return name in DRIVERS


def get_speed(name):
    if name not in DRIVERS:
        return 0
    train = DRIVERS[name]
    return train.speed


def get_train_name(name):
    if name not in DRIVERS:
        return ''
    train = DRIVERS[name]
    return train.name


def accelerate(name: str, delta: int, step_size=1/6.):
    if name not in DRIVERS or delta == 0:
        return
    train = DRIVERS[name]
    train.accelerate(delta)


def stop(name=None):
    if name is None:
        GENERATOR.stop()
    else:
        if name not in DRIVERS:
            return
        train = DRIVERS[name]
        train.stop()


def start():
    GENERATOR.start()


def is_power_on():
    return GENERATOR.is_sending
