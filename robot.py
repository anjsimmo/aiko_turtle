#!/usr/bin/env python3
#
# ChatRobotAgent: one virtual robot, as an Aiko Actor implementing the
# <Chat> and <Robot> Interfaces (<Robot> composed of <Move>, <Grasp>,
# <Perceive> and <Telemetry>, as the robot's kind allows: kinds.py).  Its
# body lives in the VirtualWorld; this Actor is the robot's voice in the
# chat and its entry in the Registrar.
#
# Anyone can run one, from anywhere, against the shared services:
#
#   source env.sh
#   ./robot.py run --name my_turtle [--kind turtle|xgo|...] [--channel robots]
#
# then, in the channel:  @@my_turtle move 100
#
# The web server (web.py) hosts a ChatRobotAgent in its own process for
# every robot created through the REST API, with host_robot().
#
# Chat commands: move D (or move F L [U], a vector in the robot's frame:
# forward, left, up, as many axes as the kind has), turn A, stop, reset,
# place X Y [H], grasp, release, look, telemetry, interfaces, join CHANNEL
# (those the kind supports; "place" teleports any kind).  Only messages
# STARTING with "@@name" are commands.

import click

import aiko_services as aiko
from aiko_services.main.discovery import get_service_proxy
from aiko_services.main.share import services_cache_create_singleton
from aiko_services.main.utilities import parse
from aiko_chat import ChatServer, get_server_service_filter
import aiko_chat.bot as bot
from aiko_chat.protocol import _decode_message

import config
from core import parse_command
from interfaces import (
    Chat, Grasp, Move, Perceive, Robot, Telemetry, aspect_tags,
)
from kinds import (
    DEFAULT_KIND, KINDS, kind_axes, kind_commands, kind_interfaces, supports,
)
from virtual_world import VirtualWorld

ROBOT_PROTOCOL = "ai.hashtag.ai/chat_robot:0"
ACK_SUFFIX = " !!!!"            # loop-prevention convention, see aiko_chat.bot


class ChatRobotAgent(bot.ChatBot, Chat, Robot, Move, Grasp, Perceive, Telemetry):
    def __init__(self, context, robot_name, channel=config.CHANNEL,
                 world_name=config.WORLD_NAME, kind=DEFAULT_KIND,
                 owner="anonymous", host="external"):
        context.call_init(self, "ChatBot", context)
        self.robot_name = robot_name
        self.botname = f"@@{robot_name}"
        self.current_channel = channel
        self.kind = kind if kind in KINDS else DEFAULT_KIND
        self.gripper = "open"       # <Grasp> state (virtual: no world needed)
        self.owner = owner
        self.host = host
        self.share["source_file"] = __file__
        self.world = None
        self.world_filter = aiko.ServiceFilter(
            "*", world_name, "*", "*", "*", "*")
        self.world_response_topic = f"{self.topic_path}/world_response"
        self.add_message_handler(
            self._world_response_handler, self.world_response_topic)
        self.world_discovery = aiko.do_discovery(
            VirtualWorld, self.world_filter,
            self._world_add_handler, self._world_remove_handler)

    def attach_known_services(self):
        """Discovery registered after the services cache has loaded gets
        no replay of the Services already known (a framework TODO), so a
        robot created inside a running process asks the cache itself"""
        cache = services_cache_create_singleton(aiko.process)
        if cache.get_state() not in ("loaded", "ready"):
            return
        services = cache.get_services()
        for service_filter, interface, add_handler in (
            (get_server_service_filter(), ChatServer,
             self.discovery_add_handler),
            (self.world_filter, VirtualWorld, self._world_add_handler)):
            for details in services.filter_services(service_filter):
                add_handler(details,
                            get_service_proxy(f"{details[0]}/in", interface))

    def print(self, output):
        print(f"ROBOT {self.robot_name}: {output}", flush=True)

    # -- world ---------------------------------------------------------------

    def _world_add_handler(self, service_details, service):
        self.print(f"world connected: {service_details[0]}")
        self.world = service
        self.world_topic = service_details[0]
        self.world.create_robot(self.robot_name, self.kind, self.owner,
                                self.host, self.world_response_topic)

    def _world_remove_handler(self, service_details):
        if service_details[0] != getattr(self, "world_topic", None):
            return                  # another world of the same name, not ours
        self.print("world disconnected")
        self.world = None
        self.world_topic = None

    def _world_response_handler(self, _aiko, topic, payload_in):
        try:
            command, fields = parse(payload_in)
        except Exception:
            return
        if command != "response" or not fields:
            return
        if fields[0] == "error":
            text = "error: " + " ".join(str(field) for field in fields[1:])
        elif fields[0] == "create":
            text = f"ready at {_pose_words(fields)}"
        else:
            text = f"{fields[0]}: now at {_pose_words(fields)}"
        self._say(text)

    def _with_world(self, action):
        if not self.world:
            return "world not connected, try again shortly"
        action(self.world)
        return None             # the world's response is relayed to chat

    # -- <Move> --------------------------------------------------------------

    def move(self, distance, username="anonymous"):
        return self._with_world(lambda world: world.apply_move(
            self.robot_name, distance, username, self.world_response_topic))

    def turn(self, angle, username="anonymous"):
        return self._with_world(lambda world: world.apply_turn(
            self.robot_name, angle, username, self.world_response_topic))

    def stop(self):
        return "stopped (a virtual turtle moves instantly, nothing to stop)"

    def reset(self, username="anonymous"):
        return self._with_world(lambda world: world.reset(
            self.robot_name, username, self.world_response_topic))

    def place(self, x, y, heading="-", username="anonymous"):
        """Teleport (not part of <Move>: a Pi can be put somewhere too)"""
        return self._with_world(lambda world: world.apply_place(
            self.robot_name, x, y, heading, username, self.world_response_topic))

    # -- <Grasp> -------------------------------------------------------------

    def grasp(self):
        self.gripper = "closed"
        return "gripper closed"

    def release(self):
        self.gripper = "open"
        return "gripper open"

    # -- <Perceive> ----------------------------------------------------------

    def snapshot(self, topic_path_response=None):
        return self._with_world(lambda world: world.get_pose(
            self.robot_name, topic_path_response or self.world_response_topic))

    # -- <Telemetry> ---------------------------------------------------------

    def get_telemetry(self, topic_path_response=None):
        telemetry = "(battery 87) (temperature 21.5)"
        if topic_path_response:
            aiko.process.message.publish(topic_path_response, "(item_count 1)")
            aiko.process.message.publish(
                topic_path_response, f"(response {telemetry})")
        return telemetry

    # -- <Robot> -------------------------------------------------------------

    def get_interfaces(self, topic_path_response=None):
        names = ["Chat", "Robot", *kind_interfaces(self.kind)]
        if topic_path_response:
            aiko.process.message.publish(
                topic_path_response, f"(item_count {len(names)})")
            for name in names:
                aiko.process.message.publish(
                    topic_path_response, f"(response {name})")
        return names

    # -- <Chat> --------------------------------------------------------------

    def send_message(self, username, recipients, message):
        if self.chat_server:
            self.chat_server.send_message(username, recipients, message)

    def receive_message(self, username, channel, message):
        # Direct delivery (remote function call), no @@mention required
        reply = self.run_command(message.strip(), username)
        if reply:
            self._say(reply, channel)

    def process_message(self, payload_in, **kwargs):
        # Channel traffic via the ChatServer: only messages STARTING with
        # our mention are commands, so prose about the robot is ignored
        fields = _decode_message(payload_in)
        message = (fields["message"] if fields else str(payload_in)).strip()
        username = str(fields.get("username", "anonymous")) if fields  \
            else "anonymous"
        if not message.startswith(self.botname + " ") and  \
                message != self.botname:
            return
        if message.endswith(ACK_SUFFIX):
            return
        chat_command = message[len(self.botname):].strip()
        self.print(f"{username}: {chat_command}")
        reply = self.run_command(chat_command, username)
        if reply:
            self._say(reply)

    def _say(self, text, channel=None):
        self.send_message(self.botname, [channel or self.current_channel],
                          f"{self.robot_name}: {text}{ACK_SUFFIX}")

    def run_command(self, chat_command, username="anonymous"):
        """Returns the immediate reply, or None when the world will reply"""
        method, arguments = parse_command(chat_command)
        if method and not supports(self.kind, method):
            return (f"a {self.kind} cannot {method}: its commands are "
                    f"{', '.join(kind_commands(self.kind))}")
        match method:
            case "move":
                return self.move(arguments[0], username)
            case "turn":
                return self.turn(arguments[0], username)
            case "stop":
                return self.stop()
            case "reset":
                return self.reset(username)
            case "place":
                return self.place(*arguments, username=username)
            case "grasp":
                return self.grasp()
            case "release":
                return self.release()
            case "look":
                return self.snapshot()
            case "telemetry":
                return f"telemetry: {self.get_telemetry()}"
            case "interfaces":
                return f"interfaces: {','.join(self.get_interfaces())}"
            case "join":
                self.change_channel(arguments[0])
                return f"joined #{arguments[0]}"
            case _:
                return arguments            # the error text

    # -- hosting -------------------------------------------------------------

    def detach(self):
        """Stop speaking for this robot (used by the web server when a
        robot it hosts is destroyed).  The Service leaves the Registrar"""
        if self.chat_server_topic:
            self.remove_message_handler(
                self.server_message_handler, self.chat_server_topic)
        self.remove_message_handler(
            self._world_response_handler, self.world_response_topic)
        # remove_service() decrements the process's Service counter, which
        # is also its id generator: the next Service created would get a
        # topic_path still held by another Actor here, and the two would
        # receive each other's messages.  Keep ids unique (aiko_services
        # process.py: service_count is used for nothing else)
        count = aiko.process.service_count
        aiko.process.remove_service(self.service_id)
        aiko.process.service_count = count


def _pose_words(fields):
    # fields: [command, name, x, y, heading, kind, z]
    try:
        words = (f"x={float(fields[2]):g} y={float(fields[3]):g} "
                 f"heading={float(fields[4]):g}")
        if len(fields) > 6 and float(fields[6]) != 0:
            words += f" z={float(fields[6]):g}"
        return words
    except (IndexError, ValueError):
        return " ".join(str(field) for field in fields[1:])


def robot_tags(robot_name, channel, kind):
    """Aspect tags per ADR-025: one per Interface this robot implements"""
    interfaces = ["Chat", "Robot", *kind_interfaces(kind)]
    return ["ec=true", "type=chat_robot", *aspect_tags(interfaces),
            f"botname=@@{robot_name}", f"channel={channel}", f"kind={kind}",
            f"axes={kind_axes(kind)}",
            f"commands={','.join(kind_commands(kind))}"]


def host_robot(robot_name, kind=DEFAULT_KIND, owner="anonymous",
               channel=config.CHANNEL, world_name=config.WORLD_NAME,
               host="external"):
    """Create the ChatRobotAgent Actor in this process and return it"""
    init_args = aiko.actor_args(
        robot_name, protocol=ROBOT_PROTOCOL,
        tags=robot_tags(robot_name, channel, kind))
    init_args.update({"robot_name": robot_name, "channel": channel,
                      "world_name": world_name, "kind": kind,
                      "owner": owner, "host": host})
    robot = aiko.compose_instance(ChatRobotAgent, init_args)
    robot.attach_known_services()
    return robot


@click.group()
def main():
    """ChatRobotAgent: a virtual robot you drive from the chat"""
    pass


@main.command(name="run")
@click.option("--name", "robot_name", type=str, required=True,
    help="robot name; also its chat mention @@NAME")
@click.option("--kind", type=click.Choice(list(KINDS)),
    default=DEFAULT_KIND, show_default=True)
@click.option("--owner", type=str, default=config.WEB_USERNAME,
    show_default=True)
@click.option("--channel", type=str, default=config.CHANNEL, show_default=True)
@click.option("--world", "world_name", type=str, default=config.WORLD_NAME,
    show_default=True)
def run_command(robot_name, kind, owner, channel, world_name):
    from core import valid_robot_name
    if not valid_robot_name(robot_name):
        raise click.BadParameter(
            "letters, digits, '_' and '-' only (max 64)", param_hint="--name")
    robot = host_robot(robot_name, kind, owner, channel, world_name)
    robot.print(f"running as @@{robot_name} in #{channel}, "
                f"topic_path={robot.topic_path}")
    aiko.process.run()


if __name__ == "__main__":
    main()
