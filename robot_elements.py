#!/usr/bin/env python3
#
# TurtleBot elements: hyperspace-bootstrapped sources and targets.
# Per the 2026-08-22 imagineering plan sketch, the robot is a hyperspace
# collection of Camera (source), Turn (target) and Forward (target).
# Each element is a small Actor that discovers the VirtualWorld ("hardware").
#
# Usage
# ~~~~~
#   source env.sh
#   ./robot_elements.py run --element turn|forward|camera [--name NAME]

import click

import aiko_services as aiko
from interfaces import Perceive, interfaces_tag
from virtual_world import VirtualWorld, WORLD_NAME

ELEMENT_NAMES = {
    "turn": "anj_turtle_turn",
    "forward": "anj_turtle_forward",
    "camera": "anj_turtle_camera",
}
ELEMENT_PROTOCOLS = {
    "turn": "ai.hashtag.ai/robot/target/turn:0",
    "forward": "ai.hashtag.ai/robot/target/forward:0",
    "camera": "ai.hashtag.ai/robot/source/camera:0",
}


class _WorldClient(aiko.Actor):
    def __init__(self, context, world_name=WORLD_NAME):
        context.call_init(self, "Actor", context)
        self.share["source_file"] = __file__
        self.world = None
        self.pending = []  # actions queued until the world is discovered
        aiko.do_discovery(
            VirtualWorld,
            aiko.ServiceFilter("*", world_name, "*", "*", "*", "*"),
            self._world_add_handler, self._world_remove_handler)

    def _world_add_handler(self, service_details, service):
        print(f"ELEMENT: world connected: {service_details[0]}", flush=True)
        self.world = service
        pending, self.pending = self.pending, []
        for action in pending:
            action(service)

    def _world_remove_handler(self, service_details):
        print("ELEMENT: world disconnected", flush=True)
        self.world = None

    def _with_world(self, action):
        if self.world:
            action(self.world)
        else:
            self.pending.append(action)


class TurnTarget(_WorldClient):
    def turn(self, angle):
        print(f"TARGET turn: {angle}", flush=True)
        self._with_world(lambda world: world.apply_turn(angle))


class ForwardTarget(_WorldClient):
    def forward(self, distance):
        print(f"TARGET forward: {distance}", flush=True)
        self._with_world(lambda world: world.apply_move(distance))


class CameraSource(_WorldClient, Perceive):
    def __init__(self, context, world_name=WORLD_NAME):
        _WorldClient.__init__(self, context, world_name)
        self.world_pose = "(unknown)"
        self.world_topic_path = None

    def _world_add_handler(self, service_details, service):
        _WorldClient._world_add_handler(self, service_details, service)
        self.world_topic_path = service_details[0]
        self.ec_consumer = aiko.ECConsumer(
            self, 0, {}, f"{self.world_topic_path}/control", "(pose)")
        self.ec_consumer.add_handler(self._pose_change_handler)

    def _pose_change_handler(self, client_id, command, item_name, item_value):
        if item_name == "pose":
            if isinstance(item_value, (list, tuple)):   # older producers
                item_value = "(" + " ".join(
                    str(value) for value in item_value) + ")"
            self.world_pose = item_value

    def snapshot(self, topic_path_response, retries=5):
        # "Frame" is the world's pose, fetched from the world's shared state
        # (camera looks at the world, robot not required).  On a cold start
        # the pose may not have synced yet: retry shortly rather than
        # reporting "(unknown)"
        from aiko_services.main.utilities import generate
        if self.world_pose == "(unknown)" and int(retries) > 0:
            import threading
            threading.Timer(2.0, self.snapshot,
                args=(topic_path_response, int(retries) - 1)).start()
            return
        frame = f"pose {self.world_pose}"
        aiko.process.message.publish(topic_path_response, "(item_count 1)")
        aiko.process.message.publish(topic_path_response,
            generate("response", [frame]))
        print(f"SOURCE camera: snapshot: {frame} -> {topic_path_response}",
            flush=True)


_ELEMENT_CLASSES = {
    "turn": TurnTarget,
    "forward": ForwardTarget,
    "camera": CameraSource,
}


@click.group()
def main():
    """TurtleBot source/target elements"""
    pass


@main.command(name="run")
@click.option("--element", type=click.Choice(list(_ELEMENT_CLASSES)),
    required=True)
@click.option("--name", type=str, default=None)
@click.option("--world", "world_name", type=str, default=WORLD_NAME)
def run_command(element, name, world_name):
    element_class = _ELEMENT_CLASSES[element]
    name = name if name else ELEMENT_NAMES[element]
    tags = ["ec=true", f"element={element}", interfaces_tag(element_class)]
    init_args = aiko.actor_args(
        name, protocol=ELEMENT_PROTOCOLS[element], tags=tags)
    init_args["world_name"] = world_name
    element_actor = aiko.compose_instance(element_class, init_args)
    print(f"ELEMENT: {element} \"{name}\" running, "
          f"topic_path={element_actor.topic_path}", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
