#!/usr/bin/env python3
#
# ChatBot that bridges Aiko Chat to the virtual TurtleRobot.
# Mention the bot in a chat message to drive the robot, e.g
#   @@anj_turtlebot forward 100
#   @@anj_turtlebot left 90
#   @@anj_turtlebot penup            ;; bare words become (action word)
#
# Usage
# ~~~~~
#   source env.sh
#   ./robot_chatbot.py run [--botname @@anj_turtlebot] [--robot anj_turtle_robot]

import click

import aiko_services as aiko
import aiko_chat.bot as bot
from aiko_chat.protocol import _decode_message

from turtle_robot import TurtleRobot, get_robot_service_filter

_BOTNAME = "@@anj_turtlebot"
_ACK_SUFFIX = " !!!!"  # same loop-prevention convention as SampleChatBot


class RobotChatBot(bot.ChatBot):
    def __init__(self, context, botname, robot_name):
        context.call_init(self, "ChatBot", context)
        self.botname = botname
        self.robot_name = robot_name
        self.robot_server = None

        self.print(f"Searching for robot {robot_name}")
        aiko.do_discovery(
            TurtleRobot, get_robot_service_filter(robot_name),
            self.discovery_add_robot_handler,
            self.discovery_remove_robot_handler)

    def discovery_add_robot_handler(self, service_details, service):
        self.print(f"Robot connected    {service_details[1]}: {service_details[0]}")
        self.robot_server = service

    def discovery_remove_robot_handler(self, service_details):
        self.print(f"Robot disconnected {service_details[1]}: {service_details[0]}")
        self.robot_server = None

    def process_message(self, payload_in, **kwargs):
        fields = _decode_message(payload_in)
        message = fields["message"] if fields else str(payload_in)
        if self.botname not in message or message.endswith(_ACK_SUFFIX):
            return
        command = message.split(self.botname)[-1].strip()
        self.print(f"Command: {command}")
        reply = self._run_command(command)
        if self.chat_server:
            self.chat_server.send_message(
                self.botname, [self.current_channel], f"{reply}{_ACK_SUFFIX}")

    def _run_command(self, command):
        if not self.robot_server:
            return f"{self.botname[2:]}: robot {self.robot_name} not connected"
        parts = command.split()
        match parts:
            case ["action", value]:
                self.robot_server.action(value)
            case ["forward", value]:
                self.robot_server.forward(value)
            case ["backward", value]:
                self.robot_server.backward(value)
            case ["left", value]:
                self.robot_server.left(value)
            case ["right", value]:
                self.robot_server.right(value)
            case _:
                self.robot_server.action(" ".join(parts))
        return f"{self.botname[2:]}: sent \"{command}\" to {self.robot_name}"


@click.group()
def main():
    """Run the robot ChatBot"""
    pass


@main.command(name="run")
@click.option("--botname", type=str, default=_BOTNAME)
@click.option("--robot", "robot_name", type=str, default="anj_turtle_robot")
def run_command(botname, robot_name):
    tags = ["ec=true"]
    init_args = aiko.actor_args(
        "anj_turtle_agent", protocol=bot._PROTOCOL_BOT, tags=tags)
    init_args["botname"] = botname
    init_args["robot_name"] = robot_name
    chatbot = aiko.compose_instance(RobotChatBot, init_args)
    chatbot.print("Type Ctrl+C to exit")
    aiko.process.run()


if __name__ == "__main__":
    main()
