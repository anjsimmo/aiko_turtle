import math

import pytest

from world_model import World, WorldError, parse_pose_text, pose_text


def test_create_move_turn_reset():
    world = World("sqlite://")
    assert world.create("t1") == {"name": "t1", "kind": "turtle",
        "owner": "anonymous", "host": "external",
        "x": 0.0, "y": 0.0, "heading": 0.0, "z": 0.0}
    assert world.turn("t1", "90")["heading"] == 90.0
    pose = world.move("t1", 100)
    assert (pose["x"], pose["y"]) == (0.0, 100.0)
    world.turn("t1", -450)                   # wraps modulo 360
    pose = world.move("t1", 10)
    assert pose["heading"] == 0.0 and pose["x"] == 10.0
    world.turn("t1", 180)
    pose = world.move("t1", 10)              # back to x=0, never "-0.0"
    assert math.copysign(1, pose["x"]) == 1 and pose["x"] == 0.0
    assert world.reset("t1") == dict(pose, x=0.0, y=0.0, heading=0.0)


def test_state_survives_a_restart():
    world = World("sqlite://")
    database = world.database
    world.create("t1", kind="xgo", owner="anj")
    world.move("t1", 50)
    reloaded = World.__new__(World)         # same database, fresh memory
    reloaded.database, reloaded.listener = database, None
    reloaded.robots = {r["name"]: r for r in database.list_robots()}
    assert reloaded.get("t1")["x"] == 50.0
    assert reloaded.get("t1")["kind"] == "xgo"
    assert reloaded.get("t1")["owner"] == "anj"


def test_history_and_destroy():
    changes = []
    world = World("sqlite://", listener=lambda e, r: changes.append(e))
    world.create("t1")
    world.move("t1", 1, username="alice")
    world.turn("t1", 2, username="bob")
    history = world.history("t1")
    assert [(h["username"], h["command"], h["argument"]) for h in history] \
        == [("anonymous", "create", "turtle"), ("alice", "move", "1.0"),
            ("bob", "turn", "2.0")]
    world.destroy("t1")
    assert world.list() == []
    assert changes == ["created", "moved", "moved", "destroyed"]
    with pytest.raises(WorldError):
        world.get("t1")


def test_errors():
    world = World("sqlite://")
    with pytest.raises(WorldError):
        world.move("ghost", 1)
    with pytest.raises(WorldError):
        world.create("bad_kind", kind="submarine")
    world.create("t1")
    with pytest.raises(WorldError):
        world.move("t1", "far")
    with pytest.raises(WorldError):
        world.move("t1", math.inf)
    assert world.create("t1", kind="xgo")["kind"] == "turtle"  # idempotent


def test_pose_text_round_trip():
    record = {"x": 1.5, "y": -2.0, "heading": 270.0, "kind": "arrow", "z": 4.0}
    assert pose_text(record) == "(1.500 -2.000 270.000 arrow 4.000)"
    assert parse_pose_text(pose_text(record)) == record
    assert parse_pose_text(["1", "2", "3"]) == \
        {"x": 1.0, "y": 2.0, "heading": 3.0, "kind": "turtle", "z": 0.0}
    assert parse_pose_text("nonsense") is None


def test_move_as_a_vector_in_the_robot_frame():
    from world_model import World, WorldError, parse_pose_text, pose_text
    world = World("sqlite://")
    world.create("d", "drone")
    world.turn("d", 90)                                  # facing +y
    pose = world.move("d", [10, 5, 25])                  # forward, left, up
    assert (pose["x"], pose["y"], pose["z"]) == (-5.0, 10.0, 25.0)
    assert world.move("d", [0, 0, -100])["z"] == 0.0     # never underground
    assert world.move("d", "3")["y"] == 13.0             # a plain number: forward
    assert world.move("d", ["1", "0", "0"])["y"] == 14.0 # strings off the wire
    world.create("t", "turtle")
    with pytest.raises(WorldError, match="cannot move left"):
        world.move("t", [1, 1])
    world.create("p", "pi")
    with pytest.raises(WorldError, match="cannot move"):
        world.move("p", 1)
    world.move("d", [0, 0, 7.5])
    assert parse_pose_text(pose_text(world.get("d")))["z"] == 7.5
    assert parse_pose_text("(1 2 3 turtle)")["z"] == 0.0  # an older world's share


def test_migration_adds_z_to_an_old_database(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE robots (name VARCHAR(64) PRIMARY KEY,
            kind VARCHAR(32) NOT NULL, owner VARCHAR(64) NOT NULL,
            host VARCHAR(32) NOT NULL, x FLOAT NOT NULL, y FLOAT NOT NULL,
            heading FLOAT NOT NULL, created_at FLOAT NOT NULL,
            updated_at FLOAT NOT NULL)""")
        connection.execute("""INSERT INTO robots VALUES
            ('old', 'turtle', 'a', 'web', 1, 2, 3, 0, 0)""")
    from world_model import World
    world = World(f"sqlite:///{path}")
    assert world.get("old")["z"] == 0.0
    assert world.move("old", 1)["z"] == 0.0
