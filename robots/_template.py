# Copy this file to robots/NAME.py (no leading underscore: modules that
# start with "_" are skipped), fill it in, add static/sprites/NAME.js if
# the robot needs a new body, run pytest, and open a pull request.  The
# contract is in robots/__init__.py; irobot.py and xgo_robot.py are real
# examples, turtle_robot.py the smallest one.
#
# Describe the robot's interface AS IT IS: the functions its Actor really
# accepts on its "in" topic today, in the units it really uses.  The
# sandbox can then speak to the real one unchanged, and the virtual one
# behaves the same.  tools/infer_interface.py drafts a module like this
# from a running robot's MQTT traffic or its source code.

from abc import abstractmethod

import aiko_services as aiko

from robots import base

NAME = "mybot"                                  # [a-z0-9_]+, also the "interface=" tag
LABEL = "My robot (where it comes from)"
DESCRIPTION = "one sentence: what the commands mean"
STATUS = base.STATUS_PROPOSED                    # STATUS_REAL once a physical one speaks it
PROTOCOL = f"{aiko.SERVICE_PROTOCOL_AIKO}/mybot:0"   # what the Actor registers with, or ""
UNITS = "what the numbers mean"
SOURCE = "the file or repo the interface was taken from"
MATCH = {"protocol": PROTOCOL}                  # or {"name": "..."}; None = virtual only
KINDS = {"mybot": {"label": "My robot", "axes": 1,
                   "description": "what it looks like and how it moves"}}


class MyBot(aiko.Interface):                    # class name must be unique
    @abstractmethod
    def move(self, distance):
        """units forward"""

    @abstractmethod
    def turn(self, angle):
        """degrees left"""


base.default_implementation(MyBot)
Interface = MyBot

COMMANDS = [("move 10", "ten units forward"), ("turn 90", "a quarter turn left")]


def parse_command(text):
    """Chat text -> (method, [arguments]) or (None, error)"""
    parts = (text or "").split()
    match parts:
        case ["move", distance]:
            return "move", [distance]
        case ["turn", angle]:
            return "turn", [angle]
        case _:
            return None, f'unknown command "{text}": try move D, turn A'


class Simulated:
    """The virtual one: act on self.body (robots/base.py Body).  Return a
    reply string, or None when the world replies with the new pose"""

    def move(self, distance):
        return self.body.move(base.number(distance, "distance"))

    def turn(self, angle):
        return self.body.turn(base.number(angle, "angle"))


def observe(direction, command, args, state):
    """Optional.  What a message on the real robot's "in" or "out" topic
    says about where it is, for its replica: see robots/__init__.py ops"""
    if direction == "in" and command == "move" and args:
        return [("move", base.number(args[0]), 0.0, 0.0)]
    if direction == "in" and command == "turn" and args:
        return [("turn", base.number(args[0]))]
    return []
