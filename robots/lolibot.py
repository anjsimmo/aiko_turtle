# The LoliBot (openhardwareconf.org/wiki/LoliBot, LCA2018): a two-wheel
# ESP32 robot running MicroPython and the aiko_engine_mp "Aiko engine".
# The 2018 firmware took bare words on its "in" topic: forward, reverse,
# left, right, stop (continuous, until the next word).  lolibot_mp/ in
# this repo is an updated firmware that keeps those words, adds an
# optional duration and an LED colour, registers with the Registrar, and
# echoes what it does on "out".  This module is that interface, and the
# virtual LoliBot that speaks it in the sandbox.

from abc import abstractmethod

import aiko_services as aiko

from robots import base

NAME = "lolibot"
LABEL = "LoliBot (MicroPython firmware in lolibot_mp/)"
DESCRIPTION = ("the OHC two-wheel ESP32 robot: forward | reverse | left | "
               "right [SECONDS] (no seconds: until stop), stop, led R G B, "
               "speed PERCENT. The 2018 bare words still work")
STATUS = base.STATUS_PROPOSED      # firmware written, not yet flashed to a bot
PROTOCOL = "org.geekscape.protocol.lolibot:1"
UNITS = "seconds of motion at a nominal 20 cm/s and 90 deg/s (scaled by speed %)"
SOURCE = "lolibot_mp/lolibot.py (updated from ../od_micro_py_files and aiko_engine_mp/lib/lolibot.py)"
MATCH = {"protocol": PROTOCOL}
KINDS = {"lolibot": {"label": "LoliBot / BeetleBot", "axes": 1,
                     "description": "the OHC two-wheel ESP32 robot (openhardwareconf.org/wiki/LoliBot) and Jon Oxer's BeetleBot"}}

LINEAR = 20.0           # units/s at speed 100
ANGULAR = 90.0          # degrees/s at speed 100
WORDS = ("forward", "reverse", "left", "right", "stop")


class LoliBot(aiko.Interface):
    @abstractmethod
    def forward(self, seconds="0"):
        """both wheels forward, for seconds (0 = until stop)"""

    @abstractmethod
    def reverse(self, seconds="0"):
        """both wheels backwards, for seconds (0 = until stop)"""

    @abstractmethod
    def left(self, seconds="0"):
        """spin left, for seconds (0 = until stop)"""

    @abstractmethod
    def right(self, seconds="0"):
        """spin right, for seconds (0 = until stop)"""

    @abstractmethod
    def stop(self):
        """both motors off"""

    @abstractmethod
    def led(self, red, green, blue):
        """the three NeoPixels, 0-255 each"""

    @abstractmethod
    def speed(self, percent):
        """motor duty, 20..100 percent"""


base.default_implementation(LoliBot)
Interface = LoliBot

COMMANDS = [
    ("forward 1", "forward for one second"),
    ("reverse 0.5", "back for half a second"),
    ("left 1", "spin left for a second (90 deg/s)"),
    ("right 1", "spin right for a second"),
    ("forward", "forward until stop (the 2018 word)"),
    ("stop", "motors off"),
    ("led 0 0 255", "LEDs blue"),
    ("speed 60", "slower"),
]


def parse_command(text):
    parts = (text or "").split()
    match parts:
        case [word] if word in WORDS:
            return word, []
        case [word, seconds] if word in WORDS[:-1]:
            return word, [seconds]
        case ["led", red, green, blue]:
            return "led", [red, green, blue]
        case ["speed", percent]:
            return "speed", [percent]
        case _:
            return None, f'unknown command "{text}": a LoliBot takes {", ".join(WORDS)} [SECONDS], led R G B, speed PERCENT'


def _ops(word, seconds, scale=1.0):
    duration = base.number(seconds, "seconds", 0.0)
    linear, angular = {"forward": (LINEAR, 0.0), "reverse": (-LINEAR, 0.0),
                       "left": (0.0, ANGULAR), "right": (0.0, -ANGULAR)}[word]
    return [("drive", linear * scale, angular * scale, duration)]


class Simulated:
    percent = 100.0
    colour = "0 0 0"

    def _go(self, word, seconds):
        try:
            return self.apply_op(_ops(word, seconds, self.percent / 100.0)[0])
        except ValueError as error:
            return str(error)

    def forward(self, seconds="0"):
        return self._go("forward", seconds)

    def reverse(self, seconds="0"):
        return self._go("reverse", seconds)

    def left(self, seconds="0"):
        return self._go("left", seconds)

    def right(self, seconds="0"):
        return self._go("right", seconds)

    def stop(self):
        return self.body.stop()

    def led(self, red, green, blue):
        self.colour = f"{red} {green} {blue}"
        return f"leds {self.colour} (virtual: nothing to see)"

    def speed(self, percent):
        self.percent = min(100.0, max(20.0, base.number(percent, "percent")))
        return f"speed {self.percent:g}%"


def observe(direction, command, args, state):
    """Dead reckon from the words sent to the real bot (it has no odometry)"""
    if direction != "in":
        return []
    if command == "speed" and args:
        state["scale"] = min(100.0, max(20.0, base.number(args[0]))) / 100.0
        return []
    if command == "stop":
        return [("stop",)]
    if command in WORDS:
        return _ops(command, args[0] if args else "0", state.get("scale", 1.0))
    return []
