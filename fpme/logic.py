import json

from fpme import signal_gen


class Train:

    def __init__(self, name, address):
        self.name = name
        self.address = address
        self.speed = 0.0


TRAINS = [
    Train('ICE', 60),
    Train('E-Lok (DB)', 24),
    Train('E-Lok (BW)', 1),
    Train('S-Bahn', 21),
    Train('Dampf-Lok', 78),
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
    new_speed = train.speed + delta * step_size
    new_speed = max(-1, min(new_speed, 1))
    train.speed = new_speed
    srcp.send(train.address, new_speed)


def stop(name=None):
    if name is None:
        srcp.set_power(False)
    else:
        if name not in DRIVERS:
            return
        train = DRIVERS[name]
        train.speed = 0
        srcp.send(train.address, speed=None)


def start():
    srcp.set_power(True)
