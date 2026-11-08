# The virtual world without Aiko: robots, their poses, the maths and the
# persistence.  VirtualWorld (virtual_world.py) wraps this as an Actor;
# the tests use it directly.

import math

from db import Database

KINDS = ("turtle", "arrow")       # sprites the web page knows how to draw


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

    def create(self, name, kind="turtle", owner="anonymous", host="external"):
        """Idempotent: creating an existing robot returns it unchanged"""
        if name in self.robots:
            return dict(self.robots[name])
        if kind not in KINDS:
            raise WorldError(f"unknown kind {kind}: choose from {KINDS}")
        record = {"name": name, "kind": kind, "owner": owner, "host": host,
                  "x": 0.0, "y": 0.0, "heading": 0.0}
        self.robots[name] = record
        self.database.save_robot(record)
        self.database.add_event(name, owner, "create", kind, 0.0, 0.0, 0.0)
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
        record = self._record(name)
        distance = _number(distance, "distance")
        radians = math.radians(record["heading"])
        # "+ 0.0" turns a -0.0 into 0.0, so a pose never reads "x=-0"
        record["x"] = round(record["x"] + distance * math.cos(radians), 3) + 0.0
        record["y"] = round(record["y"] + distance * math.sin(radians), 3) + 0.0
        return self._moved(record, username, "move", distance)

    def turn(self, name, angle, username="anonymous"):
        record = self._record(name)
        angle = _number(angle, "angle")
        record["heading"] = round((record["heading"] + angle) % 360, 3)
        return self._moved(record, username, "turn", angle)

    def reset(self, name, username="anonymous"):
        record = self._record(name)
        record["x"], record["y"], record["heading"] = 0.0, 0.0, 0.0
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
                                record["x"], record["y"], record["heading"])
        self._notify("moved", record)
        return dict(record)

    def _notify(self, event, record):
        if self.listener:
            self.listener(event, dict(record))


def _number(value, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise WorldError(f"{what} must be a number, not {value!r}")
    if not math.isfinite(number):
        raise WorldError(f"{what} must be finite")
    return number


def pose_text(record):
    """The share value for one robot: "(x y heading kind)" """
    return (f"({record['x']:.3f} {record['y']:.3f} "
            f"{record['heading']:.3f} {record['kind']})")


def parse_pose_text(text):
    """Inverse of pose_text(); None if it does not parse"""
    if isinstance(text, (list, tuple)):
        parts = [str(part) for part in text]
    else:
        parts = str(text).strip("()").split()
    if len(parts) < 3:
        return None
    try:
        x, y, heading = (float(part) for part in parts[:3])
    except ValueError:
        return None
    kind = parts[3] if len(parts) > 3 else "turtle"
    return {"x": x, "y": y, "heading": heading, "kind": kind}
