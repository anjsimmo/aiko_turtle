#!/usr/bin/env python3
#
# A small agent in the chat: discovers every robot through the Registrar
# (anything tagged "robot=0" and "chat=0"), and when someone writes
# "@@square NAME" it makes that robot draw a square by sending it chat
# commands.  This is the shape of agent.py without the LLM; replace the
# body of handle() with your own planner, model or rules.
#
#   export AIKO_MQTT_HOST=aiko.hashtag.ai
#   python3 agent_bot.py                       # then, in #robots: @@square my_turtle
#
# Conventions it follows: bots are "@@name", humans "@name"; a robot acts
# only on messages that START with its "@@name"; replies end with " !!!!"
# so bots do not answer bots.

import threading
import time

import aiko_services as aiko
from aiko_services.main.share import services_cache_create_singleton
import aiko_chat.bot as bot
from aiko_chat.protocol import _decode_message

BOTNAME = "@@square"
CHANNEL = "robots"
ACK = " !!!!"


class SquareBot(bot.ChatBot):
    def __init__(self, context):
        context.call_init(self, "ChatBot", context)
        self.botname = BOTNAME
        self.current_channel = CHANNEL

    def robots(self):
        """name -> tags, for every Service advertising <Robot> and <Chat>"""
        cache = services_cache_create_singleton(aiko.process)
        found = {}
        for details in cache.get_services():
            tags = [str(tag) for tag in details[5]]
            if "robot=0" in tags and "chat=0" in tags:
                found[details[1]] = tags
        return found

    def process_message(self, payload_in, **kwargs):
        fields = _decode_message(payload_in) or {}
        message = str(fields.get("message", "")).strip()
        username = str(fields.get("username", "?"))
        if not message.startswith(BOTNAME) or message.endswith(ACK):
            return
        if username.startswith("@@"):
            return                              # never take orders from bots
        threading.Thread(target=self.handle, args=(username, message),
                         daemon=True).start()   # never block the event thread

    def handle(self, username, message):
        words = message.split()
        robots = self.robots()
        target = words[1] if len(words) > 1 else None
        if target not in robots:
            self.say(f"{username}: say \"{BOTNAME} NAME\"; I can see "
                     f"{', '.join('@@' + name for name in robots) or 'no robots'}")
            return
        if "move=0" not in robots[target]:
            self.say(f"{username}: @@{target} cannot move (no <Move>)")
            return
        self.say(f"{username}: drawing a square with @@{target}")
        for _ in range(4):
            self.send(f"@@{target} move 100")
            time.sleep(1)
            self.send(f"@@{target} turn 90")
            time.sleep(1)

    def send(self, text):                       # a command: no ACK suffix
        self.chat_server.send_message(BOTNAME, [CHANNEL], text)

    def say(self, text):                        # a reply: with it
        self.chat_server.send_message(BOTNAME, [CHANNEL], text + ACK)


init_args = aiko.actor_args("square_bot",
    tags=["ec=true", "type=chat_agent", "chat=0", "agent=0", f"botname={BOTNAME}"])
aiko.compose_instance(SquareBot, init_args)
print(f"{BOTNAME} listening in #{CHANNEL} (Ctrl-C to stop)")
aiko.process.run()
