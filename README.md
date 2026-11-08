# Aiko Imagineering — 2026-08-22

A virtual **ChatRobotAgent** ("Angie's TurtleBot" pattern) built on
[aiko_services](https://github.com/geekscape/aiko_services) and
[aiko_chat](https://github.com/geekscape/aiko_chat), following the
2026-08-15 Aiko Services Design doc and the 2026-08-22 imagineering plan.
The demo shows the **robot and the chat side by side** in a browser page:
drive the robot from the chat and watch it move.

What was built (all four phases work end-to-end):

- **Phase 0** — virtual robot connects to Aiko Chat (notebook pattern, updated
  to the current S-expression wire protocol).
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
- **Phase 3** — **ChatSpace** CRUD from the Chat REPL. New `chat_space.py` in
  aiko_chat: a HyperSpace whose channel members **MUST implement `<Chat>`**
  (enforced against the live Registrar tags). New REPL commands + a live
  channel list. *Needs the aiko_chat working-tree changes on the ChatServer
  side, see "Repo changes" below.*
- **Phase 4** — **LLM ChatAgent** (`@@anj_agent`, OpenAI with a `claude -p`
  fallback) discovers robots + capabilities from Registrar tags and drives
  them through chat (e.g. "draw a square" → four `move`/`turn` commands + a
  `look`).

## Topology (since 2026-11-08)

The shared services run on **aiko.hashtag.ai** and are *not* started here:
Registrar, HyperSpace and ChatServer (plus the MQTT broker). Everything in
this directory connects to them via `AIKO_MQTT_HOST=aiko.hashtag.ai` and
namespace `aiko` (see `env.sh`).

Locally you run only the robot side:

| Process | What |
|---|---|
| `chat_robot_agent.py` | the ChatRobotAgent `@@anj_turtlebot` (+ its lazily started elements) |
| `chat_llm_agent.py` | the LLM ChatAgent `@@anj_agent` |
| `world_viewer_web.py` | the robot + chat page at http://localhost:8123 |

## Prerequisites

- conda env `aiko` (Python 3.13) with `aiko_services` and `aiko_chat`
  installed editable from `/home/anj/src/aiko/{aiko_services,aiko_chat}`.
- `source env.sh` sets `PATH` (aiko env), `AIKO_MQTT_HOST=aiko.hashtag.ai`,
  `AIKO_NAMESPACE=aiko`, `PYTHONUNBUFFERED=1`.
- LLM ChatAgent: `OPENAI_API_KEY` (env or `/home/anj/src/aiko/open-ai-key.txt`),
  otherwise it shells out to the `claude` CLI (`claude -p --model haiku`).

## Run it

```bash
cd /home/anj/src/aiko/imagineering-2026-08-22
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

ChatSpace CRUD from the REPL (replies come from `@@chat_space`) — only
works against a ChatServer running the aiko_chat working-tree changes:

```text
:lc                               ;; live channel list (from shared state)
:space_list /                     ;; :sl  render the whole ChatSpace
:space_create myrobots            ;; :sc  new channel Category
:space_add myrobots anj_turtlebot ;; :sa  OK - implements <Chat>
:space_add myrobots anj_turtle_world  ;; REJECTED - no <Chat> interface
:space_remove channels/myrobots/anj_turtlebot   ;; :sr
```

## Files

| File | Purpose |
|---|---|
| `start.sh`, `stop.sh` | start/stop the local processes (logs in `logs/`) |
| `env.sh` | environment (aiko conda env PATH, MQTT host, namespace) |
| `interfaces.py` | `<Chat>` `<Robot>` `<Move>` `<Telemetry>` `<Perceive>` + `interfaces=` tag helpers |
| `virtual_world.py` | VirtualWorld actor: the virtual "hardware" (pose) |
| `robot_elements.py` | Camera **source**, Turn/Forward **targets** (pipeline Target concept) |
| `robot_space_setup.py` | writes the robot's hyperspace bootstrap entries |
| `chat_robot_agent.py` | the ChatRobotAgent: `<Chat>`+`<Robot>`, lazy LifeCycleManager, hyperspace self-registration |
| `chat_llm_agent.py` | Phase 4 LLM ChatAgent (robot discovery via tags, OpenAI / `claude -p`) |
| `world_viewer_web.py` | robot + chat side by side in the browser (http://localhost:8123) |
| `world_viewer.py` | live ASCII visual of the world in a terminal |
| `test_chat_space.py` | Phase 3 CRUD/enforcement exercise script |
| `virtual_robot.py`, `robot_chatbot.py` | Phase 0 (superseded by chat_robot_agent) |
| `report.html` | the 2026-08-22 session report |
| `_robot_space_/` | (generated, ignored) the robot's hyperspace definition |
| `_world_space_/`, `_chat_server_/` | (legacy, ignored) storage from when HyperSpace and ChatServer ran locally |

## Repo changes (working trees, not committed)

- `aiko_chat`: new `src/aiko_chat/chat_space.py`; ChatSpace + `space_*`
  methods in `chat_server.py`; REPL commands + live `:lc` in `chat_repl.py`.
  The ChatServer on aiko.hashtag.ai runs aiko_chat `main` without these, so
  the `:space_*` commands and `:lc` are inert against it. `chat_space.py`
  is still imported locally (`implements()` helper) by the LLM ChatAgent.
- `aiko_services`: the August fixes (`hyperspace.py` `remove()`/`update()`,
  `share.py` `ECProducer._update_consumers()` using `generate()`) are now
  in `master`.

## Findings / known issues

- **ECConsumer filters must be lists.** Since `share.py` serialises the
  share request with `generate()`, a filter passed as the string `"(pose)"`
  arrives as a quoted string and matches nothing (no sync, no updates; the
  camera reported `(unknown)`). Pass `["pose"]`. Fixed in the viewers and
  the Camera source on 2026-11-08.
- **Channel `robots` is not in the remote ChatServer's channel list**
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
