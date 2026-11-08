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

    def create_robot(self, name, kind, owner):
        return self._guard(self.world.create, name, kind, owner, "web")

    def destroy_robot(self, name):
        return self._guard(self.world.destroy, name)

    def move(self, name, distance, username):
        return self._guard(self.world.move, name, distance, username)

    def turn(self, name, angle, username):
        return self._guard(self.world.turn, name, angle, username)

    def reset(self, name, username):
        return self._guard(self.world.reset, name, username)

    def pose(self, name):
        return self._guard(self.world.get, name)

    def history(self, name, limit):
        return self._guard(self.world.history, name, limit)

    def send_chat(self, username, message):
        self.sent.append((username, message))
        self.hub.publish_chat({"username": username, "message": message,
                               "timestamp": 1.0})


@pytest.fixture
def client():
    backend = FakeBackend()
    client = TestClient(create_app(backend))
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
    assert client.backend.sent == [("zoe", "@@t1 move 1")]
    assert client.get("/api/chat").json()[0]["username"] == "zoe"
    assert client.get("/docs").status_code == 200
    assert "Turtle World" in client.get("/").text


def test_event_replay_for_a_new_page(client):
    client.post("/api/robots", json={"name": "t1"})
    client.post("/api/robots/t1/move", json={"distance": 5})
    hub = client.backend.hub
    queue_, replay = hub.subscribe()
    kinds = [event["kind"] for event in replay]
    assert kinds[0] == "status" and kinds.count("robot") == 2
    hub.unsubscribe(queue_)
