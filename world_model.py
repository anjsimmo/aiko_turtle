# The virtual world without Aiko: robots, their poses, the maths and the
# persistence.  VirtualWorld (virtual_world.py) wraps this as an Actor;
# the tests use it directly.
#
# A robot has a pose (x, y, heading, z), a pen (does it leave a trail), a
# kind (its body), an interface (what it speaks) and, while a continuous
# command runs, a velocity that tick() integrates: the XGO walks until
# told to stop, the LoliBot drives for a number of seconds.

import math
import time

from db import Database
import robots as registry

AXIS_NAMES = ("forward", "left", "up")
TICK_SAVE_PERIOD = 1.0          # s between database writes while driving


class WorldError(Exception):
    pass


class World:
    def __init__(self, database_url, listener=None, clock=time.time):
        self.database = Database(database_url)
        self.robots = {record["name"]: record
                       for record in self.database.list_robots()}
        for record in self.robots.values():
            record.update(vx=0.0, vy=0.0, w=0.0, until=0.0)
        self.listener = listener  # listener(event, record) on every change
        self.clock = clock

    # -- robots ------------------------------------------------------------

    def list(self):
        return [self._public(record) for record in self.robots.values()]

    def get(self, name):
        return self._public(self._record(name))

    def create(self, name, kind="turtle", owner="anonymous", host="external",
               x=0.0, y=0.0, heading=0.0, interface=None, source=""):
        """Idempotent: creating an existing robot returns it unchanged"""
        if name in self.robots:
            return self._public(self.robots[name])
        try:
            kind, interface = registry.resolve(kind, interface or None)
        except ValueError as error:
            raise WorldError(str(error))
        record = {"name": name, "kind": kind, "interface": interface,
                  "owner": owner, "host": host, "source": source or "",
                  "x": round(_number(x, "x"), 3) + 0.0,
                  "y": round(_number(y, "y"), 3) + 0.0,
                  "heading": round(_number(heading, "heading") % 360, 3),
                  "z": 0.0, "pen": 1, "vx": 0.0, "vy": 0.0, "w": 0.0, "until": 0.0}
        self.robots[name] = record
        self.database.save_robot(record)
        self.database.add_event(name, owner, "create", f"{kind},{interface}",
                                record["x"], record["y"], record["heading"])
        self._notify("created", record)
        return self._public(record)

    def destroy(self, name):
        record = self.robots.pop(name, None)
        if record is None:
            raise WorldError(f"unknown robot {name}")
        self.database.delete_robot(name)
        self._notify("destroyed", record)
        return self._public(record)

    def set_host(self, name, host, source=None):
        """Who speaks for the robot: web, external (someone's own
        process), or replica (a real robot, source = its topic path)"""
        record = self._record(name)
        record["host"] = host
        if source is not None:
            record["source"] = source
        self.database.save_robot(record)
        self._notify("moved", record)
        return self._public(record)
        return self._public(record)

    # -- motion --------------------------------------------------------------

    def move(self, name, distance, username="anonymous"):
        """distance: a number (forward) or a vector of up to three numbers
        in the robot's frame, (forward left up); the kind says how many
        axes it has (1 skid drive, 2 omni, 3 flying)"""
        record = self._record(name)
        forward, left, up = _vector(distance, registry.kind_axes(record["kind"]),
                                    record["kind"])
        self._translate(record, forward, left, up)
        argument = (f"{forward:g}" if not left and not up
                    else f"{forward:g},{left:g},{up:g}")
        return self._moved(record, username, "move", argument)

    def turn(self, name, angle, username="anonymous"):
        record = self._record(name)
        angle = _number(angle, "angle")
        record["heading"] = round((record["heading"] + angle) % 360, 3)
        return self._moved(record, username, "turn", f"{angle:g}")

    def reset(self, name, x=0.0, y=0.0, heading=0.0, username="anonymous"):
        """Put the robot at (x, y) facing heading, on the ground, still.
        No arguments: the origin.  Works for every kind (a Pi can be put
        somewhere even though it cannot move), so it is not part of any
        interface: it is the sandbox's hand"""
        record = self._record(name)
        record["x"] = round(_number(x, "x"), 3) + 0.0
        record["y"] = round(_number(y, "y"), 3) + 0.0
        record["heading"] = round(_number(heading, "heading") % 360, 3)
        record["z"] = 0.0
        record.update(vx=0.0, vy=0.0, w=0.0, until=0.0)
        argument = "" if not (record["x"] or record["y"] or record["heading"])  \
            else f"{record['x']:g},{record['y']:g},{record['heading']:g}"
        return self._moved(record, username, "reset", argument)

    def drive(self, name, forward, left=0.0, angular=0.0, seconds=0.0,
              username="anonymous"):
        """Start moving at forward and left units/s in the robot's frame
        and angular degrees/s, for seconds (0 = until stop()).  tick()
        integrates it"""
        record = self._record(name)
        forward, left = _number(forward, "forward"), _number(left, "left")
        angular, seconds = _number(angular, "angular"), _number(seconds, "seconds")
        axes = registry.kind_axes(record["kind"])
        if axes == 0 and (forward or left):
            raise WorldError(f"a {record['kind']} cannot move")
        if axes < 2 and left:
            raise WorldError(f"a {record['kind']} cannot move left: it has 1 axis")
        if seconds < 0:
            raise WorldError("seconds must be 0 (until stop) or positive")
        now = self.clock()
        record.update(vx=forward, vy=left, w=angular,
                      until=now + seconds if seconds else 0.0, _tick=now, _saved=now)
        argument = f"{forward:g},{left:g},{angular:g},{seconds:g}"
        return self._moved(record, username, "drive", argument)

    def stop(self, name, username="anonymous"):
        record = self._record(name)
        if not self.moving(record):
            return self._public(record)
        record.update(vx=0.0, vy=0.0, w=0.0, until=0.0)
        return self._moved(record, username, "stop", "")

    def set_pen(self, name, down, username="anonymous"):
        record = self._record(name)
        record["pen"] = 1 if str(down).lower() in ("1", "true", "down", "on") else 0
        return self._moved(record, username, "pen", "down" if record["pen"] else "up")

    @staticmethod
    def moving(record):
        return bool(record.get("vx") or record.get("vy") or record.get("w"))

    def tick(self, now=None):
        """Advance every driving robot; call it 5 to 10 times a second.
        Returns the names that moved"""
        now = self.clock() if now is None else now
        moved = []
        for record in list(self.robots.values()):
            if not self.moving(record):
                continue
            last = record.get("_tick", now)
            end = min(now, record["until"]) if record["until"] else now
            dt = max(0.0, end - last)
            if dt:
                self._translate(record, record["vx"] * dt, record["vy"] * dt, 0.0)
                record["heading"] = round((record["heading"] + record["w"] * dt) % 360, 3)
            record["_tick"] = now
            finished = bool(record["until"]) and now >= record["until"]
            if finished:
                record.update(vx=0.0, vy=0.0, w=0.0, until=0.0)
                self._moved(record, "world", "stop", "done")
            elif dt:
                if now - record.get("_saved", 0) >= TICK_SAVE_PERIOD:
                    record["_saved"] = now
                    self.database.save_robot(record)
                self._notify("moved", record)
            if dt or finished:
                moved.append(record["name"])
        return moved

    def history(self, name, limit=100):
        self._record(name)
        return self.database.list_events(name, limit)

    # -- internals -----------------------------------------------------------

    def _record(self, name):
        if name not in self.robots:
            raise WorldError(f"unknown robot {name}")
        return self.robots[name]

    @staticmethod
    def _public(record):
        """The record without the integrator's scratch fields"""
        public = {key: value for key, value in record.items()
                  if not key.startswith("_")}
        public["moving"] = World.moving(record)
        for key in ("vx", "vy", "w", "until"):
            public.pop(key, None)
        return public

    @staticmethod
    def _translate(record, forward, left, up):
        radians = math.radians(record["heading"])
        cos, sin = math.cos(radians), math.sin(radians)
        # "+ 0.0" turns a -0.0 into 0.0, so a pose never reads "x=-0"
        record["x"] = round(record["x"] + forward * cos - left * sin, 3) + 0.0
        record["y"] = round(record["y"] + forward * sin + left * cos, 3) + 0.0
        record["z"] = max(0.0, round(record.get("z", 0.0) + up, 3)) + 0.0

    def _moved(self, record, username, command, argument):
        self.database.save_robot(record)
        self.database.add_event(record["name"], username, command, argument,
                                record["x"], record["y"], record["heading"],
                                record.get("z", 0.0))
        self._notify("moved", record)
        return self._public(record)

    def _notify(self, event, record):
        if self.listener:
            self.listener(event, self._public(record))


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
    """The share value for one robot:
    "(x y heading kind z pen interface host moving)" """
    return (f"({record['x']:.3f} {record['y']:.3f} {record['heading']:.3f} "
            f"{record['kind']} {record.get('z', 0.0):.3f} "
            f"{'down' if record.get('pen', 1) else 'up'} "
            f"{record.get('interface', 'proposed')} {record.get('host', 'external')} "
            f"{'moving' if record.get('moving') else 'still'})")


def parse_pose_text(text):
    """Inverse of pose_text(); None if it does not parse.  Everything after
    the heading is optional, so an older world's share still parses"""
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
    return {"x": x, "y": y, "heading": heading, "z": z,
            "kind": parts[3] if len(parts) > 3 else "turtle",
            "pen": 0 if len(parts) > 5 and parts[5] == "up" else 1,
            "interface": parts[6] if len(parts) > 6 else "proposed",
            "host": parts[7] if len(parts) > 7 else "external",
            "moving": len(parts) > 8 and parts[8] == "moving"}
