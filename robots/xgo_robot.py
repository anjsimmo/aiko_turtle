# The XGO-Mini 2 robot dog (laika and oscar at the meetup), as the
# aiko_services example Actor speaks it today: examples/xgo_robot/robot.py
# and xgo_robot.py.  move is continuous (a direction and a stride until
# stop), turn is a speed until stop, and "action NAME" plays one of the
# dog's built-in moves.  The aiko_chat ChatServer drives these robots
# through recipient "robot" with S-expressions like (action sit); its LLM
# prompt is where the phrasing of the examples below comes from.

from abc import abstractmethod

import aiko_services as aiko

from robots import base

NAME = "xgo_robot"
LABEL = "XGO-Mini 2 robot dog (aiko_services example)"
DESCRIPTION = ("the XGO quadruped as its Actor accepts commands today: action "
               "sit | stand | ..., move x|y STRIDE (mm, continuous until stop), "
               "turn SPEED (deg/s until stop), claw, arm, attitude, reset")
STATUS = base.STATUS_REAL
PROTOCOL = f"{aiko.SERVICE_PROTOCOL_AIKO}/xgo_robot:0"
UNITS = "stride in mm per step (x: -25..25, y: -18..18), turn in degrees/s (-100..100, + = left)"
SOURCE = "aiko_services/src/aiko_services/examples/xgo_robot/robot.py (robots laika and oscar)"
MATCH = {"protocol": PROTOCOL}
KINDS = {"xgo": {"label": "XGO robot dog", "axes": 2,
                 "description": "quadruped with camera, arm and microphone; walks forward and sideways"}}

ACTIONS = ("fall", "stand", "crawl", "circle", "step", "squat", "roll", "pitch",
           "yaw", "roll_pitch_yaw", "pee", "sit", "beckon", "stretch", "wave",
           "wiggle_body", "wiggle_tail", "sniff", "shake_paw", "arm")
STEPS_PER_SECOND = 2.0          # a guess at the gait: stride mm x steps/s -> speed


class XGORobot(aiko.Interface):
    @abstractmethod
    def action(self, value):
        """one of: fall stand crawl circle step squat roll pitch yaw roll_pitch_yaw pee sit beckon stretch wave wiggle_body wiggle_tail sniff shake_paw arm"""

    @abstractmethod
    def arm(self, x, z):
        """arm position: x -80..155, z -95..155"""

    @abstractmethod
    def arm_mode(self, stabilize):
        """true | false"""

    @abstractmethod
    def attitude(self, pitch="nil", roll="nil", yaw="nil"):
        """pitch -15..15, roll -20..10, yaw -11..11 (nil = unchanged)"""

    @abstractmethod
    def body_mode(self, stabilize):
        """true | false"""

    @abstractmethod
    def claw(self, grip):
        """0 (open) .. 255 (closed)"""

    @abstractmethod
    def move(self, direction, stride="nil"):
        """direction x (forward) | y (left); stride mm per step, until stop"""

    @abstractmethod
    def reset(self):
        """stop and stand square"""

    @abstractmethod
    def screen_detail(self, enabled=None):
        """show details on the screen: true | false (default: toggle)"""

    @abstractmethod
    def stop(self):
        """stop moving or turning"""

    @abstractmethod
    def terminate(self, immediate=False):
        """stop the Actor (never sent from the sandbox)"""

    @abstractmethod
    def translation(self, x="nil", y="nil", z="nil"):
        """body offset: x -35..35, y -18..18, z 75..115"""

    @abstractmethod
    def turn(self, speed):
        """degrees/s, -100 (clockwise) .. 100, until stop"""


base.default_implementation(XGORobot)
Interface = XGORobot
METHODS = [spec["name"] for spec in base.method_specs(XGORobot)]

COMMANDS = [
    ("action sit", "sit down"),
    ("action stand", "stand up"),
    ("action wiggle_tail", "happy"),
    ("action stretch", "or sniff, wave, shake_paw, pee, ..."),
    ("move x 25", "walk forward, 25 mm strides, until stop"),
    ("move x -25", "walk backwards"),
    ("move y 18", "walk left (y -18: right)"),
    ("turn 50", "turn left at 50 deg/s until stop (negative: right)"),
    ("stop", "stop walking or turning"),
    ("claw 255", "close the gripper (0 opens)"),
    ("arm 100 100", "arm position x z"),
    ("reset", "stop and stand square"),
]


def parse_command(text):
    parts = (text or "").split()
    if not parts:
        return None, "empty command"
    method, args = parts[0], parts[1:]
    if method not in METHODS:
        return None, f'unknown command "{text}": the XGO accepts {", ".join(METHODS)}'
    if method == "terminate":
        return None, "terminate is never sent from the sandbox: it would stop the real dog's Actor"
    if method == "action" and (len(args) != 1 or args[0] not in ACTIONS):
        return None, f"action takes one of {', '.join(ACTIONS)}"
    return method, args


def _speed(direction, stride):
    """(linear, lateral) units/s for a stride in mm"""
    units = base.number(stride, "stride", 0.0) * base.UNITS_PER_MM * STEPS_PER_SECOND
    return (units, 0.0) if direction != "y" else (0.0, units)


class Simulated:
    posture = "standing"
    grip = 0

    def action(self, value):
        value = str(value)
        if value not in ACTIONS:
            return f"action takes one of {', '.join(ACTIONS)}"
        self.posture = {"sit": "sitting", "stand": "standing", "squat": "squatting",
                        "fall": "lying down"}.get(value, self.posture)
        if value == "circle":
            return self.body.drive(0.0, 45.0, 8.0)
        return f"{value} (virtual: {self.posture})"

    def arm(self, x, z):
        return f"arm at x={x} z={z} (virtual)"

    def arm_mode(self, stabilize):
        return f"arm stabilise {stabilize} (virtual)"

    def attitude(self, pitch="nil", roll="nil", yaw="nil"):
        return f"attitude pitch={pitch} roll={roll} yaw={yaw} (virtual)"

    def body_mode(self, stabilize):
        return f"body stabilise {stabilize} (virtual)"

    def claw(self, grip):
        self.grip = int(base.number(grip, "grip"))
        return f"claw {self.grip} ({'closed' if self.grip > 127 else 'open'})"

    def move(self, direction, stride="nil"):
        linear, lateral = _speed(direction, stride)
        if not linear and not lateral:
            return self.body.stop()
        self.posture = "walking"
        return self.body.drive_vector(linear, lateral, 0.0)

    def reset(self):
        self.posture = "standing"
        return self.body.stop()

    def screen_detail(self, enabled=None):
        return f"screen detail {enabled if enabled is not None else 'toggled'} (virtual)"

    def stop(self):
        return self.body.stop()

    def terminate(self, immediate=False):
        return "terminate is not simulated"

    def translation(self, x="nil", y="nil", z="nil"):
        return f"translation x={x} y={y} z={z} (virtual)"

    def turn(self, speed):
        degrees = base.number(speed, "speed")
        if not degrees:
            return self.body.stop()
        return self.body.drive(0.0, degrees, 0.0)


def observe(direction, command, args, state):
    """The dog publishes no pose: dead reckon from its commands.  The real
    Actor echoes each command on out, so count only the in side"""
    if direction != "in":
        return []
    match command, args:
        case "move", [axis, *rest]:
            linear, lateral = _speed(axis, rest[0] if rest else "0")
            return [("drive_vector", linear, lateral, 0.0)] if (linear or lateral) else [("stop",)]
        case "turn", [speed]:
            degrees = base.number(speed)
            return [("drive", 0.0, degrees, 0.0)] if degrees else [("stop",)]
        case ("stop" | "reset"), _:
            return [("stop",)]
        case "action", ["circle"]:
            return [("drive", 0.0, 45.0, 8.0)]
    return []
