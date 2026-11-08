# The virtual world without Aiko: robots, their poses, the maths and the
# persistence.  VirtualWorld (virtual_world.py) wraps this as an Actor;
# the tests use it directly.

import math

from db import Database
from kinds import AXIS_NAMES, KINDS, kind_axes


class WorldError(Exception):
    pass


class World:
    def __init__(self, database_url, listener=None):
        self.database = Database(database_url)
        self.robots = {record["name"]: record
                       for record in self.database.list_robots()}
        self.listener = listener  # listener(event, record) on every change

    # -- robots ------------------------------------------------------------

    def list(self):
        return [dict(record) for record in self.robots.values()]

    def get(self, name):
        if name not in self.robots:
            raise WorldError(f"unknown robot {name}")
        return dict(self.robots[name])

    def create(self, name, kind="turtle", owner="anonymous", host="external",
               x=0.0, y=0.0, heading=0.0):
        """Idempotent: creating an existing robot returns it unchanged"""
        if name in self.robots:
            return dict(self.robots[name])
        if kind not in KINDS:
            raise WorldError(f"unknown kind {kind}: choose from {', '.join(KINDS)}")
        record = {"name": name, "kind": kind, "owner": owner, "host": host,
                  "x": round(_number(x, "x"), 3) + 0.0,
                  "y": round(_number(y, "y"), 3) + 0.0,
                  "heading": round(_number(heading, "heading") % 360, 3),
                  "z": 0.0}
        self.robots[name] = record
        self.database.save_robot(record)
        self.database.add_event(name, owner, "create", kind,
                                record["x"], record["y"], record["heading"])
        self._notify("created", record)
        return dict(record)

    def destroy(self, name):
        if name not in self.robots:
            raise WorldError(f"unknown robot {name}")
        record = self.robots.pop(name)
        self.database.delete_robot(name)
        self._notify("destroyed", record)
        return dict(record)

    # -- motion --------------------------------------------------------------

    def move(self, name, distance, username="anonymous"):
        """distance: a number (forward) or a vector of up to three numbers
        in the robot's frame, (forward left up); the kind says how many
        axes it has (kinds.py: 1 skid drive, 2 omni, 3 flying)"""
        record = self._record(name)
        forward, left, up = _vector(distance, kind_axes(record["kind"]),
                                    record["kind"])
        radians = math.radians(record["heading"])
        cos, sin = math.cos(radians), math.sin(radians)
        # "+ 0.0" turns a -0.0 into 0.0, so a pose never reads "x=-0"
        record["x"] = round(record["x"] + forward * cos - left * sin, 3) + 0.0
        record["y"] = round(record["y"] + forward * sin + left * cos, 3) + 0.0
        record["z"] = max(0.0, round(record.get("z", 0.0) + up, 3)) + 0.0
        argument = (str(forward) if not left and not up
                    else f"{forward:g},{left:g},{up:g}")
        return self._moved(record, username, "move", argument)

    def turn(self, name, angle, username="anonymous"):
        record = self._record(name)
        angle = _number(angle, "angle")
        record["heading"] = round((record["heading"] + angle) % 360, 3)
        return self._moved(record, username, "turn", angle)

    def place(self, name, x, y, heading=None, username="anonymous"):
        """Teleport: any kind, even one that cannot move by itself"""
        record = self._record(name)
        record["x"] = round(_number(x, "x"), 3) + 0.0
        record["y"] = round(_number(y, "y"), 3) + 0.0
        if heading is not None and heading != "-":
            record["heading"] = round(_number(heading, "heading") % 360, 3)
        return self._moved(record, username, "place", f"{record['x']:g},{record['y']:g}")

    def reset(self, name, username="anonymous"):
        record = self._record(name)
        record["x"], record["y"], record["heading"] = 0.0, 0.0, 0.0
        record["z"] = 0.0
        return self._moved(record, username, "reset", "")

    def history(self, name, limit=100):
        self._record(name)
        return self.database.list_events(name, limit)

    # -- internals -----------------------------------------------------------

    def _record(self, name):
        if name not in self.robots:
            raise WorldError(f"unknown robot {name}")
        return self.robots[name]

    def _moved(self, record, username, command, argument):
        self.database.save_robot(record)
        self.database.add_event(record["name"], username, command, argument,
                                record["x"], record["y"], record["heading"],
                                record.get("z", 0.0))
        self._notify("moved", record)
        return dict(record)

    def _notify(self, event, record):
        if self.listener:
            self.listener(event, dict(record))


def _vector(distance, axes, kind):
    """(forward, left, up) from a number, a string, or a list of 1 to 3
    numbers; refuses axes the kind does not have"""
    if isinstance(distance, str) and " " in distance.strip("() "):
        distance = distance.strip("()").split()
    if isinstance(distance, (list, tuple)):
        parts = [_number(part, AXIS_NAMES[min(index, 2)])
                 for index, part in enumerate(distance)]
    else:
        parts = [_number(distance, "distance")]
    if not parts or len(parts) > 3:
        raise WorldError("move takes 1 to 3 numbers: forward [left [up]]")
    if axes == 0:
        raise WorldError(f"a {kind} cannot move")
    for index, part in enumerate(parts):
        if index >= axes and part:
            raise WorldError(f"a {kind} cannot move {AXIS_NAMES[index]}: "
                             f"it has {axes} ax{'is' if axes == 1 else 'es'}")
    parts += [0.0] * (3 - len(parts))
    return parts


def _number(value, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise WorldError(f"{what} must be a number, not {value!r}")
    if not math.isfinite(number):
        raise WorldError(f"{what} must be finite")
    return number


def pose_text(record):
    """The share value for one robot: "(x y heading kind z)" """
    return (f"({record['x']:.3f} {record['y']:.3f} "
            f"{record['heading']:.3f} {record['kind']} {record.get('z', 0.0):.3f})")


def parse_pose_text(text):
    """Inverse of pose_text(); None if it does not parse.  The z is
    optional, so an older world's share still parses"""
    if isinstance(text, (list, tuple)):
        parts = [str(part) for part in text]
    else:
        parts = str(text).strip("()").split()
    if len(parts) < 3:
        return None
    try:
        x, y, heading = (float(part) for part in parts[:3])
        z = float(parts[4]) if len(parts) > 4 else 0.0
    except ValueError:
        return None
    kind = parts[3] if len(parts) > 3 else "turtle"
    return {"x": x, "y": y, "heading": heading, "kind": kind, "z": z}
