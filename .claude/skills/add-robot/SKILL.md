---
name: add-robot
description: Use when adding a new robot kind or interface to aiko_turtle, or inferring a robot's interface from MQTT traffic or source code.
---

# Adding a robot to aiko_turtle

A robot is one module in `robots/` (its interface, as the robot speaks it
today) plus one sprite in `static/sprites/`. Nothing else needs editing:
the registry lists the package.

## 1. Gather evidence

Either let the tool draft it:

    source env.sh
    ./tools/infer_interface.py NAME --registrar NAME --seconds 30   # live robot
    ./tools/infer_interface.py NAME --watch 'aiko/#' --seconds 30   # raw traffic
    ./tools/infer_interface.py NAME --code ../path/to/robot_client.py
    ./tools/infer_interface.py NAME --notes "move is metres, turn clockwise degrees"

Flags combine. Without `--write` the draft goes to stdout; with `--write` it
lands in `robots/NAME.py` (never overwriting without `--force`). Treat the
result as a draft to review, not a finished module.

Or read the robot's Actor source yourself. Where the known real ones came from:

- iRobot: `../zebra-robot/robot_client.py` (the Actor is aiko_irobot on Zebra2)
- XGO: `aiko_chat`'s hardcoded XGO example (`robots/xgo_robot.py` cites it)
- legacy turtle: the June 2026 notebooks in `../old_tutorials`
- LoliBot: `lolibot_mp/` here (updated from `../od_micro_py_files`)

Those source trees are read-only reference: never edit them to fit the
sandbox; the sandbox fits them.

## 2. Write robots/NAME.py

Copy `robots/_template.py` to `robots/NAME.py` and fill it in per the
contract in the comment block at the top of `robots/__init__.py` (NAME,
LABEL, DESCRIPTION, STATUS, UNITS, PROTOCOL, SOURCE, Interface, Simulated,
parse_command, COMMANDS, MATCH, optional observe/KINDS/FITS/tags/supports).
Use `robots/turtle_robot.py` as a worked example. Describe the interface
exactly as the robot speaks it today, not as you would redesign it.

"As it is" checklist:

- Units: metres or centimetres, degrees or radians, seconds or ticks. Put
  them in UNITS and in docstrings.
- Sign conventions: is positive turn clockwise or anticlockwise? Is +y up
  or down? Which way is "left"?
- Continuous versus instantaneous motion: does `move 0.2` go 0.2 m and stop,
  or set a velocity until the next command? Continuous ones need `drive`
  and `stop` ops in observe().
- Queries: which commands answer on a topic_path_response (telemetry, look,
  battery)? Declare them so the reply is routed back.
- Dangerous commands (power_off, reboot, firmware, anything that can hurt
  the robot or lock it up): the Simulated class must refuse them in the
  sandbox, as `power_off` does elsewhere.
- Unknown words: parse_command returns `(None, error)` naming valid commands.
- STATUS is real only if you saw it work on a live robot.

## 3. Sprite

Create `static/sprites/NAME.js` registering:

    SPRITES.NAME = function (c, col) { /* draw with ctx */ };

Draw it top-down, nose along +x, about 40 px across, using the page's
helpers `rr`, `dot`, `arm` and the canvas `ctx`. Look at the existing files
in `static/sprites/` for the style (`turtle.js` is the simplest, `irobot.js`
a round base). A kind without a sprite file is drawn as a plain arrow.

## 4. Test

    python3 -m pytest -q tests

The registry test loads every module and checks NAME, STATUS, that
Simulated implements every Interface method, and that parse_command returns
a method for every COMMANDS example.

## 5. Try it

Never use the production `turtle_world`. Set a dev world first (see README):

    export TURTLE_WORLD=dev_world_yourname
    ./robot.py run --name test_NAME --kind NAME

Then in the chat: `@@test_NAME help`, and try each COMMANDS example.

## 6. Pull request

Commit `robots/NAME.py`, `static/sprites/NAME.js` and any test changes on a
branch and open a pull request. Say in the description where the evidence
came from (live robot, code, human notes) and what remains unverified.
