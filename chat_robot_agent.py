#!/usr/bin/env python3
#
# ChatRobotAgent: an Actor implementing the <Chat> and <Robot> Interfaces
# (<Robot> composed of <Move> and <Telemetry>), per the 2026-08-15 Aiko
# Services Design doc and the 2026-08-22 imagineering plan.
#
# The robot is a hyperspace collection of sources and targets (camera, turn,
# forward + the virtual world "hardware").  The hyperspace entries are not
# running Actors: they are bootstrap definitions, and this agent acts as
# the LifeCycleManager (via an embedded ProcessManager) that lazily starts
# each element Service the first time it is needed.
#
# Chat usage (mention the bot in a channel it has joined):
#   @@anj_turtlebot move 100      ;; <Move>  -> Forward target -> world
#   @@anj_turtlebot turn 90       ;; <Move>  -> Turn target   -> world
#   @@anj_turtlebot stop          ;; <Move>
#   @@anj_turtlebot look          ;; <Perceive> via Camera source
#   @@anj_turtlebot telemetry     ;; <Telemetry>
#   @@anj_turtlebot interfaces    ;; <Robot> get_interfaces
#
# Usage
# ~~~~~
#   source env.sh
#   ./robot_space_setup.py                      # once, creates _robot_space_
#   ./chat_robot_agent.py run [--botname @@anj_turtlebot] [--channel robot]

from pathlib import Path
import shlex

import click

import aiko_services as aiko
from aiko_services.main.hyperspace import (
    HyperSpaceImpl, PROTOCOL as HYPERSPACE_PROTOCOL,
)
from aiko_services.main.process_manager import ProcessManagerImpl
from aiko_services.main.utilities import parse
import aiko_chat.bot as bot
from aiko_chat.protocol import _decode_message

from interfaces import (
    Chat, Move, Robot, Telemetry,
    CHAT_ROBOT_PROTOCOL, interface_names, interfaces_tag,
)

_BOTNAME = "@@anj_turtlebot"
_CHANNEL = "robots"
_SPACE_DIR = "_robot_space_"
_ROBOT_NAME = "anj_turtlebot"
_ACK_SUFFIX = " !!!!"          # loop-prevention convention, see aiko_chat.bot


class ElementProxy(aiko.Actor):
    # Public methods any robot element may expose; used to build the
    # ServiceRemoteProxy (only called methods need to exist remotely)
    def turn(self, angle): pass
    def forward(self, distance): pass
    def snapshot(self, topic_path_response): pass
    def apply_move(self, distance): pass
    def apply_turn(self, angle): pass
    def reset(self): pass


class ChatRobotAgent(bot.ChatBot, Chat, Robot, Move, Telemetry):
    def __init__(self, context, botname, channel, space_dir, robot_name,
                 join_space=True):
        context.call_init(self, "ChatBot", context)
        self.botname = botname
        self.current_channel = channel
        self.robot_name = robot_name
        self.space_dir = space_dir
        self.share["source_file"] = __file__

        # LifeCycleManager for the robot's hyperspace elements
        self.process_manager = aiko.compose_instance(
            ProcessManagerImpl,
            aiko.actor_args(f"{robot_name}_lcm", tags=["ec=true"]))

        self.elements = {}
        self._load_robot_space(Path(space_dir) / robot_name)

        # <Perceive> responses from the Camera source arrive here
        self.camera_response_topic = f"{self.topic_path}/camera_response"
        self.add_message_handler(
            self._camera_response_handler, self.camera_response_topic)

        if join_space:
            self._join_robot_collection()

    # ----------------------------------------------------------------- #
    # Phase 2: add this robot to the "robots" collection of the running
    # HyperSpace (named after the local hostname, see "aiko_hyperspace run").
    # The entry is a Dependency: WHAT to discover (ServiceFilter including
    # the implemented interfaces), WHO manages its lifecycle (our
    # ProcessManager) and WHERE its definition is stored (the robot space)

    def _join_robot_collection(self):
        service_filter = aiko.ServiceFilter(
            "*", self.robot_name, CHAT_ROBOT_PROTOCOL, "*", "*",
            [interfaces_tag(self)])
        lifecycle_manager_url = self.process_manager.topic_path
        storage_url = f"file://{Path(self.space_dir).resolve()}"

        def join(hyperspace):
            self.print(f"Joining HyperSpace collection robots/"
                       f"{self.robot_name}")
            hyperspace.create("robots")
            hyperspace.add(f"robots/{self.robot_name}",
                service_filter, lifecycle_manager_url, storage_url)

        aiko.do_command(HyperSpaceImpl,
            aiko.ServiceFilter(name=None, protocol=HYPERSPACE_PROTOCOL),
            join)

    # ----------------------------------------------------------------- #
    # Robot hyperspace definition: entries bootstrap the element Services

    def _load_robot_space(self, robot_space_path):
        if not robot_space_path.is_dir():
            raise SystemExit(
                f"Robot space {robot_space_path} not found: "
                "run ./robot_space_setup.py first")
        for entry_path in sorted(robot_space_path.iterdir()):
            if entry_path.name.startswith("."):
                continue
            try:
                command, fields = parse(entry_path.read_text().strip())
            except Exception:
                command, fields = None, None
            if command != "bootstrap" or not isinstance(fields, dict):
                self.print(f"Ignoring entry without bootstrap: {entry_path}")
                continue
            element = {"bootstrap": fields, "service": None,
                       "spawned": False, "pending": []}
            self.elements[entry_path.name] = element
            aiko.do_discovery(
                ElementProxy,
                aiko.ServiceFilter(
                    "*", fields["name"], "*", "*", "*", "*"),
                lambda details, service, name=entry_path.name:
                    self._element_add_handler(name, details, service),
                lambda details, name=entry_path.name:
                    self._element_remove_handler(name, details))
            self.print(f"Element defined: {entry_path.name} "
                       f"-> {fields['name']} (not started)")

    def _element_add_handler(self, name, service_details, service):
        self.print(f"Element connected:    {name}: {service_details[0]}")
        element = self.elements[name]
        element["service"] = service
        pending, element["pending"] = element["pending"], []
        for action in pending:
            action(service)

    def _element_remove_handler(self, name, service_details):
        self.print(f"Element disconnected: {name}")
        self.elements[name]["service"] = None
        self.elements[name]["spawned"] = False

    def _request_spawn(self, name):
        # Lazily bootstrap the element Service via the LifeCycleManager.
        # Non-blocking: discovery events arrive on this same event thread,
        # so we must never wait here (see _element_add_handler)
        element = self.elements.get(name)
        if element and not element["service"] and not element["spawned"]:
            command_line = shlex.split(element["bootstrap"]["command"])
            self.print(f"Lazily starting element: {name}: {command_line}")
            self.process_manager.create(
                command_line[0], command_line[1:], uid=name)
            element["spawned"] = True

    def _with_element(self, name, action):
        # Run action(service) now, or queue it until the element connects
        element = self.elements.get(name)
        if not element:
            return f"unknown element {name}"
        if element["service"]:
            action(element["service"])
            return "done"
        self._request_spawn(name)
        element["pending"].append(action)
        return f"queued, lazily starting {name}"

    # ----------------------------------------------------------------- #
    # <Move> ... motor Targets (Aiko Pipelines "Target" concept: robot components
    # wrapped so they can also be driven as pipeline targets; calling the
    # interface directly, as here, is equally valid)

    def move(self, distance):
        self._request_spawn("world")
        status = self._with_element(
            "forward", lambda target: target.forward(distance))
        return f"move {distance}: {status}"

    def turn(self, angle):
        self._request_spawn("world")
        status = self._with_element("turn", lambda target: target.turn(angle))
        return f"turn {angle}: {status}"

    def stop(self):
        return "stopped (virtual robot is never really moving)"

    # ----------------------------------------------------------------- #
    # <Perceive> ... camera source

    def look(self):
        self._request_spawn("world")
        status = self._with_element(
            "camera",
            lambda camera: camera.snapshot(self.camera_response_topic))
        return f"look: {status}"

    def _camera_response_handler(self, _aiko, topic, payload_in):
        try:
            command, parameters = parse(payload_in)
        except Exception:
            return
        if command == "response":
            frame = " ".join(str(parameter) for parameter in parameters)
            self.send_message(
                self.botname, [self.current_channel],
                f"camera: {frame}{_ACK_SUFFIX}")

    # ----------------------------------------------------------------- #
    # <Telemetry>

    def get_telemetry(self, topic_path_response=None):
        telemetry = "(battery 87) (temperature 21.5)"
        if topic_path_response:
            aiko.process.message.publish(
                topic_path_response, "(item_count 1)")
            aiko.process.message.publish(
                topic_path_response, f"(response {telemetry})")
        return telemetry

    # ----------------------------------------------------------------- #
    # <Robot>

    def get_interfaces(self, topic_path_response=None):
        names = interface_names(self)
        if topic_path_response:
            aiko.process.message.publish(
                topic_path_response, f"(item_count {len(names)})")
            for name in names:
                aiko.process.message.publish(
                    topic_path_response, f"(response {name})")
        return names

    # ----------------------------------------------------------------- #
    # <Chat>

    def send_message(self, username, recipients, message):
        if self.chat_server:
            self.chat_server.send_message(username, recipients, message)

    def receive_message(self, username, channel, message):
        # Direct delivery (remote function call), no @@mention required
        self.print(f"receive_message: {username} #{channel}: {message}")
        reply = self._run_command(message.strip())
        self.send_message(
            self.botname, [channel or self.current_channel],
            f"{self.botname[2:]}: {reply}{_ACK_SUFFIX}")

    def process_message(self, payload_in, **kwargs):
        # Channel traffic (via ChatServer): only execute direct commands,
        # i.e messages STARTING with our mention ("@@bot move 100"), so
        # prose that merely mentions the robot is not misread as a command
        fields = _decode_message(payload_in)
        message = fields["message"] if fields else str(payload_in)
        message = message.strip()
        if not message.startswith(self.botname) or  \
            message.endswith(_ACK_SUFFIX):
            return
        chat_command = message[len(self.botname):].strip()
        self.print(f"Chat command: {chat_command}")
        reply = self._run_command(chat_command)
        self.send_message(
            self.botname, [self.current_channel],
            f"{self.botname[2:]}: {reply}{_ACK_SUFFIX}")

    # ----------------------------------------------------------------- #

    def _run_command(self, chat_command):
        parts = chat_command.split()
        match parts:
            case ["move", distance]:
                return self.move(distance)
            case ["turn", angle]:
                return self.turn(angle)
            case ["stop"]:
                return self.stop()
            case ["reset"] | ["home"]:
                status = self._with_element(
                    "world", lambda world: world.reset())
                return f"reset to origin: {status}"
            case ["look"]:
                return self.look()
            case ["telemetry"] | ["battery"]:
                return f"telemetry: {self.get_telemetry()}"
            case ["interfaces"]:
                return f"interfaces: {','.join(self.get_interfaces())}"
            case ["join", channel]:
                self.change_channel(channel)
                return f"joined #{channel}"
            case _:
                return (f"unknown command \"{chat_command}\": try move D, "
                        "turn A, stop, reset, look, telemetry, interfaces, "
                        "join C")


@click.group()
def main():
    """ChatRobotAgent: <Chat> + <Robot> virtual TurtleBot"""
    pass


@main.command(name="run")
@click.option("--botname", type=str, default=_BOTNAME)
@click.option("--channel", type=str, default=_CHANNEL)
@click.option("--space-dir", type=str, default=_SPACE_DIR)
@click.option("--robot", "robot_name", type=str, default=_ROBOT_NAME)
@click.option("--join-space/--no-join-space", default=True)
def run_command(botname, channel, space_dir, robot_name, join_space):
    tags = ["ec=true", "type=chat_robot",
        interfaces_tag(ChatRobotAgent),
        f"botname={botname}", f"channel={channel}",
        "commands=move,turn,stop,reset,look,telemetry,interfaces,join"]
    init_args = aiko.actor_args(
        robot_name, protocol=CHAT_ROBOT_PROTOCOL, tags=tags)
    init_args.update({
        "botname": botname, "channel": channel,
        "space_dir": space_dir, "robot_name": robot_name,
        "join_space": join_space})
    agent = aiko.compose_instance(ChatRobotAgent, init_args)
    agent.print(f"ChatRobotAgent {robot_name} running as {botname} "
                f"in #{channel}, topic_path={agent.topic_path}")
    agent.print(f"Interfaces: {','.join(interface_names(agent))}")
    aiko.process.run()


if __name__ == "__main__":
    main()
