#!/usr/bin/env python3
# Exercise the Phase 3 ChatSpace CRUD via the ChatServer remote interface.
# Watches the "general" channel for @@chat_space replies.

import threading
import time

import aiko_services as aiko
from aiko_chat import ChatServer, get_server_service_filter
from aiko_chat.protocol import format_incoming


class SpaceTester(aiko.Actor):
    def __init__(self, context):
        context.call_init(self, "Actor", context)
        self.chat_server = None
        aiko.do_discovery(ChatServer, get_server_service_filter(),
            self.add_handler, lambda details: None)

    def add_handler(self, service_details, service):
        self.chat_server = service
        self.add_message_handler(
            self.message_handler, f"{service_details[0]}/general")
        threading.Thread(target=self.run_tests, daemon=True).start()

    def message_handler(self, _aiko, topic, payload_in):
        print(f"REPLY: {format_incoming(payload_in)}", flush=True)

    def run_tests(self):
        server = self.chat_server
        steps = [
            ("space_list /", lambda: server.space_list("general", "/")),
            ("space_create robots",
                lambda: server.space_create("general", "robots")),
            ("space_add robots anj_turtlebot (expect ACCEPT)",
                lambda: server.space_add(
                    "general", "robots", "anj_turtlebot")),
            ("space_add robots anj_turtle_world (expect REJECT: no <Chat>)",
                lambda: server.space_add(
                    "general", "robots", "anj_turtle_world")),
            ("space_add robots no_such_service (expect REJECT: not found)",
                lambda: server.space_add(
                    "general", "robots", "no_such_service")),
            ("space_list channels",
                lambda: server.space_list("general", "channels")),
        ]
        time.sleep(2)
        for description, step in steps:
            print(f"STEP: {description}", flush=True)
            step()
            time.sleep(3)
        time.sleep(3)
        aiko.process.terminate()


init_args = aiko.actor_args("anj_space_tester", tags=["ec=true"])
tester = aiko.compose_instance(SpaceTester, init_args)
aiko.process.run()
