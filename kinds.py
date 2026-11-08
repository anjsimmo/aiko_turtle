# The robot kinds: what a robot in the world can be.  Each kind has a
# sprite the page knows how to draw (static/index.html, drawSprite) and
# the Interfaces it implements, which decide the chat commands it accepts
# and the aspect tags it registers with.
#
# To add a kind: one entry here, one sprite function in the page, and a
# pull request.  See README "Adding a robot kind".

KINDS = {
    "turtle": {
        "label": "Turtle",
        "description": "the classic drawing turtle: moves, turns, leaves a trail",
        "interfaces": ["Move", "Perceive", "Telemetry"],
    },
    "lolibot": {
        "label": "LoliBot / BeetleBot",
        "description": "the OHC two-wheel ESP32 robot (openhardwareconf.org/wiki/LoliBot) "
                       "and Jon Oxer's BeetleBot",
        "interfaces": ["Move", "Perceive", "Telemetry"],
    },
    "xgo": {
        "label": "XGO robot dog",
        "description": "quadruped with camera and microphone",
        "interfaces": ["Move", "Perceive", "Telemetry"],
    },
    "lekiwi": {
        "label": "LeKiwi",
        "description": "LeRobot's three-wheel omni base carrying an SO-101 arm",
        "interfaces": ["Move", "Grasp", "Perceive", "Telemetry"],
    },
    "so101": {
        "label": "LeRobot SO-101 arm",
        "description": "a fixed arm with a gripper: it grasps, it does not drive",
        "interfaces": ["Grasp", "Perceive", "Telemetry"],
    },
    "drone": {
        "label": "Drone",
        "description": "a generic quadcopter; in this flat world it moves in 2D",
        "interfaces": ["Move", "Perceive", "Telemetry"],
    },
    "pi": {
        "label": "Raspberry Pi",
        "description": "a Pi with a small display, speaker and microphone: senses, does not move",
        "interfaces": ["Perceive", "Telemetry"],
    },
    "arrow": {
        "label": "Arrow",
        "description": "a plain marker, for when the robot is the point and not the picture",
        "interfaces": ["Move", "Perceive", "Telemetry"],
    },
}

DEFAULT_KIND = "turtle"

# Which Interface each chat command needs (core.parse_command names)
COMMAND_INTERFACES = {
    "move": "Move", "turn": "Move", "stop": "Move", "reset": "Move",
    "grasp": "Grasp", "release": "Grasp",
    "look": "Perceive",
    "telemetry": "Telemetry",
    "interfaces": None, "join": None,       # every robot
}


def kind_interfaces(kind):
    return list(KINDS.get(kind, KINDS[DEFAULT_KIND])["interfaces"])


def supports(kind, command):
    interface = COMMAND_INTERFACES.get(command)
    return interface is None or interface in kind_interfaces(kind)


def kind_commands(kind):
    """The chat commands a kind accepts, in the order of core.COMMANDS"""
    return [command for command in COMMAND_INTERFACES if supports(kind, command)]


def describe():
    """For /api/kinds and the page"""
    return [dict(name=name, **spec, commands=kind_commands(name))
            for name, spec in KINDS.items()]
