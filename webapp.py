# The web application (FastAPI): the robots-and-chat page, a REST API for
# creating and driving robots, and one SSE stream of poses and chat.
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
from fastapi.responses import HTMLResponse, StreamingResponse
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
    def create_robot(self, name, kind, owner, x=0.0, y=0.0, heading=0.0): ...
    def place(self, name, x, y, heading, username): ...   # heading None = keep
    def destroy_robot(self, name): ...
    def move(self, name, distance, username): ...
    def turn(self, name, angle, username): ...
    def reset(self, name, username): ...
    def pose(self, name): ...
    def history(self, name, limit): ...         # [event, ...]
    def send_chat(self, username, message, channel=None): ...
    def channels(self): ...                     # {"following": [...], "known": [...]}
    def follow_channel(self, channel): ...      # start relaying a channel
    def system(self): ...                       # {"mqtt": {...}, "services": [...]}
    def mqtt_watch(self, topic, seconds, limit): ...   # [{"topic","payload","timestamp"}]
    def mqtt_publish(self, topic, payload): ...
    def mqtt_subscribe(self, topic, client): ...       # client.put(message) until
    def mqtt_unsubscribe(self, topic, client): ...     # unsubscribed


class EventHub:
    """Fan-out of robot poses, chat messages and status to the page's SSE
    clients, with replay of recent history for a newly connected page"""

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
                 "type": robot.get("kind", kinds.DEFAULT_KIND)}
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
    """An EventHub client for the async SSE route: the hub puts events
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
        description=f"one of {', '.join(kinds.KINDS)} (GET /api/kinds)")
    owner: str = Username
    x: float = Field(default=0.0, description="where it starts")
    y: float = 0.0
    heading: float = 0.0


class PlaceRequest(BaseModel):
    x: float
    y: float
    heading: Optional[float] = Field(default=None, description="omit to keep")
    username: str = Username


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


# -- the app ---------------------------------------------------------------------

_bearer = HTTPBearer(auto_error=False)


def create_app(backend, channel=config.CHANNEL, username=config.WEB_USERNAME,
               agent=config.AGENT_BOTNAME, api_token=config.API_TOKEN,
               api_token_public=config.API_TOKEN_PUBLIC):
    """api_token: when non-empty, every request that changes something
    (POST, DELETE) must carry "Authorization: Bearer <api_token>".
    Reads and the pages stay open.  api_token_public: the token is shown
    on the page and in /api/status, pre-filled, so it is a formality"""

    app = FastAPI(
        title="aiko_turtle",
        description=(
            "Virtual robots in a shared world, driven over REST here or over "
            "Aiko Chat (`@@name move 100` in the channel).  Create a robot "
            "with any name; a longer, unusual name is less likely to clash "
            "with someone else's.  Live poses and chat: GET /events (SSE).  "
            "The human guide, with Aiko and REST examples: /guide."
            + ("  **POST and DELETE need a bearer token** (the Authorize "
               "button)" + (f": `{api_token}`." if api_token_public else
               "; ask for it in the chat.") if api_token else "")),
        version="1.1")
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

    def call(function, *arguments):
        try:
            return function(*arguments)
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

    @app.get("/api/status", tags=["world"])
    def status():
        status = dict(call(backend.status), auth=bool(api_token),
                      channel=channel, agent=agent,
                      streams=len(backend.hub.clients))
        if api_token and api_token_public:
            status["token"] = api_token
        return status

    @app.get("/api/kinds", tags=["robots"])
    def list_kinds():
        """The robot kinds, with the Interfaces and chat commands of each"""
        return kinds.describe()

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
        """Publish one message.  Example: a robot's <Move> is
        {"topic": "<its topic_path>/in", "payload": "(move 100 @me)"}"""
        call(backend.mqtt_publish, body.topic, body.payload)
        return {"published": True, "topic": body.topic}

    @app.get("/api/mqtt/events", tags=["mqtt"], dependencies=write)
    async def mqtt_events(request: Request, topic: str):
        """The same as a stream of server-sent events, until you hang up:
        curl -N '.../api/mqtt/events?topic=aiko/%23&token=...'"""
        client = _AsyncClient(asyncio.get_running_loop())
        call(backend.mqtt_subscribe, topic, client)
        return sse(request, client, [],
                   lambda: backend.mqtt_unsubscribe(topic, client))

    @app.get("/api/robots", tags=["robots"])
    def list_robots():
        return call(backend.list_robots)

    @app.post("/api/robots", tags=["robots"], status_code=201,
              dependencies=write)
    def create_robot(robot: RobotCreate):
        check_name(robot.name)
        if robot.kind not in kinds.KINDS:
            raise HTTPException(422,
                f"kind must be one of {', '.join(kinds.KINDS)}")
        return call(backend.create_robot, robot.name, robot.kind, robot.owner,
                    robot.x, robot.y, robot.heading)

    @app.get("/api/robots/{name}", tags=["robots"])
    def get_robot(name: str):
        check_name(name)
        return call(backend.pose, name)

    @app.delete("/api/robots/{name}", tags=["robots"], dependencies=write)
    def destroy_robot(name: str):
        check_name(name)
        return call(backend.destroy_robot, name)

    @app.post("/api/robots/{name}/move", tags=["drive"], dependencies=write)
    def move(name: str, body: MoveRequest):
        """distance 100 = forward; [100, 0, 30] = forward and up (a drone);
        [0, 50] = sideways (an omni base).  Errors if the kind lacks the axis"""
        check_name(name)
        if isinstance(body.distance, list) and not 1 <= len(body.distance) <= 3:
            raise HTTPException(422, "distance: a number or 1 to 3 numbers")
        return call(backend.move, name, body.distance, body.username)

    @app.post("/api/robots/{name}/turn", tags=["drive"], dependencies=write)
    def turn(name: str, body: TurnRequest):
        check_name(name)
        return call(backend.turn, name, body.angle, body.username)

    @app.post("/api/robots/{name}/place", tags=["drive"], dependencies=write)
    def place(name: str, body: PlaceRequest):
        """Teleport: works for every kind, even one that cannot move itself
        (the page does this when you drag a robot)"""
        check_name(name)
        return call(backend.place, name, body.x, body.y, body.heading,
                    body.username)

    @app.post("/api/robots/{name}/reset", tags=["drive"], dependencies=write)
    def reset(name: str, body: Optional[ResetRequest] = None):
        check_name(name)
        username = body.username if body else "anonymous"
        return call(backend.reset, name, username)

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
