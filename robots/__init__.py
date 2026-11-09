# The robots: one module per robot interface, real or virtual, found by
# listing this package.  Adding a robot is adding one file here (and a
# sprite in static/sprites/); nothing else needs editing.
#
# A module describes ONE interface: the functions a robot accepts on its
# "/in" topic, exactly as the robot speaks them today.  Real robots are
# described as they are (the iRobot's "move 0.2" in metres, the XGO's
# "action sit"), not as a future design might wish them to be.  Each
# module may add KINDS: bodies (a sprite and how many axes it moves in)
# that speak the interface by default.
#
# Module contract (see _template.py for a copy-and-edit start):
#
#   NAME         interface id, [a-z0-9_]+ (also the "interface=" tag)
#   LABEL, DESCRIPTION, STATUS (base.STATUS_*), UNITS (what numbers mean)
#   PROTOCOL     the Aiko protocol string the robot registers with ("" if
#                unknown); a virtual robot registers with the same one
#   SOURCE       where the interface was taken from (a file, a repo, a person)
#   Interface    aiko.Interface subclass: the abstract methods, docstrings
#                are the spec people read on the page
#   Simulated    mixin with concrete methods: the virtual robot, acting on
#                self.body (base.Body); returns a reply string or None
#   parse_command(text) -> (method, args) or (None, error): chat -> call
#   COMMANDS     [(example, help)] shown as buttons and in the guide
#   MATCH        how to find real robots in the Registrar:
#                {"name": ..., "protocol": ...} (either may be omitted);
#                None = nothing physical speaks it yet
#   observe(direction, command, args, state) -> [op, ...]   (optional)
#                dead reckoning for the replica of a real robot: what a
#                message on its "in" or "out" topic says about its pose;
#                ops: ("move", fwd, left, up) ("turn", deg) ("place", x, y, h)
#                ("drive", linear, angular, seconds) ("stop",) ("pen", bool)
#   KINDS        {kind: {label, description, axes, sprite?}} bodies this
#                module introduces (optional)
#   FITS         [kind, ...] other kinds that may choose this interface
#   DEFAULT_KIND the body a replica gets (default: the first of KINDS)
#   tags(kind)   extra Registrar tags for a virtual robot (optional)
#   supports(kind, method) -> bool  (optional; default: every method)

import importlib
import pkgutil
import re

from robots import base

INTERFACES = {}             # name -> module
KINDS = {}                  # name -> {label, description, axes, sprite, interfaces}
DEFAULT_KIND = "turtle"
_NAME = re.compile(r"^[a-z0-9_]+$")
_KIND_ORDER = ("turtle", "lolibot", "xgo", "irobot", "lekiwi", "so101", "drone", "pi")
_PRIORITY = {base.STATUS_REAL: 0, base.STATUS_LEGACY: 1, base.STATUS_PROPOSED: 2}


def _load():
    modules = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        if not hasattr(module, "NAME"):
            continue                    # a helper module, not a robot
        if not _NAME.match(module.NAME):
            raise ValueError(f"robots/{info.name}.py: NAME must match [a-z0-9_]+")
        if module.STATUS not in base.STATUSES:
            raise ValueError(f"robots/{info.name}.py: STATUS must be one of {base.STATUSES}")
        INTERFACES[module.NAME] = module
        modules.append(module)
    modules.sort(key=lambda module: (_PRIORITY[module.STATUS], module.NAME))
    for module in modules:              # bodies, with their own interface first
        for kind, spec in getattr(module, "KINDS", {}).items():
            entry = KINDS.setdefault(kind, dict(
                label=spec.get("label", kind), description=spec.get("description", ""),
                axes=spec.get("axes", 1), sprite=spec.get("sprite", kind),
                interfaces=[]))
            entry["interfaces"].append(module.NAME)
    for module in modules:              # then the interfaces that also fit
        for kind in getattr(module, "FITS", []):
            if kind in KINDS and module.NAME not in KINDS[kind]["interfaces"]:
                KINDS[kind]["interfaces"].append(module.NAME)
    for kind, entry in KINDS.items():   # the default: real, else legacy, else proposed
        entry["interfaces"].sort(key=lambda name: (
            _PRIORITY[INTERFACES[name].STATUS],
            0 if kind in getattr(INTERFACES[name], "KINDS", {}) else 1, name))
    ordered = [kind for kind in _KIND_ORDER if kind in KINDS]
    ordered += [kind for kind in KINDS if kind not in ordered]
    for kind in ordered:                # the page's order: the familiar ones first
        KINDS[kind] = KINDS.pop(kind)


_load()


def default_interface(kind):
    return KINDS.get(kind, KINDS[DEFAULT_KIND])["interfaces"][0]


def resolve(kind=None, interface=None):
    """(kind, interface), validated: a kind and one of its interfaces,
    the defaults when not given"""
    kind = kind or DEFAULT_KIND
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}: choose from {', '.join(KINDS)}")
    interface = interface or default_interface(kind)
    if interface not in INTERFACES:
        raise ValueError(f"unknown interface {interface}: choose from "
                         f"{', '.join(INTERFACES)}")
    if interface not in KINDS[kind]["interfaces"]:
        raise ValueError(f"a {kind} does not speak {interface}: choose from "
                         f"{', '.join(KINDS[kind]['interfaces'])}")
    return kind, interface


def kind_axes(kind):
    return KINDS.get(kind, KINDS[DEFAULT_KIND])["axes"]


def supports(interface, kind, method):
    module = INTERFACES[interface]
    if method not in {spec["name"] for spec in base.method_specs(module.Interface)}:
        return False                    # not a function of this interface at all
    check = getattr(module, "supports", None)
    return check(kind, method) if check else True


def commands(interface, kind=None):
    """The chat examples of an interface, [(example, help)], for a kind"""
    module = INTERFACES[interface]
    examples = []
    for example, help_text in module.COMMANDS:
        method = module.parse_command(example)[0]
        if kind is None or method is None or supports(interface, kind, method):
            examples.append((example, help_text))
    return examples


def method_names(interface, kind=None):
    module = INTERFACES[interface]
    return [spec["name"] for spec in base.method_specs(module.Interface)
            if kind is None or supports(interface, kind, spec["name"])]


def tags(interface, kind):
    module = INTERFACES[interface]
    extra = getattr(module, "tags", None)
    return list(extra(kind)) if extra else []


def describe_interface(name, kind=None):
    """For /api/interfaces: the spec a person (or an agent) reads"""
    module = INTERFACES[name]
    specs = [spec for spec in base.method_specs(module.Interface)
             if kind is None or supports(name, kind, spec["name"])]
    return {"name": name, "label": module.LABEL, "description": module.DESCRIPTION,
            "status": module.STATUS, "protocol": module.PROTOCOL,
            "version": protocol_version(module.PROTOCOL),
            "units": module.UNITS, "source": getattr(module, "SOURCE", ""),
            "real": getattr(module, "MATCH", None) is not None,
            "match": getattr(module, "MATCH", None),
            "default_kind": replica_kind(name),
            "methods": specs,
            "commands": [{"example": example, "help": help_text}
                         for example, help_text in commands(name, kind)],
            "kinds": [kind_name for kind_name, entry in KINDS.items()
                      if name in entry["interfaces"]]}


def protocol_version(protocol):
    """The ":N" at the end of an Aiko protocol id, or None if there is none"""
    _, _, version = (protocol or "").rpartition(":")
    return version if version.isdigit() else None


def describe_interfaces():
    return [describe_interface(name) for name in INTERFACES]


def describe_kinds():
    """For /api/kinds and the page: each body, its interfaces, and the
    chat commands of its default interface"""
    result = []
    for kind, entry in KINDS.items():
        interface = entry["interfaces"][0]
        result.append(dict(name=kind, label=entry["label"],
            description=entry["description"], axes=entry["axes"],
            sprite=entry["sprite"], interface=interface,
            interfaces=list(entry["interfaces"]),
            commands=[example for example, _ in commands(interface, kind)],
            methods=method_names(interface, kind)))
    return result


def replica_kind(interface):
    module = INTERFACES[interface]
    kind = getattr(module, "DEFAULT_KIND", None)
    if not kind:
        own = list(getattr(module, "KINDS", {}))
        kind = own[0] if own else next(
            (kind for kind, entry in KINDS.items() if interface in entry["interfaces"]),
            DEFAULT_KIND)
    return kind


def observe(interface, direction, command, args, state):
    """Dead reckoning for a replica: [] when the module has no observe()"""
    module = INTERFACES[interface]
    watcher = getattr(module, "observe", None)
    if not watcher:
        return []
    try:
        return list(watcher(direction, command, list(args or []), state) or [])
    except (ValueError, TypeError, IndexError):
        return []
