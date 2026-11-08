# aiko_turtle

Virtual robots in a shared world, for the AI+ML+Robots community to learn
and play with [Aiko Services](https://github.com/geekscape/aiko_services).
Anyone can create a robot, drive it from the chat, from a REST API, from
an LLM agent or from their own Aiko code, and watch every robot move in
the browser. A live instance is at **https://turtle.aiko.hashtag.ai**
(the in-page [guide](https://turtle.aiko.hashtag.ai/guide) is the
friendliest start).

Built on the official, unmodified
[aiko_services](https://github.com/geekscape/aiko_services) and
[aiko_chat](https://github.com/geekscape/aiko_chat). Everything here is
application code; the shared services (MQTT broker, Registrar, HyperSpace,
ChatServer) run on the community instance **aiko.hashtag.ai**.

**Who this is for.** Beginners who want to see a robot move in ten
minutes, and developers who want to build agents and robots on a real
distributed framework. The virtual robots use the same Interfaces a
physical one would, so what you write here plugs into a real XGO, LoliBot
or LeKiwi at the [meetup](https://www.meetup.com/ai-ml-robots/).

**How it was made.** Much of this code was written with an AI coding
assistant, with a human deciding what to build, reviewing it and running
it. The hard part is human work: Aiko Services has been developed over
years by Andy Gelme, who leads the AI+ML+Robots group, and the group's
study sessions are where the robot Interfaces used here are being worked
out. Those Interfaces are a work in progress (Aiko has the machinery for
defining them; which ones a robot should have is still being thought
through), so this project is one proposal, not the answer. Pull requests,
issues and ideas are welcome from everyone, whatever your level; the
"Contributing" section says where to start.

**Last tested with** aiko_services `39796ee` (2026-11-07) and aiko_chat
`9edb211` (2026-10-31), the heads of `master` and `main` at the time. The
aim is that it always works with the latest; if it does not, those are the
commits to compare against.

## How it fits together

| Process | What it is |
|---|---|
| `virtual_world.py` | **VirtualWorld** Actor: holds every robot's pose, persists them in a database, publishes them as the share `robots.<name>` |
| `robot.py` | **ChatRobotAgent**: one Actor per robot, implementing `<Chat>` and `<Robot>` composed of the Interfaces its kind has (`<Move>` `<Grasp>` `<Perceive>` `<Telemetry>`, see `kinds.py`). Its body is in the world; it is the robot's voice in the chat and its entry in the Registrar |
| `web.py` | **web server** (FastAPI): the pages (`/`, `/world`, `/chat`, `/guide`, `/system`), the REST API (`/docs`) and a live SSE stream. It also *hosts* a ChatRobotAgent for every robot created over REST, so those answer in the chat too |
| `agent.py` | **LLM ChatAgent** `@@pilot`: discovers robots from Registrar tags and drives them in natural language. Rate limited |
| `mcp_server.py` | **MCP server**: the robots as tools for Claude Code, Claude Desktop or any MCP client, over the REST API |

Every robot in the world is always answerable in the chat and listed in
the Registrar:

- **Over REST / the page**: `POST /api/robots`. The web server hosts the
  robot's chat Actor, and re-hosts every robot after a restart.
- **Over Aiko, from any machine**: `./robot.py run --name NAME`. While
  your process runs, *it* speaks for the robot and the web server steps
  back; when it exits, the web server takes over again. So your own code
  (or a physical robot) can stand in for a virtual one at any time.

Both are the same thing: a row in the world's database and a
`<Chat>`+`<Robot>` Service in the Registrar.

Identity is deliberately not validated: pick any user name and any robot
name. If you do not want others driving your robot, pick a longer, more
unusual name.

## Install

```bash
git clone https://github.com/geekscape/aiko_services && pip install -e aiko_services
git clone https://github.com/geekscape/aiko_chat     && pip install -e aiko_chat
git clone https://github.com/anjsimmo/aiko_turtle    && cd aiko_turtle
pip install -r requirements.txt
cp .env.example .env          # optional: edit what you need
```

Python 3.12+. A venv or conda env is fine; `env.sh` warns if the `python3`
it finds lacks the packages. Set `AIKO_PYTHON_BIN` in `.env` to the `bin`
of your environment if you do not want to activate it each time.

## Configure

Everything is a variable with a default, read from the environment, then
`.env` (not committed), then `config.py`. See `.env.example`. The ones
you are most likely to touch:

| Variable | Default | |
|---|---|---|
| `AIKO_MQTT_HOST` | `aiko.hashtag.ai` | the shared services |
| `TURTLE_WORLD` | `turtle_world` | name of the VirtualWorld Service |
| `TURTLE_DATABASE_URL` | `sqlite:///turtle.db` | any SQLAlchemy URL; relative to the working directory, like HyperSpace storage |
| `TURTLE_CHANNEL` | `robots` | chat channel |
| `TURTLE_WEB_PORT` | `8123` | the web server binds `127.0.0.1` |
| `TURTLE_API_TOKEN` | *(empty)* | set it and every POST/DELETE on the REST API needs `Authorization: Bearer <token>`; reads and pages stay open |
| `TURTLE_API_TOKEN_PUBLIC` | `true` | show the token on the page and in `/guide`, pre-filled: a formality that keeps stray bots out, not developers. `false` to hide it |
| `OPENAI_API_KEY` | | the agent falls back to the `claude` CLI without it |
| `TURTLE_LLM_RATE_PER_MINUTE` | `10` | agent requests per minute (also `_USER_` per user, and `_QUEUE_LIMIT`) |

## Run

```bash
./start.sh      # world, web server, agent (logs in logs/)
./stop.sh
```

Or by hand, each in its own terminal, after `source env.sh`:

```bash
./virtual_world.py run
./web.py
./agent.py run
./robot.py run --name my_turtle      # a robot of your own, from anywhere
```

## Try it

Open **http://localhost:8123**. The world is on the left: create a robot
(pick a kind), click one to select it, use the quick-command buttons. The
`#robots` channel is on the right, with your name in the box (any name;
humans are `@name`, the page adds the `@`). The dropdown in the chat
header switches channels. `/world` is the map alone, `/chat` the chat
alone, `/guide` the human guide, `/system` the Registrar and MQTT details.

**REST** (interactive docs at http://localhost:8123/docs):

```bash
curl -X POST localhost:8123/api/robots -H 'Content-Type: application/json' \
     -d '{"name": "my_turtle", "kind": "turtle", "owner": "me"}'
curl -X POST localhost:8123/api/robots/my_turtle/turn -H 'Content-Type: application/json' \
     -d '{"angle": 90, "username": "me"}'
curl -X POST localhost:8123/api/robots/my_turtle/move -H 'Content-Type: application/json' \
     -d '{"distance": 100, "username": "me"}'
curl localhost:8123/api/robots                 # everyone's robots
curl localhost:8123/api/robots/my_turtle/history
curl -N localhost:8123/events                  # live poses + chat (SSE)
curl -X DELETE localhost:8123/api/robots/my_turtle
```

Every drive call returns the new pose. `GET /api/kinds` lists the kinds
and what each can do; `GET /api/chat/channels` the channels. With the
token, `/api/mqtt` watches a topic, streams one, or publishes to one, so
any Aiko Service can be called from a language with no Aiko client yet
(`/guide` has the three curl lines). The page's live stream is a
WebSocket at `/ws`; `/events` is the same as server-sent events.

**Chat** (the page, `aiko_chat repl` after `:cc robots`, or
`aiko_chat send robots "..."`):

```text
@@my_turtle move 100         ;; <Move>, replies with the new pose
@@my_drone move 100 0 30     ;; a vector: forward, left, up (as many axes as the kind has)
@@my_turtle turn 90          ;; degrees counter-clockwise
@@my_pi reset 100 -50        ;; put it there (any kind); plain "reset" = the origin
@@my_arm grasp               ;; <Grasp>, kinds with a gripper
@@my_turtle look             ;; <Perceive>
@@my_turtle telemetry        ;; <Telemetry>
@@my_turtle interfaces       ;; <Robot>
@@my_turtle reset            ;; the origin, or "reset X Y [H]" for anywhere
@@pilot move my_turtle in a star shape   ;; the LLM agent
```

Robots act only on messages that *start* with their `@@name`. Replies end
with ` !!!!`, the aiko_chat convention that stops bots answering bots.
Forget the `@@` and the page shows a reminder under the chat.

**Your own code** (the full power, from any machine; see `/guide`):

```bash
./robot.py run --name my_dog --kind xgo      # your process is the robot
python3 examples/aiko_drive.py my_dog        # discover it, call its <Move> directly
python3 examples/agent_bot.py                # a 60-line chat agent: @@square my_dog
python3 examples/rest_drive.py my_dog        # the same over REST, stdlib only
```

`examples/colab_turtle.ipynb` walks a beginner through both paths in
Google Colab (written for Colab, not yet run there: reports welcome).

**MCP** (Claude Code, Claude Desktop, any MCP client), no Aiko needed:

```bash
pip install mcp
claude mcp add turtle -e TURTLE_URL=https://turtle.aiko.hashtag.ai -- python3 $PWD/mcp_server.py
```

## Robot kinds

| kind | what it is | Interfaces |
|---|---|---|
| `turtle` | the classic drawing turtle | Move Perceive Telemetry |
| `lolibot` | the OHC [LoliBot](https://openhardwareconf.org/wiki/LoliBot), and Jon Oxer's BeetleBot | Move Perceive Telemetry |
| `xgo` | XGO robot dog (walks forward and sideways) | Move Perceive Telemetry |
| `lekiwi` | LeKiwi: LeRobot's omni base with an SO-101 arm (moves sideways too) | Move Grasp Perceive Telemetry |
| `so101` | LeRobot SO-101 arm: grasps, does not drive | Grasp Perceive Telemetry |
| `drone` | a generic quadcopter: `move` is a 3D vector, forward, left, up | Move Perceive Telemetry |
| `pi` | a Raspberry Pi with display, speaker and mic: senses, does not move | Perceive Telemetry |

A kind decides the sprite on the map, the chat commands a robot accepts
(`@@pi move 10` gets "a pi cannot move", `@@turtle move 0 50` gets "a
turtle cannot move left"), how many axes `move` takes, and the aspect
tags it registers with. `reset X Y [H]` puts any kind anywhere (plain
`reset` is the origin), and so does dragging it on the map. Register a robot of a kind and `aiko_registrar list` shows exactly
what it can do.

**Adding a kind** (a pull request is very welcome, or fork and build your
own world on top of this one):

1. One entry in `kinds.py`: label, description, the Interfaces it has.
2. One drawing function in `static/index.html`, next to `drawTurtle`:
   top-down, nose along +x, about 40 px across, in the robot's colour
   `col`. Add it to the `SPRITES` table.
3. If it needs a new Interface, add the Interface to `interfaces.py`
   (abstract methods plus a `*Default` placeholder), the command to
   `core.parse_command` and `kinds.COMMAND_INTERFACES`, and the
   implementation to `ChatRobotAgent`. Run `pytest`.

## Tests

```bash
python3 -m pytest -q tests      # 17 tests, well under a second, no broker needed
```

They cover the world maths and persistence, the chat command and LLM
output parsers, the rate limiter, the kinds, and the REST API (including
channels and the bearer token) against a fake backend.

## State

| What | Where | Owner |
|---|---|---|
| robot definitions and poses | `robots` table | the world |
| every command, who sent it, the resulting pose | `events` table (`/api/robots/NAME/history`) | the world |
| live poses | the share `robots.<name>` on the world's topic | the world |
| which robots the web server speaks for | `host` column = `web` | the world, written by the web server |

The world is the only writer. Restart anything and the robots are where
they were. Change the database with one variable (`TURTLE_DATABASE_URL`).

## Deploying on a server

[docs/deployment.md](docs/deployment.md) walks through the public
instance at **https://turtle.aiko.hashtag.ai** step by step: the
aiko_services production instance, `.env`, the three entries in
`${HOST}_supervisor.json` (from `supervisor.json.example`), nginx with a
Let's Encrypt certificate, DNS, and how to update it (`git pull`, then
`sudo systemctl restart aiko.service`). The web server binds localhost;
the proxy needs `proxy_buffering off` for the SSE endpoint.

## Files

| File | Purpose |
|---|---|
| `config.py` | settings: environment, then `.env`, then defaults |
| `db.py` | the `robots` and `events` tables (SQLAlchemy Core) |
| `world_model.py` | the world without Aiko: poses, maths, persistence |
| `virtual_world.py` | the VirtualWorld Actor |
| `interfaces.py` | `<Chat>` `<Robot>` `<Move>` `<Grasp>` `<Perceive>` `<Telemetry>` and the aspect tags |
| `kinds.py` | the robot kinds: Interfaces and commands of each |
| `core.py` | chat command parser, LLM output parser, rate limiter, name rule |
| `robot.py` | ChatRobotAgent (`./robot.py run`, and `host_robot()` for the web server) |
| `agent.py` | the LLM ChatAgent |
| `webapp.py` | the FastAPI app and routes (no Aiko; testable) |
| `static/` | the pages: `index.html` (also `/world`, `/chat`), `guide.html`, `system.html` |
| `mcp_server.py` | MCP server over the REST API |
| `examples/` | `rest_drive.py`, `aiko_drive.py`, `agent_bot.py`, `colab_turtle.ipynb` |
| `web.py` | the Aiko-connected backend and server |
| `tests/` | pytest |
| `start.sh` `stop.sh` `env.sh` | local convenience |
| `supervisor.json.example` | ProcessManager definition entries |
| `docs/` | `deployment.md` (server setup and updates), `aiko.hashtag.ai/` (the landing page of the community host), the 2026-08-22 imagineering session report |

## Design notes

- **Aspect tags.** A robot registers with one tag per Interface it
  implements, `chat=0 robot=0 move=0 perceive=0 telemetry=0` (the
  framework's one-aspect-per-tag convention, as in ADR-025 and the
  display protocol), plus `botname=`, `channel=`, `kind=`, `commands=`.
  The agent discovers robots with `implements(tags, "Robot")`; a
  ServiceFilter can select on `tags=["move=0"]`. Versioning comes free:
  a `move=1` robot simply does not match a `move=0` client. A kind
  without `<Move>` simply has no `move=0` tag.
- **The Interfaces** follow the 2026-08-15 study-group design: `<Robot>`
  composed of `<Move>` (move, turn, stop), `<Telemetry>`, `<Perceive>`,
  and `<Grasp>` for the arms. As in that design, `move` takes a vector
  rather than a command per axis: a number is forward, `[forward, left,
  up]` in the robot's own frame does the rest, and the kind says how many
  axes it has (`axes` in `kinds.py`: a turtle 1, an omni base 2, a drone
  3). `<Navigation>` (move_to a landmark) is the obvious next one; the
  design's `walk`, `start`/`stop` for low-cost drones, and bumper-style
  triggers are open questions worth a discussion at the meetup.
- **One world process, one Actor per robot.** The earlier design (each
  robot a hyperspace collection of lazily started source/target
  processes, with an embedded ProcessManager) is in the git history. It
  was replaced because every known issue came from the process split.
- **Hosting.** The web server creates ChatRobotAgent Actors in its own
  process (Aiko Services supports several Services per process). One
  framework detail: discovery registered after the services cache has
  loaded gets no replay of known Services (a TODO in `share.py`), so
  `ChatRobotAgent.attach_known_services()` reads the cache itself.
- **Service ids are never reused.** `aiko.process.remove_service()`
  decrements the counter that also generates Service ids, so the next
  Actor created in the process would share a topic path with a live one
  and the two would hear each other's messages. `ChatRobotAgent.detach()`
  restores the counter. Worth an upstream fix.
- **Request/response from HTTP threads.** `web.py` calls the world with a
  per-request response topic and waits on a queue. Never do that on the
  Aiko event thread: the reply arrives on it.

## Contributing

Everything is welcome: a new robot kind, a better sprite, a tutorial, a
bug report, a question. Good first contributions:

- a kind for a robot you own (see "Adding a kind" above);
- running `examples/colab_turtle.ipynb` in Colab and reporting what broke;
- an example in another language against the REST API;
- `<Navigation>` or a 3D `<Move>` for the drone.

Open an issue or a pull request at
[github.com/anjsimmo/aiko_turtle](https://github.com/anjsimmo/aiko_turtle),
or bring it to the [AI+ML+Robots meetup](https://www.meetup.com/ai-ml-robots/)
([ai-ml-robots.github.io](https://ai-ml-robots.github.io/)), where the real
robots are.

## Known issues

- Removing a wildcard message handler in aiko_services raises (process.py
  does `del` on a list), so `web.py` keeps one handler per distinct MQTT
  topic pattern watched through `/api/mqtt` and fans out to the current
  watchers instead. Worth an upstream fix.

- Channel `robots` is not in the ChatServer's channel list (`:lc`); the
  server relays to any channel, so it works. Avoid the channel `robot`,
  which the server routes to XGO robots.
- The agent sends robot commands one second apart; order is kept because
  the world applies each instantly.
- No identity: anyone can drive any robot, by design for now.
