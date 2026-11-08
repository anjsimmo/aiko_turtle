#!/usr/bin/env python3
#
# Headless virtual TurtleRobot Actor (no GUI: pose is tracked in shared state)
#
# Usage
# ~~~~~
#   source env.sh
#   ./virtual_robot.py run [--name anj_turtle_robot]
#
# Remote calls (publish S-expression to {topic_path}/in):
#   (forward 100) (backward 50) (left 90) (right 45) (action penup)

import math

import click

import aiko_services as aiko
from turtle_robot import ROBOT_NAME, ROBOT_PROTOCOL, TurtleRobot


class VirtualTurtleRobot(aiko.Actor):
    def __init__(self, context):
        context.call_init(self, "Actor", context)
        self.share["source_file"] = __file__
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0  # degrees, 0 = +x axis
        self.pen_down = True
        self._publish_pose()

    def _publish_pose(self):
        pose = f"({self.x:.1f} {self.y:.1f} {self.heading:.1f})"
        self.ec_producer.update("pose", pose)
        print(f"ROBOT: pose x={self.x:.1f} y={self.y:.1f} "
              f"heading={self.heading:.1f} pen={'down' if self.pen_down else 'up'}",
              flush=True)

    def _move(self, distance):
        radians = math.radians(self.heading)
        self.x += distance * math.cos(radians)
        self.y += distance * math.sin(radians)
        self._publish_pose()

    def action(self, value):
        print(f"ROBOT: action {value}", flush=True)
        match value:
            case "penup":
                self.pen_down = False
            case "pendown":
                self.pen_down = True
            case "forward":
                self._move(100)
            case "backward":
                self._move(-100)
            case "left":
                self.heading = (self.heading + 90) % 360
            case "right":
                self.heading = (self.heading - 90) % 360
            case _:
                print(f"ROBOT: unknown action {value}", flush=True)
                return
        self._publish_pose()

    def forward(self, value):
        print(f"ROBOT: forward {value}", flush=True)
        self._move(float(value))

    def backward(self, value):
        print(f"ROBOT: backward {value}", flush=True)
        self._move(-float(value))

    def left(self, value):
        print(f"ROBOT: left {value}", flush=True)
        self.heading = (self.heading + float(value)) % 360
        self._publish_pose()

    def right(self, value):
        print(f"ROBOT: right {value}", flush=True)
        self.heading = (self.heading - float(value)) % 360
        self._publish_pose()


@click.group()
def main():
    """Virtual TurtleRobot Actor"""
    pass


@main.command(name="run")
@click.option("--name", type=str, default=ROBOT_NAME)
def run_command(name):
    tags = ["ec=true", "type=robot",
            "commands=action,forward,backward,left,right"]
    init_args = aiko.actor_args(name, protocol=ROBOT_PROTOCOL, tags=tags)
    robot = aiko.compose_instance(VirtualTurtleRobot, init_args)
    print(f"ROBOT: {name} running, topic_path={robot.topic_path}", flush=True)
    aiko.process.run()


if __name__ == "__main__":
    main()
