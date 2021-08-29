from typing import Dict

STATE = {i: None for i in range(1, 4)}  # key = platform number,  False=straight, True=curved

ARRIVAL_CONFIGURATIONS = {
    'A': {
        1: {1: True},
        2: {1: False}
    },
    'B': {
        1: {1: False},
        2: {1: True}
    },
    'C': {
        2: {}
    },
    'D': {
        2: {}
    },
}
DEPARTURE_CONFIGURATIONS = {
    1: {
        'A': {1: True},
        'B': {1: False},
    },
    2: {
        'A': {2: True, 1: False},
        'B': {2: True, 1: True},
        'C': {2: False},
    },
    3: {
        'A': {3: True, 2: True, 1: False},
        'B': {3: True, 2: True, 1: True},
        'C': {3: True, 2: False},
        'D': {3: False},
    }
}


def _get_target_configuration(arrival: bool, platform: int, track: str):
    if arrival:
        return ARRIVAL_CONFIGURATIONS[track][platform]
    else:
        return DEPARTURE_CONFIGURATIONS[platform][track]


def get_possible_arrival_platforms(from_track: str) -> tuple:
    return tuple(ARRIVAL_CONFIGURATIONS[from_track].keys())


def get_possible_departure_tracks(from_platform: int) -> tuple:
    return tuple(DEPARTURE_CONFIGURATIONS[from_platform].keys())


def set_switches(arrival: bool, platform: int, track: str):
    target = _get_target_configuration(arrival, platform, track)
    for switch, target_state in target.items():
        current_state = STATE[switch]
        if current_state != target_state:
            _set_switch(switch, target_state)


def _set_switch(switch: int, curved: bool):
    """ Sends a signal to the specified track switch. """
    print(f"Setting switch {switch} to state curved={curved}")
    STATE[switch] = curved


def are_switches_correct_for(arrival: bool, platform: int, track: str):
    target = _get_target_configuration(arrival, platform, track)
    for switch, target_state in target.items():
        if STATE[switch] != target_state:
            return False
    return True

