from typing import Tuple, Sequence

import numpy as np
from PIL import Image
from dataclasses import dataclass


@dataclass
class TrainFunction:
    name: str
    id: int
    default_status: bool
    switch_on_at_night: bool


LIGHT = TrainFunction('Licht', 0, False, True)
SLOW_MODE = TrainFunction("Langsam-Modus", 3, False, False)
INSTANT_ACCELERATION = TrainFunction("Instantane Beschleunigung", 4, True, False)


class Train:

    def __init__(self, name: str, icon: str, address: int, speeds: Sequence, acceleration: float, has_built_in_acceleration: bool = True, supports_mm2: bool = True, stop_by_mm1_reverse=True, functions: Tuple[TrainFunction, ...] = (LIGHT,), img_path: str = None):
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
        self.stop_by_mm1_reverse = stop_by_mm1_reverse
        self.img_path = img_path
        self.image = Image.open(img_path) if img_path else None
        self.functions = functions

    def __repr__(self):
        return self.name

    @property
    def img_res(self):
        if self.image:
            return self.image.size
        else:
            return -1, -1


ICE = Train('ICE', "🚅", 3, acceleration=25., img_path="ICE.png",
            speeds=np.linspace(0, 310, 15),
            functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
RE = Train('RE', "🚉", 1, acceleration=30., img_path="E-Lok BW.png", stop_by_mm1_reverse=False,
           speeds=(0, 13.4, 24.9, 45.6, 66.5, 86.3, 107.6, 124.5, 139.5, 155.6, 173.2, 190.9, 201.1, 215.2, 226),
           functions=(LIGHT, TrainFunction("Nebelscheinwerfer", 2, False, False), TrainFunction("Fahrtlicht hinten", 3, False, False), INSTANT_ACCELERATION))
RB = Train('RB', "🚉", 24, acceleration=30., supports_mm2=False, stop_by_mm1_reverse=False, img_path="E-Lok DB.png",
           speeds=(0, 1.9, 20.2, 33, 49.2, 62.7, 77.1, 93.7, 109, 124.5, 136.9, 154.7, 168.7, 181.6, 183))
S = Train('S', "Ⓢ", 48, acceleration=35., img_path="S-Bahn.png",
          speeds=(0, 1.9, 5.2, 9.6, 14.8, 22, 29.9, 40.7, 51.2, 64.1, 77.1, 90.8, 106.3, 120.2, 136),
          functions=(LIGHT, TrainFunction("Innenbeleuchtung", 1, False, True), TrainFunction("Motor", 2, False, False), TrainFunction("Horn", 3, False, False), INSTANT_ACCELERATION))
DAMPF = Train('Dampf', "🚂", 78, acceleration=30., img_path="Dampf.png",
              speeds=(0, 0.1, 0.2, 0.3, 48, 80, 100, 110, 120, 140, 165, 180, 192, 202, 210))
DIESEL_218 = Train('218', "🛲", 73, acceleration=25., img_path="Thumb_BR218_Beige.png",
                   speeds=[0, None, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220],
                   functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
DIESEL = Train('Diesel', "🛲", 72, acceleration=25., img_path="Diesel.png",
               speeds=np.linspace(0, 217, 15),
               functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E40 = Train('E40', "🚉", 23, acceleration=30., img_path="Thumb_E40.png", stop_by_mm1_reverse=False,
            speeds=np.linspace(0, 220, 15),
            functions=(LIGHT, INSTANT_ACCELERATION, TrainFunction('Hupe', -1, False, False)))
BUS = Train('Bus', "🚌", 62, acceleration=40., img_path="Thumb_Schienenbus.png", stop_by_mm1_reverse=False,
            speeds=np.linspace(0, 190, 15),
            functions=())

TRAINS = [ICE, RE, RB, S, DAMPF, DIESEL_218, DIESEL, E40, BUS]  # available trains

TRAINS_BY_NAME = {train.name: train for train in TRAINS}

CONTROLS = {
    'device_name': ICE
}
