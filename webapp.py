# The web application (FastAPI): the robots-and-chat page, a REST API for
# creating and driving robots, and one live stream of poses and chat.
#
# No Aiko here: create_app(backend) takes any object with the Backend
# methods below.  web.py provides the Aiko-connected backend; the tests a
# fake one.  Interactive API docs are served at /docs; the pages are the
# files in static/.

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import List, Optional, Union

from fastapi import (
    Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

import config
import kinds
from core import valid_robot_name

_HISTORY_LIMIT = 300    # chat messages kept per channel
_TRAIL_LIMIT = 500      # poses per robot, replayed to a newly opened page
_STATIC = Path(__file__).parent / "static"


class BackendError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Backend:
    """What create_app() needs.  Every method may raise BackendError"""
    hub = None                                  # an EventHub

    def status(self): ...                       # {"world": bool, "chat": str|None}
    def list_robots(self): ...                  # [robot, ...]
    def create_robot(self, name, kind, owner, x=0.0, y=0.0, heading=0.0,
                     interface=None): ...
    def destroy_robot(self, name): ...
    def move(self, name, distance, username): ...
    def turn(self, name, angle, username): ...
    def reset(self, name, username, x=0.0, y=0.0, heading=0.0): ...
    def pose(self, name): ...
    def robot_info(self, name): ...             # pose + interface spec + topic paths
    def history(self, name, limit): ...         # [event, ...]
    def command(self, name, chat_command, username): ...  # any chat command
    def send_chat(self, username, message, channel=None): ...
    def channels(self): ...                     # {"following": [...], "known": [...]}
    def follow_channel(self, channel): ...      # start relaying a channel
    def system(self): ...                       # {"mqtt": {...}, "services": [...]}
    def mqtt_watch(self, topic, seconds, limit): ...   # [{"topic","payload","timestamp"}]
    def mqtt_publish(self, topic, payload): ...
    def mqtt_subscribe(self, topic, client): ...       # client.put(message) until
    def mqtt_unsubscribe(self, topic, client): ...     # unsubscribed


class EventHub:
    """Fan-out of robot poses, chat messages and status to the page's
    live clients, with replay of recent history for a newly connected page"""

    def __init__(self):
        self.clients = set()
        self.trails = {}            # robot name -> [pose event, ...]
        self.chat = {}              # channel -> [message, ...]
        self.status = {"kind": "status", "world": False, "chat": None}
        self.lock = threading.Lock()

    def _broadcast(self, event):
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            client.put(event)

    def publish_robot(self, robot):
        event = {"kind": "robot", "name": robot["name"], "x": robot["x"],
                 "y": robot["y"], "heading": robot["heading"],
                 "z": robot.get("z", 0.0),
                 "type": robot.get("kind", kinds.DEFAULT_KIND),
                 "interface": robot.get("interface", ""),
                 "host": robot.get("host", "external"),
                 "pen": bool(robot.get("pen", 1)),
                 "moving": bool(robot.get("moving", False)),
                 "online": bool(robot.get("online", True))}
        with self.lock:
            trail = self.trails.setdefault(robot["name"], [])
            trail.append(event)
            del trail[:-_TRAIL_LIMIT]
        self._broadcast(event)

    def remove_robot(self, name):
        with self.lock:
            self.trails.pop(name, None)
        self._broadcast({"kind": "robot_removed", "name": name})

    def clear_robots(self):
        with self.lock:
            names = list(self.trails)
            self.trails.clear()
        for name in names:
            self._broadcast({"kind": "robot_removed", "name": name})

    def publish_chat(self, message):
        message = dict(message, kind="chat")
        message.setdefault("channel", config.CHANNEL)
        with self.lock:
            history = self.chat.setdefault(message["channel"], [])
            history.append(message)
            del history[:-_HISTORY_LIMIT]
        self._broadcast(message)

    def chat_history(self, channel):
        with self.lock:
            return list(self.chat.get(channel, []))

    def set_status(self, **changes):
        with self.lock:
            self.status.update(changes)
            status = dict(self.status)
        self._broadcast(status)

    def subscribe(self, client=None):
        """client: anything with put(event); default a queue.Queue"""
        client = client if client is not None else queue.Queue()
        with self.lock:
            replay = [dict(self.status)]
            for trail in self.trails.values():
                replay.extend(trail)
            for history in self.chat.values():
                replay.extend(history)
            self.clients.add(client)
        return client, replay

    def unsubscribe(self, client):
        with self.lock:
            self.clients.discard(client)


class _AsyncClient:
    """An EventHub client for the async routes: the hub puts events
    from Aiko's threads, the route awaits them on the event loop"""

    def __init__(self, loop):
        self.loop = loop
        self.queue = asyncio.Queue()

    def put(self, event):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event)


# -- request / response models -------------------------------------------------

Username = Field(default="anonymous", min_length=1, max_length=64,
                 description="any name you like, no login; humans are @name "
                             "by convention, bots @@name")
Channel = Field(default=None, min_length=1, max_length=64,
                description=f"chat channel (default {config.CHANNEL})")


class RobotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64,
        description="letters, digits, '_' and '-'; also the chat mention @@name")
    kind: str = Field(default=kinds.DEFAULT_KIND,
        description=f"the body: one of {', '.join(kinds.KINDS)} (GET /api/kinds)")
    interface: Optional[str] = Field(default=None,
        description="what it speaks: one of the kind's interfaces (GET /api/kinds); "
                    "default the kind's own. GET /api/interfaces describes each")
    owner: str = Username
    x: float = Field(default=0.0, description="where it starts")
    y: float = 0.0
    heading: float = 0.0


class MoveRequest(BaseModel):
    distance: Union[float, List[float]] = Field(
        description="a number: units forward (negative = backwards); or a "
                    "vector [forward, left, up] in the robot's frame, as "
                    "many axes as the kind has (GET /api/kinds)")
    username: str = Username


class TurnRequest(BaseModel):
    angle: float = Field(description="degrees counter-clockwise")
    username: str = Username


class ResetRequest(BaseModel):
    x: float = Field(default=0.0, description="where to put it (default: the origin)")
    y: float = 0.0
    heading: float = 0.0
    username: str = Username


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=200,
                         description="a chat command in the robot's own "
                                     "interface, without the mention: e.g. "
                                     "move 100 (robot), move 0.2 (irobot), "
                                     "action sit (xgo_robot), forward 100 "
                                     "(turtle_robot); or help")
    username: str = Username


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    username: str = Username
    channel: Optional[str] = Channel


class MqttPublish(BaseModel):
    topic: str = Field(min_length=1, max_length=256,
                       description=f"must start with {config.AIKO_NAMESPACE}/")
    payload: str = Field(max_length=4000,
                         description="usually an S-expression, e.g. (move 100)")


class ChannelRequest(BaseModel):
    channel: str = Field(min_length=1, max_length=64,
                         pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _wire(argument):
    """An argument as the wire takes it: a list becomes (a b c)"""
    if isinstance(argument, (list, tuple)):
        return "(" + " ".join(str(part) for part in argument) + ")"
    return str(argument)


# -- the app ---------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def create_app(backend, channel=config.CHANNEL, username=config.WEB_USERNAME,
               agent=config.AGENT_BOTNAME, api_token=config.API_TOKEN,
               api_token_public=config.API_TOKEN_PUBLIC, title=config.TITLE):
    """api_token: when non-empty, every request that changes something
    (POST, DELETE) must carry "Authorization: Bearer <api_token>".
    Reads and the pages stay open.  api_token_public: the token is shown
    on the page and in /api/status, pre-filled, so it is a formality"""

    app = FastAPI(
        title=title,
        description=(
            "Virtual robots in a shared world, each speaking the interface "
            "of a real robot (or the Aiko-native robot:0), driven over REST here or "
            "over Aiko Chat (`@@name move 100` in the channel).  Real robots "
            "found in the Registrar appear as replicas.  Create a robot with any "
            "name; a longer, unusual name is less likely to clash with "
            "someone else's.  Live poses and chat: GET /events (SSE).  The "
            "human guide, with Aiko and REST examples: /guide."
            + ("  **POST and DELETE need a bearer token** (the Authorize "
               "button)" + (f": `{api_token}`." if api_token_public else
               "; ask for it in the chat.") if api_token else "")),
        version="2.0")
    app.state.backend = backend

    def authorized(request: Request,
            credentials: HTTPAuthorizationCredentials = Depends(_bearer)):
        if not api_token:
            return
        given = credentials.credentials if credentials  \
            else request.query_params.get("token")
        if given != api_token:
            raise HTTPException(401, "bearer token required (see /guide)",
                                headers={"WWW-Authenticate": "Bearer"})

    write = [Depends(authorized)]

    def call(function, *arguments, **keywords):
        try:
            return function(*arguments, **keywords)
        except BackendError as error:
            raise HTTPException(error.status, error.detail)

    def check_name(name):
        if not valid_robot_name(name):
            raise HTTPException(422,
                "robot name: letters, digits, '_' and '-' only (max 64)")

    def static_page(name, view=""):
        text = (_STATIC / name).read_text(encoding="utf-8")
        return (text.replace("__CHANNEL__", channel)
                    .replace("__USERNAME__", username)
                    .replace("__AGENT__", agent)
                    .replace("__VIEW__", view)
                    .replace("__TITLE__", title)
                    .replace("__AUTH__", "true" if api_token else "false"))

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def page():
        return static_page("index.html")

    @app.get("/world", response_class=HTMLResponse, include_in_schema=False)
    def world_page():
        return static_page("index.html", "world")

    @app.get("/chat", response_class=HTMLResponse, include_in_schema=False)
    def chat_page():
        return static_page("index.html", "chat")

    @app.get("/guide", response_class=HTMLResponse, include_in_schema=False)
    def guide_page():
        return static_page("guide.html")

    @app.get("/system", response_class=HTMLResponse, include_in_schema=False)
    def system_page():
        return static_page("system.html")

    @app.get("/sprites/{name}.js", include_in_schema=False)
    def sprite(name: str):
        """One drawing function per kind: static/sprites/NAME.js"""
        if not valid_robot_name(name) or not (_STATIC / "sprites" / f"{name}.js").is_file():
            raise HTTPException(404, "no such sprite")
        return FileResponse(_STATIC / "sprites" / f"{name}.js",
                            media_type="application/javascript")

    def sse(request, client, replay, cleanup):
        # Async on purpose: Starlette cancels an async generator the moment
        # the client goes away, so a closed tab frees its connection at
        # once; a blocking generator would sit in a worker thread until
        # its next keepalive
        async def stream():
            try:
                for event in replay:
                    yield f"data: {json.dumps(event)}\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(client.queue.get(), 15)
                        yield f"data: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                cleanup()

        return StreamingResponse(stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/events", include_in_schema=False)
    async def events(request: Request):
        """Live poses, chat and status as server-sent events (curl -N)"""
        hub = backend.hub
        client = _AsyncClient(asyncio.get_running_loop())
        _, replay = hub.subscribe(client)
        return sse(request, client, replay, lambda: hub.unsubscribe(client))

    @app.websocket("/ws")
    async def live(websocket: WebSocket):
        # The page's live stream.  A WebSocket is not counted against the
        # browser's ~6 HTTP/1.1 connections per host, which a tab holding
        # an SSE stream is: with several tabs open the next page load
        # would hang until one closed
        await websocket.accept()
        hub = backend.hub
        client = _AsyncClient(asyncio.get_running_loop())
        _, replay = hub.subscribe(client)

        async def sender():
            for event in replay:
                await websocket.send_text(json.dumps(event))
            while True:
                event = await client.queue.get()
                await websocket.send_text(json.dumps(event))

        task = asyncio.create_task(sender())
        try:
            while True:
                await websocket.receive_text()     # pings; raises on close
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            task.cancel()
            hub.unsubscribe(client)

    @app.get("/api/status", tags=["system"])
    def status():
        status = dict(call(backend.status), auth=bool(api_token),
                      channel=channel, agent=agent, title=title,
                      streams=len(backend.hub.clients))
        if api_token and api_token_public:
            status["token"] = api_token
        return status

    @app.get("/api/kinds", tags=["robots"])
    def list_kinds():
        """The bodies: sprite, axes, the interfaces each may speak (the
        first is its own) and the chat commands of that interface"""
        return kinds.describe()

    @app.get("/api/interfaces", tags=["robots"])
    def list_interfaces():
        """Every interface: the functions a robot of it accepts on its
        "in" topic, exactly as the real robot does (status real), as an
        older one did (legacy) or as a design proposes (proposed)"""
        return kinds.describe_interfaces()

    @app.get("/api/interfaces/{name}", tags=["robots"])
    def get_interface(name: str, kind: Optional[str] = None):
        """One interface's spec; with ?kind= only the methods that body has"""
        if name not in kinds.INTERFACES:
            raise HTTPException(404, f"unknown interface {name}")
        if kind is not None and kind not in kinds.KINDS:
            raise HTTPException(404, f"unknown kind {kind}")
        return kinds.describe_interface(name, kind)

    @app.get("/api/system", tags=["system"])
    def system():
        """The shared Aiko services: MQTT details and the Registrar's
        Service list (this is what /system shows)"""
        return call(backend.system)

    @app.get("/api/mqtt", tags=["mqtt"], dependencies=write)
    def mqtt_watch(topic: str, seconds: float = 5, limit: int = 200):
        """Subscribe to a topic (MQTT wildcards + and # allowed, within
        the namespace) for up to 30 seconds and return what arrived.
        The token may also be given as ?token= for this and the stream"""
        return call(backend.mqtt_watch, topic, max(0.1, min(seconds, 30)),
                    max(1, min(limit, 1000)))

    @app.post("/api/mqtt", tags=["mqtt"], status_code=202, dependencies=write)
    def mqtt_publish(body: MqttPublish):
        """Publish one message.  Example: a robot's move is
        {"topic": "<its topic_path>/in", "payload": "(move 100)"}"""
        call(backend.mqtt_publish, body.topic, body.payload)
        return {"published": True, "topic": body.topic}

    @app.get("/api/mqtt/events", tags=["mqtt"], dependencies=write)
    async def mqtt_events(request: Request, topic: str):
        """The same as a stream of server-sent events, until you hang up:
        curl -N '.../api/mqtt/events?topic=aiko/%23&token=...'
        Up to four topics, comma separated, share one stream"""
        topics = [part.strip() for part in topic.split(",") if part.strip()][:4]
        if not topics:
            raise HTTPException(422, "topic required")
        client = _AsyncClient(asyncio.get_running_loop())
        subscribed = []
        try:
            for one in topics:
                call(backend.mqtt_subscribe, one, client)
                subscribed.append(one)
        except HTTPException:
            for one in subscribed:
                backend.mqtt_unsubscribe(one, client)
            raise

        def cleanup():
            for one in subscribed:
                backend.mqtt_unsubscribe(one, client)

        return sse(request, client, [], cleanup)

    @app.get("/api/robots", tags=["robots"])
    def list_robots():
        """Every robot: pose, kind, interface, host (web: hosted here,
        external: someone's own process, replica: a real robot's replica),
        online (false: a replica whose real robot is away), topic_path"""
        return call(backend.list_robots)

    @app.post("/api/robots", tags=["robots"], status_code=201,
              dependencies=write)
    def create_robot(robot: RobotCreate):
        check_name(robot.name)
        if robot.kind not in kinds.KINDS:
            raise HTTPException(422,
                f"kind must be one of {', '.join(kinds.KINDS)}")
        if robot.interface and robot.interface not in kinds.kind_interfaces(robot.kind):
            raise HTTPException(422, f"a {robot.kind} speaks one of "
                                f"{', '.join(kinds.kind_interfaces(robot.kind))}")
        return call(backend.create_robot, robot.name, robot.kind, robot.owner,
                    robot.x, robot.y, robot.heading, interface=robot.interface)

    @app.get("/api/robots/{name}", tags=["robots"])
    def get_robot(name: str):
        check_name(name)
        return call(backend.pose, name)

    @app.get("/api/robots/{name}/interface", tags=["robots"])
    def robot_interface(name: str):
        """The robot with the spec of the interface it speaks (methods,
        example commands, protocol) and its topic path on the bus, for
        calling it over Aiko or raw MQTT"""
        check_name(name)
        return call(backend.robot_info, name)

    @app.get("/api/robots/{name}/wire", tags=["robots"])
    def robot_wire(name: str, command: str):
        """What a chat command becomes on the wire, without sending it:
        the remote function call (method, arguments), the S-expression
        payload and the topic it goes to, plus the Python that would do
        it over Aiko.  The page's aiko and mqtt layers use this"""
        check_name(name)
        info = call(backend.robot_info, name)
        interface = info.get("interface") or kinds.default_interface(info["kind"])
        module = kinds.INTERFACES[interface]
        method, arguments = module.parse_command(command.strip())
        if method is None:
            raise HTTPException(422, arguments)
        wire = [_wire(argument) for argument in arguments]
        payload = "(" + " ".join([method, *wire]) + ")"
        topic_path = info.get("real_topic_path") or info.get("topic_path")
        python = (f"robot = aiko.ServiceFilter(\"*\", \"{name}\", \"*\", \"*\", \"*\", \"*\")  "
                  f"# then do_discovery(...), and on the proxy:\n"
                  f"robot.{method}({', '.join(repr(a) for a in arguments)})")
        return {"name": name, "interface": interface, "method": method,
                "arguments": arguments, "payload": payload,
                "topic": f"{topic_path}/in" if topic_path else None,
                "replica": info.get("host") == "replica", "python": python}

    @app.delete("/api/robots/{name}", tags=["robots"], dependencies=write)
    def destroy_robot(name: str):
        check_name(name)
        return call(backend.destroy_robot, name)

    @app.post("/api/robots/{name}/move", tags=["robots"], dependencies=write)
    def move(name: str, body: MoveRequest):
        """The sandbox's hand, not the robot's interface: move the body
        in world units whatever it speaks.  distance 100 = forward;
        [100, 0, 30] = forward and up (a drone); [0, 50] = sideways (an
        omni base).  Errors if the kind lacks the axis.  To drive a
        robot in its own words use /command"""
        check_name(name)
        if isinstance(body.distance, list) and not 1 <= len(body.distance) <= 3:
            raise HTTPException(422, "distance: a number or 1 to 3 numbers")
        return call(backend.move, name, body.distance, body.username)

    @app.post("/api/robots/{name}/turn", tags=["robots"], dependencies=write)
    def turn(name: str, body: TurnRequest):
        """The sandbox's hand: turn the body, degrees counter-clockwise"""
        check_name(name)
        return call(backend.turn, name, body.angle, body.username)

    @app.post("/api/robots/{name}/reset", tags=["robots"], dependencies=write)
    def reset(name: str, body: Optional[ResetRequest] = None):
        """Put the robot at x, y facing heading (default: the origin),
        on the ground, still.  Every kind, even one that cannot move
        itself (the page does this when you drag a robot)"""
        check_name(name)
        body = body or ResetRequest()
        return call(backend.reset, name, body.username, body.x, body.y,
                    body.heading)

    @app.post("/api/robots/{name}/command", tags=["robots"], dependencies=write)
    def command(name: str, body: CommandRequest):
        """A command in the robot's OWN interface, without the @@mention,
        exactly as the chat takes it: move 100 (robot), move 0.2
        (irobot), action sit (xgo_robot), forward 100 (turtle_robot);
        "help" lists them.  A replica forwards it to the real robot.  The
        reply comes back here as well as in the chat; a command the
        interface lacks is a 422 with the robot's explanation"""
        check_name(name)
        return call(backend.command, name, body.command.strip(), body.username)

    @app.get("/api/robots/{name}/history", tags=["robots"])
    def history(name: str, limit: int = 100):
        check_name(name)
        return call(backend.history, name, max(1, min(limit, 1000)))

    @app.post("/api/chat", tags=["chat"], status_code=202, dependencies=write)
    def send_chat(body: ChatMessage):
        call(backend.send_chat, body.username, body.message,
             body.channel or channel)
        return {"sent": True, "channel": body.channel or channel}

    @app.get("/api/chat", tags=["chat"])
    def chat_history(channel: Optional[str] = None):
        """Recent messages of one channel (default: the robots channel)"""
        return backend.hub.chat_history(channel or app.state.channel)

    @app.get("/api/chat/channels", tags=["chat"])
    def list_channels():
        """Channels this server relays ("following") and the ones the
        ChatServer lists ("known")"""
        return call(backend.channels)

    @app.post("/api/chat/channels", tags=["chat"], status_code=201,
              dependencies=write)
    def follow_channel(body: ChannelRequest):
        """Start relaying a channel: its messages then arrive on /events
        and in GET /api/chat?channel=..."""
        return call(backend.follow_channel, body.channel)

    app.state.channel = channel
    return app
