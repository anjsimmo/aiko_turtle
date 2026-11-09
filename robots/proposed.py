# The proposed interface: the 2026-08-15 Aiko Services study-group design,
# <Robot> composed of <Move> <Grasp> <Perceive> <Telemetry>, one aspect
# tag per Interface ("move=0").  Nothing physical speaks it yet: it is
# what the virtual robots speak by default, and one proposal for what a
# future real robot could speak.  The real ones (irobot.py, xgo_robot.py,
# turtle_robot.py) are described as they are today.

import aiko_services as aiko

from robots import base
from interfaces import Grasp, Move, Perceive, Telemetry

NAME = "proposed"
LABEL = "Proposed: Move / Grasp / Perceive / Telemetry (2026-08 design)"
DESCRIPTION = ("the study group's 2026-08-15 design: move takes a vector in "
               "the robot's own frame (forward [left [up]]), turn is degrees "
               "counter-clockwise; one aspect tag per Interface. A proposal: "
               "no physical robot speaks it yet")
STATUS = base.STATUS_PROPOSED
PROTOCOL = "ai.hashtag.ai/chat_robot:0"
UNITS = "world units (cm) and degrees"
SOURCE = "2026-08-15 Aiko Services Study Group: Squad Design (interfaces.py)"
MATCH = None

# The bodies that speak it by default, and which aspects each has
KINDS = {
    "turtle": {"label": "Turtle", "axes": 1,
               "description": "the classic drawing turtle: moves, turns, leaves a trail"},
    "lekiwi": {"label": "LeKiwi", "axes": 2,
               "description": "LeRobot's three-wheel omni base carrying an SO-101 arm: moves in any direction"},
    "so101": {"label": "LeRobot SO-101 arm", "axes": 0,
              "description": "a fixed arm with a gripper: it grasps, it does not drive"},
    "drone": {"label": "Drone", "axes": 3,
              "description": "a generic quadcopter: move is a 3D vector (forward, left, up)"},
    "pi": {"label": "Raspberry Pi", "axes": 0,
           "description": "a Pi with a small display, speaker and microphone: senses, does not move"},
}
FITS = ["xgo", "lolibot", "irobot"]        # any body may try the proposal

ASPECTS = {
    "turtle": ["Move", "Perceive", "Telemetry"],
    "lekiwi": ["Move", "Grasp", "Perceive", "Telemetry"],
    "so101": ["Grasp", "Perceive", "Telemetry"],
    "drone": ["Move", "Perceive", "Telemetry"],
    "pi": ["Perceive", "Telemetry"],
}
_DEFAULT_ASPECTS = ["Move", "Perceive", "Telemetry"]
METHOD_ASPECT = {"move": "Move", "turn": "Move", "stop": "Move",
                 "grasp": "Grasp", "release": "Grasp",
                 "snapshot": "Perceive", "get_telemetry": "Telemetry"}


class ProposedRobot(Move, Grasp, Perceive, Telemetry):
    """<Robot> of the 2026-08 design, composed of its four aspects"""


base.default_implementation(ProposedRobot)
Interface = ProposedRobot


def aspects(kind):
    return list(ASPECTS.get(kind, _DEFAULT_ASPECTS))


def supports(kind, method):
    aspect = METHOD_ASPECT.get(method)
    return aspect is None or aspect in aspects(kind)


def tags(kind):
    """One aspect tag per Interface (ADR-025), plus the axes"""
    from robots import kind_axes
    return [f"{aspect.lower()}=0" for aspect in aspects(kind)] + [f"axes={kind_axes(kind)}"]


COMMANDS = [
    ("move 100", "forward 100 units (negative = backwards)"),
    ("move 0 50", "a vector: forward, left (omni bases and walkers)"),
    ("move 0 0 30", "forward, left, up (drones)"),
    ("turn 90", "degrees counter-clockwise"),
    ("stop", "stop (a virtual robot moves instantly: nothing to stop)"),
    ("grasp", "close the gripper (kinds with an arm)"),
    ("release", "open the gripper"),
    ("look", "where am I (<Perceive> snapshot)"),
    ("telemetry", "battery and temperature (<Telemetry>)"),
]


def parse_command(text):
    parts = (text or "").split()
    match parts:
        case ["move", distance]:
            return "move", [distance]
        case ["move", _, _] | ["move", _, _, _]:
            return "move", [parts[1:]]              # a vector in the robot's frame
        case ["turn", angle]:
            return "turn", [angle]
        case ["stop"]:
            return "stop", []
        case ["grasp"] | ["grab"] | ["close"]:
            return "grasp", []
        case ["release"] | ["open"]:
            return "release", []
        case ["look"] | ["snapshot"]:
            return "snapshot", []
        case ["telemetry"] | ["battery"]:
            return "get_telemetry", []
        case _:
            return None, f'unknown command "{text}"'


class Simulated:
    """The virtual robot: <Move> goes to the world, the rest is state here"""

    gripper = "open"

    def move(self, distance, username=None):
        if username:
            self.current_username = username
        if isinstance(distance, str) and " " in distance.strip("() "):
            distance = distance.strip("()").split()
        parts = list(distance) if isinstance(distance, (list, tuple)) else [distance]
        if not 1 <= len(parts) <= 3:
            return "move takes 1 to 3 numbers: forward [left [up]]"
        try:
            forward, left, up = (parts + [0.0, 0.0])[:3]
            return self.body.move(base.number(forward, "forward"),
                                  base.number(left, "left"), base.number(up, "up"))
        except ValueError as error:
            return str(error)

    def turn(self, angle, username=None):
        if username:
            self.current_username = username
        try:
            return self.body.turn(base.number(angle, "angle"))
        except ValueError as error:
            return str(error)

    def stop(self):
        return "stopped (a virtual robot moves instantly, nothing to stop)"

    def grasp(self):
        self.gripper = "closed"
        return "gripper closed"

    def release(self):
        self.gripper = "open"
        return "gripper open"

    def snapshot(self, topic_path_response=None):
        if topic_path_response:
            pose = self.body.last_pose or {}
            self.respond(topic_path_response, "pose", *[
                f"{pose.get(key, 0.0):.3f}" for key in ("x", "y", "heading", "z")])
        return self.body.pose()

    def get_telemetry(self, topic_path_response=None):
        telemetry = "(battery 87) (temperature 21.5)"
        if topic_path_response:
            self.respond(topic_path_response, telemetry)
        return f"telemetry: {telemetry}"
