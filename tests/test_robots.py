# The robots package: every interface module keeps the contract, its
# virtual robot implements every function, and its replica dead reckons.
# No Aiko process: the body records the world calls it would make.

import inspect

import pytest

import robots
from robots import base


class RecordingAgent:
    """Stands in for the robot Actor: _world_call records, last_pose is set"""

    def __init__(self):
        self.calls, self.last_pose = [], {"x": 0.0, "y": 0.0, "heading": 0.0, "z": 0.0}
        self.published, self.responses, self.telemetry_period = [], [], 0.0
        self.current_username = "tester"

    def _world_call(self, method, arguments, with_username=True):
        self.calls.append((method, arguments))

    def respond(self, topic_path_response, *fields):
        self.responses.append((topic_path_response, fields))

    def publish_out(self, payload):
        self.published.append(payload)

    def set_telemetry_period(self, period):
        self.telemetry_period = period


def virtual(interface):
    """A virtual robot of one interface, standing alone"""
    module = robots.INTERFACES[interface]
    agent = RecordingAgent()

    class Robot(module.Simulated):
        pass
    robot = Robot()
    robot.body = base.Body(agent)
    robot.apply_op = robot.body.apply
    robot.current_username = "tester"
    robot.respond, robot.publish_out = agent.respond, agent.publish_out
    robot.set_telemetry_period = agent.set_telemetry_period
    return robot, agent


@pytest.mark.parametrize("name", sorted(robots.INTERFACES))
def test_module_contract(name):
    module = robots.INTERFACES[name]
    assert module.NAME == name
    assert module.STATUS in (base.STATUS_REAL, base.STATUS_LEGACY, base.STATUS_PROPOSED)
    for attribute in ("LABEL", "DESCRIPTION", "UNITS", "PROTOCOL", "SOURCE"):
        assert isinstance(getattr(module, attribute), str), attribute
    specs = base.method_specs(module.Interface)
    assert specs, "an interface with no functions"
    for spec in specs:                       # the virtual robot answers every function
        method = getattr(module.Simulated, spec["name"], None)
        assert callable(method), f"{name}.Simulated lacks {spec['name']}"
        assert spec["doc"], f"{name}.{spec['name']} has no docstring (the spec people read)"
    for example, help_text in module.COMMANDS:
        method, arguments = module.parse_command(example)
        assert method is not None, f"{name}: example {example!r} does not parse: {arguments}"
        assert method in {spec["name"] for spec in specs} or method == "generic"
        assert help_text
    assert module.parse_command("definitely not a command xyz")[0] is None
    assert module.parse_command("")[0] is None
    match = getattr(module, "MATCH", None)
    assert match is None or (isinstance(match, dict) and (match.get("name") or match.get("protocol")))
    if module.STATUS == base.STATUS_REAL:
        assert match, "a real interface says how to find the real robot"
        assert callable(getattr(module, "observe", None)), "a real interface dead reckons its replica"


def test_kinds_and_resolution():
    assert list(robots.KINDS)[:4] == ["turtle", "lolibot", "xgo", "irobot"]
    assert robots.resolve("turtle", None) == ("turtle", "turtle_robot")   # the tutorial's, by default
    assert robots.resolve("lekiwi", None) == ("lekiwi", "robot")
    assert robots.protocol_version("a/b/xgo_robot:0") == "0" and robots.protocol_version("") is None
    assert robots.resolve("xgo", None) == ("xgo", "xgo_robot")        # the real one first
    assert robots.resolve("turtle", "turtle_robot") == ("turtle", "turtle_robot")
    with pytest.raises(ValueError):
        robots.resolve("pi", "xgo_robot")
    with pytest.raises(ValueError):
        robots.resolve("submarine", None)
    assert robots.replica_kind("irobot") == "irobot" and robots.replica_kind("xgo_robot") == "xgo"
    for kind in robots.describe_kinds():
        assert kind["interfaces"][0] == kind["interface"]
        assert kind["sprite"] and kind["axes"] in (0, 1, 2, 3)
    assert "move=0" in robots.tags("robot", "turtle")
    assert "move=0" not in robots.tags("robot", "pi")
    module = robots.INTERFACES["robot"]
    assert module.PROTOCOL.endswith("/robot:0") and module.MATCH == {"protocol": module.PROTOCOL}


def test_aiko_native_virtual_robot():
    robot, agent = virtual("robot")
    assert robot.move(100) is None and agent.calls[-1] == ("apply_move", [[100.0, 0.0, 0.0]])
    robot.move("0 50"); assert agent.calls[-1] == ("apply_move", [[0.0, 50.0, 0.0]])
    robot.turn(90); assert agent.calls[-1] == ("apply_turn", [90.0])
    assert "forward" in robot.move("1 2 3 4")
    assert robot.grasp() and robot.gripper == "closed"
    assert robot.release() and robot.gripper == "open"
    module = robots.INTERFACES["robot"]
    assert module.parse_command("move 100") == ("move", ["100"])
    assert module.parse_command("move 0 50") == ("move", [["0", "50"]])
    assert module.parse_command("battery") == ("get_telemetry", [])
    assert module.parse_command("grab") == ("grasp", [])


def test_legacy_turtle_robot():
    module = robots.INTERFACES["turtle_robot"]
    assert module.STATUS == base.STATUS_LEGACY
    assert module.PROTOCOL.endswith("turtle_robot:0")
    robot, agent = virtual("turtle_robot")
    robot.forward(100); assert agent.calls[-1] == ("apply_move", [[100.0, 0.0, 0.0]])
    robot.left(90); assert agent.calls[-1] == ("apply_turn", [90.0])
    robot.right(90); assert agent.calls[-1] == ("apply_turn", [-90.0])
    robot.backward(10); assert agent.calls[-1] == ("apply_move", [[-10.0, 0.0, 0.0]])
    assert module.parse_command("forward 100") == ("forward", ["100"])
    assert "turtle" in robots.describe_interface("turtle_robot")["kinds"]


def test_irobot_as_it_is():
    module = robots.INTERFACES["irobot"]
    assert module.STATUS == base.STATUS_REAL and module.MATCH == {"name": "robot"}
    names = {spec["name"] for spec in base.method_specs(module.Interface)}
    assert {"move", "turn", "stop", "drive", "arc", "goto", "dock", "undock",
            "telemetry", "led", "beep", "battery", "pose", "sensors"} <= names
    robot, agent = virtual("irobot")
    robot.move(1)                                           # one metre
    assert agent.calls[-1] == ("apply_move", [[100.0, 0.0, 0.0]])
    robot.turn(90); assert agent.calls[-1] == ("apply_turn", [90.0])
    robot.battery("aiko/x/y/z/reply")                       # a query answers on the reply topic
    assert agent.responses and agent.responses[-1][0] == "aiko/x/y/z/reply"
    assert module.parse_command("move 0.5") == ("move", ["0.5"])
    for word in ("power_off", "e_stop 1", "terminate", "reset_pose"):
        method, error = module.parse_command(word)
        assert method is None or method != "power_off", word
    # dead reckoning for the replica: in commands move it, an out pose wins
    state = {}
    assert robots.observe("irobot", "in", "move", ["1"], state) == [("move", 100.0, 0.0, 0.0)]
    assert robots.observe("irobot", "in", "turn", ["-45"], state) == [("turn", -45.0)]
    assert robots.observe("irobot", "out", "pose", ["1", "2", "90"], state) == [("place", 100.0, 200.0, 90.0)]
    assert robots.observe("irobot", "in", "move", ["1"], state) == []   # the pose stream is fresh
    assert robots.observe("irobot", "out", "hazard", ["bump"], state) == [("stop",)]
    assert robots.observe("irobot", "in", "nonsense", [], {}) == []
    assert robots.observe("irobot", "in", "move", ["far"], {}) == []     # bad numbers never raise


def test_xgo_as_it_is():
    module = robots.INTERFACES["xgo_robot"]
    assert module.STATUS == base.STATUS_REAL and module.PROTOCOL.endswith("xgo_robot:0")
    robot, agent = virtual("xgo_robot")
    robot.move("x", 100)                                    # 100 mm strides, until stop
    assert agent.calls[-1][0] == "apply_drive"
    robot.stop(); assert agent.calls[-1][0] == "apply_stop"
    assert module.parse_command("move x 100") == ("move", ["x", "100"])
    assert module.parse_command("action sit") == ("action", ["sit"])
    assert module.parse_command("action 2")[0] is None             # names, from the dog's table
    assert robots.observe("xgo_robot", "in", "stop", [], {}) == [("stop",)]
    ops = robots.observe("xgo_robot", "in", "move", ["x", "100"], {})
    assert ops and ops[0][0] == "drive_vector" and ops[0][1] > 0
    assert robots.observe("xgo_robot", "out", "move", ["x", "100"], {}) == []   # echoes do not count twice


def test_lolibot_proposed_firmware_words():
    module = robots.INTERFACES["lolibot"]
    assert module.STATUS == base.STATUS_PROPOSED
    robot, agent = virtual("lolibot")
    robot.forward(2); assert agent.calls[-1][0] == "apply_drive"
    robot.stop(); assert agent.calls[-1][0] == "apply_stop"
    assert module.parse_command("forward") == ("forward", [])
    assert module.parse_command("left 1") == ("left", ["1"])


def test_body_ops_and_method_specs():
    agent = RecordingAgent()
    body = base.Body(agent)
    body.apply(("move", 1, 2, 3)); assert agent.calls[-1] == ("apply_move", [[1, 2, 3]])
    body.apply(("place", 1, 2, 3)); assert agent.calls[-1][0] == "reset"
    body.apply(("pen", False)); assert agent.calls[-1] == ("set_pen", ["up"])
    assert "unknown op" in body.apply(("fly",))
    specs = base.method_specs(robots.INTERFACES["robot"].Interface)
    assert [spec["name"] for spec in specs][:1] and all("(" in spec["signature"] for spec in specs)
    assert base.number("1.5", "x") == 1.5
    with pytest.raises(ValueError):
        base.number("inf", "x")
