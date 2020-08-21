import json

from fpme import signal_gen


GENERATOR = signal_gen.SignalGenerator('COM1', signal_gen.Motorola2())


class Train:

    def __init__(self, name, address, speeds=(-14, -12, -9, -7, -4, 0, 4, 7, 9, 12, 14)):
        self.name = name
        self.address = address
        self.speeds = speeds
        self.speed_level = speeds.index(0)
        self.func_active = False

    def accelerate(self, delta_level):
        self.speed_level = max(0, min(self.speed_level + delta_level, len(self.speeds) - 1))
        self._update()

    def stop(self):
        self.speed_level = self.speeds.index(0)
        self._update()

    def _update(self):
        GENERATOR.set(self.address, self.speeds[self.speed_level], self.func_active)


TRAINS = [
    Train('ICE', 60, (-12, -9, -6, -4, 0, 4, 6, 9, 14)),
    Train('E-Lok (DB)', 24, (-14, -9, -7, -4, 0, 4, 7, 9, 14)),
    Train('E-Lok (BW)', 1),
    Train('S-Bahn', 48, (-14, -10, -7, -4, 0, 4, 7, 10, 14)),
    Train('Dampf-Lok', 78, (-12, -9, -7, -4, 0, 4, 7, 9, 14)),
    Train('Diesel-Lok', 72),
]
TRAINS = {train.name: train for train in TRAINS}

DRIVERS = {}


def load_drivers(file='../users.json'):
    with open(file) as users:
        user_dict = json.load(users)
        DRIVERS.clear()
        for user_name, train_name in user_dict.items():
            DRIVERS[user_name] = TRAINS[train_name]


load_drivers()


def can_control(name):
    return name in DRIVERS


def get_speed(name):
    if name not in DRIVERS:
        return 0
    train = DRIVERS[name]
    return train.speeds[train.speed_level] / 14.


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
