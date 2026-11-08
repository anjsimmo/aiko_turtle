#!/usr/bin/env python3
#
# Phase 4: ChatAgent (LLM-powered; "ChatAgent" disambiguates from chatbots
# and from physical bots) that discovers robots in the chat, their
# capabilities, and how to control them.
#
# Discovery: any Service advertising both <Robot> and <Chat> in its
# "interfaces=..." tag is a controllable robot; its "botname=", "channel="
# and "commands=" tags describe how to talk to it over chat.
#
# LLM backend: OpenAI API (key from $OPENAI_API_KEY or
# /home/anj/src/aiko/open-ai-key.txt), falling back to the local
# "claude" CLI in headless mode (-p) if OpenAI is unavailable.
#
# Usage
# ~~~~~
#   source env.sh
#   ./chat_llm_agent.py run [--botname @@anj_agent] [--channel robots]
#
# Then in chat:  @@anj_agent please draw a square with the turtle robot

import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

import click

import aiko_services as aiko
from aiko_services.main.share import services_cache_create_singleton
import aiko_chat.bot as bot
from interfaces import implements
from aiko_chat.protocol import _decode_message

_BOTNAME = "@@anj_agent"
_CHANNEL = "robots"
_ACK_SUFFIX = " !!!!"
_HISTORY_LIMIT = 20
_KEY_FILE = "/home/anj/src/aiko/open-ai-key.txt"
_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_CLAUDE_COMMAND = ["claude", "-p", "--model", "haiku"]
_LLM_TIMEOUT = 120

_ACTION_PATTERN = re.compile(r"^\((say|command)\s+(.*)\)\s*$")


def _load_openai_key():
    key = os.environ.get("OPENAI_API_KEY")
    if not key and Path(_KEY_FILE).exists():
        for line in Path(_KEY_FILE).read_text().splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key


def _call_llm(prompt, log):
    key = _load_openai_key()
    if key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            response = client.chat.completions.create(
                model=_OPENAI_MODEL, timeout=_LLM_TIMEOUT,
                messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content.strip()
        except Exception as exception:
            log(f"OpenAI failed ({exception}), falling back to claude CLI")
    result = subprocess.run(
        _CLAUDE_COMMAND, input=prompt, capture_output=True, text=True,
        timeout=_LLM_TIMEOUT)
    return result.stdout.strip()


class ChatAgent(bot.ChatBot):
    def __init__(self, context, botname, channel):
        context.call_init(self, "ChatBot", context)
        self.botname = botname
        self.current_channel = channel
        self.share["source_file"] = __file__

        self.history = []           # recent channel messages, oldest first
        self.requests = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    # ----------------------------------------------------------------- #
    # Robot discovery: capabilities from the Registrar's Service tags

    def discover_robots(self):
        services_cache = services_cache_create_singleton(aiko.process)
        robots = []
        for service_details in services_cache.get_services():
            tags = service_details[5]
            if implements(tags, "Robot") and implements(tags, "Chat"):
                details = {"name": service_details[1]}
                for tag in tags:
                    key, _, value = str(tag).partition("=")
                    if key in ("botname", "channel", "commands", "interfaces"):
                        details[key] = value
                robots.append(details)
        return robots

    # ----------------------------------------------------------------- #
    # Chat

    def process_message(self, payload_in, **kwargs):
        fields = _decode_message(payload_in)
        message = fields["message"] if fields else str(payload_in)
        username = fields.get("username", "?") if fields else "?"
        self.history.append(f"{username}: {message}")
        del self.history[:-_HISTORY_LIMIT]

        if self.botname not in message or message.endswith(_ACK_SUFFIX):
            return
        request = message.split(self.botname, 1)[-1].strip()
        self.print(f"Request: {request}")
        self.requests.put(request)

    def _say(self, text):
        if self.chat_server:
            self.chat_server.send_message(
                self.botname, [self.current_channel], text)

    # ----------------------------------------------------------------- #
    # LLM worker (own thread: never block the Aiko event thread)

    def _worker(self):
        while True:
            request = self.requests.get()
            try:
                self._handle_request(request)
            except Exception as exception:
                self.print(f"Worker error: {exception}")
                self._say(f"agent error: {exception}")
            self.requests.task_done()

    def _handle_request(self, request):
        robots = self.discover_robots()
        prompt = self._build_prompt(request, robots)
        self.print(f"Robots discovered: "
                   f"{[robot['name'] for robot in robots]}")
        output = _call_llm(prompt, self.print)
        self.print(f"LLM output:\n{output}")

        executed = False
        for line in output.splitlines():
            match = _ACTION_PATTERN.match(line.strip())
            if not match:
                continue
            action, argument = match.group(1), match.group(2).strip()
            executed = True
            if action == "say":
                self._say(argument)
            elif action == "command":
                self._say(argument)     # e.g "@@anj_turtlebot move 100"
                time.sleep(2.0)         # let the robot act in order
        if not executed:
            self._say(output[:280] if output else "agent: no response")

    def _build_prompt(self, request, robots):
        robot_lines = []
        for robot in robots:
            robot_lines.append(
                f"- name: {robot['name']}, mention: "
                f"{robot.get('botname', '@@' + robot['name'])}, "
                f"chat commands: {robot.get('commands', 'unknown')}, "
                f"interfaces: {robot.get('interfaces', 'unknown')}")
        robots_text = "\n".join(robot_lines) if robot_lines  \
            else "(no robots discovered)"
        history_text = "\n".join(self.history[-_HISTORY_LIMIT:])
        return f"""You are {self.botname}, an agent in the #{self.current_channel} channel of a robot chat system.
You control robots by sending them chat commands that mention their botname.

Discovered robots and their capabilities:
{robots_text}

Robot command semantics: move D moves D units forward (negative = backwards),
turn A turns A degrees counter-clockwise, stop stops, look reports the camera
view (robot pose), telemetry reports battery, interfaces lists interfaces.

Recent channel history (oldest first):
{history_text}

The user asked you: {request}

Reply ONLY with one or more lines, each in exactly one of these forms:
(say TEXT)                        ;; a chat reply to the humans
(command BOTNAME COMMAND ARGS)    ;; one robot chat command, for example:
                                  ;; (command @@anj_turtlebot move 100)
Lines are executed in order. Use several (command ...) lines for multi-step
tasks. Do not output anything else."""


@click.group()
def main():
    """LLM-powered ChatAgent controlling discovered robots"""
    pass


@main.command(name="run")
@click.option("--botname", type=str, default=_BOTNAME)
@click.option("--channel", type=str, default=_CHANNEL)
def run_command(botname, channel):
    tags = ["ec=true", "type=chat_agent",
        "interfaces=Chat,Agent", f"botname={botname}"]
    init_args = aiko.actor_args("anj_agent", tags=tags)
    init_args.update({"botname": botname, "channel": channel})
    agent = aiko.compose_instance(ChatAgent, init_args)
    backend = "OpenAI" if _load_openai_key() else "claude CLI"
    agent.print(f"ChatAgent running as {botname} in #{channel} "
                f"(LLM backend: {backend})")
    aiko.process.run()


if __name__ == "__main__":
    main()
