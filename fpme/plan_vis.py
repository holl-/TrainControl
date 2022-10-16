from typing import Iterable

import control
from control import State, update_state, OUTER_CONNECTION, OUTER, INTERIM, OUTER_UNTIL_SWITCH, HALF_TRAIN, INNER_CONNECTION, INNER

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.image as mpimg


def show(trains: Iterable[control.Controller]):
    img = mpimg.imread('Gleisplan v3.png')
    fig, ax = plt.subplots(1, 1)
    ax.imshow(img, extent=(-2.5, 194.5, -2, 195))
    circles = [plt.Circle((3, 3), radius=2) for train in trains]
    for circle in circles:
        ax.add_patch(circle)

    for i in range(1000):
        for train, circle in zip(trains, circles):
            circle.set_center(get_position(train.state))
        plt.pause(0.005)
        plt.draw()


def get_position(state: State):
    p = state.position
    if p == float('nan'):
        return 0, 0
    if state.outer_track:
        if p > OUTER:
            p -= OUTER
        P = [-OUTER_CONNECTION - HALF_TRAIN, -OUTER_CONNECTION, 0, 605.6, 1194.8, 2107.2, OUTER_UNTIL_SWITCH, 3342.8, 4104.0, 4746.7, OUTER]
        X = [16, 16, 50, 100, 165, 165, 120, 40, 8, 10, 50]
        Y = [60 + HALF_TRAIN * .1, 60, 20, 20, 60, 150, 170, 170, 100, 40, 20]
        return np.interp(p, P, X), np.interp(p, P, Y)
    else:  # inner track
        PXY = [
            [-INNER_CONNECTION - INTERIM - 1000, 220, 170],
            [-INNER_CONNECTION - INTERIM, 120, 170],
            [-INNER_CONNECTION - 629.6, 20, 130],
            [-INNER_CONNECTION, 20, 60],
            [0, 50, 30],
            [458.1, 90, 50],
            [1414.9, 90, 143],
            [1644.0, 100, 160],
            [2209.5, 155, 160],
            [2835.6, 155, 83],
            [3024.1, 140, 65],
            [INNER, 50, 30],
            [INNER + INNER_CONNECTION, 20, 60],
        ]
        P, X, Y = np.array(PXY).T
        return np.interp(p, P, X), np.interp(p, P, Y)


if __name__ == '__main__':
    show([control.GTO, control.IGBT])