#!/usr/bin/env python3
#
# The web server: FastAPI (webapp.py) on top of an Aiko-connected backend.
# It is itself an Aiko Actor: it mirrors the VirtualWorld's "robots.*"
# share, follows the chat channel like "aiko_chat repl", hosts a virtual
# robot Actor for every robot created through the REST API, and hosts a
# REPLICA for every real robot it finds in the Registrar (robots/NAME.py says
# how each real one is recognised), so real robots show on the map and
# answer in the chat too.
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
from aiko_services.main.discovery import get_service_proxy
from aiko_services.main.share import services_cache_create_singleton
from aiko_services.main.utilities import parse
from aiko_chat import ChatServer, get_server_service_filter
from aiko_chat.protocol import _decode_message

import config
import robots as registry
from robot import SANDBOX_TAG, ChatRobotBase, host_robot, host_replica
from virtual_world import VirtualWorld
from webapp import BackendError, EventHub, create_app
from world_model import parse_pose_text

_REQUEST_TIMEOUT = 5.0
_HOST = "web"                   # "host" of robots created through REST
_REPLICA = "replica"                  # "host" of the replica of a real robot
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


def _tags(service_details):
    tags = {}
    for tag in service_details[5] or []:
        key, _, value = str(tag).partition("=")
        tags[key] = value
    return tags


def real_robot_interface(service_details, world_name=None):
    """The interface a Registrar entry speaks, if a robots/ module
    recognises it as a real robot (by name or protocol): else None.
    A Service tagged world=NAME is a stand-in for one sandbox only
    (tools/fake_robot.py): real robots carry no world tag"""
    topic_path, name, protocol = service_details[:3]
    world = _tags(service_details).get("world")
    if world_name is not None and world and world != world_name:
        return None
    for interface, module in registry.INTERFACES.items():
        match = getattr(module, "MATCH", None)
        if not match:
            continue
        if "name" in match and match["name"] != name:
            continue
        if "protocol" in match and match["protocol"] != protocol:
            continue
        return interface
    return None


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
        self.mqtt_watch_client = None   # paho client, see _mqtt_client()
        self.mqtt_lock = threading.Lock()
        self.hosted = {}            # robot name -> virtual robot Actor (ours)
        self.external = {}          # robot name -> topic path, other people's processes
        self.replicas = {}             # robot name -> replica Actor (ours), real robot present
        self.real = {}              # real robot topic path -> (robot name, interface)
        self.records = {}           # robot name -> last pose from the share
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
        # Every Service: virtual robots in other people's processes (then
        # this process stops speaking for them), and REAL robots, which
        # get a replica here.  Tags are matched by hand: the filter would
        # need one filter per module
        aiko.do_discovery(
            ChatRobotBase, aiko.ServiceFilter("*", "*", "*", "*", "*", "*"),
            self._service_add_handler, self._service_remove_handler)

    # -- the Registrar: other people's robots and real robots ----------------

    def _service_add_handler(self, service_details, service):
        topic_path, name = service_details[0], service_details[1]
        if topic_path.startswith(self.process_prefix):
            return                      # one of ours
        tags = _tags(service_details)
        if tags.get(SANDBOX_TAG) == "virtual":
            if tags.get("world", self.world_name) != self.world_name:
                return                  # a developer's own world, on the shared broker
            self.external[name] = topic_path
            if name in self.hosted:
                print(f"WEB: @@{name} now has its own process", flush=True)
                # Not here: this runs inside the services cache's handler
                # loop and (un)hosting registers handlers of its own (aiko
                # share.py iterates a set that would change size)
                self._post_message(ActorTopic.IN, "unhost", [name])
            return
        if SANDBOX_TAG in tags:
            return                      # another sandbox's replica or web server
        interface = real_robot_interface(service_details, self.world_name)
        if interface:
            print(f"WEB: real robot {name} at {topic_path} speaks {interface}",
                  flush=True)
            self._post_message(ActorTopic.IN, "replica", [name, interface, topic_path])

    def _service_remove_handler(self, service_details):
        topic_path, name = service_details[0], service_details[1]
        if topic_path.startswith(self.process_prefix):
            return
        if topic_path in self.real:
            self._post_message(ActorTopic.IN, "drop_replica", [topic_path])
            return
        if self.external.get(name) != topic_path:
            return
        self.external.pop(name, None)
        if self.world and name in self.records:
            print(f"WEB: @@{name} lost its own process", flush=True)
            record = self.records[name]
            self._post_message(ActorTopic.IN, "host",
                               [name, record["kind"], "anonymous", record["interface"]])

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
            self.records.pop(name, None)
            self.hub.remove_robot(name)
            return
        pose = parse_pose_text(item_value)
        if pose:
            self.records[name] = pose
            self.hub.publish_robot(dict(pose, name=name, online=self.online(name, pose)))

    def online(self, name, pose):
        """A replica is online while its real robot is in the Registrar"""
        return name in self.replicas if pose.get("host") == _REPLICA else True

    # -- requests to the world, from the HTTP threads -----------------------

    def _request(self, call, need_world=True):
        """call(world, topic_path_response) -> the response rows"""
        if need_world and not self.world:
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
        if not result:
            return []                       # (item_count 0): nothing to list
        if result[0][0] == "error":
            detail = " ".join(result[0][1:])
            status = 404 if detail.startswith("unknown robot") else 422
            raise BackendError(status, detail)
        return result

    def _robot(self, row):
        # row: [command, name, x, y, heading, kind, z, host, owner, interface, source, pen, moving]
        robot = {"name": row[1], "x": float(row[2]), "y": float(row[3]),
                 "heading": float(row[4]), "kind": row[5],
                 "z": float(row[6]) if len(row) > 6 else 0.0}
        if len(row) > 8:
            robot["host"], robot["owner"] = row[7], row[8]
        if len(row) > 12:
            robot.update(interface=row[9], source="" if row[10] == "-" else row[10],
                         pen=row[11] == "down", moving=row[12] == "moving")
        robot["online"] = self.online(robot["name"], robot)
        robot["topic_path"] = self.topic_path_of(robot["name"])
        return robot

    def topic_path_of(self, name):
        if name in self.hosted:
            return self.hosted[name].topic_path
        if name in self.replicas:
            return self.replicas[name].topic_path
        return self.external.get(name)

    # -- Backend methods (webapp.py) ------------------------------------------

    def status(self):
        return {"world": self.world is not None,
                "chat": self.chat_topic, "hosted": sorted(self.hosted),
                "replicas": sorted(self.replicas)}

    def list_robots(self):
        return [self._robot(row) for row in
                self._request(lambda world, topic: world.list_robots(topic))]

    def pose(self, name):
        return self._robot(self._request(
            lambda world, topic: world.get_pose(name, topic))[0])

    def create_robot(self, name, kind, owner, x=0.0, y=0.0, heading=0.0,
                     interface=None):
        try:
            kind, interface = registry.resolve(kind, interface)
        except ValueError as error:
            raise BackendError(422, str(error))
        robot = self._robot(self._request(lambda world, topic:
            world.create_robot(name, kind, owner, _HOST, topic, x, y, heading,
                               interface, ""))[0])
        if robot.get("host") == _REPLICA:
            return robot                # it existed already, as a replica
        self._post_message(ActorTopic.IN, "host", [name, kind, owner, interface])
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

    def command(self, name, chat_command, username):
        """Any chat command over REST: a remote call on the robot's own
        Actor (virtual, hosted here or in someone else's process; or the
        replica of a real robot, which forwards it)"""
        topic_path = self.topic_path_of(name)
        if not topic_path:
            raise BackendError(404, f"unknown robot {name}, or it has no "
                               "live process (create it here, or run "
                               "robot.py)")
        robot = get_service_proxy(f"{topic_path}/in", ChatRobotBase)
        rows = self._request(lambda _world, topic: robot.command(
            chat_command, username, topic), need_world=False)
        return {"name": name, "command": chat_command,
                "reply": " ".join(rows[0][1:])}   # an error row raised already

    def robot_info(self, name):
        """The robot, its interface spec and where it is on the bus, for
        the page's interface box and the aiko/mqtt layers"""
        robot = self.pose(name)
        interface = robot.get("interface", registry.default_interface(robot["kind"]))
        info = dict(robot, spec=registry.describe_interface(interface, robot["kind"]))
        if robot.get("host") == _REPLICA:
            info["real_topic_path"] = robot.get("source") or None
        return info

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
                "tags": [str(tag) for tag in (tags or [])],
                "real_robot": real_robot_interface(details, self.world_name)})
        services.sort(key=lambda service: service["topic_path"])
        return {
            "mqtt": {"host": config.AIKO_MQTT_HOST, "port": config.AIKO_MQTT_PORT,
                     "namespace": config.AIKO_NAMESPACE,
                     "registrar_topic": f"{config.AIKO_NAMESPACE}/service/registrar",
                     "chat_server_topic": self.chat_topic,
                     "world_topic": self.world_topic},
            "cache_state": cache.get_state(),
            "services": services,
            "real_robots": [{"name": name, "interface": interface, "topic_path": topic}
                            for topic, (name, interface) in sorted(self.real.items())],
            "channels": self.channels()}

    # -- MQTT, for /api/mqtt (HTTP threads) ---------------------------------

    def _mqtt_topic(self, topic):
        prefix = f"{config.AIKO_NAMESPACE}/"
        if not topic.startswith(prefix) or len(topic) <= len(prefix):
            raise BackendError(422, f"topic must start with {prefix}")
        return topic

    def _mqtt_client(self):
        """A separate paho client for watching: the broker does the
        wildcard matching.  Aiko's own dispatcher (process.py
        topic_matcher) matches "prefix/#" one level deep only and "+"
        patterns by their first and last token, so a handler registered
        for "aiko/#" through add_message_handler() never sees the deeper
        topics.  Same broker, credentials and TLS setting as Aiko"""
        if self.mqtt_watch_client:
            return self.mqtt_watch_client
        import paho.mqtt.client as mqtt
        message = aiko.process.message
        if not hasattr(message, "mqtt_transport"):   # Aiko is still connecting
            raise BackendError(503, "not connected to the broker yet, retry in a moment")
        client = mqtt.Client(transport=message.mqtt_transport)
        if message.mqtt_tls_enabled:
            client.tls_set()
        if message.mqtt_username:
            client.username_pw_set(
                message.mqtt_username, message.mqtt_password)
        client.on_connect = self._mqtt_on_connect
        client.on_message = self._mqtt_on_message
        client.reconnect_delay_set(1, 30)
        client.connect_async(message.mqtt_host, message.mqtt_port,
                             keepalive=60)
        client.loop_start()
        self.mqtt_watch_client = client
        return client

    def _mqtt_on_connect(self, client, _userdata, _flags, _rc):
        with self.mqtt_lock:          # (re)subscribe everything watched
            for pattern in self.mqtt_watchers:
                client.subscribe(pattern)

    def mqtt_subscribe(self, topic, client):
        """client.put({"topic", "payload", "timestamp"}) for every message
        on topic (wildcards allowed) until mqtt_unsubscribe()"""
        topic = self._mqtt_topic(topic)
        with self.mqtt_lock:
            if topic not in self.mqtt_watchers:
                if len(self.mqtt_watchers) >= _MQTT_TOPIC_LIMIT:
                    raise BackendError(429, "too many distinct topics watched; "
                                       "use a wildcard pattern")
                self.mqtt_watchers[topic] = set()
                self._mqtt_client().subscribe(topic)
            self.mqtt_watchers[topic].add(client)

    def mqtt_unsubscribe(self, topic, client):
        with self.mqtt_lock:
            watchers = self.mqtt_watchers.get(topic)
            if watchers is None:
                return
            watchers.discard(client)
            if not watchers:
                del self.mqtt_watchers[topic]
                self._mqtt_client().unsubscribe(topic)

    def _mqtt_on_message(self, _client, _userdata, message):
        payload = message.payload.decode("utf-8", "replace")
        event = {"kind": "mqtt", "topic": message.topic,
                 "payload": payload, "timestamp": time.time()}
        with self.mqtt_lock:
            clients = [client for pattern, watchers in self.mqtt_watchers.items()
                       if _topic_matches(pattern, message.topic)
                       for client in watchers]
        for client in clients:
            client.put(event)

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

    # -- hosting robot Actors (Actor thread) --------------------------------

    def host(self, name, kind="turtle", owner="anonymous", interface=""):
        if name not in self.hosted and name not in self.replicas:
            try:
                self.hosted[name] = host_robot(
                    name, kind, owner, self.channel, self.world_name,
                    host=_HOST, interface=interface or None)
            except ValueError as error:
                print(f"WEB: cannot host @@{name}: {error}", flush=True)
                return
            print(f"WEB: hosting @@{name} ({kind}, {interface or 'default'})", flush=True)

    def unhost(self, name):
        robot = self.hosted.pop(name, None)
        if robot:
            robot.detach()
            print(f"WEB: released @@{name}", flush=True)

    def replica(self, name, interface, source):
        """A real robot appeared: host its replica.  Its sandbox name is its
        registered name, unless a virtual robot already has that name"""
        if source in self.real:
            return
        host = source.split("/")[1] if source.count("/") > 1 else "real"
        record = self.records.get(name)
        if record and record.get("host") != _REPLICA:
            name = f"{name}_{host}"
        self.real[source] = (name, interface)
        self.replicas[name] = host_replica(name, interface, source,
                                     channel=self.channel, world_name=self.world_name)
        print(f"WEB: replica @@{name} of {source} ({interface})", flush=True)

    def drop_replica(self, source):
        name, _ = self.real.pop(source, (None, None))
        replica = self.replicas.pop(name, None)
        if replica:
            replica.replica_detach()
            replica.detach()
            print(f"WEB: real robot {source} gone, replica @@{name} offline", flush=True)
            record = self.records.get(name)
            if record:
                self.hub.publish_robot(dict(record, name=name, online=False))

    def rehost_robots(self):
        # After a (re)connect to the world: speak for every virtual robot
        # that has no live process of its own (a later discovery of one
        # unhosts).  Replicas are hosted only while their real robot is
        try:
            robots = self.list_robots()
        except BackendError as error:
            print(f"WEB: cannot list robots: {error.detail}", flush=True)
            return
        for robot in robots:
            name = robot["name"]
            if robot.get("host") == _REPLICA:
                continue
            if name not in self.external and name not in self.hosted:
                self._post_message(ActorTopic.IN, "host",
                    [name, robot["kind"], robot.get("owner"),
                     robot.get("interface", "")])

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
    init_args = aiko.actor_args("turtle_web",
                                tags=["ec=true", "type=web", f"{SANDBOX_TAG}=web"])
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
