from core import RateLimiter, parse_actions, valid_robot_name


def test_parse_actions():
    output = """(say Drawing a square)
(command @@t1 move 100)
garbage line
  (command @@t1 turn 90)
(think not allowed)"""
    assert parse_actions(output) == [
        ("say", "Drawing a square"), ("command", "@@t1 move 100"),
        ("command", "@@t1 turn 90")]
    assert parse_actions("") == []


def test_rate_limiter_per_user_and_global():
    now = [0.0]
    limiter = RateLimiter(per_minute=3, per_key_per_minute=2,
                          clock=lambda: now[0])
    assert limiter.allow("alice") and limiter.allow("alice")
    assert not limiter.allow("alice")          # alice's bucket is empty
    assert limiter.allow("bob")                # global has one left
    assert not limiter.allow("bob")            # global is empty
    now[0] += 60                               # a minute refills both
    assert limiter.allow("alice")


def test_valid_robot_name():
    assert valid_robot_name("my_turtle-2")
    assert not valid_robot_name("")
    assert not valid_robot_name("_leading")
    assert not valid_robot_name("has space")
    assert not valid_robot_name("a" * 65)


def test_kinds():
    from kinds import KINDS, kind_axes, kind_commands, kind_interfaces, supports
    assert set(KINDS) >= {"turtle", "lolibot", "xgo", "irobot", "lekiwi", "so101", "drone", "pi"}
    assert supports("turtle", "forward") and not supports("turtle", "move")   # legacy words
    assert supports("turtle", "move", "robot") and not supports("pi", "move")
    assert supports("so101", "grasp") and not supports("turtle", "grasp")
    assert (kind_axes("turtle"), kind_axes("lekiwi"), kind_axes("drone"), kind_axes("pi")) == (1, 2, 3, 0)
    assert kind_commands("pi") == ["look", "telemetry"]        # no <Move>
    assert kind_interfaces("turtle") == ["turtle_robot", "robot"]  # legacy before proposed
    assert kind_interfaces("xgo")[0] == "xgo_robot"             # the real one first
