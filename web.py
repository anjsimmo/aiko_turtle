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
from aiko_services.main.share import services_cache_create_singleton
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
_MQTT_TOPIC_LIMIT = 64          # distinct topic patterns /api/mqtt may watch


def _topic_matches(pattern, topic):
    """MQTT topic filter matching: + is one level, # the rest"""
    p, t = pattern.split("/"), topic.split("/")
    for index, part in enumerate(p):
        if part == "#":
            return True
        if index >= len(t) or (part != "+" and part != t[index]):
            return False
    return len(p) == len(t)


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
        self.chat_topic = None          # the ChatServer's topic path
        self.followed = {channel}       # channels relayed to the page
        self.chat_share = {}            # the ChatServer's share (channel_list)
        self.chat_consumer = None
        self.mqtt_watchers = {}     # topic pattern -> {clients with put()}
        self.mqtt_lock = threading.Lock()
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
        # row: [command, name, x, y, heading, kind, z, (host, owner)]
        robot = {"name": row[1], "x": float(row[2]), "y": float(row[3]),
                 "heading": float(row[4]), "kind": row[5],
                 "z": float(row[6]) if len(row) > 6 else 0.0}
        if len(row) > 8:
            robot["host"], robot["owner"] = row[7], row[8]
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

    def create_robot(self, name, kind, owner, x=0.0, y=0.0, heading=0.0):
        robot = self._robot(self._request(lambda world, topic:
            world.create_robot(name, kind, owner, _HOST, topic, x, y, heading))[0])
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

    def reset(self, name, username, x=0.0, y=0.0, heading=0.0):
        return self._robot(self._request(lambda world, topic:
            world.reset(name, x, y, heading, username, topic))[0])

    def history(self, name, limit):
        rows = self._request(
            lambda world, topic: world.get_history(name, limit, topic))
        return [{"timestamp": float(row[1]), "username": row[2],
                 "command": row[3], "argument": "" if row[4] == "-" else row[4],
                 "x": float(row[5]), "y": float(row[6]),
                 "heading": float(row[7]),
                 "z": float(row[8]) if len(row) > 8 else 0.0} for row in rows]

    def send_chat(self, username, message, channel=None):
        if not self.chat_server:
            raise BackendError(503, "chat server not connected")
        channel = channel or self.channel
        self.follow_channel(channel)
        self.chat_server.send_message(username, [channel], message)

    def channels(self):
        known = self.chat_share.get("channel_list", [])
        if isinstance(known, dict):
            known = list(known)
        elif not isinstance(known, (list, tuple)):
            known = [str(known)]
        return {"default": self.channel, "following": sorted(self.followed),
                "known": sorted({str(name) for name in known} | self.followed)}

    def follow_channel(self, channel):
        if channel not in self.followed:
            self.followed.add(channel)
            if self.chat_topic:
                self.add_message_handler(
                    self._chat_handler, f"{self.chat_topic}/{channel}")
            print(f"WEB: following #{channel}", flush=True)
        return self.channels()

    def system(self):
        """The shared services, for /system: what a newcomer needs to
        connect by MQTT, and the Registrar's view of who is running"""
        cache = services_cache_create_singleton(aiko.process)
        services = []
        for details in cache.get_services():
            topic_path, name, protocol, transport, owner, tags = details[:6]
            services.append({
                "topic_path": topic_path, "name": name, "protocol": protocol,
                "transport": transport, "owner": owner,
                "tags": [str(tag) for tag in (tags or [])]})
        services.sort(key=lambda service: service["topic_path"])
        return {
            "mqtt": {"host": config.AIKO_MQTT_HOST, "port": config.AIKO_MQTT_PORT,
                     "namespace": config.AIKO_NAMESPACE,
                     "registrar_topic": f"{config.AIKO_NAMESPACE}/service/registrar",
                     "chat_server_topic": self.chat_topic,
                     "world_topic": self.world_topic},
            "cache_state": cache.get_state(),
            "services": services,
            "channels": self.channels()}

    # -- MQTT, for /api/mqtt (HTTP threads) ---------------------------------

    def _mqtt_topic(self, topic):
        prefix = f"{config.AIKO_NAMESPACE}/"
        if not topic.startswith(prefix) or len(topic) <= len(prefix):
            raise BackendError(422, f"topic must start with {prefix}")
        return topic

    def mqtt_subscribe(self, topic, client):
        """client.put({"topic", "payload", "timestamp"}) for every message
        on topic (wildcards allowed) until mqtt_unsubscribe().  One Aiko
        handler per distinct topic, kept for good: removing a wildcard
        handler trips an aiko_services bug (process.py does "del" on the
        wildcard list), and the set of topics people ask for is small"""
        topic = self._mqtt_topic(topic)
        with self.mqtt_lock:
            if topic not in self.mqtt_watchers:
                if len(self.mqtt_watchers) >= _MQTT_TOPIC_LIMIT:
                    raise BackendError(429, "too many distinct topics watched; "
                                       "use a wildcard pattern")
                self.mqtt_watchers[topic] = set()
                self.add_message_handler(self._mqtt_handler, topic)
            self.mqtt_watchers[topic].add(client)

    def mqtt_unsubscribe(self, topic, client):
        with self.mqtt_lock:
            self.mqtt_watchers.get(topic, set()).discard(client)

    def _mqtt_handler(self, _aiko, message_topic, payload_in):
        if isinstance(payload_in, bytes):
            payload_in = payload_in.decode("utf-8", "replace")
        message = {"kind": "mqtt", "topic": message_topic,
                   "payload": str(payload_in), "timestamp": time.time()}
        with self.mqtt_lock:
            clients = [client for pattern, watchers in self.mqtt_watchers.items()
                       if _topic_matches(pattern, message_topic)
                       for client in watchers]
        for client in clients:
            client.put(message)

    def mqtt_watch(self, topic, seconds, limit):
        box = queue.Queue()
        self.mqtt_subscribe(topic, box)
        messages, deadline = [], time.monotonic() + seconds
        try:
            while len(messages) < limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    messages.append(box.get(timeout=remaining))
                except queue.Empty:
                    break
        finally:
            self.mqtt_unsubscribe(topic, box)
        return messages

    def mqtt_publish(self, topic, payload):
        topic = self._mqtt_topic(topic)
        if "#" in topic or "+" in topic:
            raise BackendError(422, "cannot publish to a wildcard topic")
        aiko.process.message.publish(topic, payload)

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
        self._chat_detach()
        self.chat_server = service
        self.chat_topic = service_details[0]
        for channel in self.followed:
            self.add_message_handler(
                self._chat_handler, f"{self.chat_topic}/{channel}")
        self.chat_consumer = aiko.ECConsumer(
            self, 1, self.chat_share, f"{self.chat_topic}/control")
        self.hub.set_status(chat=service_details[0])

    def _chat_remove_handler(self, service_details):
        if service_details[0] != self.chat_topic:
            return
        print("WEB: chat server disconnected", flush=True)
        self._chat_detach()
        self.hub.set_status(chat=None)

    def _chat_detach(self):
        if self.chat_topic:
            for channel in self.followed:
                self.remove_message_handler(
                    self._chat_handler, f"{self.chat_topic}/{channel}")
        if self.chat_consumer:
            self.chat_consumer.terminate()
        self.chat_consumer = None
        self.chat_server = None
        self.chat_topic = None
        self.chat_share.clear()

    def _chat_handler(self, _aiko, topic, payload_in):
        fields = _decode_message(payload_in)
        if not fields:
            return
        try:
            timestamp = float(fields.get("timestamp", time.time()))
        except (TypeError, ValueError):
            timestamp = time.time()
        channel = str(fields.get("channel") or topic.rsplit("/", 1)[-1])
        self.hub.publish_chat({
            "username": str(fields.get("username", "") or ""),
            "message": str(fields.get("message", "")),
            "channel": channel, "timestamp": timestamp})


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
    if config.API_TOKEN:
        print("WEB: REST writes need the bearer token (TURTLE_API_TOKEN)",
              flush=True)

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
