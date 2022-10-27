import os
from dataclasses import dataclass
from typing import List

HALF_TRAIN = 366  # Distance from train center to outermost wheel
TRAIN_CONTACT = 195  # Distance from train center to outermost contact wheel
INNER = 4137.7  # Length of inner track (excluding joint track)
OUTER = 5201.2  # Length of outer track
INNER_CONNECTION = 565.5
OUTER_CONNECTION = 643.0
INTERIM = 1794.8
OUTER_UNTIL_SWITCH = 2565.4

I_AIRPORT = 1832.5
I_ERDING = 2835.6
I_MUNICH = HALF_TRAIN + 50
O_ERDING = 1595.6
O_AIRPORT = 2565.4
O_MUNICH = 5100
O_CONTACT_NORTH = 4558.2
I_AIRPORT_CONTACT_WEST = -1801.0

OUTER_CONTACT = 'RI'  # contact 1 (red)
INNER_CONTACT = 'DSR'  # contact 2 (yellow)
AIRPORT_CONTACT = 'CD'  # contact 3 (green)

NAN = float('nan')

@dataclass
class State:
    cumulative_signed_distance: float
    outer_track: bool  # None if unknown
    position: float  # Position of the train center on the track in mm, nan if unknown
    aligned: bool  # Whether driving forward increases the position, None if unknown

    def __str__(self):
        return f"{'?' if self.outer_track is None else 'outer' if self.outer_track else 'inner'} {self.position:.1f} {'?' if self.aligned is None else 'fwd' if self.aligned else 'bwd'}"

    @staticmethod
    def from_line(line: str):
        track, pos, aligned = line.strip().split(' ')
        track = {'outer': True, 'inner': False, '?': None}[track]
        aligned = {'fwd': True, 'bwd': False, '?': None}[aligned]
        return State(0, track, float(pos), aligned)


def update_state(state: State, cumulative_signed_distance):
    delta = (int(state.aligned) * 2 - 1) * (cumulative_signed_distance - state.cumulative_signed_distance)
    position = state.position + delta
    outer_track = state.outer_track
    aligned = state.aligned
    if outer_track and position > OUTER + HALF_TRAIN:
        position -= OUTER
    elif outer_track and position < -OUTER_CONNECTION - HALF_TRAIN:
        outer_track = False
        position += (OUTER_CONNECTION - INNER_CONNECTION)
    elif not outer_track and position > INNER + HALF_TRAIN:
        position = - (position - INNER)
        aligned = not aligned
    elif not outer_track and position < -(INNER_CONNECTION + INTERIM + HALF_TRAIN):
        outer_track = True
        position = OUTER_UNTIL_SWITCH - (-position - INNER_CONNECTION - INTERIM)
    return State(cumulative_signed_distance, outer_track, position, aligned)





# def exit_unsafe_switches(state: State) -> float:
#     if state.outer_track and -HALF_TRAIN - OUTER_CONNECTION < state.position < HALF_TRAIN - OUTER_CONNECTION:
#         return state.position - OUTER_CONNECTION - HALF_TRAIN
#         # ToDo Kontaktgleis testen
#     elif not state.outer_track and False:
#         return 0  # ToDo
#     else:
#         return 0

# print(exit_unsafe_switches(State(0, True, 0, True)))


def get_last_log_index() -> int or None:
    if not os.path.isdir('logs'):
        return 0
    logs = [f for f in os.listdir('logs') if f.startswith('pos_') and f.endswith('.txt')]
    if not logs:
        return 0
    i = [int(f[4:f.index('.')]) for f in logs]
    last_log_index = max(i)
    return last_log_index


def read_last_positions() -> List[State or None]:
    last_log_index = get_last_log_index()
    if not last_log_index:
        return [None, None]
    with open(f'logs/pos_{last_log_index}.txt', 'r') as f:
        lines = f.readlines()
    if not lines:
        return [None, None]
    return [State.from_line(s) for s in lines[-1].split(',')]


def create_log_file():
    os.path.isdir('logs') or os.makedirs('logs')
    return open(f'logs/pos_{get_last_log_index() + 1}.txt', 'w')
