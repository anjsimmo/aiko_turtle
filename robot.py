#!/usr/bin/env python3
#
# ChatRobotAgent: one robot in the sandbox, as an Aiko Actor.  It speaks
# ONE interface (robots/NAME.py: the functions on its "in" topic, exactly
# as the real robot of that interface accepts them) plus <Chat>, so the
# same robot answers a remote function call, a chat command and the REST
# API.  Its body lives in the VirtualWorld.
#
# Two kinds of robot Actor are built here, one class per interface:
#
#   virtual  the Simulated implementation of the interface: a call acts on
#            the body in the world            (host "web" or "external")
#   replica     the replica of a REAL robot found in the Registrar: a call is
#            forwarded to the real Actor, and what the real one sends and
#            receives moves the replica by dead reckoning   (host "replica")
#
# Anyone can run a virtual one, from anywhere, against the shared services:
#
#   source env.sh
#   ./robot.py run --name my_turtle [--kind turtle] [--interface proposed]
#
# then, in the channel:  @@my_turtle move 100
#
# The web server (web.py) hosts one for every robot created over REST and
# a replica for every real robot it discovers, with host_robot() and
# host_replica().
#
# Chat: a message STARTING with "@@name" is a command for that robot, in
# the words of its interface ("help" lists them).  Every robot also takes
# the sandbox's own words: help, place X Y [H] (put it somewhere), join
# CHANNEL.

import time

import click

import aiko_services as aiko
from aiko_services.main.discovery import get_service_proxy
from aiko_services.main.share import services_cache_create_singleton
from aiko_services.main.utilities import generate, parse
from aiko_chat import ChatServer, get_server_service_filter
import aiko_chat.bot as bot
from aiko_chat.protocol import _decode_message

import config
import robots as registry
from robots import base
from interfaces import Chat, Robot
from virtual_world import VirtualWorld

ROBOT_PROTOCOL = "ai.hashtag.ai/chat_robot:0"   # virtual robots with no protocol of their own
REPLICA_PROTOCOL = "ai.hashtag.ai/replica:0"
ACK_SUFFIX = " !!!!"            # loop-prevention convention, see aiko_chat.bot
SANDBOX_TAG = "sandbox"         # sandbox=virtual | sandbox=replica: ours, in the Registrar
RELAY_SECONDS = 15.0            # a replica relays the real robot's "out" this long after a command
GENERIC = ("help", "interfaces", "commands", "join", "place", "teleport",
           "reset", "home")


class ChatRobotBase(bot.ChatBot, Chat, Robot):
    """What every robot Actor here has: the chat, the world, the body"""

    def __init__(self, context, robot_name, channel=config.CHANNEL,
                 world_name=config.WORLD_NAME, kind=registry.DEFAULT_KIND,
                 interface=None, owner="anonymous", host="external",
                 source=""):
        context.call_init(self, "ChatBot", context)
        self.robot_name = robot_name
        self.botname = f"@@{robot_name}"
        self.current_channel = channel
        self.kind, self.interface = registry.resolve(kind, interface)
        self.module = registry.INTERFACES[self.interface]
        self.owner = owner
        self.host = host
        self.source = source
        self.body = base.Body(self)
        self.apply_op = self.body.apply
        self.last_pose = None
        self.current_username = "anonymous"
        self.telemetry_timer = None
        self.share["source_file"] = __file__
        self.share["interface"] = self.interface
        self.world = None
        self.world_topic = None
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
                                self.host, self.world_response_topic,
                                0.0, 0.0, 0.0, self.interface, self.source or "")

    def _world_remove_handler(self, service_details):
        if service_details[0] != self.world_topic:
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
            self._say("error: " + " ".join(str(field) for field in fields[1:]))
            return
        pose = _pose(fields)
        if pose:
            self.last_pose = pose
        if fields[0] == "create":
            self._say(f"ready at {_pose_words(fields)}")
        elif fields[0] in ("pose", "host"):
            self._say(f"at {_pose_words(fields)}")
        elif fields[0] == "drive" and pose and pose.get("moving"):
            self._say(f"moving from {_pose_words(fields)}")
        else:
            self._say(f"{fields[0]}: now at {_pose_words(fields)}")

    def _world_call(self, method, arguments, with_username=True):
        """A remote function of the world, replying to our topic"""
        if not self.world:
            return "world not connected, try again shortly"
        arguments = [_wire(argument) for argument in arguments]
        if with_username:
            arguments.append(self.current_username)
        getattr(self.world, method)(self.robot_name, *arguments,
                                    self.world_response_topic)
        return None             # the world's response is relayed to the chat

    # -- for the Simulated implementations -----------------------------------

    def respond(self, topic_path_response, *fields):
        """A query's reply: (item_count 1) then (response FIELDS) on the
        caller's topic, if given; the text for the chat either way"""
        fields = [str(field) for field in fields]
        if topic_path_response and topic_path_response != "-":
            aiko.process.message.publish(topic_path_response, "(item_count 1)")
            aiko.process.message.publish(
                topic_path_response, generate("response", fields))
        return " ".join(fields)

    def publish_out(self, payload):
        aiko.process.message.publish(f"{self.topic_path}/out", payload)

    def set_telemetry_period(self, period):
        if self.telemetry_timer:
            aiko.event.remove_timer_handler(self.telemetry_timer)
            self.telemetry_timer = None
        if period and period > 0 and hasattr(self, "telemetry_tick"):
            self.telemetry_timer = self.telemetry_tick
            aiko.event.add_timer_handler(self.telemetry_tick, period)

    def stop(self):
        """Service.stop() terminates the whole process: never that over
        the wire.  An interface with its own stop overrides this"""
        return "stop is not one of this robot's commands"

    def terminate(self, botname="all"):
        """ChatBot.terminate() ends the process: fine for a robot run in
        its own process, never for one hosted by the web server"""
        if self.host == "external":
            return super().terminate(botname)
        return "terminate is not one of this robot's commands"

    # -- <Robot> -------------------------------------------------------------

    def get_interfaces(self, topic_path_response=None):
        names = ["Chat", "Robot", self.interface]
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

    def help_text(self):
        module = self.module
        examples = ", ".join(example for example, _ in registry.commands(
            self.interface, self.kind))
        return (f"a {self.kind} speaking {self.interface} ({module.STATUS}): "
                f"{examples or 'no commands'}; also help, place X Y [H], "
                f"join CHANNEL")

    def run_command(self, chat_command, username="anonymous"):
        """Returns the immediate reply, or None when the world will reply"""
        self.current_username = username
        method, arguments = self.module.parse_command(chat_command)
        if method is None:
            if self._generic_matches(chat_command):
                return self._generic(chat_command)   # None: the world replies
            return f"{arguments}; also: help, place X Y [H], join CHANNEL"
        if not registry.supports(self.interface, self.kind, method):
            return (f"a {self.kind} cannot {method}: its commands are "
                    f"{', '.join(registry.method_names(self.interface, self.kind))}")
        try:
            result = getattr(self, method)(*arguments)
        except (TypeError, ValueError) as error:
            return f"{method}: {error}"
        except NotImplementedError as error:
            return str(error)
        return result if isinstance(result, str) or result is None else str(result)

    def _generic(self, chat_command):
        """The sandbox's own words, the same for every interface"""
        parts = chat_command.split()
        match parts:
            case ["help"] | ["interfaces"] | ["commands"]:
                return self.help_text()
            case ["join", channel]:
                self.change_channel(channel)
                return f"joined #{channel}"
            case ["place" | "teleport" | "reset" | "home"]:
                return self.body.place(0.0, 0.0, 0.0)
            case ["place" | "teleport" | "reset" | "home", x, y]:
                return self._place(x, y, 0.0)
            case ["place" | "teleport" | "reset" | "home", x, y, heading]:
                return self._place(x, y, heading)
        return None

    def _place(self, x, y, heading):
        try:
            return self.body.place(base.number(x, "x"), base.number(y, "y"),
                                   base.number(heading, "heading"))
        except ValueError as error:
            return str(error)

    def command(self, chat_command, username="anonymous",
                topic_path_response=None):
        """Any chat command, as a remote function call with the reply on
        topic_path_response: (response ok TEXT) or (response error TEXT).
        The web server's POST /api/robots/NAME/command uses this"""
        method, arguments = self.module.parse_command(chat_command)
        if method is None and self._generic_matches(chat_command):
            method = "generic"
        if method is None:
            status, reply = "error", arguments
        elif method != "generic" and not registry.supports(
                self.interface, self.kind, method):
            status, reply = "error", self.run_command(chat_command, username)
        else:
            status = "ok"
            reply = self.run_command(chat_command, username)  \
                or "sent, the world replies in the chat"
        self.print(f"{username} (direct): {chat_command} -> {reply}")
        if topic_path_response:
            aiko.process.message.publish(topic_path_response, "(item_count 1)")
            aiko.process.message.publish(
                topic_path_response, generate("response", [status, reply]))
        return reply

    @staticmethod
    def _generic_matches(chat_command):
        return (chat_command.split() or [""])[0] in GENERIC

    # -- hosting -------------------------------------------------------------

    def detach(self):
        """Stop speaking for this robot (used by the web server when a
        robot it hosts is destroyed).  The Service leaves the Registrar"""
        self.set_telemetry_period(0)
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


class ReplicaMixin:
    """The replica of a real robot: every interface function is forwarded
    to the real Actor's "in" topic, and what the real one sends and
    receives moves the replica by dead reckoning (the module's observe())"""

    def replica_attach(self):
        self.replica_state = {}
        self.last_command_at = 0.0
        self.real = get_service_proxy(f"{self.source}/in", self.module.Interface)
        self.replica_response_topic = f"{self.topic_path}/replica_response"
        self.add_message_handler(self._real_in_handler, f"{self.source}/in")
        self.add_message_handler(self._real_out_handler, f"{self.source}/out")
        self.add_message_handler(self._replica_response_handler, self.replica_response_topic)

    def replica_detach(self):
        self.remove_message_handler(self._real_in_handler, f"{self.source}/in")
        self.remove_message_handler(self._real_out_handler, f"{self.source}/out")
        self.remove_message_handler(self._replica_response_handler, self.replica_response_topic)

    def _observe(self, direction, payload_in):
        try:
            command, arguments = parse(payload_in)
        except Exception:
            return
        for op in registry.observe(self.interface, direction, command,
                                   arguments, self.replica_state):
            self.body.apply(op)

    def _real_in_handler(self, _aiko, topic, payload_in):
        self._observe("in", payload_in)

    def _real_out_handler(self, _aiko, topic, payload_in):
        self._observe("out", payload_in)
        if time.time() - self.last_command_at < RELAY_SECONDS:
            self._say(f"(out) {payload_in}")

    def _replica_response_handler(self, _aiko, topic, payload_in):
        try:
            command, fields = parse(payload_in)
        except Exception:
            return
        if command == "response":
            self._say("(response) " + " ".join(str(field) for field in fields))

    def forward_call(self, method, arguments, takes_response):
        self.last_command_at = time.time()
        arguments = [_wire(argument) for argument in arguments]
        if takes_response:
            arguments.append(self.replica_response_topic)
        getattr(self.real, method)(*arguments)
        return f"sent ({' '.join([method, *arguments])}) to {self.source}/in"


def _forwarder(method, takes_response):
    def forward(self, *arguments):
        return self.forward_call(method, arguments, takes_response)
    forward.__name__ = method
    return forward


_CLASSES = {}


def actor_class(interface, replica=False):
    """The Actor class for one interface: virtual (Simulated) or replica"""
    key = (interface, replica)
    if key not in _CLASSES:
        module = registry.INTERFACES[interface]
        if replica:
            methods = {spec["name"]: _forwarder(
                spec["name"], "topic_path_response" in spec["signature"])
                for spec in base.method_specs(module.Interface)}
            bases = (ReplicaMixin, ChatRobotBase, module.Interface)
            name = f"Replica_{interface}"
        else:
            # Simulated first: Service.stop() would terminate the process
            methods, bases, name = {}, (module.Simulated, ChatRobotBase,
                                        module.Interface), f"Robot_{interface}"
        methods["__module__"] = __name__
        _CLASSES[key] = type(name, bases, methods)
    return _CLASSES[key]


def _wire(argument):
    """Arguments as the wire takes them: a list becomes (a b c)"""
    if isinstance(argument, (list, tuple)):
        return "(" + " ".join(str(part) for part in argument) + ")"
    return argument


def _pose(fields):
    # fields: [command, name, x, y, heading, kind, z, host, owner, interface, source, pen, moving]
    try:
        pose = {"x": float(fields[2]), "y": float(fields[3]),
                "heading": float(fields[4]),
                "z": float(fields[6]) if len(fields) > 6 else 0.0}
    except (IndexError, ValueError):
        return None
    pose["moving"] = len(fields) > 12 and fields[12] == "moving"
    return pose


def _pose_words(fields):
    pose = _pose(fields)
    if not pose:
        return " ".join(str(field) for field in fields[1:])
    words = f"x={pose['x']:g} y={pose['y']:g} heading={pose['heading']:g}"
    if pose["z"]:
        words += f" z={pose['z']:g}"
    return words


def robot_tags(robot_name, channel, kind, interface, world_name=config.WORLD_NAME,
               replica_of=None):
    """Registrar tags: one aspect tag per Interface where the interface
    has aspects (ADR-025), plus what the chat and the agent need.  Tag
    values hold no spaces, one property per tag"""
    tags = ["ec=true", f"{SANDBOX_TAG}={'replica' if replica_of else 'virtual'}",
            "type=chat_robot", "chat=0", "robot=0", f"interface={interface}",
            f"botname=@@{robot_name}", f"channel={channel}", f"kind={kind}",
            f"world={world_name}",
            f"commands={','.join(registry.method_names(interface, kind))}"]
    tags += registry.tags(interface, kind)
    if replica_of:
        tags.append(f"replica_of={replica_of}")
    return tags


def host_robot(robot_name, kind=registry.DEFAULT_KIND, owner="anonymous",
               channel=config.CHANNEL, world_name=config.WORLD_NAME,
               host="external", interface=None):
    """Create a virtual robot's Actor in this process and return it"""
    kind, interface = registry.resolve(kind, interface)
    module = registry.INTERFACES[interface]
    init_args = aiko.actor_args(
        robot_name, protocol=module.PROTOCOL or ROBOT_PROTOCOL,
        tags=robot_tags(robot_name, channel, kind, interface, world_name))
    init_args.update({"robot_name": robot_name, "channel": channel,
                      "world_name": world_name, "kind": kind,
                      "interface": interface, "owner": owner, "host": host})
    robot = aiko.compose_instance(actor_class(interface), init_args)
    robot.attach_known_services()
    return robot


def host_replica(robot_name, interface, source, kind=None, owner="anonymous",
              channel=config.CHANNEL, world_name=config.WORLD_NAME):
    """Create the replica of the real robot at topic path "source" """
    kind = kind or registry.replica_kind(interface)
    kind, interface = registry.resolve(kind, interface)
    init_args = aiko.actor_args(
        f"replica_{robot_name}", protocol=REPLICA_PROTOCOL,
        tags=robot_tags(robot_name, channel, kind, interface, world_name,
                        replica_of=source))
    init_args.update({"robot_name": robot_name, "channel": channel,
                      "world_name": world_name, "kind": kind,
                      "interface": interface, "owner": owner, "host": "replica",
                      "source": source})
    replica = aiko.compose_instance(actor_class(interface, replica=True), init_args)
    replica.replica_attach()
    replica.attach_known_services()
    return replica


@click.group()
def main():
    """ChatRobotAgent: a virtual robot you drive from the chat"""
    pass


@main.command(name="run")
@click.option("--name", "robot_name", type=str, required=True,
    help="robot name; also its chat mention @@NAME")
@click.option("--kind", type=click.Choice(list(registry.KINDS)),
    default=registry.DEFAULT_KIND, show_default=True)
@click.option("--interface", type=click.Choice(list(registry.INTERFACES)),
    default=None, help="what it speaks (default: the kind's own)")
@click.option("--owner", type=str, default=config.WEB_USERNAME,
    show_default=True)
@click.option("--channel", type=str, default=config.CHANNEL, show_default=True)
@click.option("--world", "world_name", type=str, default=config.WORLD_NAME,
    show_default=True)
def run_command(robot_name, kind, interface, owner, channel, world_name):
    from core import valid_robot_name
    if not valid_robot_name(robot_name):
        raise click.BadParameter(
            "letters, digits, '_' and '-' only (max 64)", param_hint="--name")
    try:
        robot = host_robot(robot_name, kind, owner, channel, world_name,
                           interface=interface)
    except ValueError as error:
        raise click.BadParameter(str(error), param_hint="--interface")
    robot.print(f"running as @@{robot_name} ({robot.kind}, {robot.interface}) "
                f"in #{channel}, topic_path={robot.topic_path}")
    aiko.process.run()


if __name__ == "__main__":
    main()
