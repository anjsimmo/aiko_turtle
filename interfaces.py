#!/usr/bin/env python3
#
# Aiko Chat and Robot Interfaces, per "2026-08-15: Aiko Services Design"
#
# <Chat>  ... send_message / receive_message
# <Robot> ... composed with one or more of <Move> <Grasp> <Telemetry> <Perceive>
#
# An Aiko "Interface" is a class whose methods are all @abstractmethod.
# An Actor implementation inherits the Interfaces it supports and defines
# the methods concretely.  Each implemented Interface is advertised as its
# own Service tag, "move=0", "grasp=0", ... (one aspect per tag, as the
# framework's ADR-025 / display protocol do), so that a ServiceFilter can
# select on a single capability ("tags=['move=0']") and a version bump
# ("move=1") simply stops matching older clients.  Which Interfaces a
# robot has depends on its kind (kinds.py).

from abc import abstractmethod
import inspect

import aiko_services as aiko

PROTOCOL_PREFIX = "ai.hashtag.ai"

CHAT_PROTOCOL = f"{PROTOCOL_PREFIX}/chat:0"
ROBOT_PROTOCOL = f"{PROTOCOL_PREFIX}/robot:0"
CHAT_ROBOT_PROTOCOL = f"{PROTOCOL_PREFIX}/chat_robot:0"

_PLUMBING = {"ABC", "object", "Interface", "ServiceProtocolInterface"}


class Chat(aiko.Interface):
    aiko.Interface.default("Chat", "interfaces.ChatDefault")

    @abstractmethod
    def send_message(self, username, recipients, message):
        pass

    @abstractmethod
    def receive_message(self, username, channel, message):
        pass


class Move(aiko.Interface):
    aiko.Interface.default("Move", "interfaces.MoveDefault")

    @abstractmethod
    def move(self, distance):
        pass

    @abstractmethod
    def turn(self, angle):
        pass

    @abstractmethod
    def stop(self):
        pass


class Telemetry(aiko.Interface):
    aiko.Interface.default("Telemetry", "interfaces.TelemetryDefault")

    @abstractmethod
    def get_telemetry(self, topic_path_response):
        pass


class Perceive(aiko.Interface):
    aiko.Interface.default("Perceive", "interfaces.PerceiveDefault")

    @abstractmethod
    def snapshot(self, topic_path_response):
        pass


class Grasp(aiko.Interface):
    aiko.Interface.default("Grasp", "interfaces.GraspDefault")

    @abstractmethod
    def grasp(self):
        pass

    @abstractmethod
    def release(self):
        pass


class Robot(aiko.Interface):
    aiko.Interface.default("Robot", "interfaces.RobotDefault")

    @abstractmethod
    def get_interfaces(self, topic_path_response):
        pass


# Placeholder default implementations: satisfy the composition machinery's
# "every Interface has an implementation" check.  Their methods are grafted
# only where the seed class leaves a method abstract, so a real Actor's
# concrete methods always win.

def _unimplemented(interface_name, method_name):
    def method(self, *args, **kwargs):
        raise NotImplementedError(
            f"<{interface_name}> {method_name}() not implemented")
    method.__name__ = method_name
    return method


class ChatDefault(Chat):
    send_message = _unimplemented("Chat", "send_message")
    receive_message = _unimplemented("Chat", "receive_message")


class MoveDefault(Move):
    move = _unimplemented("Move", "move")
    turn = _unimplemented("Move", "turn")
    stop = _unimplemented("Move", "stop")


class TelemetryDefault(Telemetry):
    get_telemetry = _unimplemented("Telemetry", "get_telemetry")


class PerceiveDefault(Perceive):
    snapshot = _unimplemented("Perceive", "snapshot")


class GraspDefault(Grasp):
    grasp = _unimplemented("Grasp", "grasp")
    release = _unimplemented("Grasp", "release")


class RobotDefault(Robot):
    get_interfaces = _unimplemented("Robot", "get_interfaces")


def _is_interface(cls):
    methods = inspect.getmembers(cls, predicate=inspect.isfunction)
    if not methods:
        return False
    return all(getattr(method, "__isabstractmethod__", False)
               for _, method in methods)


def interface_names(instance_or_class):
    cls = instance_or_class if inspect.isclass(instance_or_class)  \
        else type(instance_or_class)
    names = []
    for klass in cls.__mro__:
        if klass.__name__ in _PLUMBING:
            continue
        if klass.__module__ != __name__:      # only the Interfaces here
            continue
        if _is_interface(klass) and klass.__name__ not in names:
            names.append(klass.__name__)
    return names


def aspect_tags(instance_or_class_or_names, version=0):
    """One tag per implemented Interface: ["chat=0", "robot=0", ...].
    Takes an Actor, a class, or a list of Interface names"""
    names = instance_or_class_or_names
    if not isinstance(names, (list, tuple)):
        names = interface_names(names)
    return [f"{name.lower()}={version}" for name in names]


def implements(tags, interface_name):
    """True if the Service tags advertise <interface_name> (any version)"""
    prefix = f"{interface_name.lower()}="
    return any(str(tag).startswith(prefix) for tag in tags or [])
