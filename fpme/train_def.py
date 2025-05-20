import os
from typing import Tuple, Sequence, Optional

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

    def __repr__(self):
        return self.name + ":" + str(self.id)

    @property
    def cooldown(self):
        return 60 if TAG_SPECIAL_SOUND in self.tags else 1


LIGHT = TrainFunction('Licht', 0, False, (TAG_DEFAULT_LIGHT,))
SLOW_MODE = TrainFunction("Langsam-Modus", 3, False, ())
INSTANT_ACCELERATION = TrainFunction("Instantane Beschleunigung", 4, True, ())
SOUND = TrainFunction("Motor", 2, False, (TAG_DEFAULT_SOUND,))


class Train:

    def __init__(self, name: str, icon: str, address: int, speeds: Sequence, acceleration: float, deceleration: float = None, has_built_in_acceleration: bool = True, supports_mm2: bool = True, stop_by_mm1_reverse=True, functions: Tuple[TrainFunction, ...] = (LIGHT,), img_path: str = None, regional_fac: float = .5, max_delay=60, delay_rate=.3):
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
        self.regional_prob = regional_fac
        self.functions = functions
        self.max_delay = max_delay
        self.delay_rate = delay_rate

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

    @property
    def primary_ability(self) -> Optional[TrainFunction]:
        for tag in [TAG_SPECIAL_SOUND, TAG_SPECIAL_LIGHT, TAG_DEFAULT_LIGHT]:
            for f in self.functions:
                if tag in f.tags:
                    return f
        return None


ICE = Train('ICE', "🚅", 3, acceleration=25., img_path="ICE.png", regional_fac=.25,
            speeds=np.linspace(0, 310, 15),
            functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E_BW_IC = Train('IC', "🚉", 1, acceleration=30., img_path="E-Lok BW.png", stop_by_mm1_reverse=False, regional_fac=.33,
                speeds=(0, 13.4, 24.9, 45.6, 66.5, 86.3, 107.6, 124.5, 139.5, 155.6, 173.2, 190.9, 201.1, 215.2, 226),
                functions=(LIGHT, TrainFunction("Nebelscheinwerfer", 2, False, (TAG_SPECIAL_LIGHT,)), TrainFunction("Fahrtlicht hinten", 3, False, (TAG_SPECIAL_LIGHT,)), INSTANT_ACCELERATION))
E_RB = Train('RB', "🚉", 24, acceleration=30., supports_mm2=False, stop_by_mm1_reverse=False, img_path="E-Lok DB.png", regional_fac=.7,
             speeds=(0, 1.9, 20.2, 33, 49.2, 62.7, 77.1, 93.7, 109, 124.5, 136.9, 154.7, 168.7, 181.6, 183))
S = Train('S', "Ⓢ", 48, acceleration=35., img_path="S-Bahn.png", regional_fac=.75,
          speeds=(0, 1.9, 5.2, 9.6, 14.8, 22, 29.9, 40.7, 51.2, 64.1, 77.1, 90.8, 106.3, 120.2, 136),
          functions=(LIGHT, TrainFunction("Innenbeleuchtung", 1, False, (TAG_DEFAULT_LIGHT,)), SOUND, TrainFunction("Horn", 3, False, (TAG_SPECIAL_SOUND,)), INSTANT_ACCELERATION),
          max_delay=35, delay_rate=.5)
DAMPF = Train('Dampf', "🚂", 78, acceleration=30., img_path="Dampf.png", regional_fac=.5,
              speeds=(0, 0.1, 0.2, 0.3, 48, 80, 100, 110, 120, 140, 165, 180, 192, 202, 210),
              functions=(LIGHT, TrainFunction("Dampfgeräusche", 1, False, (TAG_DEFAULT_SOUND,)),
                         TrainFunction("Glocke", 3, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Horn", 2, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Kohle schaufeln", 4, False, (TAG_SPECIAL_SOUND,))))
BEIGE_218 = Train('218 B', "🛲", 73, acceleration=25., img_path="Thumb_BR218_Beige.png", regional_fac=.5,
                  speeds=[0, None, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220],
                  functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
ROT_218 = Train('218 R', "🛲", 74, acceleration=40., img_path="Thumb_BR218_Rot.png", regional_fac=.5,
                speeds=[0, 15, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220],
                functions=(LIGHT, TrainFunction("Motor", 1, False, (TAG_DEFAULT_SOUND,), warmup_time=19.5, reverse_time=4.), TrainFunction("Horn 1", 3, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Horn 2", 2, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Lüfter", 4, False, (TAG_SPECIAL_SOUND,))))
DIESEL = Train('Diesel', "🛲", 72, acceleration=25., img_path="Diesel.png", regional_fac=.5,
               speeds=np.linspace(0, 180, 15),
               functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E40_RE_BLAU = Train('RE', "🚉", 23, acceleration=30., img_path="Thumb_E40.png", stop_by_mm1_reverse=False, regional_fac=.6,
                    speeds=np.linspace(0, 220, 15),
                    functions=(LIGHT, INSTANT_ACCELERATION, TrainFunction('Horn', -1, False, (TAG_SPECIAL_SOUND,))))  # ToDo which ID?
BUS = Train('Bus', "🚌", 62, acceleration=40., img_path="Thumb_Schienenbus.png", stop_by_mm1_reverse=False, regional_fac=.8,
            speeds=[0, 0.1, 0.2, *np.linspace(0, 190, 12)],
            functions=(), max_delay=10, delay_rate=0.1)

TRAINS = [ICE, E_BW_IC, E_RB, S, BEIGE_218, ROT_218, DIESEL, E40_RE_BLAU, BUS, DAMPF]  # available trains

TRAINS_BY_NAME = {train.name: train for train in TRAINS}

for train in TRAINS:
    print(train.name, train.primary_ability)
