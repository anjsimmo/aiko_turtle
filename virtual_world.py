#!/usr/bin/env python3
#
# VirtualWorld Actor: the virtual "hardware" the TurtleBot lives in.
# Owns the robot pose; MotorSinks apply movement, the CameraSource renders it.
#
# Usage
# ~~~~~
#   source env.sh
#   ./virtual_world.py run [--name anj_turtle_world]

import math

import click

import aiko_services as aiko

WORLD_NAME = "anj_turtle_world"
WORLD_PROTOCOL = "ai.hashtag.ai/virtual_world:0"
_GRID = 11      # render grid is _GRID x _GRID cells, 100 units per cell


class VirtualWorld(aiko.Actor):
    def __init__(self, context):
        context.call_init(self, "Actor", context)
        self.share["source_file"] = __file__
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0  # degrees, 0 = +x axis
        self._publish_pose()

    def _publish_pose(self):
        self.ec_producer.update(
            "pose", f"({self.x:.1f} {self.y:.1f} {self.heading:.1f})")
        print(f"WORLD: pose x={self.x:.1f} y={self.y:.1f} "
              f"heading={self.heading:.1f}", flush=True)

    def apply_move(self, distance):
        radians = math.radians(self.heading)
        self.x += float(distance) * math.cos(radians)
        self.y += float(distance) * math.sin(radians)
        self._publish_pose()

    def apply_turn(self, angle):
        self.heading = (self.heading + float(angle)) % 360
        self._publish_pose()

    def reset(self):
        print("WORLD: reset", flush=True)
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0
        self._publish_pose()

    def render(self):
        # ASCII picture: robot on a grid, arrow shows heading
        half = _GRID // 2
        column = min(max(int(round(self.x / 100)) + half, 0), _GRID - 1)
        row = min(max(half - int(round(self.y / 100)), 0), _GRID - 1)
        arrows = [">", "^", "<", "v"]
        arrow = arrows[int(((self.heading + 45) % 360) // 90)]
        lines = []
        for r in range(_GRID):
            line = "".join(
                arrow if (r, c) == (row, column) else "."
                for c in range(_GRID))
            lines.append(line)
        return "\n".join(lines)

    def get_pose(self, topic_path_response):
        aiko.process.message.publish(topic_path_response, "(item_count 1)")
        aiko.process.message.publish(topic_path_response,
            f"(response {self.x:.1f} {self.y:.1f} {self.heading:.1f})")


@click.group()
def main():
    """VirtualWorld Actor"""
    pass


@main.command(name="run")
@click.option("--name", type=str, default=WORLD_NAME)
def run_command(name):
    tags = ["ec=true", "type=virtual_world"]
    init_args = aiko.actor_args(name, protocol=WORLD_PROTOCOL, tags=tags)
    world = aiko.compose_instance(VirtualWorld, init_args)
    print(f"WORLD: {name} running, topic_path={world.topic_path}", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
