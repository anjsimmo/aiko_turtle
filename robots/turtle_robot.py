# The June 2026 tutorial's virtual turtle, exactly as the two Colab
# notebooks speak it (old_tutorials/*part1_agent.ipynb drives it,
# *part2_robot.ipynb is it): an Actor named "turtle_robot" (renamed by
# each student) with forward / backward / left / right / action.  A robot
# created here with this interface answers the old part-1 notebook, and a
# turtle run from the old part-2 notebook appears here as a replica.

import aiko_services as aiko
from abc import abstractmethod

from robots import base

NAME = "turtle_robot"
LABEL = "Legacy virtual turtle (June 2026 tutorial)"
DESCRIPTION = ("the Colab tutorial turtle of June 2026: forward / backward in "
               "turtle steps, left / right in degrees, action penup | pendown "
               "| forward | left | right | backward")
STATUS = base.STATUS_LEGACY
PROTOCOL = f"{aiko.SERVICE_PROTOCOL_AIKO}/turtle_robot:0"
UNITS = "turtle steps (1 = 1 world unit) and degrees"
SOURCE = "examples/notebooks/ (the June 2026 tutorial, part 2)"
MATCH = {"protocol": PROTOCOL}
FITS = ["turtle"]
DEFAULT_KIND = "turtle"

ACTIONS = ("penup", "pendown", "forward", "left", "right", "backward")


class TurtleRobot(aiko.Interface):
    @abstractmethod
    def action(self, value):
        """penup | pendown | forward (100) | left (90) | right (90) | backward (100)"""

    @abstractmethod
    def forward(self, value):
        """turtle steps forward"""

    @abstractmethod
    def left(self, value):
        """degrees, turning left (counter-clockwise)"""

    @abstractmethod
    def right(self, value):
        """degrees, turning right (clockwise)"""

    @abstractmethod
    def backward(self, value):
        """turtle steps backward"""


base.default_implementation(TurtleRobot)
Interface = TurtleRobot


COMMANDS = [
    ("forward 100", "100 turtle steps forward"),
    ("backward 50", "50 steps back"),
    ("left 90", "turn left 90 degrees"),
    ("right 90", "turn right 90 degrees"),
    ("action penup", "stop drawing the trail"),
    ("action pendown", "draw the trail again"),
    ("action forward", "the defaults: forward 100, left 90, right 90, backward 100"),
]


def parse_command(text):
    parts = (text or "").split()
    match parts:
        case ["action", value] if value in ACTIONS:
            return "action", [value]
        case [value] if value in ("penup", "pendown"):
            return "action", [value]
        case ["forward" | "backward" | "left" | "right" as method, value]:
            return method, [value]
        case ["forward" | "backward" | "left" | "right" as method]:
            return "action", [method]
        case _:
            return None, f'unknown command "{text}"'


def _ops(method, value):
    """What one call means for the pose: the ops of robots/__init__"""
    if method == "action":
        return {"penup": [("pen", False)], "pendown": [("pen", True)],
                "forward": [("move", 100.0, 0.0, 0.0)], "backward": [("move", -100.0, 0.0, 0.0)],
                "left": [("turn", 90.0)], "right": [("turn", -90.0)]}.get(value, [])
    steps = base.number(value, method)
    return {"forward": [("move", steps, 0.0, 0.0)], "backward": [("move", -steps, 0.0, 0.0)],
            "left": [("turn", steps)], "right": [("turn", -steps)]}[method]


class Simulated:
    def _do(self, method, value):
        try:
            ops = _ops(method, value)
        except (ValueError, KeyError) as error:
            return str(error)
        if not ops:
            return f"action {value}: not one of {', '.join(ACTIONS)}"
        reply = None
        for op in ops:
            reply = self.apply_op(op)
        return reply

    def action(self, value):
        return self._do("action", str(value))

    def forward(self, value):
        return self._do("forward", value)

    def backward(self, value):
        return self._do("backward", value)

    def left(self, value):
        return self._do("left", value)

    def right(self, value):
        return self._do("right", value)


def observe(direction, command, args, state):
    """A command on the real turtle's "in" topic moves the replica the same way"""
    if direction != "in" or command not in ("action", "forward", "backward", "left", "right"):
        return []
    return _ops(command, args[0] if args else "")
