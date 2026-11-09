#!/usr/bin/env python3
#
# VirtualWorld Actor: the shared virtual "hardware" every robot lives in.
# Holds every robot's pose, persists them (db.py, TURTLE_DATABASE_URL),
# integrates continuous motion ten times a second, and publishes each
# pose as the share "robots.<name>" = "(x y heading kind z pen interface
# host moving)".
#
# Remote functions (each optional "topic_path_response" gets
# "(item_count 1)" then "(response <command> name x y heading kind z)" or
# "(response error <reason>)"; list_robots adds host, owner, interface,
# source and pen):
#
#   create_robot name [kind] [owner] [host] [topic_path_response] [x y heading] [interface] [source]
#   destroy_robot name [topic_path_response]
#   set_host name host [source] [topic_path_response]
#   apply_move name distance [username] [topic_path_response]   ;; distance: N or (F L U)
#   apply_turn name angle    [username] [topic_path_response]
#   apply_drive name forward left angular seconds [username] [topic_path_response]
#   apply_stop name [username] [topic_path_response]
#   set_pen name down|up [username] [topic_path_response]
#   reset name [x y heading] [username] [topic_path_response]  ;; no x y: the origin
#   get_pose name topic_path_response
#   list_robots topic_path_response        ;; N responses
#   get_history name limit topic_path_response
#
# Usage
# ~~~~~
#   source env.sh
#   ./virtual_world.py run [--name turtle_world] [--database sqlite:///turtle.db]

import click

import aiko_services as aiko
from aiko_services.main.utilities import generate

import config
from world_model import World, WorldError, pose_text

WORLD_PROTOCOL = "ai.hashtag.ai/virtual_world:0"
TICK_PERIOD = 0.1               # s: the integrator for continuous motion


class VirtualWorld(aiko.Actor):
    def __init__(self, context, database_url=config.DATABASE_URL):
        context.call_init(self, "Actor", context)
        self.share["source_file"] = __file__
        self.share["robots"] = {}
        self.world = World(database_url, listener=self._changed)
        for record in self.world.list():
            self._changed("loaded", record)
        print(f"WORLD: {len(self.world.robots)} robots loaded from "
              f"{database_url}", flush=True)
        aiko.event.add_timer_handler(self._tick, TICK_PERIOD)

    def _tick(self):
        self.world.tick()

    # -- share ---------------------------------------------------------------

    def _changed(self, event, record):
        name = record["name"]
        if event == "destroyed":
            self.ec_producer.remove(f"robots.{name}")
        else:
            self.ec_producer.update(f"robots.{name}", pose_text(record))
        if event != "moved" or not record.get("moving"):
            print(f"WORLD: {event} {name} {pose_text(record)}", flush=True)

    # -- responses -----------------------------------------------------------

    def _respond(self, topic_path_response, command, result):
        if not topic_path_response or topic_path_response == "-":
            return
        if isinstance(result, WorldError):
            fields = ["error", str(result)]
        else:
            fields = [command, *_pose_fields(result)]
        aiko.process.message.publish(topic_path_response, "(item_count 1)")
        aiko.process.message.publish(
            topic_path_response, generate("response", fields))

    def _do(self, command, topic_path_response, function, *arguments):
        try:
            result = function(*arguments)
        except WorldError as error:
            result = error
            print(f"WORLD: {command}: {error}", flush=True)
        self._respond(topic_path_response, command, result)

    # -- remote functions ----------------------------------------------------

    def create_robot(self, name, kind="turtle", owner="anonymous",
                     host="external", topic_path_response=None,
                     x=0.0, y=0.0, heading=0.0, interface="", source=""):
        self._do("create", topic_path_response, self.world.create, name, kind,
                 owner, host, x, y, heading, interface or None, source)

    def destroy_robot(self, name, topic_path_response=None):
        self._do("destroy", topic_path_response, self.world.destroy, name)

    def set_host(self, name, host, source="-", topic_path_response=None):
        self._do("host", topic_path_response, self.world.set_host, name, host,
                 None if source == "-" else source)

    def apply_move(self, name, distance, username="anonymous",
                   topic_path_response=None):
        self._do("move", topic_path_response,
                 self.world.move, name, distance, username)

    def apply_turn(self, name, angle, username="anonymous",
                   topic_path_response=None):
        self._do("turn", topic_path_response,
                 self.world.turn, name, angle, username)

    def apply_drive(self, name, forward, left=0.0, angular=0.0, seconds=0.0,
                    username="anonymous", topic_path_response=None):
        self._do("drive", topic_path_response, self.world.drive, name,
                 forward, left, angular, seconds, username)

    def apply_stop(self, name, username="anonymous", topic_path_response=None):
        self._do("stop", topic_path_response, self.world.stop, name, username)

    def set_pen(self, name, down="down", username="anonymous",
                topic_path_response=None):
        self._do("pen", topic_path_response, self.world.set_pen, name, down,
                 username)

    def reset(self, name, x=0.0, y=0.0, heading=0.0, username="anonymous",
              topic_path_response=None):
        self._do("reset", topic_path_response,
                 self.world.reset, name, x, y, heading, username)

    def get_pose(self, name, topic_path_response):
        self._do("pose", topic_path_response, self.world.get, name)

    def list_robots(self, topic_path_response):
        records = self.world.list()
        aiko.process.message.publish(
            topic_path_response, f"(item_count {len(records)})")
        for record in records:
            aiko.process.message.publish(topic_path_response,
                generate("response", ["robot", *_pose_fields(record)]))

    def get_history(self, name, limit, topic_path_response):
        try:
            events = self.world.history(name, int(limit))
        except (WorldError, ValueError) as error:
            self._respond(topic_path_response, "history", WorldError(error))
            return
        aiko.process.message.publish(
            topic_path_response, f"(item_count {len(events)})")
        for event in events:
            aiko.process.message.publish(topic_path_response,
                generate("response", ["event", f"{event['timestamp']:.3f}",
                    event["username"], event["command"],
                    event["argument"] or "-", f"{event['x']:.3f}",
                    f"{event['y']:.3f}", f"{event['heading']:.3f}",
                    f"{event.get('z', 0.0):.3f}"]))


def _pose_fields(record):
    """name x y heading kind z host owner interface source pen moving"""
    return [record["name"], f"{record['x']:.3f}", f"{record['y']:.3f}",
            f"{record['heading']:.3f}", record["kind"],
            f"{record.get('z', 0.0):.3f}", record.get("host", "external"),
            record.get("owner", "anonymous"), record.get("interface", "robot"),
            record.get("source") or "-", "down" if record.get("pen", 1) else "up",
            "moving" if record.get("moving") else "still"]


@click.group()
def main():
    """VirtualWorld Actor"""
    pass


@main.command(name="run")
@click.option("--name", type=str, default=config.WORLD_NAME, show_default=True)
@click.option("--database", "database_url", type=str,
    default=config.DATABASE_URL, show_default=True)
def run_command(name, database_url):
    tags = ["ec=true", "type=virtual_world"]
    init_args = aiko.actor_args(name, protocol=WORLD_PROTOCOL, tags=tags)
    init_args["database_url"] = database_url
    world = aiko.compose_instance(VirtualWorld, init_args)
    print(f"WORLD: {name} running, topic_path={world.topic_path}", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
