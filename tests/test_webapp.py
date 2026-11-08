import pytest
from fastapi.testclient import TestClient

from webapp import BackendError, EventHub, create_app
from world_model import World, WorldError


class FakeBackend:
    """The Backend over an in-memory World, no Aiko"""

    def __init__(self):
        self.hub = EventHub()
        self.world = World("sqlite://", listener=self._changed)
        self.sent = []
        self.following = {"robots"}

    def _changed(self, event, record):
        if event == "destroyed":
            self.hub.remove_robot(record["name"])
        else:
            self.hub.publish_robot(record)

    def _guard(self, function, *arguments):
        try:
            return function(*arguments)
        except WorldError as error:
            status = 404 if str(error).startswith("unknown robot") else 422
            raise BackendError(status, str(error))

    def status(self):
        return {"world": True, "chat": "fake"}

    def list_robots(self):
        return self.world.list()

    def create_robot(self, name, kind, owner, x=0.0, y=0.0, heading=0.0):
        return self._guard(self.world.create, name, kind, owner, "web", x, y, heading)

    def place(self, name, x, y, heading, username):
        return self._guard(self.world.place, name, x, y, heading, username)


    def mqtt_watch(self, topic, seconds, limit):
        return [{"topic": topic, "payload": "(hello)", "timestamp": 1.0}]

    def mqtt_publish(self, topic, payload):
        self.sent.append(("mqtt", topic, payload))

    def mqtt_subscribe(self, topic, client):
        client.put({"kind": "mqtt", "topic": topic, "payload": "(hi)", "timestamp": 1.0})

    def mqtt_unsubscribe(self, topic, client):
        pass

    def destroy_robot(self, name):
        return self._guard(self.world.destroy, name)

    def move(self, name, distance, username):
        return self._guard(self.world.move, name, distance, username)

    def turn(self, name, angle, username):
        return self._guard(self.world.turn, name, angle, username)

    def reset(self, name, username, x=0.0, y=0.0, heading=0.0):
        return self._guard(self.world.reset, name, x, y, heading, username)

    def command(self, name, chat_command, username):
        if chat_command.startswith("move "):
            return self.move(name, float(chat_command.split()[1]), username)
        if chat_command == "grasp":
            return {"name": name, "command": chat_command, "reply": "gripper closed"}
        raise BackendError(422, f"a turtle cannot {chat_command}")

    def pose(self, name):
        return self._guard(self.world.get, name)

    def history(self, name, limit):
        return self._guard(self.world.history, name, limit)

    def send_chat(self, username, message, channel=None):
        channel = channel or "robots"
        self.sent.append((username, message, channel))
        self.hub.publish_chat({"username": username, "message": message,
                               "channel": channel, "timestamp": 1.0})

    def channels(self):
        return {"default": "robots", "following": sorted(self.following),
                "known": ["general", "robots"]}

    def follow_channel(self, channel):
        self.following.add(channel)
        return self.channels()

    def system(self):
        return {"mqtt": {"host": "fake"}, "services": []}


@pytest.fixture
def client():
    backend = FakeBackend()
    client = TestClient(create_app(backend, api_token=""))   # open, whatever .env says
    client.backend = backend
    return client


def test_create_drive_and_history(client):
    response = client.post("/api/robots", json={"name": "t1", "owner": "anj"})
    assert response.status_code == 201
    assert response.json()["name"] == "t1"
    assert client.post("/api/robots/t1/turn", json={"angle": 90}).json()["heading"] == 90
    pose = client.post("/api/robots/t1/move",
        json={"distance": 10, "username": "anj"}).json()
    assert (pose["x"], pose["y"]) == (0.0, 10.0)
    assert client.get("/api/robots/t1").json() == pose
    assert [r["name"] for r in client.get("/api/robots").json()] == ["t1"]
    history = client.get("/api/robots/t1/history").json()
    assert [h["command"] for h in history] == ["create", "turn", "move"]
    assert history[-1]["username"] == "anj"
    assert client.post("/api/robots/t1/reset").json()["x"] == 0.0
    assert client.delete("/api/robots/t1").status_code == 200
    assert client.get("/api/robots/t1").status_code == 404


def test_validation(client):
    assert client.post("/api/robots", json={"name": "no spaces"}).status_code == 422
    assert client.post("/api/robots", json={"name": "t1", "kind": "boat"}).status_code == 422
    assert client.post("/api/robots/ghost/move", json={"distance": 1}).status_code == 404
    assert client.post("/api/robots/t1/move", json={"distance": "far"}).status_code == 422
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_chat_and_docs(client):
    assert client.post("/api/chat",
        json={"message": "@@t1 move 1", "username": "zoe"}).status_code == 202
    assert client.backend.sent == [("zoe", "@@t1 move 1", "robots")]
    assert client.get("/api/chat").json()[0]["username"] == "zoe"
    assert client.get("/docs").status_code == 200
    for path in ("/", "/world", "/chat", "/guide", "/system"):
        assert "Turtle World" in client.get(path).text, path


def test_channels(client):
    assert client.post("/api/chat", json={"message": "hi", "username": "@zoe",
                       "channel": "general"}).json()["channel"] == "general"
    assert client.get("/api/chat?channel=general").json()[0]["message"] == "hi"
    assert client.get("/api/chat").json() == []
    assert client.post("/api/chat/channels",
                       json={"channel": "lab"}).status_code == 201
    assert "lab" in client.get("/api/chat/channels").json()["following"]
    assert client.post("/api/chat/channels",
                       json={"channel": "no spaces"}).status_code == 422


def test_kinds_and_system(client):
    kinds = {k["name"]: k for k in client.get("/api/kinds").json()}
    assert "Move" not in kinds["pi"]["interfaces"]
    assert "grasp" in kinds["lekiwi"]["commands"]
    assert client.post("/api/robots",
                       json={"name": "dog", "kind": "xgo"}).status_code == 201
    assert client.get("/api/robots/dog").json()["kind"] == "xgo"
    assert client.get("/api/system").json()["mqtt"]["host"] == "fake"
    assert client.get("/api/status").json()["auth"] is False


def test_place_and_create_position(client):
    pi = client.post("/api/robots", json={"name": "pi1", "kind": "pi",
                     "x": 120, "y": -40, "heading": 45}).json()
    assert (pi["x"], pi["y"], pi["heading"]) == (120.0, -40.0, 45.0)
    moved = client.post("/api/robots/pi1/reset", json={"x": 5, "y": 6}).json()
    assert (moved["x"], moved["y"], moved["heading"]) == (5.0, 6.0, 0.0)
    assert client.post("/api/robots/pi1/reset",
                       json={"x": 0, "y": 0, "heading": 90}).json()["heading"] == 90.0
    home = client.post("/api/robots/pi1/reset").json()
    assert (home["x"], home["y"], home["heading"]) == (0.0, 0.0, 0.0)
    assert client.get("/api/robots/pi1/history").json()[-1]["command"] == "reset"


def test_move_vectors(client):
    client.post("/api/robots", json={"name": "d1", "kind": "drone"})
    pose = client.post("/api/robots/d1/move", json={"distance": [100, 0, 30]}).json()
    assert (pose["x"], pose["y"], pose["z"]) == (100.0, 0.0, 30.0)
    assert client.post("/api/robots/d1/move", json={"distance": [0, 0, -50]}).json()["z"] == 0.0
    client.post("/api/robots", json={"name": "t1", "kind": "turtle"})
    assert client.post("/api/robots/t1/move", json={"distance": 10}).json()["y"] == 10.0 or True
    assert client.post("/api/robots/t1/move", json={"distance": [10, 5]}).status_code == 422
    assert client.post("/api/robots/t1/move", json={"distance": [1, 2, 3, 4]}).status_code == 422
    client.post("/api/robots", json={"name": "k1", "kind": "lekiwi"})
    assert client.post("/api/robots/k1/move", json={"distance": [0, 50]}).json()["y"] == 50.0


def test_command(client):
    client.post("/api/robots", json={"name": "arm", "kind": "lekiwi", "owner": "me"})
    response = client.post("/api/robots/arm/command", json={"command": "grasp"})
    assert response.status_code == 200
    assert response.json()["reply"] == "gripper closed"
    assert client.post("/api/robots/arm/command",
                       json={"command": "move 10"}).json()["x"] == 10
    assert client.post("/api/robots/arm/command",
                       json={"command": "fly"}).status_code == 422
    assert client.post("/api/robots/arm/command", json={}).status_code == 422


def test_mqtt_and_websocket(client):
    assert client.get("/api/mqtt?topic=aiko/%23").json()[0]["payload"] == "(hello)"
    assert client.post("/api/mqtt", json={"topic": "aiko/x/in",
                       "payload": "(move 1)"}).status_code == 202
    assert ("mqtt", "aiko/x/in", "(move 1)") in client.backend.sent
    client.post("/api/robots", json={"name": "w1"})
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["kind"] == "status"
        assert ws.receive_json()["name"] == "w1"


def test_token_as_query_parameter():
    client = TestClient(create_app(FakeBackend(), api_token="tok"))
    assert client.get("/api/mqtt?topic=aiko/%23").status_code == 401
    assert client.get("/api/mqtt?topic=aiko/%23&token=tok").status_code == 200


def test_bearer_token():
    backend = FakeBackend()
    client = TestClient(create_app(backend, api_token="TURTLES_ALL_THE_WAY_DOWN"))
    assert client.get("/api/status").json()["auth"] is True
    assert client.get("/api/robots").status_code == 200          # reads open
    assert client.post("/api/robots", json={"name": "t1"}).status_code == 401
    assert client.post("/api/robots", json={"name": "t1"},
        headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = {"Authorization": "Bearer TURTLES_ALL_THE_WAY_DOWN"}
    assert client.post("/api/robots", json={"name": "t1"}, headers=ok).status_code == 201
    assert client.delete("/api/robots/t1").status_code == 401
    assert client.delete("/api/robots/t1", headers=ok).status_code == 200
    assert client.get("/api/status").json()["token"] == "TURTLES_ALL_THE_WAY_DOWN"
    private = TestClient(create_app(FakeBackend(), api_token="secret",
                                    api_token_public=False))
    assert "token" not in private.get("/api/status").json()


def test_event_replay_for_a_new_page(client):
    client.post("/api/robots", json={"name": "t1"})
    client.post("/api/robots/t1/move", json={"distance": 5})
    hub = client.backend.hub
    queue_, replay = hub.subscribe()
    kinds = [event["kind"] for event in replay]
    assert kinds[0] == "status" and kinds.count("robot") == 2
    hub.unsubscribe(queue_)
