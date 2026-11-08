# Aiko Imagineering — 2026-08-22

A virtual **ChatRobotAgent** ("Angie's TurtleBot" pattern) built on
[aiko_services](https://github.com/geekscape/aiko_services) and
[aiko_chat](https://github.com/geekscape/aiko_chat), following the
2026-08-15 Aiko Services Design doc and the 2026-08-22 imagineering plan.

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
  channel list.
- **Phase 4** — **LLM ChatAgent** (`@@anj_agent`, backed by `claude -p`)
  discovers robots + capabilities from Registrar tags and drives them through
  chat (e.g. "draw a square" → four `move`/`turn` commands + a `look`).

## Prerequisites

- conda env `aiko` (Python 3.13) with `aiko_services` and `aiko_chat`
  installed editable from `/home/anj/src/aiko/{aiko_services,aiko_chat}`.
- `source env.sh` sets `PATH` (aiko env), `AIKO_MQTT_HOST=aiko.hashtag.ai`,
  `AIKO_NAMESPACE=aiko`.
- LLM agent shells out to the `claude` CLI (`claude -p --model haiku`).

## Start the stack (in order, each in the background or its own terminal)

```bash
cd /home/anj/src/aiko/imagineering-2026-08-22
source env.sh

aiko_registrar &                                            # 1. registrar
(cd _world_space_ && aiko_hyperspace run &)                 # 2. world hyperspace
bash /home/anj/src/aiko/aiko_chat/src/aiko_chat/chat_start.sh &  # 3. chat server
./robot_space_setup.py     # once only: writes _robot_space_ bootstrap entries
./chat_robot_agent.py run &                                 # 4. the robot
./chat_llm_agent.py run &                                   # 5. the LLM agent
```

Everything is currently RUNNING (started 2026-08-22, logs in `logs/`).
Only the robot's elements (world/camera/turn/forward) start lazily on demand.

## Try it out

Live visuals (each is one command; drive the robot from chat and watch):

```bash
source env.sh && ./world_viewer_web.py   # graphical: open http://localhost:8123
source env.sh && ./world_viewer.py       # text: ASCII map in the terminal
```

`world_viewer_web.py` is self-contained (Python stdlib): it serves a live
canvas page and relays each pose change to the browser as it happens.

Dashboard: `export AIKO_MQTT_HOST=aiko.hashtag.ai` then `aiko_dashboard`.

Interactive chat (own terminal):

```bash
source env.sh && aiko_chat repl        # then:  :cc robots
```

Things to type in the REPL (or send with
`aiko_chat send robots "..."` from a script/agent):

```text
@@anj_turtlebot move 100          ;; <Move> -> lazily starts world + forward
@@anj_turtlebot turn 90           ;; counter-clockwise degrees
@@anj_turtlebot look              ;; <Perceive> camera -> reports pose
@@anj_turtlebot telemetry         ;; <Telemetry>
@@anj_turtlebot interfaces        ;; <Robot> get_interfaces
@@anj_turtlebot reset             ;; back to origin (0,0) heading 0
@@anj_agent draw a triangle with the turtle robot   ;; natural language!
```

ChatSpace CRUD from the REPL (replies come from `@@chat_space`):

```text
:lc                               ;; live channel list (from shared state)
:space_list /                     ;; :sl  render the whole ChatSpace
:space_create myrobots            ;; :sc  new channel Category
:space_add myrobots anj_turtlebot ;; :sa  OK - implements <Chat>
:space_add myrobots anj_turtle_world  ;; REJECTED - no <Chat> interface
:space_remove channels/myrobots/anj_turtlebot   ;; :sr
```

HyperSpace CLI (Phase 2 collection the robot joined):

```bash
cd _world_space_ && aiko_hyperspace dump     # server-side log shows entries
ls -la robots/                               # write-through storage on disk
```

## Files

| File | Purpose |
|---|---|
| `env.sh` | environment (aiko conda env PATH, MQTT host, namespace) |
| `interfaces.py` | `<Chat>` `<Robot>` `<Move>` `<Telemetry>` `<Perceive>` + `interfaces=` tag helpers |
| `virtual_world.py` | VirtualWorld actor: the virtual "hardware" (pose) |
| `robot_elements.py` | Camera **source**, Turn/Forward **targets** (pipeline Target concept) |
| `robot_space_setup.py` | writes the robot's hyperspace bootstrap entries |
| `chat_robot_agent.py` | the ChatRobotAgent: `<Chat>`+`<Robot>`, lazy LifeCycleManager, hyperspace self-registration |
| `chat_llm_agent.py` | Phase 4 LLM agent (robot discovery via tags, `claude -p` backend) |
| `world_viewer_web.py` | graphical live view in the browser (http://localhost:8123) |
| `world_viewer.py` | live ASCII visual of the world in a terminal |
| `test_chat_space.py` | Phase 3 CRUD/enforcement exercise script |
| `virtual_robot.py`, `robot_chatbot.py` | Phase 0 (superseded by chat_robot_agent) |
| `_robot_space_/` | the robot's hyperspace definition (bootstrap Dependencies) |
| `_world_space_/` | the world HyperSpace storage (`robots/` collection) |
| `_chat_server_/` | the ChatServer's ChatSpace storage (channels/users) |

Changes were also made in the two repos (working trees, not committed):

- `aiko_chat`: new `src/aiko_chat/chat_space.py`; ChatSpace + `space_*`
  methods in `chat_server.py`; REPL commands + live `:lc` in `chat_repl.py`.
- `aiko_services`: two one-line bug fixes in `main/hyperspace.py`
  (`remove()` passed 4 args/undefined var to `_destroy()`; `update()`
  subscripted a Category instead of using `.share`), and one in
  `main/share.py`: `ECProducer._update_consumers()` hand-formatted live
  update payloads (a marked TODO), so values containing parentheses/spaces
  — like the world pose — arrived at ECConsumers as nested lists while the
  initial sync (which uses `generate()`) arrived intact. Symptom: viewers
  showed fresh state on restart but never live-updated.

## Findings / known issues

- **Command ordering across lazily-started elements is not guaranteed.**
  Each element drains its own pending queue when it connects, so on a cold
  start "move, turn, move…" can interleave out of order (visible in the first
  square test). Proper fix: serialize commands robot-side with completion
  acks. Warm runs are ordered.
- The framework doesn't persist ServiceFilter/LCM/storage details in storage
  files yet (open TODO); the `(bootstrap ...)` S-expression in
  `_robot_space_` dependency files is a proposed answer to "what is stored in
  each Dependency storage file?".
- Robots execute only messages *starting* with their `@@botname` (prose that
  merely mentions them is ignored) — needed once the LLM agent started
  chatting about robots.
- `aiko_hyperspace` CLI `list` prints via a response topic and was flaky
  here; `dump` (server-side log) and the on-disk symlinks are reliable.
