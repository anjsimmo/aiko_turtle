#!/usr/bin/env python3
#
# Live terminal viewer for the VirtualWorld: watches the world's shared
# pose and redraws an ASCII map with the robot's trail in real time.
# Run it in its own terminal while you drive the robot from chat.
#
# Usage
# ~~~~~
#   source env.sh
#   ./world_viewer.py [--name anj_turtle_world] [--grid 21]

import click

import aiko_services as aiko
from virtual_world import VirtualWorld, WORLD_NAME

_CELL_UNITS = 50    # world units per grid cell
_ARROWS = [">", "^", "<", "v"]


class WorldViewer(aiko.Actor):
    def __init__(self, context, world_name=WORLD_NAME, grid=21):
        context.call_init(self, "Actor", context)
        self.grid = grid
        self.trail = set()
        self.pose = None
        print(f"VIEWER: waiting for world \"{world_name}\" ...", flush=True)
        aiko.do_discovery(
            VirtualWorld,
            aiko.ServiceFilter("*", world_name, "*", "*", "*", "*"),
            self._add_handler, self._remove_handler)

    def _add_handler(self, service_details, service):
        if getattr(self, "ec_consumer", None):
            self.ec_consumer.terminate()
        self.ec_consumer = aiko.ECConsumer(
            self, 0, {}, f"{service_details[0]}/control", ["pose"])
        self.ec_consumer.add_handler(self._pose_handler)

    def _remove_handler(self, service_details):
        print("VIEWER: world disconnected", flush=True)
        if getattr(self, "ec_consumer", None):
            self.ec_consumer.terminate()
            self.ec_consumer = None

    def _pose_handler(self, client_id, command, item_name, item_value):
        if item_name != "pose":
            return
        try:
            if isinstance(item_value, (list, tuple)):   # older producers
                values = [str(value) for value in item_value]
            else:
                values = str(item_value).strip("()").split()
            x, y, heading = (float(value) for value in values)
        except (ValueError, TypeError):
            return
        self.pose = (x, y, heading)
        self.trail.add(self._cell(x, y))
        self._draw()

    def _cell(self, x, y):
        half = self.grid // 2
        column = min(max(int(round(x / _CELL_UNITS)) + half, 0), self.grid - 1)
        row = min(max(half - int(round(y / _CELL_UNITS)), 0), self.grid - 1)
        return (row, column)

    def _draw(self):
        x, y, heading = self.pose
        robot_cell = self._cell(x, y)
        arrow = _ARROWS[int(((heading + 45) % 360) // 90)]
        print("\033[2J\033[H", end="")     # clear screen, home cursor
        print(f"VirtualWorld   x={x:.1f} y={y:.1f} heading={heading:.1f}")
        print("+" + "-" * self.grid + "+")
        for row in range(self.grid):
            line = ""
            for column in range(self.grid):
                if (row, column) == robot_cell:
                    line += arrow
                elif (row, column) in self.trail:
                    line += "*"
                else:
                    line += "."
            print(f"|{line}|")
        print("+" + "-" * self.grid + "+", flush=True)


@click.command()
@click.option("--name", "world_name", type=str, default=WORLD_NAME)
@click.option("--grid", type=int, default=21)
def main(world_name, grid):
    init_args = aiko.actor_args("anj_world_viewer", tags=["ec=true"])
    init_args.update({"world_name": world_name, "grid": grid})
    aiko.compose_instance(WorldViewer, init_args)
    aiko.process.run()


if __name__ == "__main__":
    main()
