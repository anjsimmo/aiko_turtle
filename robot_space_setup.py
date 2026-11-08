#!/usr/bin/env python3
#
# Create the TurtleBot's hyperspace definition: a Category of Dependencies
# describing the robot's elements (sources and targets).  The entries are NOT
# running Actors: each Dependency storage file holds the bootstrap details
# (service name, protocol, command line) that a LifeCycleManager uses to
# lazily start the Service when first needed.
#
# This answers the aiko_chat TODO "What is stored in each Dependency storage
# file?" -- a (bootstrap ...) S-expression.
#
# Usage
# ~~~~~
#   source env.sh
#   ./robot_space_setup.py [--space-dir _robot_space_] [--robot anj_turtlebot]

import os
from pathlib import Path
import subprocess
import sys

import click

from aiko_services.main.utilities import generate

_HERE = Path(__file__).parent.resolve()

ROBOT_NAME = "anj_turtlebot"
SPACE_DIR = "_robot_space_"

ELEMENTS = {
    "world": {
        "name": "anj_turtle_world",
        "protocol": "ai.hashtag.ai/virtual_world:0",
        "element": "world",
        "command":
            f"{_HERE}/virtual_world.py run --name anj_turtle_world",
    },
    "camera": {
        "name": "anj_turtle_camera",
        "protocol": "ai.hashtag.ai/robot/source/camera:0",
        "element": "camera",
        "command":
            f"{_HERE}/robot_elements.py run --element camera",
    },
    "turn": {
        "name": "anj_turtle_turn",
        "protocol": "ai.hashtag.ai/robot/target/turn:0",
        "element": "turn",
        "command":
            f"{_HERE}/robot_elements.py run --element turn",
    },
    "forward": {
        "name": "anj_turtle_forward",
        "protocol": "ai.hashtag.ai/robot/target/forward:0",
        "element": "forward",
        "command":
            f"{_HERE}/robot_elements.py run --element forward",
    },
}


def _storage_file(*arguments):
    subprocess.run(["aiko_storage_file", *arguments], check=False)


@click.command()
@click.option("--space-dir", type=str, default=SPACE_DIR)
@click.option("--robot", "robot_name", type=str, default=ROBOT_NAME)
def main(space_dir, robot_name):
    space_path = Path(space_dir)
    space_path.mkdir(parents=True, exist_ok=True)
    os.chdir(space_path)

    if not Path("_hyperspace_").is_dir():
        _storage_file("initialize")
    if not Path(robot_name).is_symlink():
        _storage_file("create", "--bootstrap", robot_name)
    for entry_name, details in ELEMENTS.items():
        entry_path = Path(robot_name) / entry_name
        if not entry_path.is_symlink():
            _storage_file("add", "--bootstrap", str(entry_path))
        entry_path.write_text(generate("bootstrap", details) + "\n")
        print(f"Wrote bootstrap: {entry_path}")

    print(f"\nRobot space \"{robot_name}\" ready in {space_path.resolve()}")
    _storage_file("list", "--bootstrap", "--long_format", "--recursive")


if __name__ == "__main__":
    main()
