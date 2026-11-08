# aiko_turtle

A virtual TurtleBot you drive from Aiko Chat, with the robot and the chat
side by side in a browser. Built during the 2026-08-22 Aiko imagineering
session.

It is a **ChatRobotAgent** ("Angie's TurtleBot" pattern) built on
[aiko_services](https://github.com/geekscape/aiko_services) and
[aiko_chat](https://github.com/geekscape/aiko_chat), following the
2026-08-15 Aiko Services Design doc and the 2026-08-22 imagineering plan.
Drive the robot from the chat and watch it move.

It runs against the **official, unmodified** `aiko_services` (master) and
`aiko_chat` (main). Everything here is application code in this directory.

What was built:

- **Phase 0** — virtual robot connects to Aiko Chat.
- **Phase 1** — `<Chat>` + `<Robot>` (`<Move>`, `<Telemetry>`, `<Perceive>`)
  Interfaces per the design doc (`interfaces.py`). The robot is a hyperspace
  collection of **sources and targets** (Camera source, Turn/Forward targets
  + a VirtualWorld "hardware" actor). Hyperspace entries are *not* running
  Actors — each Dependency storage file holds a `(bootstrap ...)` S-expression
  (service name, protocol, command line) and the robot's embedded
  ProcessManager **lazily starts** each element the first time it is needed.
- **Phase 2** — on startup the robot **adds itself** to the running
  HyperSpace's `robots/` collection (ServiceFilter incl. an `interfaces=` tag,
  LifeCycleManager URL, storage URL).
- **Phase 4** — **LLM ChatAgent** (`@@anj_agent`, OpenAI with a `claude -p`
  fallback) discovers robots + capabilities from Registrar tags and drives
  them through chat (e.g. "draw a square" → four `move`/`turn` commands + a
  `look`).
- **Phase 3** (ChatSpace: channel members must implement `<Chat>`) was
  prototyped as a change *inside* aiko_chat and is **not part of this repo**
  (it required a modified ChatServer). See "Design notes" below for the
  framework-conformant way to do it.

## Topology

The shared services run on **aiko.hashtag.ai** (MQTT broker, Registrar,
HyperSpace, ChatServer) and are not started here. Everything in this
directory connects to them. To use another deployment, set the usual Aiko
variables *before* sourcing `env.sh` — it only fills in defaults:

```bash
AIKO_MQTT_HOST=localhost AIKO_NAMESPACE=aiko ./start.sh
```

Locally you run only the robot side:

| Process | What |
|---|---|
| `chat_robot_agent.py` | the ChatRobotAgent `@@anj_turtlebot` (+ its lazily started elements) |
| `chat_llm_agent.py` | the LLM ChatAgent `@@anj_agent` |
| `world_viewer_web.py` | the robot + chat page at http://localhost:8123 |

## Prerequisites

- Python 3.12+ with the two official packages installed, for example:

  ```bash
  git clone https://github.com/anjsimmo/aiko_turtle
  git clone https://github.com/geekscape/aiko_services && pip install -e aiko_services
  git clone https://github.com/geekscape/aiko_chat     && pip install -e aiko_chat
  ```

  (`pip install -e` is what the Aiko ReadMe uses; a venv or conda env is fine.)
- `env.sh` prepends `$AIKO_PYTHON_BIN` (default: the `aiko` conda env's `bin`)
  to `PATH` if that directory exists; otherwise activate your own env first.
- A Registrar + ChatServer reachable at `$AIKO_MQTT_HOST` (default
  `aiko.hashtag.ai`, namespace `aiko`).
- LLM ChatAgent: `OPENAI_API_KEY` in the environment (or the fallback file
  `/home/anj/src/aiko/open-ai-key.txt`); without a key it shells out to the
  `claude` CLI (`claude -p --model haiku`).
- Optional: `mosquitto_sub` for watching raw MQTT traffic.

## Run it

```bash
cd aiko_turtle
./start.sh      # robot, LLM agent, web page (logs in logs/)
./stop.sh       # stops them and the robot's elements
```

`start.sh` runs `./robot_space_setup.py` once if `_robot_space_/` is missing
(it writes the robot's bootstrap entries; the directory is not versioned
because it holds absolute paths and symlinks).

By hand, each in its own terminal:

```bash
source env.sh
./chat_robot_agent.py run          # the robot
./chat_llm_agent.py run            # the LLM ChatAgent
./world_viewer_web.py              # http://localhost:8123
```

## Try it out

Open **http://localhost:8123**: the live world (canvas, LoliBot sprite,
trail) is on the left and the `#robots` channel on the right, with a send
box and quick-command buttons. The page is a chat client like
`aiko_chat repl` (discovers the ChatServer, subscribes to the channel topic,
sends with `ChatServer.send_message()`), so it shows everyone's messages,
including the robot's and the agent's replies. Narrow windows stack the two
panels.

Things to type (in the page, in `aiko_chat repl` after `:cc robots`, or
with `aiko_chat send robots "..."`):

```text
@@anj_turtlebot move 100          ;; <Move> -> lazily starts world + forward
@@anj_turtlebot turn 90           ;; counter-clockwise degrees
@@anj_turtlebot look              ;; <Perceive> camera -> reports pose
@@anj_turtlebot telemetry         ;; <Telemetry>
@@anj_turtlebot interfaces        ;; <Robot> get_interfaces
@@anj_turtlebot reset             ;; back to origin (0,0) heading 0
@@anj_agent draw a triangle with the turtle robot   ;; natural language!
```

Other views: `./world_viewer.py` (ASCII map in a terminal) and
`aiko_dashboard` (with `env.sh` sourced).

## Files

| File | Purpose |
|---|---|
| `start.sh`, `stop.sh` | start/stop the local processes (logs in `logs/`) |
| `env.sh` | environment defaults (PATH, MQTT host/port, namespace); preset values win |
| `interfaces.py` | `<Chat>` `<Robot>` `<Move>` `<Telemetry>` `<Perceive>` + `interfaces=` tag helpers |
| `virtual_world.py` | VirtualWorld actor: the virtual "hardware" (pose) |
| `robot_elements.py` | Camera **source**, Turn/Forward **targets** (pipeline Target concept) |
| `robot_space_setup.py` | writes the robot's hyperspace bootstrap entries |
| `chat_robot_agent.py` | the ChatRobotAgent: `<Chat>`+`<Robot>`, lazy LifeCycleManager, hyperspace self-registration |
| `chat_llm_agent.py` | Phase 4 LLM ChatAgent (robot discovery via tags, OpenAI / `claude -p`) |
| `world_viewer_web.py` | robot + chat side by side in the browser (http://localhost:8123) |
| `world_viewer.py` | live ASCII visual of the world in a terminal |
| `virtual_robot.py`, `robot_chatbot.py` | Phase 0 (superseded by chat_robot_agent) |
| `report.html` | the 2026-08-22 session report |
| `_robot_space_/` | (generated, ignored) the robot's hyperspace definition |

## Design notes

- **Advertising Interfaces.** The robot advertises what it implements as one
  tag, `interfaces=Chat,Robot,Move,Telemetry`, parsed by `implements()` in
  `interfaces.py`. The Registrar matches tags by exact `key=value`, so that
  tag cannot be used in a `ServiceFilter`. The Aiko Services convention
  (ADR-025, s_00 §1.3) is one tag per aspect derived from its protocol id,
  e.g. `chat=0 robot=0 move=0`, which a ServiceFilter *can* select on.
  Switching to that is the natural next step.
- **Channel membership (the Phase 3 idea).** With per-aspect tags, "who is in
  #robots and can chat" is simply the discovery query
  `tags=["chat=0", "channel=robots"]` (the robot already advertises
  `channel=robots`) — no stored member list and no server-side gate needed.
  If a stored ChatSpace is wanted anyway, put the condition in each entry's
  Dependency ServiceFilter instead of subclassing `HyperSpaceImpl`
  (constitution P5/P7; HyperSpace write validation belongs to the
  `storage_mutation` gate of s_05 once that exists).

## Findings / known issues

- **ECConsumer filters must be lists.** `share.py` serialises the share
  request with `generate()`, so a filter passed as the string `"(pose)"`
  arrives as a quoted string and matches nothing (no sync, no updates).
  Pass `["pose"]`.
- **Channel `robots` is not in the ChatServer's channel list**
  (general, llm, random, robot, yolo). The server republishes to any
  channel topic, so it works, but `:lc` won't show it. Avoid `robot`: the
  server treats that recipient specially (XGO robot routing).
- **Command ordering across lazily-started elements is not guaranteed.**
  Each element drains its own pending queue when it connects, so on a cold
  start "move, turn, move…" can interleave out of order. Proper fix:
  serialize commands robot-side with completion acks. Warm runs are ordered.
- The framework doesn't persist ServiceFilter/LCM/storage details in storage
  files yet (open TODO); the `(bootstrap ...)` S-expression in
  `_robot_space_` dependency files is a proposed answer to "what is stored in
  each Dependency storage file?".
- Robots execute only messages *starting* with their `@@botname` (prose that
  merely mentions them is ignored) — needed once the LLM agent started
  chatting about robots.
- The robot's HyperSpace join handler fires twice on startup (harmless:
  `create()`/`add()` are idempotent).
