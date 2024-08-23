import os
from typing import Tuple, Sequence

import numpy as np
from PIL import Image
from dataclasses import dataclass

TAG_DEFAULT_LIGHT = 'default-light'
TAG_DEFAULT_SOUND = 'default-sound'
TAG_SPECIAL_LIGHT = 'special-light'
TAG_SPECIAL_SOUND = 'special-sound'


@dataclass
class TrainFunction:
    name: str
    id: int
    default_status: bool
    tags: Tuple[str]
    warmup_time: float = 0.  # how long until train can move if this function is on.
    reverse_time: float = 0.  # how long until the train can move backwards if this function is on.

    def __hash__(self):
        return hash(id)

    def __eq__(self, other):
        return isinstance(other, TrainFunction) and self.name == other.name and self.id == other.id


LIGHT = TrainFunction('Licht', 0, False, (TAG_DEFAULT_LIGHT,))
SLOW_MODE = TrainFunction("Langsam-Modus", 3, False, ())
INSTANT_ACCELERATION = TrainFunction("Instantane Beschleunigung", 4, True, ())
SOUND = TrainFunction("Motor", 2, False, (TAG_DEFAULT_SOUND,))


class Train:

    def __init__(self, name: str, icon: str, address: int, speeds: Sequence, acceleration: float, deceleration: float = None, has_built_in_acceleration: bool = True, supports_mm2: bool = True, stop_by_mm1_reverse=True, functions: Tuple[TrainFunction, ...] = (LIGHT,), img_path: str = None):
        assert len(speeds) == 15, len(speeds)
        self.name: str = name
        self.address: int = address
        self.icon = icon
        self.supports_mm2 = supports_mm2
        self.speed_codes = tuple(i for i, s in enumerate(speeds) if s is not None)
        self.speeds: tuple = tuple(s for s in speeds if s is not None)
        self.locomotive_speeds = speeds  # unencumbered by cars
        self.has_built_in_acceleration: bool = has_built_in_acceleration
        self.acceleration: float = acceleration
        self.deceleration: float = deceleration if deceleration else 2 * acceleration
        self.stop_by_mm1_reverse = stop_by_mm1_reverse
        self.img_path = img_path
        self.image = Image.open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', img_path)) if img_path else None
        self.functions = functions

    def __repr__(self):
        return self.name

    @property
    def img_res(self):
        if self.image:
            return self.image.size
        else:
            return -1, -1

    @property
    def max_speed(self):
        return self.speeds[-1]


ICE = Train('ICE', "🚅", 3, acceleration=25., img_path="ICE.png",
            speeds=np.linspace(0, 310, 15),
            functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E_BW_IC = Train('RE', "🚉", 1, acceleration=30., img_path="E-Lok BW.png", stop_by_mm1_reverse=False,
                speeds=(0, 13.4, 24.9, 45.6, 66.5, 86.3, 107.6, 124.5, 139.5, 155.6, 173.2, 190.9, 201.1, 215.2, 226),
                functions=(LIGHT, TrainFunction("Nebelscheinwerfer", 2, False, (TAG_SPECIAL_LIGHT,)), TrainFunction("Fahrtlicht hinten", 3, False, (TAG_SPECIAL_LIGHT,)), INSTANT_ACCELERATION))
E_RB = Train('RB', "🚉", 24, acceleration=30., supports_mm2=False, stop_by_mm1_reverse=False, img_path="E-Lok DB.png",
             speeds=(0, 1.9, 20.2, 33, 49.2, 62.7, 77.1, 93.7, 109, 124.5, 136.9, 154.7, 168.7, 181.6, 183))
S = Train('S', "Ⓢ", 48, acceleration=35., img_path="S-Bahn.png",
          speeds=(0, 1.9, 5.2, 9.6, 14.8, 22, 29.9, 40.7, 51.2, 64.1, 77.1, 90.8, 106.3, 120.2, 136),
          functions=(LIGHT, TrainFunction("Innenbeleuchtung", 1, False, (TAG_DEFAULT_LIGHT,)), SOUND, TrainFunction("Horn", 3, False, (TAG_SPECIAL_SOUND,)), INSTANT_ACCELERATION))
DAMPF = Train('Dampf', "🚂", 78, acceleration=30., img_path="Dampf.png",
              speeds=(0, 0.1, 0.2, 0.3, 48, 80, 100, 110, 120, 140, 165, 180, 192, 202, 210),
              functions=(LIGHT, TrainFunction("Dampfgeräusche", 1, False, (TAG_DEFAULT_SOUND,)),
                         TrainFunction("Hupe", 2, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Glocke", 3, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Kohle schaufeln", 4, False, (TAG_SPECIAL_SOUND,))))
BEIGE_218 = Train('218 B', "🛲", 73, acceleration=25., img_path="Thumb_BR218_Beige.png",
                  speeds=[0, None, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220],
                  functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
ROT_218 = Train('218 R', "🛲", 74, acceleration=25., img_path="Thumb_BR218_Beige.png",
                speeds=[0, 15, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220],
                functions=(LIGHT, TrainFunction("Motor", 1, False, (TAG_DEFAULT_SOUND,), warmup_time=19.5, reverse_time=4.), TrainFunction("Hupe 2", 2, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Hupe 1", 3, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Lüfter", 4, False, (TAG_SPECIAL_SOUND,))))
DIESEL = Train('Diesel', "🛲", 72, acceleration=25., img_path="Diesel.png",
               speeds=np.linspace(0, 217, 15),
               functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E40_RE_BLAU = Train('E40', "🚉", 23, acceleration=30., img_path="Thumb_E40.png", stop_by_mm1_reverse=False,
                    speeds=np.linspace(0, 220, 15),
                    functions=(LIGHT, INSTANT_ACCELERATION, TrainFunction('Hupe', -1, False, (TAG_SPECIAL_SOUND,))))
BUS = Train('Bus', "🚌", 62, acceleration=40., img_path="Thumb_Schienenbus.png", stop_by_mm1_reverse=False,
            speeds=np.linspace(0, 190, 15),
            functions=())

TRAINS = [ICE, E_BW_IC, E_RB, S, BEIGE_218, ROT_218, DIESEL, E40_RE_BLAU, BUS, DAMPF]  # available trains

TRAINS_BY_NAME = {train.name: train for train in TRAINS}

RAILCARS_TRAINS = [ICE, E_RB, S, E40_RE_BLAU, BUS]
LOCOMOTIVE_TRAINS = [DAMPF, BEIGE_218, ROT_218, DIESEL, E_BW_IC]  # IC driven by RE (BW)

CONTROLS = {
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_fdc80171a4bd&Col01#b&2a97252d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': ICE,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_588ea725c7a3&Col01#b&13df0efa&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': DAMPF,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_45ee447eb09a&Col01#b&20a8da1a&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': DIESEL,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_e0eebb488ace&Col01#b&316fd37&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': ROT_218,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_1e89fff2c7db&Col01#b&20fc5261&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': BUS,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_3675eb0ae2f9&Col01#b&29342c48&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': S,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_8fd1f0ddfca6&Col01#b&2671a960&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': E_RB,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_61f5dd3d7341&Col01#b&2c7afc78&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': E40_RE_BLAU,
    '\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_9b64950eee81&Col01#b&1cbc610d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': E_BW_IC,
    # Mice
    '\\\\?\\HID#VID_1EA7&PID_0002&MI_01&Col02#9&2025eeb3&0&0001#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': BEIGE_218,
    '\\\\?\\HID#VID_093A&PID_2510#7&414c0de&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}': ICE,  # USB
    # Keyboard
    '\\\\?\\ACPI#HPQ8001#4&2abdae0d&0#{884b96c3-56ef-11d1-bc8c-00a0c91405dd}': ICE,  # Laptop
}

""" VR Park Controllers:
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_588ea725c7a3&Col01#b&13df0efa&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_9b64950eee81&Col01#b&1cbc610d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_e0eebb488ace&Col01#b&316fd37&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_1e89fff2c7db&Col01#b&20fc5261&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_45ee447eb09a&Col01#b&20a8da1a&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_61f5dd3d7341&Col01#b&2c7afc78&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_8fd1f0ddfca6&Col01#b&2671a960&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_3675eb0ae2f9&Col01#b&29342c48&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
\\\\?\\HID#{00001812-0000-1000-8000-00805f9b34fb}_Dev_VID&0205ac_PID&022c_REV&011b_fdc80171a4bd&Col01#b&2a97252d&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
"""
""" Others
Mouse: \\\\?\\HID#VID_093A&PID_2510#7&414c0de&0&0000#{378de44c-56ef-11d1-bc8c-00a0c91405dd}
Keyboard \\\\?\\ACPI#HPQ8001#4&2abdae0d&0#{884b96c3-56ef-11d1-bc8c-00a0c91405dd}
"""
