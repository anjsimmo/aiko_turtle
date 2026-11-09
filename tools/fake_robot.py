#!/usr/bin/env python3
#
# fake_robot: a stand-in for a real robot, to test what the sandbox does
# when one connects, without the robot.  It registers with the Registrar
# exactly as the real robot's software does (same protocol, same name,
# same functions on its "in" topic, taken from robots/NAME.py), so the
# sandbox makes a twin of it.  What it does with telemetry is yours to
# choose, because that is what differs most between real robots:
#
#   --telemetry none   says nothing about where it is (an XGO, a LoliBot):
#                      the twin can only dead reckon from the commands
#   --telemetry pose   reports (pose X Y HEADING) on "out" every --period
#                      seconds in the interface's units (the iRobot's
#                      format): the twin snaps to it
#   --telemetry odd    reports in a format the sandbox does not know
#                      (a JSON odometry blob): the twin must ignore it
#   --drift PERCENT    the robot really moves PERCENT of what it was told
#                      (slipping wheels): with "pose" the twin corrects,
#                      with "none" it drifts away from the truth
#   --echo / --no-echo echo each command on "out", as the XGO does
#
# By default it is tagged world=TURTLE_WORLD so that only YOUR sandbox
# (the one whose world has that name) twins it; a real robot has no such
# tag and every sandbox on the broker twins it.  --like-real drops the tag
# to behave exactly like the real thing (then the production sandbox will
# twin it too: use a name nobody will mistake).
#
# Usage (with env.sh sourced; the dev names of README "Run it locally"):
#   ./tools/fake_robot.py xgo_robot --name devxgo_anj
#   ./tools/fake_robot.py irobot --telemetry pose --period 1 --drift 80
#   ./tools/fake_robot.py irobot --telemetry odd
#   ./tools/fake_robot.py turtle_robot --name my_turtle_anj
#   ./tools/fake_robot.py lolibot --telemetry none --no-echo
# Then drive the twin on the page (or send to its "in" topic from the
# mqtt layer) and watch this process print what arrived.

import json
import math
import sys
import time
from pathlib import Path

import click

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiko_services as aiko                                  # noqa: E402
from aiko_services.main.utilities import generate             # noqa: E402

import config                                                 # noqa: E402
import robots                                                 # noqa: E402
from robots import base                                       # noqa: E402

TICK = 0.1


class Pose:
    """Where the stand-in really is, in world units (cm) and degrees,
    integrated from the interface's own dead-reckoning rule so that a
    real robot and its stand-in agree when nothing slips"""

    def __init__(self, drift):
        self.x = self.y = self.heading = 0.0
        self.vx = self.vy = self.w = 0.0
        self.until = 0.0
        self.scale = drift / 100.0

    def apply(self, op):
        match op:
            case ("move", forward, left, _):
                self._translate(forward * self.scale, left * self.scale)
            case ("turn", degrees):
                self.heading = (self.heading + degrees * self.scale) % 360
            case ("place", x, y, heading):
                self.x, self.y, self.heading = x, y, heading % 360
            case ("drive", linear, angular, seconds):
                self._drive(linear, 0.0, angular, seconds)
            case ("drive_vector", forward, left, angular, *rest):
                self._drive(forward, left, angular, rest[0] if rest else 0.0)
            case ("stop",):
                self.vx = self.vy = self.w = 0.0

    def _drive(self, forward, left, angular, seconds):
        self.vx, self.vy, self.w = forward, left, angular
        self.until = time.time() + seconds if seconds else 0.0

    def _translate(self, forward, left):
        radians = math.radians(self.heading)
        self.x += forward * math.cos(radians) - left * math.sin(radians)
        self.y += forward * math.sin(radians) + left * math.cos(radians)

    def tick(self, dt):
        if not (self.vx or self.vy or self.w):
            return
        if self.until and time.time() >= self.until:
            self.vx = self.vy = self.w = 0.0
            return
        self._translate(self.vx * dt * self.scale, self.vy * dt * self.scale)
        self.heading = (self.heading + self.w * dt * self.scale) % 360


def make_actor(module, name, telemetry, period, echo, drift, world_tag):
    """An Actor class with every function of the interface"""
    pose = Pose(drift)
    state = {}
    specs = base.method_specs(module.Interface)
    units = base.UNITS_PER_METRE if module.NAME == "irobot" else 1.0

    def report(self):
        if telemetry == "pose":
            self._out(f"(pose {pose.x / units:.3f} {pose.y / units:.3f} {pose.heading:.1f})")
        elif telemetry == "odd":
            self._out("(odometry " + json.dumps({"x_mm": round(pose.x * 10), "y_mm": round(pose.y * 10),
                      "yaw_rad": round(math.radians(pose.heading), 4), "t": round(time.time(), 1)}) + ")")

    def make_method(spec):
        takes_response = "topic_path_response" in spec["signature"]

        def method(self, *args):
            args = [str(arg) for arg in args]
            reply_to = args.pop() if takes_response and args else None
            print(f"{name} <- ({' '.join([spec['name'], *args])})", flush=True)
            for op in robots.observe(module.NAME, "in", spec["name"], args, state):
                pose.apply(op)
            if echo:
                self._out(generate(spec["name"], args))
            if reply_to:                            # a query: answer something plausible
                aiko.process.message.publish(reply_to, "(item_count 1)")
                aiko.process.message.publish(reply_to, generate(
                    "response", [spec["name"], "fake", f"{pose.x / units:.3f}",
                                 f"{pose.y / units:.3f}", f"{pose.heading:.1f}"]))
        method.__name__ = spec["name"]
        return method

    attributes = {spec["name"]: make_method(spec) for spec in specs}

    def __init__(self, context):
        context.get_implementation("Actor").__init__(self, context)
        self._last = time.time()
        aiko.event.add_timer_handler(self._tick, TICK)
        if telemetry != "none":
            aiko.event.add_timer_handler(lambda: report(self), period)

    def _out(self, payload):
        aiko.process.message.publish(self.topic_out, payload)

    def _tick(self):
        now = time.time()
        pose.tick(now - self._last)
        self._last = now

    attributes.update(__init__=__init__, _out=_out, _tick=_tick, pose=pose)
    return type(f"Fake_{module.NAME}", (aiko.Actor, module.Interface), attributes)


@click.command()
@click.argument("interface", type=click.Choice(sorted(robots.INTERFACES)))
@click.option("--name", default=None, help="Registrar name (default: what the real one "
              "registers as, else fake_INTERFACE)")
@click.option("--telemetry", type=click.Choice(["none", "pose", "odd"]), default="none",
              show_default=True, help="what it reports on its out topic")
@click.option("--period", default=1.0, show_default=True, help="seconds between reports")
@click.option("--echo/--no-echo", default=True, show_default=True,
              help="echo each command on out, as the XGO does")
@click.option("--drift", default=100.0, show_default=True,
              help="percent of each commanded motion that really happens")
@click.option("--world", default=config.WORLD_NAME, show_default=True,
              help="only the sandbox with this world name twins it")
@click.option("--like-real", is_flag=True, help="no world tag: every sandbox twins it")
def main(interface, name, telemetry, period, echo, drift, world, like_real):
    """A stand-in for a real robot speaking INTERFACE, registered as the
    real one would be, with the telemetry behaviour you choose"""
    module = robots.INTERFACES[interface]
    match = getattr(module, "MATCH", None) or {}
    name = name or match.get("name") or f"fake_{interface}"
    if not module.PROTOCOL and "protocol" in match:
        raise click.UsageError(f"{interface} has no protocol to register with")
    tags = ["ec=true", "stand_in=1", f"interface={interface}"]
    if not like_real:
        tags.append(f"world={world}")
    actor_class = make_actor(module, name, telemetry, period, echo, drift, world)
    init_args = aiko.actor_args(name, protocol=module.PROTOCOL or None, tags=tags)
    actor = aiko.compose_instance(actor_class, init_args)
    print(f"{name}: a stand-in {interface} ({module.STATUS}) at {actor.topic_path}, "
          f"protocol {module.PROTOCOL or '(none: matched by name)'}, telemetry {telemetry}"
          f"{f' every {period:g} s' if telemetry != 'none' else ''}, drift {drift:g}%, "
          f"{'echo' if echo else 'no echo'}, "
          f"{'like a real robot (no world tag)' if like_real else f'for the sandbox world {world}'}",
          flush=True)
    print(f"functions on {actor.topic_path}/in: "
          f"{', '.join(spec['name'] for spec in base.method_specs(module.Interface))}", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
