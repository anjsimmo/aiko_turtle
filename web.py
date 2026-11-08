#!/usr/bin/env python3
#
# The web server: FastAPI (webapp.py) on top of an Aiko-connected backend.
# It is itself an Aiko Actor: it mirrors the VirtualWorld's "robots.*"
# share, follows the chat channel like "aiko_chat repl", and hosts a
# ChatRobotAgent for every robot created through the REST API, so those
# robots are discoverable Services and answer in the chat too.
#
# Usage
# ~~~~~
#   source env.sh
#   ./web.py [--port 8123] [--channel robots] [--world turtle_world]
#   then open http://localhost:8123  (REST docs at /docs)

import itertools
import queue
import threading
import time

import click
import uvicorn

import aiko_services as aiko
from aiko_services.main.actor import ActorTopic
from aiko_services.main.utilities import parse
from aiko_chat import ChatServer, get_server_service_filter
from aiko_chat.protocol import _decode_message

import config
from robot import ROBOT_PROTOCOL, ChatRobotAgent, host_robot
from virtual_world import VirtualWorld
from webapp import BackendError, EventHub, create_app
from world_model import parse_pose_text

_REQUEST_TIMEOUT = 5.0
_HOST = "web"                   # "host" of robots created through REST


class AikoBackend(aiko.Actor):
    def __init__(self, context, world_name=config.WORLD_NAME,
                 channel=config.CHANNEL):
        context.call_init(self, "Actor", context)
        self.share["source_file"] = __file__
        self.world_name = world_name
        self.channel = channel
        self.hub = EventHub()
        self.world = None
        self.world_topic = None
        self.ec_consumer = None
        self.chat_server = None
        self.chat_topic = None
        self.hosted = {}            # robot name -> ChatRobotAgent (ours)
        self.external = set()       # robots with their own live process
        self.kinds = {}             # robot name -> kind, from the share
        self.process_prefix = self.topic_path.rsplit("/", 1)[0] + "/"
        self.request_lock = threading.Lock()
        self.request_ids = itertools.count()
        print(f"WEB: waiting for world \"{world_name}\" and chat server ...",
              flush=True)
        aiko.do_discovery(
            VirtualWorld,
            aiko.ServiceFilter("*", world_name, "*", "*", "*", "*"),
            self._world_add_handler, self._world_remove_handler)
        aiko.do_discovery(
            ChatServer, get_server_service_filter(),
            self._chat_add_handler, self._chat_remove_handler)
        # Every robot in the world is always answerable: this process hosts
        # a ChatRobotAgent for each one, unless someone runs their own
        # "robot.py run --name NAME", which then speaks for it instead
        aiko.do_discovery(
            ChatRobotAgent,
            aiko.ServiceFilter("*", "*", ROBOT_PROTOCOL, "*", "*", "*"),
            self._robot_add_handler, self._robot_remove_handler)

    # -- other people's robot processes --------------------------------------

    def _robot_add_handler(self, service_details, service):
        if service_details[0].startswith(self.process_prefix):
            return                  # one of ours
        name = service_details[1]
        self.external.add(name)
        if name in self.hosted:
            print(f"WEB: @@{name} now has its own process", flush=True)
            self.unhost(name)

    def _robot_remove_handler(self, service_details):
        if service_details[0].startswith(self.process_prefix):
            return
        name = service_details[1]
        self.external.discard(name)
        if self.world and name in self.kinds:
            print(f"WEB: @@{name} lost its own process", flush=True)
            self.host(name, self.kinds[name])

    # -- world ---------------------------------------------------------------

    def _world_add_handler(self, service_details, service):
        print(f"WEB: world connected: {service_details[0]}", flush=True)
        self.world = service
        self.world_topic = service_details[0]
        if self.ec_consumer:
            self.ec_consumer.terminate()
        self.hub.clear_robots()
        self.ec_consumer = aiko.ECConsumer(
            self, 0, {}, f"{service_details[0]}/control", ["robots"])
        self.ec_consumer.add_handler(self._robots_handler)
        self.hub.set_status(world=True)
        # _request() blocks on a reply that arrives on this very thread,
        # so the listing runs on its own thread, like an HTTP request does
        threading.Thread(target=self.rehost_robots, daemon=True).start()

    def _world_remove_handler(self, service_details):
        if service_details[0] != self.world_topic:
            return                  # another world of the same name, not ours
        print("WEB: world disconnected", flush=True)
        self.world = None
        self.world_topic = None
        if self.ec_consumer:
            self.ec_consumer.terminate()
            self.ec_consumer = None
        self.hub.set_status(world=False)

    def _robots_handler(self, client_id, command, item_name, item_value):
        if not item_name.startswith("robots."):
            return
        name = item_name[len("robots."):]
        if command == "remove":
            self.kinds.pop(name, None)
            self.hub.remove_robot(name)
            return
        pose = parse_pose_text(item_value)
        if pose:
            self.kinds[name] = pose["kind"]
            self.hub.publish_robot(dict(pose, name=name))

    # -- requests to the world, from the HTTP threads -----------------------

    def _request(self, call):
        """call(world, topic_path_response) -> the world's response rows"""
        if not self.world:
            raise BackendError(503, "world not connected")
        topic = f"{self.topic_path}/response/{next(self.request_ids)}"
        box = queue.Queue()
        rows, expected = [], None

        def handler(_aiko, _topic, payload_in):
            nonlocal expected
            try:
                command, fields = parse(payload_in)
            except Exception:
                return
            if command == "item_count":
                expected = int(fields[0])
                if expected == 0:
                    box.put([])
            elif command == "response":
                rows.append([str(field) for field in fields])
                if expected is not None and len(rows) >= expected:
                    box.put(list(rows))

        self.add_message_handler(handler, topic)
        try:
            with self.request_lock:
                call(self.world, topic)
            try:
                result = box.get(timeout=_REQUEST_TIMEOUT)
            except queue.Empty:
                raise BackendError(504, "no response from the world")
        finally:
            self.remove_message_handler(handler, topic)
        if result and result[0][0] == "error":
            detail = " ".join(result[0][1:])
            status = 404 if detail.startswith("unknown robot") else 422
            raise BackendError(status, detail)
        return result

    @staticmethod
    def _robot(row):
        # row: [command, name, x, y, heading, kind, (host, owner)]
        robot = {"name": row[1], "x": float(row[2]), "y": float(row[3]),
                 "heading": float(row[4]), "kind": row[5]}
        if len(row) > 7:
            robot["host"], robot["owner"] = row[6], row[7]
        return robot

    # -- Backend methods (webapp.py) ------------------------------------------

    def status(self):
        return {"world": self.world is not None,
                "chat": self.chat_topic, "hosted": sorted(self.hosted)}

    def list_robots(self):
        return [self._robot(row) for row in
                self._request(lambda world, topic: world.list_robots(topic))]

    def pose(self, name):
        return self._robot(self._request(
            lambda world, topic: world.get_pose(name, topic))[0])

    def create_robot(self, name, kind, owner):
        robot = self._robot(self._request(lambda world, topic:
            world.create_robot(name, kind, owner, _HOST, topic))[0])
        self._post_message(ActorTopic.IN, "host", [name, kind, owner])
        return robot

    def destroy_robot(self, name):
        robot = self._robot(self._request(
            lambda world, topic: world.destroy_robot(name, topic))[0])
        self._post_message(ActorTopic.IN, "unhost", [name])
        return robot

    def move(self, name, distance, username):
        return self._robot(self._request(lambda world, topic:
            world.apply_move(name, distance, username, topic))[0])

    def turn(self, name, angle, username):
        return self._robot(self._request(lambda world, topic:
            world.apply_turn(name, angle, username, topic))[0])

    def reset(self, name, username):
        return self._robot(self._request(lambda world, topic:
            world.reset(name, username, topic))[0])

    def history(self, name, limit):
        rows = self._request(
            lambda world, topic: world.get_history(name, limit, topic))
        return [{"timestamp": float(row[1]), "username": row[2],
                 "command": row[3], "argument": "" if row[4] == "-" else row[4],
                 "x": float(row[5]), "y": float(row[6]),
                 "heading": float(row[7])} for row in rows]

    def send_chat(self, username, message):
        if not self.chat_server:
            raise BackendError(503, "chat server not connected")
        self.chat_server.send_message(username, [self.channel], message)

    # -- hosting ChatRobotAgents for REST-created robots (Actor thread) ----

    def host(self, name, kind="turtle", owner="anonymous"):
        if name not in self.hosted:
            self.hosted[name] = host_robot(
                name, kind, owner, self.channel, self.world_name, host=_HOST)
            print(f"WEB: hosting @@{name}", flush=True)

    def unhost(self, name):
        robot = self.hosted.pop(name, None)
        if robot:
            robot.detach()
            print(f"WEB: released @@{name}", flush=True)

    def rehost_robots(self):
        # After a (re)connect to the world: speak for every robot that has
        # no live process of its own (a later discovery of one unhosts)
        try:
            robots = self.list_robots()
        except BackendError as error:
            print(f"WEB: cannot list robots: {error.detail}", flush=True)
            return
        for robot in robots:
            name = robot["name"]
            if name not in self.external and name not in self.hosted:
                self._post_message(ActorTopic.IN, "host",
                    [name, robot["kind"], robot.get("owner")])

    # -- chat ----------------------------------------------------------------

    def _chat_add_handler(self, service_details, service):
        print(f"WEB: chat server connected: {service_details[0]}", flush=True)
        self.chat_server = service
        if self.chat_topic:
            self.remove_message_handler(self._chat_handler, self.chat_topic)
        self.chat_topic = f"{service_details[0]}/{self.channel}"
        self.add_message_handler(self._chat_handler, self.chat_topic)
        self.hub.set_status(chat=service_details[0])

    def _chat_remove_handler(self, service_details):
        print("WEB: chat server disconnected", flush=True)
        self.chat_server = None
        self.hub.set_status(chat=None)

    def _chat_handler(self, _aiko, topic, payload_in):
        fields = _decode_message(payload_in)
        if not fields:
            return
        try:
            timestamp = float(fields.get("timestamp", time.time()))
        except (TypeError, ValueError):
            timestamp = time.time()
        self.hub.publish_chat({
            "username": str(fields.get("username", "") or ""),
            "message": str(fields.get("message", "")),
            "timestamp": timestamp})


@click.command()
@click.option("--host", type=str, default=config.WEB_HOST, show_default=True)
@click.option("--port", type=int, default=config.WEB_PORT, show_default=True)
@click.option("--channel", type=str, default=config.CHANNEL, show_default=True)
@click.option("--world", "world_name", type=str, default=config.WORLD_NAME,
    show_default=True)
def main(host, port, channel, world_name):
    init_args = aiko.actor_args("turtle_web", tags=["ec=true", "type=web"])
    init_args.update({"world_name": world_name, "channel": channel})
    backend = aiko.compose_instance(AikoBackend, init_args)
    app = create_app(backend, channel=channel)

    server = uvicorn.Server(uvicorn.Config(
        app, host=host, port=port, log_level="warning"))

    def serve():
        # uvicorn returns at once when it cannot bind (port in use):
        # then the whole process must go, not linger without a web server
        server.run()
        print(f"WEB: web server stopped (port {port} in use?), exiting",
              flush=True)
        aiko.process.terminate(1)

    threading.Thread(target=serve, daemon=True).start()
    print(f"WEB: open http://{host}:{port}  (API docs at /docs)", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
