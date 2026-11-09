# The iRobot Create 3 on Zebra2: a Create 3 vacuum base (suction removed,
# a Raspberry Pi on top) run by the "aiko_irobot" Actor, which registers
# under the name "robot".  Described exactly as that Actor accepts it
# today, taken from ../zebra-robot/robot_client.py (the Actor itself is
# aiko_irobot/robot.py on the Pi and not in this repo): metres, degrees
# (+ = left), fire-and-forget commands, and four queries that reply to a
# topic.  The real Actor echoes commands and publishes (pose x y heading)
# and (hazard ...) on its "out" topic, which is what the replica listens to.

import time
from abc import abstractmethod

import aiko_services as aiko

from robots import base

NAME = "irobot"
LABEL = "iRobot Create 3 (aiko_irobot on Zebra2)"
DESCRIPTION = ("the Create 3 base with a Pi on top, as its aiko_irobot Actor "
               "accepts commands today: move in metres, turn in degrees (+ = "
               "left), drive, arc, goto, dock, leds, beeps; queries battery, "
               "pose, dock_status, sensors")
STATUS = base.STATUS_REAL
PROTOCOL = ""           # not recorded in the client code; found by its name
UNITS = "metres and degrees (+ = left); drive is m/s and degrees/s"
SOURCE = "../zebra-robot/robot_client.py (Actor: aiko_irobot/robot.py on Zebra2, registered as \"robot\")"
MATCH = {"name": "robot"}
KINDS = {"irobot": {"label": "iRobot Create 3", "axes": 1,
                    "description": "the Create 3 vacuum base with a Raspberry Pi where the suction was: drives in metres (Zebra2)"}}

SPEED = 0.15 * base.UNITS_PER_METRE      # m/s the Actor drives at, in units/s
POSE_FRESH = 10.0                         # s: a pose stream this recent beats dead reckoning
QUERIES = ("battery", "pose", "dock_status", "sensors")
POWER = ("power_off", "terminate")       # never simulated or forwarded


class IRobot(aiko.Interface):
    @abstractmethod
    def move(self, distance):
        """metres forward (negative = backwards)"""

    @abstractmethod
    def turn(self, angle):
        """degrees, + = left"""

    @abstractmethod
    def stop(self):
        """stop moving"""

    @abstractmethod
    def walk(self, time_budget):
        """wander for this many seconds"""

    @abstractmethod
    def drive(self, linear, angular, seconds):
        """m/s, degrees/s, for seconds"""

    @abstractmethod
    def arc(self, angle, radius):
        """degrees along an arc of radius metres"""

    @abstractmethod
    def goto(self, x, y, heading, achieve_heading):
        """to x y (metres, odometry frame) heading; achieve_heading 0|1"""

    @abstractmethod
    def goto_odom(self, x, y, tolerance):
        """to x y (metres) within tolerance metres"""

    @abstractmethod
    def dock(self):
        """drive onto the dock"""

    @abstractmethod
    def undock(self):
        """back off the dock"""

    @abstractmethod
    def wall_follow(self, side, seconds):
        """left | right, for seconds"""

    @abstractmethod
    def telemetry(self, period):
        """publish (pose x y heading) on out every period seconds; 0 stops"""

    @abstractmethod
    def led(self, red, green, blue):
        """light ring colour 0-255"""

    @abstractmethod
    def led_off(self):
        """light ring off"""

    @abstractmethod
    def led_animation(self, spin, red, green, blue, seconds):
        """blink | spin, colour, for seconds"""

    @abstractmethod
    def beep(self, frequency, duration_ms):
        """hertz, milliseconds"""

    @abstractmethod
    def song(self, name):
        """chirp | alert | done"""

    @abstractmethod
    def e_stop(self, enable):
        """1 cuts the motors, 0 re-arms them"""

    @abstractmethod
    def reset_pose(self):
        """odometry back to 0 0 0"""

    @abstractmethod
    def power_off(self):
        """power the robot off (never sent from the sandbox)"""

    @abstractmethod
    def terminate(self):
        """stop the Actor (never sent from the sandbox)"""

    @abstractmethod
    def battery(self, topic_path_response):
        """query: (response battery percent=87 volts=14.6)"""

    @abstractmethod
    def pose(self, topic_path_response):
        """query: (response pose x y heading) in metres and degrees"""

    @abstractmethod
    def dock_status(self, topic_path_response):
        """query: docked or not"""

    @abstractmethod
    def sensors(self, topic_path_response):
        """query: bumpers, cliffs, ir"""


base.default_implementation(IRobot)
Interface = IRobot
METHODS = [spec["name"] for spec in base.method_specs(IRobot)]

COMMANDS = [
    ("move 0.2", "0.2 metres forward"),
    ("turn 90", "90 degrees left"),
    ("stop", "stop"),
    ("drive 0.1 30 2", "0.1 m/s while turning 30 deg/s, for 2 s"),
    ("arc 90 0.3", "a quarter circle of radius 0.3 m"),
    ("walk 3", "wander for 3 s"),
    ("undock", "back off the dock (and dock to return)"),
    ("beep 880 200", "880 Hz for 200 ms"),
    ("led 0 255 0", "light ring green (led_off to clear)"),
    ("song chirp", "chirp | alert | done"),
    ("reset_pose", "odometry back to the origin"),
    ("battery", "query the battery"),
    ("pose", "query the odometry pose"),
    ("e_stop 1", "cut the motors (e_stop 0 re-arms)"),
]


def parse_command(text):
    parts = (text or "").split()
    if not parts:
        return None, "empty command"
    method, args = parts[0], parts[1:]
    if method not in METHODS:
        return None, f'unknown command "{text}": the iRobot accepts {", ".join(METHODS)}'
    if method in POWER:
        return None, f"{method} is never sent from the sandbox: it would switch the real robot off"
    if method in QUERIES and args:
        return None, f"{method} is a query: no arguments"
    return method, args


def _metres(value, what="distance"):
    return base.number(value, what) * base.UNITS_PER_METRE


class Simulated:
    """A Create 3 in the world: distances in metres become world units"""

    led_colour = "off"
    docked = True
    estopped = False
    telemetry_period = 0.0

    def _moving(self):
        if self.estopped:
            return "e_stop is on: send e_stop 0 first"
        return None

    def move(self, distance):
        return self._moving() or self.body.move(_metres(distance))

    def turn(self, angle):
        return self._moving() or self.body.turn(base.number(angle, "angle"))

    def stop(self):
        return self.body.stop()

    def walk(self, time_budget):
        return self._moving() or self.body.drive(
            SPEED, 0.0, base.number(time_budget, "seconds"))

    def drive(self, linear, angular, seconds):
        return self._moving() or self.body.drive(
            _metres(linear, "linear"), base.number(angular, "angular"),
            base.number(seconds, "seconds"))

    def arc(self, angle, radius):
        import math
        degrees, r = base.number(angle, "angle"), _metres(radius, "radius")
        chord = 2 * r * math.sin(math.radians(abs(degrees)) / 2)
        half = math.radians(degrees / 2)
        self.body.move(chord * math.cos(half), chord * math.sin(half))
        return self.body.turn(degrees)

    def goto(self, x, y, heading, achieve_heading="1"):
        return self._moving() or self.body.place(
            _metres(x, "x"), _metres(y, "y"), base.number(heading, "heading"))

    def goto_odom(self, x, y, tolerance="0.05"):
        pose = self.body.last_pose or {}
        return self._moving() or self.body.place(
            _metres(x, "x"), _metres(y, "y"), pose.get("heading", 0.0))

    def dock(self):
        self.docked = True
        return "docked (virtual)"

    def undock(self):
        self.docked = False
        self.body.move(-0.5 * base.UNITS_PER_METRE)
        return self.body.turn(180)

    def wall_follow(self, side, seconds):
        return self._moving() or self.body.drive(
            SPEED, 0.0, base.number(seconds, "seconds"))

    def telemetry(self, period):
        self.telemetry_period = base.number(period, "period")
        self.set_telemetry_period(self.telemetry_period)
        return f"pose telemetry every {self.telemetry_period:g} s" if  \
            self.telemetry_period else "pose telemetry off"

    def led(self, red, green, blue):
        self.led_colour = f"{red} {green} {blue}"
        return f"light ring {self.led_colour} (virtual: nothing to see)"

    def led_off(self):
        self.led_colour = "off"
        return "light ring off"

    def led_animation(self, spin, red, green, blue, seconds):
        return f"light ring {spin} {red} {green} {blue} for {seconds} s (virtual)"

    def beep(self, frequency, duration_ms):
        return f"beep {frequency} Hz for {duration_ms} ms (virtual: nothing to hear)"

    def song(self, name):
        return f"song {name} (virtual: nothing to hear)"

    def e_stop(self, enable):
        self.estopped = str(enable) in ("1", "true", "True")
        if self.estopped:
            self.body.stop()
        return "motors cut" if self.estopped else "motors armed"

    def reset_pose(self):
        return self.body.place(0.0, 0.0, 0.0)

    def power_off(self):
        return "power_off is not simulated"

    def terminate(self):
        return "terminate is not simulated"

    def battery(self, topic_path_response=None):
        return self.respond(topic_path_response, "battery", "percent=87", "volts=14.6")

    def pose(self, topic_path_response=None):
        pose = self.body.last_pose
        if not pose:
            return self.body.pose()
        return self.respond(topic_path_response, "pose",
            f"{pose['x'] / base.UNITS_PER_METRE:.3f}",
            f"{pose['y'] / base.UNITS_PER_METRE:.3f}", f"{pose['heading']:.1f}")

    def dock_status(self, topic_path_response=None):
        return self.respond(topic_path_response, "dock_status",
                            "docked" if self.docked else "undocked")

    def sensors(self, topic_path_response=None):
        return self.respond(topic_path_response, "sensors",
                            "bumpers=none", "cliffs=none")

    def telemetry_tick(self):
        """Called every telemetry period: publish the pose like the real one"""
        pose = self.body.last_pose
        if pose:
            self.publish_out(f"(pose {pose['x'] / base.UNITS_PER_METRE:.3f} "
                             f"{pose['y'] / base.UNITS_PER_METRE:.3f} {pose['heading']:.1f})")


def observe(direction, command, args, state):
    """The real Actor publishes (pose x y heading) when telemetry is on,
    which is the truth; otherwise dead reckon from the commands sent"""
    now = time.time()
    if direction == "out":
        if command == "pose" and len(args) >= 3:
            state["pose_at"] = now
            return [("place", _metres(args[0]), _metres(args[1]), base.number(args[2]))]
        if command == "hazard":
            return [("stop",)]
        return []
    if now - state.get("pose_at", 0) < POSE_FRESH:
        return []                           # the pose stream will say where it went
    match command, args:
        case "move", [distance]:
            return [("move", _metres(distance), 0.0, 0.0)]
        case "turn", [angle]:
            return [("turn", base.number(angle))]
        case "stop", _:
            return [("stop",)]
        case "walk", [seconds]:
            return [("drive", SPEED, 0.0, base.number(seconds))]
        case "drive", [linear, angular, seconds]:
            return [("drive", _metres(linear), base.number(angular), base.number(seconds))]
        case "wall_follow", [_, seconds]:
            return [("drive", SPEED, 0.0, base.number(seconds))]
        case "goto", [x, y, heading, *_]:
            return [("place", _metres(x), _metres(y), base.number(heading))]
        case "reset_pose", _:
            return [("place", 0.0, 0.0, 0.0)]
        case "undock", _:
            return [("move", -50.0, 0.0, 0.0), ("turn", 180.0)]
        case "e_stop", ["1"]:
            return [("stop",)]
    return []
