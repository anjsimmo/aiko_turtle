#!/usr/bin/env python3
#
# VirtualWorld Actor: the shared virtual "hardware" every turtle lives in.
# Holds every robot's pose, persists them (db.py, TURTLE_DATABASE_URL) and
# publishes them as the share "robots.<name>" = "(x y heading kind)".
#
# Remote functions (each optional "topic_path_response" gets
# "(item_count 1)" then "(response <command> name x y heading kind)" or
# "(response error <reason>)"):
#
#   create_robot name [kind] [owner] [host] [topic_path_response]
#   destroy_robot name [topic_path_response]
#   apply_move name distance [username] [topic_path_response]
#   apply_turn name angle    [username] [topic_path_response]
#   reset name               [username] [topic_path_response]
#   get_pose name topic_path_response
#   list_robots topic_path_response        ;; N responses, with host and owner
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

    # -- share ---------------------------------------------------------------

    def _changed(self, event, record):
        name = record["name"]
        if event == "destroyed":
            self.ec_producer.remove(f"robots.{name}")
        else:
            self.ec_producer.update(f"robots.{name}", pose_text(record))
        print(f"WORLD: {event} {name} {pose_text(record)}", flush=True)

    # -- responses -----------------------------------------------------------

    def _respond(self, topic_path_response, command, result):
        if not topic_path_response or topic_path_response == "-":
            return
        if isinstance(result, WorldError):
            fields = ["error", str(result)]
        else:
            fields = [command, result["name"], f"{result['x']:.3f}",
                      f"{result['y']:.3f}", f"{result['heading']:.3f}",
                      result["kind"]]
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
                     host="external", topic_path_response=None):
        self._do("create", topic_path_response,
                 self.world.create, name, kind, owner, host)

    def destroy_robot(self, name, topic_path_response=None):
        self._do("destroy", topic_path_response, self.world.destroy, name)

    def apply_move(self, name, distance, username="anonymous",
                   topic_path_response=None):
        self._do("move", topic_path_response,
                 self.world.move, name, distance, username)

    def apply_turn(self, name, angle, username="anonymous",
                   topic_path_response=None):
        self._do("turn", topic_path_response,
                 self.world.turn, name, angle, username)

    def reset(self, name, username="anonymous", topic_path_response=None):
        self._do("reset", topic_path_response,
                 self.world.reset, name, username)

    def get_pose(self, name, topic_path_response):
        self._do("pose", topic_path_response, self.world.get, name)

    def list_robots(self, topic_path_response):
        records = self.world.list()
        aiko.process.message.publish(
            topic_path_response, f"(item_count {len(records)})")
        for record in records:
            aiko.process.message.publish(topic_path_response,
                generate("response", ["robot", record["name"],
                    f"{record['x']:.3f}", f"{record['y']:.3f}",
                    f"{record['heading']:.3f}", record["kind"],
                    record["host"], record["owner"]]))

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
                    f"{event['y']:.3f}", f"{event['heading']:.3f}"]))


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
