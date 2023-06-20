import datetime
from enum import Enum

from typing import NamedTuple, List, Optional

DOMAIN = "prana"

class Speed(Enum):
    OFF = 0
    LOW = 1
    HIGH = 10
    SPEED_2 = 2
    SPEED_3 = 3
    SPEED_4 = 4
    SPEED_5 = 5
    SPEED_6 = 6
    SPEED_7 = 7
    SPEED_8 = 8
    SPEED_9 = 9

    @classmethod
    def all_options(cls) -> List[str]:
        return ["low", "l", "high", "h", "off", "stop", "2", "3", "4", "5", "6", "7", "8", "9"]

    @classmethod
    def from_str(cls, speed: str) -> "Speed":
        speed = str(speed).lower().strip()
        if speed in ["low", "l"]:
            return cls.LOW
        if speed in ["high", "h"]:
            return cls.HIGH
        if speed in ["off", "stop"]:
            return cls.OFF
        try:
            speed_int = int(speed)
            if 0 <= speed_int <= 10:
                return cls(speed_int)
        except ValueError:
            pass
        raise ValueError("String {} is not valid speed identifier".format(speed))

    def to_int(self) -> int:
        return int(self.value)

class Mode(Enum):
    NORMAL = "normal"
    NIGHT = "night"
    HIGH = "high"


class PranaSensorsState(object):
    def __init__(self) -> None:
        self.temperature_in: Optional[float] = None
        self.temperature_out: Optional[float] = None
        self.humidity: Optional[int] = None
        self.pressure: Optional[int] = None
        self.voc: Optional[int] = None
        self.co2: Optional[int] = None

    def __repr__(self):
        return (
            "Temperature: (in: {}, out: {}), Humidity: {}, Pressure: {}".format(
                self.temperature_in, self.temperature_out, self.humidity, self.pressure
            )
            + ", VOC: {}, CO2: {}".format(self.voc, self.co2)
            if self.co2 is not None or self.voc is not None
            else ""
        )

    def to_dict(self) -> dict:
        return dict(
            temperature_in=self.temperature_in,
            temperature_out=self.temperature_out,
            humidity=self.humidity,
            pressure=self.pressure,
            voc=self.voc,
            co2=self.co2,
        )


class PranaState(object):
    def __init__(self) -> None:
        self.speed_locked: Optional[int] = None
        self.speed_in: Optional[int] = None
        self.speed_out: Optional[int] = None
        self.night_mode: Optional[bool] = None
        self.auto_mode: Optional[bool] = None
        self.flows_locked: Optional[bool] = None
        self.is_on: Optional[bool] = None
        self.mini_heating_enabled: Optional[bool] = None
        self.winter_mode_enabled: Optional[bool] = None
        self.is_input_fan_on: Optional[bool] = None
        self.is_output_fan_on: Optional[bool] = None
        self.brightness: Optional[int] = None
        self.sensors: Optional[PranaSensorsState] = None
        self.timestamp: Optional[datetime.datetime] = None

    @property
    def speed(self):
        if not self.is_on:
            return 0
        return self.speed_locked if self.flows_locked else int((self.speed_in + self.speed_out) / 2)

    def __repr__(self):
        res = "Prana state: {}, Speed: {}, Winter Mode: {}, Heating: {}, Flows locked: {}, Brightness: {}".format(
            "RUNNING" if self.is_on else "IDLE",
            self.speed,
            self.winter_mode_enabled,
            self.mini_heating_enabled,
            self.flows_locked,
            self.brightness,
        )
        if self.sensors is not None:
            res += " Sensors: {" + repr(self.sensors) + "}"
        return res

    def to_dict(self) -> dict:
        return dict(
            speed_locked=self.speed_locked,
            speed_in=self.speed_in,
            speed_out=self.speed_out,
            night_mode=self.night_mode,
            auto_mode=self.auto_mode,
            flows_locked=self.flows_locked,
            is_on=self.is_on,
            mini_heating_enabled=self.mini_heating_enabled,
            winter_mode_enabled=self.winter_mode_enabled,
            is_input_fan_on=self.is_input_fan_on,
            is_output_fan_on=self.is_output_fan_on,
            timestamp=self.timestamp if self.timestamp is not None else None,
            speed=self.speed,
            brightness=self.brightness,
            sensors=self.sensors.to_dict() if self.sensors is not None else None,
        )

class EFFECTS (Enum):
    jump_red_green_blue = 0x87
    jump_red_green_blue_yellow_cyan_magenta_white = 0x88
    crossfade_red = 0x8b
    crossfade_green = 0x8c
    crossfade_blue = 0x8d
    crossfade_yellow = 0x8e
    crossfade_cyan = 0x8f
    crossfade_magenta = 0x90
    crossfade_white = 0x91
    crossfade_red_green = 0x92
    crossfade_red_blue = 0x93
    crossfade_green_blue = 0x94
    crossfade_red_green_blue = 0x89
    crossfade_red_green_blue_yellow_cyan_magenta_white = 0x8a
    blink_red = 0x96
    blink_green = 0x97
    blink_blue = 0x98
    blink_yellow = 0x99
    blink_cyan = 0x9a
    blink_magenta = 0x9b
    blink_white = 0x9c
    blink_red_green_blue_yellow_cyan_magenta_white = 0x95

EFFECTS_list = ['jump_red_green_blue',
    'jump_red_green_blue_yellow_cyan_magenta_white',
    'crossfade_red',
    'crossfade_green',
    'crossfade_blue',
    'crossfade_yellow',
    'crossfade_cyan',
    'crossfade_magenta',
    'crossfade_white',
    'crossfade_red_green',
    'crossfade_red_blue',
    'crossfade_green_blue',
    'crossfade_red_green_blue',
    'crossfade_red_green_blue_yellow_cyan_magenta_white',
    'blink_red',
    'blink_green',
    'blink_blue',
    'blink_yellow',
    'blink_cyan',
    'blink_magenta',
    'blink_white',
    'blink_red_green_blue_yellow_cyan_magenta_white'
    ]

class WEEK_DAYS (Enum):
    monday = 0x01
    tuesday = 0x02
    wednesday = 0x04
    thursday = 0x08
    friday = 0x10
    saturday = 0x20
    sunday = 0x40
    all = (0x01 + 0x02 + 0x04 + 0x08 + 0x10 + 0x20 + 0x40)
    week_days = (0x01 + 0x02 + 0x04 + 0x08 + 0x10)
    weekend_days = (0x20 + 0x40)
    none = 0x00




#print(EFFECTS.blink_red.value)
