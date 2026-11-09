#!/usr/bin/env python3
#
# ChatAgent: an LLM-powered agent in the chat that discovers the robots
# (Services advertising the <Robot> and <Chat> aspects in their tags),
# their commands, and drives them in natural language:
#
#   @@pilot draw a square with my_turtle
#
# LLM backend: OpenAI (OPENAI_API_KEY) falling back to the local "claude"
# CLI in headless mode.  Rate limited per user and overall, with a bounded
# queue, so a busy or looping channel cannot run up a bill.
#
# Usage
# ~~~~~
#   source env.sh
#   ./agent.py run [--botname @@pilot] [--channel robots]

import queue
import subprocess
import threading
import time

import click

import aiko_services as aiko
from aiko_services.main.share import services_cache_create_singleton
import aiko_chat.bot as bot
from aiko_chat.protocol import _decode_message

import config
import robots as registry
from core import RateLimiter, parse_actions
from interfaces import implements

ACK_SUFFIX = " !!!!"
_HISTORY_LIMIT = 20
_CLAUDE_COMMAND = ["claude", "-p", "--model", "haiku"]
_LLM_TIMEOUT = 120


def call_llm(prompt, log):
    if config.OPENAI_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=config.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=config.OPENAI_MODEL, timeout=_LLM_TIMEOUT,
                messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content.strip()
        except Exception as exception:
            log(f"OpenAI failed ({exception}), falling back to claude CLI")
    try:
        result = subprocess.run(
            _CLAUDE_COMMAND, input=prompt, capture_output=True, text=True,
            timeout=_LLM_TIMEOUT)
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exception:
        log(f"claude CLI failed: {exception}")
        return ""


class ChatAgent(bot.ChatBot):
    def __init__(self, context, botname, channel):
        context.call_init(self, "ChatBot", context)
        self.botname = botname
        self.current_channel = channel
        self.share["source_file"] = __file__
        self.history = []           # recent channel messages, oldest first
        self.requests = queue.Queue(maxsize=config.LLM_QUEUE_LIMIT)
        self.limiter = RateLimiter(
            config.LLM_RATE_PER_MINUTE, config.LLM_RATE_PER_USER_PER_MINUTE)
        self.share["requests"] = 0
        self.share["rejected"] = 0
        threading.Thread(target=self._worker, daemon=True).start()

    def print(self, output):
        print(f"AGENT: {output}", flush=True)

    # -- robot discovery: capabilities from the Registrar's Service tags ---

    def discover_robots(self):
        services_cache = services_cache_create_singleton(aiko.process)
        robots = []
        for service_details in services_cache.get_services():
            tags = service_details[5]
            if implements(tags, "Robot") and implements(tags, "Chat"):
                details = {"name": service_details[1]}
                for tag in tags:
                    key, _, value = str(tag).partition("=")
                    if key in ("botname", "channel", "commands", "kind",
                               "interface", "sandbox"):
                        details[key] = value
                robots.append(details)
        return robots

    # -- chat ----------------------------------------------------------------

    def process_message(self, payload_in, **kwargs):
        fields = _decode_message(payload_in)
        message = fields["message"] if fields else str(payload_in)
        username = str(fields.get("username", "anonymous")) if fields  \
            else "anonymous"
        self.history.append(f"{username}: {message}")
        del self.history[:-_HISTORY_LIMIT]

        if self.botname not in message or message.endswith(ACK_SUFFIX):
            return
        if username.startswith("@@"):
            return                  # never take requests from other bots
        request = message.split(self.botname, 1)[-1].strip()
        if not self.limiter.allow(username):
            self.share["rejected"] = self.share["rejected"] + 1
            self._say(f"{username}: rate limit, try again in a minute")
            return
        try:
            self.requests.put_nowait((username, request))
            self.share["requests"] = self.share["requests"] + 1
            self.print(f"{username}: {request}")
        except queue.Full:
            self._say(f"{username}: busy, try again shortly")

    def _say(self, text):
        if self.chat_server:
            self.chat_server.send_message(
                self.botname, [self.current_channel], text + ACK_SUFFIX)

    def _command(self, text):
        # A robot command is sent as-is: the robot only acts on messages
        # that start with its mention, so the ack suffix must not be there
        if self.chat_server:
            self.chat_server.send_message(
                self.botname, [self.current_channel], text)

    # -- LLM worker (own thread: never block the Aiko event thread) --------

    def _worker(self):
        while True:
            username, request = self.requests.get()
            try:
                self._handle_request(username, request)
            except Exception as exception:
                self.print(f"worker error: {exception}")
                self._say(f"agent error: {exception}")
            self.requests.task_done()

    def _handle_request(self, username, request):
        robots = self.discover_robots()
        self.print(f"robots: {[robot['name'] for robot in robots]}")
        output = call_llm(self._build_prompt(username, request, robots),
                          self.print)
        self.print(f"LLM output:\n{output}")
        actions = parse_actions(output)
        for action, argument in actions:
            if action == "say":
                self._say(argument)
            elif action == "command":
                self._command(argument)     # e.g "@@my_turtle move 100"
                time.sleep(1.0)             # let the robot act in order
        if not actions:
            self._say(output[:280] if output else "agent: no response")

    def _build_prompt(self, username, request, robots):
        robot_lines, interfaces = [], {}
        for robot in robots:
            interface = robot.get("interface", "")
            robot_lines.append(
                f"- {robot.get('botname', '@@' + robot['name'])}"
                f" (kind {robot.get('kind', '?')}, interface {interface or '?'},"
                f"{' a TWIN of a real robot,' if robot.get('sandbox') == 'twin' else ''}"
                f" functions: {robot.get('commands', 'unknown')})")
            if interface in registry.INTERFACES and interface not in interfaces:
                module = registry.INTERFACES[interface]
                examples = "; ".join(f"{example}: {help_text}" for example, help_text
                                     in registry.commands(interface, robot.get("kind")))
                interfaces[interface] = (f"- {interface} ({module.STATUS}; "
                                         f"{module.UNITS}): {examples}")
        robots_text = "\n".join(robot_lines) or "(no robots discovered)"
        interfaces_text = "\n".join(interfaces.values()) or "(none)"
        history_text = "\n".join(self.history[-_HISTORY_LIMIT:])
        return f"""You are {self.botname}, an agent in the #{self.current_channel} channel of a robot chat system.
You control robots by sending them chat commands that start with their mention.
Each robot speaks ONE interface, in its own words and units; use only the
commands of that interface, exactly as the examples show.

Discovered robots:
{robots_text}

The interfaces, with example commands and what they mean:
{interfaces_text}

Every robot also takes: help, place X Y [H] (teleport, sandbox only).
A twin forwards your command to a real robot: be careful and brief.

Recent channel history (oldest first):
{history_text}

{username} asked you: {request}

Reply ONLY with one or more lines, each in exactly one of these forms:
(say TEXT)                        ;; a chat reply to the humans
(command @@ROBOT COMMAND ARGS)    ;; one robot chat command, for example:
                                  ;; (command @@my_turtle move 100)
Lines are executed in order. Use several (command ...) lines for multi-step
tasks. If the user names no robot and there is exactly one, use it; if there
are several, ask which. Do not output anything else."""


@click.group()
def main():
    """LLM-powered ChatAgent that drives the discovered robots"""
    pass


@main.command(name="run")
@click.option("--botname", type=str, default=config.AGENT_BOTNAME,
    show_default=True)
@click.option("--channel", type=str, default=config.CHANNEL, show_default=True)
def run_command(botname, channel):
    tags = ["ec=true", "type=chat_agent", "chat=0", "agent=0",
            f"botname={botname}", f"channel={channel}"]
    init_args = aiko.actor_args(botname.lstrip("@"), tags=tags)
    init_args.update({"botname": botname, "channel": channel})
    agent = aiko.compose_instance(ChatAgent, init_args)
    backend = "OpenAI" if config.OPENAI_API_KEY else "claude CLI"
    agent.print(f"running as {botname} in #{channel} (LLM: {backend})")
    aiko.process.run()


if __name__ == "__main__":
    main()
