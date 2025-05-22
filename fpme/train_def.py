import os
from functools import cached_property
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


@dataclass(frozen=True)
class TrainInfo:
    name: Optional[str]
    icon: str
    regional_prob: float = .5
    max_delay: int = 60
    delay_rate: float = .2
    can_reverse: bool = True


@dataclass(frozen=True)
class Train:
    info: TrainInfo
    locomotive: str
    product_number: str
    address: int
    masked_speeds: Sequence[Optional[float]]
    acceleration: float
    custom_deceleration: Optional[float] = None
    has_built_in_acceleration: bool = True
    supports_mm2: bool = True
    stop_by_mm1_reverse: bool = True
    functions: Tuple[TrainFunction, ...] = (LIGHT,)
    img_path: str = None

    def __post_init__(self):
        assert len(self.masked_speeds) == 15, len(self.masked_speeds)

    @property
    def name(self):
        return self.info.name or ""

    def __repr__(self):
        return self.name

    @cached_property
    def speeds(self) -> Tuple[float, ...]:
        return tuple(s for s in self.masked_speeds if s is not None)

    @cached_property
    def speed_codes(self) -> Tuple[int, ...]:
        return tuple(i for i, s in enumerate(self.masked_speeds) if s is not None)

    @cached_property
    def image(self):
        return Image.open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', self.img_path)) if self.img_path else None

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

    @property
    def deceleration(self):
        return self.custom_deceleration if self.custom_deceleration is not None else 2 * self.acceleration

    @property
    def is_passenger_train(self):
        return self.info is not GUETER


GUETER =            TrainInfo(None, "🚂/🛲", 1, 0, 0, can_reverse=False)
# --- Rail cars ---
ICE_ =              TrainInfo("ICE", "🚅", .33, max_delay=95, delay_rate=.35)
S_ =                TrainInfo("S", "Ⓢ", .75, max_delay=30, delay_rate=.3)
BUS_ =              TrainInfo("Bus", "🚌", .8, max_delay=10, delay_rate=0.1)
# --- Wagons ---
INTERREGIO_BLAU =   TrainInfo("IC", "🚉", .3)
RB_ROT =            TrainInfo("RB", "🚉", .7)
SILBERLING =        TrainInfo("N/E", "🚉", .6)  # Nahverkehrszug / Eilzug
RE_TUERKIS =        TrainInfo("RE", "🚉", .35)


# --- Passenger trains ---
ICE = Train(ICE_, "BR 402 (ICE 2)", "Märklin 29786", 3, (*np.linspace(0, 310, 15),), 25., img_path="ICE.png",
            functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E_BW = Train(INTERREGIO_BLAU, "BR 101", "Märklin 37394", 1, (0, 13, 25, 46, 67, 86, 108, 125, 140, 156, 173, 191, 201, 215, 226), 30., img_path="E-Lok BW.png", stop_by_mm1_reverse=False,
             functions=(LIGHT, TrainFunction("Nebelscheinwerfer", 2, False, (TAG_SPECIAL_LIGHT,)), TrainFunction("Fahrtlicht hinten", 3, False, (TAG_SPECIAL_LIGHT,)), INSTANT_ACCELERATION))
E_RB = Train(RB_ROT, "BR 146.1", "Märklin 29475", 24, (0, 2, 20, 33, 49, 63, 77, 94, 109, 124, 137, 155, 169, 182, 183), 30., supports_mm2=False, stop_by_mm1_reverse=False, img_path="E-Lok DB.png")
S = Train(S_, "BR 648.2 (LINT 41)", "Märklin 37730", 48, (0, 2, 5, 10, 15, 22, 30, 41, 51, 64, 77, 91, 106, 120, 136), 35., img_path="S-Bahn.png",
          functions=(LIGHT, TrainFunction("Innenbeleuchtung", 1, False, (TAG_DEFAULT_LIGHT,)), SOUND, TrainFunction("Horn", 3, False, (TAG_SPECIAL_SOUND,)), INSTANT_ACCELERATION))
BEIGE = Train(SILBERLING, "BR 218", "Märklin 3074", 73, (0, None, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220), 25., img_path="Thumb_BR218_Beige.png",
              functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
ROT = Train(RE_TUERKIS, 'BR 218', "Märklin 3075", 74, (0, 15, 31, 47, 62, 78, 94, 110, 125, 141, 157, 172, 188, 204, 220), 40., img_path="Thumb_BR218_Rot.png",
            functions=(LIGHT, TrainFunction("Motor", 1, False, (TAG_DEFAULT_SOUND,), warmup_time=19.5, reverse_time=4.), TrainFunction("Horn 1", 3, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Horn 2", 2, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Lüfter", 4, False, (TAG_SPECIAL_SOUND,))))
BUS = Train(BUS_, "VT95", "Märklin H0 3016", 62, (0, .1, .2, *np.linspace(0, 190, 12)), 40., img_path="Thumb_Schienenbus.png", stop_by_mm1_reverse=False, functions=())

# --- Freight trains ---
DAMPF = Train(GUETER, "BR 81", "Märklin 29185", 78, (0, 0.1, 0.2, 0.3, 48, 80, 100, 110, 120, 140, 165, 180, 192, 202, 210), 30., img_path="Dampf.png",
              functions=(LIGHT, TrainFunction("Dampfgeräusche", 1, False, (TAG_DEFAULT_SOUND,)), TrainFunction("Glocke", 3, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Horn", 2, False, (TAG_SPECIAL_SOUND,)), TrainFunction("Kohle schaufeln", 4, False, (TAG_SPECIAL_SOUND,))))
DIESEL = Train(GUETER, "V 60 (BR 360)", "Märklin 29155", 72, (*np.linspace(0, 180, 15),), 25., img_path="Diesel.png",
               functions=(LIGHT, SLOW_MODE, INSTANT_ACCELERATION))
E40 = Train(GUETER, "BR E40", "Märklin 39140", 23, (*np.linspace(0, 220, 15),), 30., img_path="Thumb_E40.png", stop_by_mm1_reverse=False,
            functions=(LIGHT, INSTANT_ACCELERATION, TrainFunction('Horn', -1, False, (TAG_SPECIAL_SOUND,))))  # ToDo which ID?


TRAINS = [ICE, S, BUS, E_RB, E_BW, ROT, BEIGE,   E40, DIESEL, DAMPF]

TRAINS_BY_NAME = {train.name: train for train in TRAINS}
