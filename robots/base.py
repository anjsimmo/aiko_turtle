# What every robot module in this package may use: the Body a simulated
# robot acts on, the status words, and the helpers that turn an Interface
# class into a spec people can read.
#
# A robot module (robots/NAME.py) is one file that says everything about
# one robot interface, real or virtual.  See robots/__init__.py for the
# contract and robots/_template.py for a copy-and-edit start.

import inspect
import math
import sys

STATUS_REAL = "real"            # a physical robot speaks this today
STATUS_LEGACY = "legacy"        # an older tutorial / robot speaks this
STATUS_PROPOSED = "proposed"    # a design, nothing physical speaks it yet
STATUSES = (STATUS_REAL, STATUS_LEGACY, STATUS_PROPOSED)

# World units are centimetres: a turtle "move 100" is a metre, an iRobot
# "move 0.2" (metres) is 20 units, an XGO stride of 25 mm is 2.5
UNITS_PER_METRE = 100.0
UNITS_PER_MM = 0.1


class Body:
    """What a Simulated robot can do to its body in the VirtualWorld.
    Each call is relayed to the world, which replies with the new pose
    (the reply is relayed to the chat and to the caller of the REST API).
    The methods return None (the world answers) or a string reply"""

    def __init__(self, agent):
        self.agent = agent

    def move(self, forward, left=0.0, up=0.0):
        """Translate in the robot's own frame, instantly"""
        return self.agent._world_call(
            "apply_move", [[forward, left, up]])

    def turn(self, degrees):
        """Rotate counter-clockwise, instantly"""
        return self.agent._world_call("apply_turn", [degrees])

    def place(self, x, y, heading=0.0):
        """Teleport, in world units"""
        return self.agent._world_call("reset", [x, y, heading])

    def drive(self, linear, angular=0.0, seconds=0.0):
        """Start moving at linear units/s forward and angular degrees/s
        counter-clockwise, for seconds (0 = until stop())"""
        return self.agent._world_call(
            "apply_drive", [linear, 0.0, angular, seconds])

    def drive_vector(self, forward, left, angular=0.0, seconds=0.0):
        """drive() with a sideways component too (omni bases, walkers)"""
        return self.agent._world_call(
            "apply_drive", [forward, left, angular, seconds])

    def stop(self):
        return self.agent._world_call("apply_stop", [])

    def apply(self, op):
        """One of the ops a module's observe() returns, applied here"""
        match op:
            case ("move", forward, left, up):
                return self.move(forward, left, up)
            case ("turn", degrees):
                return self.turn(degrees)
            case ("place", x, y, heading):
                return self.place(x, y, heading)
            case ("drive", linear, angular, seconds):
                return self.drive(linear, angular, seconds)
            case ("drive_vector", forward, left, angular, *rest):
                return self.drive_vector(forward, left, angular, *rest)
            case ("stop",):
                return self.stop()
            case ("pen", down):
                return self.pen(down)
        return f"unknown op {op!r}"

    def pen(self, down):
        """Draw a trail or not (the legacy turtle's penup / pendown)"""
        return self.agent._world_call("set_pen", ["down" if down else "up"])

    def pose(self):
        """Ask the world for the pose; it replies to the chat"""
        return self.agent._world_call("get_pose", [])

    @property
    def last_pose(self):
        """The last pose the world reported, {"x", "y", "heading", "z"}
        or None"""
        return self.agent.last_pose


def method_specs(interface_class):
    """The abstract methods of an Interface class (and the Interfaces it
    is composed of), as [{name, signature, doc}] in definition order: the
    spec a person reads on the page"""
    specs, seen = [], set()
    for klass in reversed(interface_class.__mro__):
        if klass.__module__ in ("abc", "builtins") or  \
                klass.__module__.startswith("aiko_services"):
            continue
        for name, member in vars(klass).items():
            if name.startswith("_") or not inspect.isfunction(member):
                continue
            if not getattr(member, "__isabstractmethod__", False) or name in seen:
                continue
            seen.add(name)
            parameters = list(inspect.signature(member).parameters.values())[1:]
            signature = ", ".join(str(parameter) for parameter in parameters)
            specs.append({"name": name, "signature": f"({signature})",
                          "doc": inspect.getdoc(member) or "",
                          "interface": klass.__name__})
    return specs


def number(value, what="value", default=None):
    """float() with a readable error; None/"nil" -> default"""
    if value in (None, "nil", "") and default is not None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number, not {value!r}")
    if not math.isfinite(result):
        raise ValueError(f"{what} must be finite")
    return result


def unimplemented(interface_name, method_name):
    """A placeholder for the composition machinery: every Interface needs
    a registered default implementation; a real Actor's concrete methods
    always win over these"""
    def method(self, *args, **kwargs):
        raise NotImplementedError(
            f"<{interface_name}> {method_name}() not implemented")
    method.__name__ = method_name
    return method


def default_implementation(interface_class, alias=None):
    """Build and register the placeholder implementation of an Interface
    class, so compose_instance() accepts an Actor that inherits it.
    Returns the placeholder class (module-level, so it is importable)"""
    import aiko_services as aiko
    name = alias or interface_class.__name__
    methods = {spec["name"]: unimplemented(name, spec["name"])
               for spec in method_specs(interface_class)}
    default = type(f"{interface_class.__name__}Default",
                   (interface_class,), methods)
    default.__module__ = interface_class.__module__
    # compose_instance() imports the placeholder by "module.ClassName",
    # so it must be an attribute of the module, not just a local
    setattr(sys.modules[interface_class.__module__], default.__name__, default)
    aiko.Interface.default(
        name, f"{interface_class.__module__}.{default.__name__}")
    return default
