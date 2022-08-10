"""
                   3
A ============================= Blue
   \\             //
    \\   2       //
     ========================== Yellow
       //
B ==================|
    // 1
C //
"""
import time

LOCK_TIME_SEC = 10.  # switches are locked in position for this long after being operated


CONFIGURATIONS = {  # Driving leftwards
    'Yellow': {
        'A': {2: False},
        'B': {2: True, 1: True},
        'C': {2: True, 1: False},
    },
    'Blue': {
        'A': {3: False},
        'B': {3: True, 2: True, 1: True},
        'C': {3: True, 2: True, 1: False},
    },
    'Any': {
        'A': {3: False, 2: False},
        'B': {3: True, 2: True, 1: True},
        'C': {3: True, 2: True, 1: False},
    }
}

SWITCHES = range(1, 4)
STATES = {switch: None for switch in SWITCHES}  # key = platform number,  False=straight, True=curved, None=unknown
LOCK_RELEASE_TIME = {switch: 0. for switch in SWITCHES}
ALL_LOCKED = False


RELAY_CHANNEL_BY_SWITCH_STATE = {
    1: {False: 1, True: 2},
    2: {False: 3, True: 4},
    3: {False: 8, True: 7},
}


def check_lock(incoming: str, track: str) -> float:
    if ALL_LOCKED:
        return float('inf')
    config = CONFIGURATIONS[incoming][track]
    for switch, target_state in config.items():
        if time.time() < LOCK_RELEASE_TIME[switch]:
            return LOCK_RELEASE_TIME[switch] - time.time()
    return 0


def set_switches(incoming: str, track: str):
    config = CONFIGURATIONS[incoming][track]
    for switch, target_state in config.items():
        LOCK_RELEASE_TIME[switch] = time.time() + LOCK_TIME_SEC
        current_state = STATES[switch]
        if current_state != target_state:
            _operate_switch(switch, target_state)


def set_all_locked(locked: bool):
    global ALL_LOCKED
    ALL_LOCKED = locked
    if locked:
        target = {1: True, 2: False, 3: False}
        for switch, target_state in target.items():
            current_state = STATES[switch]
            if current_state != target_state:
                _operate_switch(switch, target_state)


def _operate_switch(switch: int, curved: bool):
    """ Sends a signal to the specified track switch. """
    print(f"Setting switch {switch} to state curved={curved}")
    from .relay8 import pulse
    channel = RELAY_CHANNEL_BY_SWITCH_STATE[switch][curved]
    if pulse(channel):
        STATES[switch] = curved


def are_switches_correct_for(incoming: str, track: str):
    config = CONFIGURATIONS[incoming][track]
    return all(STATES[switch] == target_state for switch, target_state in config.items())
