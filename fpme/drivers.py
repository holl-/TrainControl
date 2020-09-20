import json

import numpy

from .trains import TRAINS, Train


class Driver:

    def __init__(self, name: str, trains: tuple):
        self.name = name
        self.trains = trains
        self.reverse = [False] * len(trains)


DRIVERS = {}  # name -> Driver


def load_train_drivers(file='../drivers.json'):
    with open(file) as users:
        user_dict = json.load(users)
        DRIVERS.clear()
        for user_name, train_names in user_dict.items():
            DRIVERS[user_name] = Driver(user_name, tuple(TRAINS[n] for n in train_names))


load_train_drivers()


def get_train(driver_name, train_index) -> Train or None:
    if driver_name not in DRIVERS:
        return None, False
    driver = DRIVERS[driver_name]
    if train_index >= len(driver.trains):
        return None, False
    return driver.trains[train_index], driver.reverse[train_index]


def set_reverse(driver_name, train_index, reverse):
    DRIVERS[driver_name].reverse[train_index] = reverse


def switch_drivers():
    perm = numpy.random.permutation(len(DRIVERS))
    drivers = numpy.array(tuple(DRIVERS.keys()))[perm]
    trains = list([DRIVERS[d] for d in drivers])
    trains.append(trains.pop(0))
    DRIVERS.clear()
    for driver, train in zip(drivers, trains):
        DRIVERS[driver] = train
    print(DRIVERS)
