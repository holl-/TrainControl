"""
                   3
D =================================== 3
   \\             //           ######
    \\   2       //            ######
C =================================== 2
       //
B =================================== 1
    // 1                           ##
A //                               ##
"""
import time

LOCK_TIME_SEC = 10.  # switches are locked in position for this long after being operated

ARRIVAL_CONFIGURATIONS = {  # Driving rightwards
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
DEPARTURE_CONFIGURATIONS = {  # Driving leftwards
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

SWITCHES = range(1, 4)
STATES = {switch: None for switch in SWITCHES}  # key = platform number,  False=straight, True=curved, None=unknown
LOCK_RELEASE_TIME = {switch: 0. for switch in SWITCHES}


def _get_target_configuration(arrival: bool, platform: int, track: str):
    if arrival:
        return ARRIVAL_CONFIGURATIONS[track][platform]
    else:
        return DEPARTURE_CONFIGURATIONS[platform][track]


def get_possible_arrival_platforms(from_track: str) -> tuple:
    return tuple(ARRIVAL_CONFIGURATIONS[from_track].keys())


def get_possible_departure_tracks(from_platform: int) -> tuple:
    return tuple(DEPARTURE_CONFIGURATIONS[from_platform].keys())


def check_lock(arrival: bool, platform: int, track: str) -> float:
    target = _get_target_configuration(arrival, platform, track)
    for switch, target_state in target.items():
        if time.time() < LOCK_RELEASE_TIME[switch]:
            return LOCK_RELEASE_TIME[switch] - time.time()
    return 0


def set_switches(arrival: bool, platform: int, track: str):
    target = _get_target_configuration(arrival, platform, track)
    for switch, target_state in target.items():
        LOCK_RELEASE_TIME[switch] = time.time() + LOCK_TIME_SEC
        current_state = STATES[switch]
        if current_state != target_state:
            _operate_switch(switch, target_state)


def _operate_switch(switch: int, curved: bool):
    """ Sends a signal to the specified track switch. """
    print(f"Setting switch {switch} to state curved={curved}")
    from .relay8 import pulse
    if pulse(switch * 2 - 1 + int(curved)):
        STATES[switch] = curved


def are_switches_correct_for(arrival: bool, platform: int, track: str):
    target = _get_target_configuration(arrival, platform, track)
    for switch, target_state in target.items():
        if STATES[switch] != target_state:
            return False
    return True

